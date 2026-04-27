from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SymbolQueueItem:
    symbol: str
    priority: int
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        return payload


def build_symbol_processing_plan(
    *,
    focus_symbol: str,
    watchlist: list[dict[str, Any]],
    positions: list[dict[str, Any]] | list[Any],
    batch_size: int,
) -> SymbolProcessingPlan:
    """Build a prioritized processing view without dropping any symbols."""

    normalized_batch_size = max(1, int(batch_size or 1))
    watch_symbols = _dedupe([str(item.get("symbol") or "").upper() for item in watchlist if item.get("symbol")])
    position_symbols = _dedupe([_position_symbol(item) for item in positions])
    focus = str(focus_symbol or "").upper()
    change_by_symbol = {
        str(item.get("symbol") or "").upper(): _safe_abs_float(item.get("changePct"))
        for item in watchlist
        if item.get("symbol")
    }

    all_symbols = _dedupe([focus, *position_symbols, *watch_symbols])
    ordered = sorted(
        all_symbols,
        key=lambda symbol: (
            0 if symbol == focus else 1,
            0 if symbol in position_symbols else 1,
            -change_by_symbol.get(symbol, 0.0),
            symbol,
        ),
    )
    processing = ordered[:normalized_batch_size]
    pending = ordered[normalized_batch_size:]
    queue: list[SymbolQueueItem] = []
    for idx, symbol in enumerate(ordered):
        if symbol in processing:
            status = "completed"
            reason = "selected for this cycle by focus/position/volatility priority"
        else:
            status = "pending"
            reason = "retained for a later batch; symbol was not discarded"
        queue.append(SymbolQueueItem(symbol=symbol, priority=idx + 1, status=status, reason=reason))

    limited = bool(pending)
    return SymbolProcessingPlan(
        batch_size=normalized_batch_size,
        total_watchlist_symbols=len(watch_symbols),
        total_position_symbols=len(position_symbols),
        total_unique_symbols=len(ordered),
        processing_symbols=processing,
        pending_symbols=pending,
        completed_symbols=list(processing),
        queue=queue,
        limited_by_batch_size=limited,
        limit_reason=(
            "Deep processing is batched to control runtime cost; pending symbols remain queued."
            if limited
            else ""
        ),
    )


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
