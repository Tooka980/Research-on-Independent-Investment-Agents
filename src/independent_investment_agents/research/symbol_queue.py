from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


STATUS_JA = {
    "queued": "処理待ち",
    "selected": "今回選択",
    "fetching": "データ取得中",
    "analyzing": "分析中",
    "completed": "分析完了",
    "failed": "失敗",
    "stale": "古い",
    "skipped": "今回見送り",
}


@dataclass(frozen=True)
class SymbolQueueItem:
    symbol: str
    priority: int
    status: str
    reason: str
    status_ja: str = ""
    last_processed_at: str | None = None
    next_process_at: str | None = None
    retry_count: int = 0
    last_error: str = ""
    completed_at: str | None = None
    evidence_created_count: int = 0
    finding_created_count: int = 0
    decision_created_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status_ja"] = payload["status_ja"] or STATUS_JA.get(self.status, self.status)
        return payload


@dataclass(frozen=True)
class SymbolProcessingPlan:
    batch_size: int
    total_watchlist_symbols: int
    total_position_symbols: int
    total_unique_symbols: int
    processing_symbols: list[str]
    pending_symbols: list[str]
    completed_symbols: list[str]
    queue: list[SymbolQueueItem] = field(default_factory=list)
    limited_by_batch_size: bool = False
    limit_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["queue"] = [item.to_dict() for item in self.queue]
        payload["processingCount"] = len(self.processing_symbols)
        payload["pendingCount"] = len(self.pending_symbols)
        payload["completedCount"] = len(self.completed_symbols)
        payload["failedCount"] = len([item for item in self.queue if item.status == "failed"])
        payload["selectedCount"] = len([item for item in self.queue if item.status == "selected"])
        return payload


def build_symbol_processing_plan(
    *,
    focus_symbol: str,
    watchlist: list[dict[str, Any]],
    positions: list[dict[str, Any]] | list[Any],
    batch_size: int,
    stored_items: list[dict[str, Any]] | None = None,
    universe_candidates: list[str] | None = None,
    analysis_completed_symbols: list[str] | None = None,
) -> SymbolProcessingPlan:
    """Build a prioritized processing view without dropping any symbols."""

    normalized_batch_size = max(1, int(batch_size or 1))
    watch_symbols = _dedupe([str(item.get("symbol") or "").upper() for item in watchlist if item.get("symbol")])
    position_symbols = _dedupe([_position_symbol(item) for item in positions])
    candidate_symbols = _dedupe(universe_candidates or [])
    stored_by_symbol = {str(item.get("symbol") or "").upper(): item for item in (stored_items or []) if item.get("symbol")}
    focus = str(focus_symbol or "").upper()
    change_by_symbol = {
        str(item.get("symbol") or "").upper(): _safe_abs_float(item.get("changePct"))
        for item in watchlist
        if item.get("symbol")
    }

    all_symbols = _dedupe([focus, *position_symbols, *watch_symbols, *candidate_symbols, *stored_by_symbol.keys()])
    completed_set = set(_dedupe(analysis_completed_symbols or []))
    ordered = sorted(
        all_symbols,
        key=lambda symbol: (
            0 if symbol == focus else 1,
            0 if symbol in position_symbols else 1,
            0 if symbol in watch_symbols else 1,
            _safe_int(stored_by_symbol.get(symbol, {}).get("priority"), 9999),
            -change_by_symbol.get(symbol, 0.0),
            symbol,
        ),
    )
    processing = ordered[:normalized_batch_size]
    pending = ordered[normalized_batch_size:]
    queue: list[SymbolQueueItem] = []
    for idx, symbol in enumerate(ordered):
        if symbol in processing:
            status = "selected"
            reason = "focus/position/watchlist priority selected this symbol for the current cycle"
            reason_ja = "フォーカス・保有・監視銘柄の優先度により今回の処理対象に選択しました。"
        elif symbol in completed_set:
            status = "completed"
            reason = "analysis artifacts were created for this symbol"
            reason_ja = "Evidence / Finding / Decision の作成が完了した銘柄です。"
        else:
            status = "queued"
            reason = "retained for a later batch; symbol was not discarded"
            reason_ja = "処理負荷を抑えるため、残りの銘柄は次回以降のキューに残しました。"
        stored = stored_by_symbol.get(symbol, {})
        queue.append(
            SymbolQueueItem(
                symbol=symbol,
                priority=idx + 1,
                status=status,
                reason=stored.get("reason") or reason,
                status_ja=STATUS_JA.get(status, status),
                last_processed_at=stored.get("last_processed_at"),
                next_process_at=stored.get("next_process_at"),
                retry_count=_safe_int(stored.get("retry_count"), 0),
                last_error=str(stored.get("last_error") or ""),
                completed_at=stored.get("completed_at") if status == "completed" else None,
                evidence_created_count=_safe_int(stored.get("evidence_created_count"), 0),
                finding_created_count=_safe_int(stored.get("finding_created_count"), 0),
                decision_created_count=_safe_int(stored.get("decision_created_count"), 0),
            )
        )

    limited = bool(pending)
    return SymbolProcessingPlan(
        batch_size=normalized_batch_size,
        total_watchlist_symbols=len(watch_symbols),
        total_position_symbols=len(position_symbols),
        total_unique_symbols=len(ordered),
        processing_symbols=processing,
        pending_symbols=pending,
        completed_symbols=[symbol for symbol in ordered if symbol in completed_set],
        queue=queue,
        limited_by_batch_size=limited,
        limit_reason=(
            "処理負荷を抑えるため、残りの銘柄は次回以降のキューに残しました。"
            if limited
            else ""
        ),
    )


class SymbolQueueRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read_items(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        items = data.get("queue", data) if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

    def write_items(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"updated_at": _utc_now(), "queue": items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class SymbolProcessingStore:
    def __init__(self, repository: SymbolQueueRepository) -> None:
        self.repository = repository

    def update_from_plan(self, plan: SymbolProcessingPlan) -> list[dict[str, Any]]:
        existing = {str(item.get("symbol") or "").upper(): item for item in self.repository.read_items()}
        for item in plan.queue:
            payload = {**existing.get(item.symbol, {}), **item.to_dict()}
            if item.status in {"selected", "fetching", "analyzing", "completed"}:
                payload["last_processed_at"] = payload.get("last_processed_at") or _utc_now()
            if item.status == "completed":
                payload["completed_at"] = payload.get("completed_at") or _utc_now()
            existing[item.symbol] = payload
        rows = sorted(existing.values(), key=lambda row: (_safe_int(row.get("priority"), 9999), str(row.get("symbol") or "")))
        self.repository.write_items(rows)
        return rows

    def mark_failed(self, symbol: str, error: str) -> None:
        rows = self.repository.read_items()
        target = symbol.upper()
        now = _utc_now()
        for row in rows:
            if str(row.get("symbol") or "").upper() == target:
                row["status"] = "failed"
                row["status_ja"] = STATUS_JA["failed"]
                row["last_error"] = error
                row["retry_count"] = _safe_int(row.get("retry_count"), 0) + 1
                row["next_process_at"] = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
                row["last_processed_at"] = now
        self.repository.write_items(rows)

    def mark_completed(self, symbol: str, *, evidence_count: int = 0, finding_count: int = 0, decision_count: int = 0) -> None:
        rows = self.repository.read_items()
        target = symbol.upper()
        now = _utc_now()
        for row in rows:
            if str(row.get("symbol") or "").upper() == target:
                row["status"] = "completed"
                row["status_ja"] = STATUS_JA["completed"]
                row["completed_at"] = now
                row["last_processed_at"] = now
                row["evidence_created_count"] = evidence_count
                row["finding_created_count"] = finding_count
                row["decision_created_count"] = decision_count
        self.repository.write_items(rows)


class SymbolRotationPolicy:
    def select(self, items: list[dict[str, Any]], batch_size: int) -> list[str]:
        now = datetime.now(UTC)
        eligible = []
        for item in items:
            status = str(item.get("status") or "queued")
            if status == "completed" and item.get("next_process_at") is None:
                continue
            next_at = _parse_dt(item.get("next_process_at"))
            if next_at and next_at > now:
                continue
            eligible.append(item)
        eligible.sort(key=lambda row: (_safe_int(row.get("priority"), 9999), _parse_dt(row.get("last_processed_at")) or datetime.min.replace(tzinfo=UTC)))
        return [str(item.get("symbol") or "").upper() for item in eligible[: max(1, int(batch_size or 1))]]


def _position_symbol(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("symbol") or "").upper()
    return str(getattr(item, "symbol", "") or "").upper()


def _dedupe(symbols: list[str]) -> list[str]:
    output: list[str] = []
    for symbol in symbols:
        clean = str(symbol or "").strip().upper()
        if clean and clean not in output:
            output.append(clean)
    return output


def _safe_abs_float(value: Any) -> float:
    try:
        return abs(float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
