from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


HORIZONS = (1, 3, 7, 30)


@dataclass
class DecisionOutcome:
    decision_id: str
    target_symbol: str
    created_at: str
    entry_price: float | None
    price_1d: float | None = None
    price_3d: float | None = None
    price_7d: float | None = None
    price_30d: float | None = None
    return_1d: float | None = None
    return_3d: float | None = None
    return_7d: float | None = None
    return_30d: float | None = None
    benchmark_return_1d: float | None = None
    benchmark_return_3d: float | None = None
    benchmark_return_7d: float | None = None
    benchmark_return_30d: float | None = None
    max_favorable_excursion: float | None = None
    max_adverse_excursion: float | None = None
    hit_stop_loss: bool = False
    hit_take_profit: bool = False
    final_outcome: str = "pending"
    used_evidence_ids: list[str] = field(default_factory=list)
    related_agent_findings: list[str] = field(default_factory=list)
    contribution_to_equity: float = 0.0
    evaluated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    id: str = field(default_factory=lambda: f"dout-{uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DecisionOutcomeTracker:
    def evaluate(
        self,
        decisions: list[dict[str, Any]],
        *,
        price_history_by_symbol: dict[str, list[dict[str, Any]]],
        benchmark_history: list[dict[str, Any]] | None = None,
    ) -> list[DecisionOutcome]:
        outcomes: list[DecisionOutcome] = []
        for decision in decisions:
            symbol = str(decision.get("target_symbol") or "").upper()
            history = price_history_by_symbol.get(symbol) or []
            if not symbol or not history:
                outcomes.append(self._pending(decision, symbol, "missing_price_history"))
                continue
            closes = [_safe_float(item.get("close") or item.get("current")) for item in history]
            closes = [value for value in closes if value is not None and value > 0]
            if not closes:
                outcomes.append(self._pending(decision, symbol, "missing_close_price"))
                continue
            entry_index = max(0, len(closes) - 31)
            entry = closes[entry_index]
            window = closes[entry_index:]
            outcome = DecisionOutcome(
                decision_id=str(decision.get("id") or ""),
                target_symbol=symbol,
                created_at=str(decision.get("created_at") or ""),
                entry_price=round(entry, 4),
                used_evidence_ids=[str(item) for item in decision.get("related_evidence_ids", [])],
                related_agent_findings=[str(item) for item in decision.get("related_findings", [])],
            )
            side = _side(decision)
            for horizon in HORIZONS:
                price = closes[min(entry_index + horizon, len(closes) - 1)]
                raw_return = (price / entry) - 1.0 if entry > 0 else None
                signed_return = -raw_return if side == "sell" and raw_return is not None else raw_return
                setattr(outcome, f"price_{horizon}d", round(price, 4))
                setattr(outcome, f"return_{horizon}d", round(signed_return, 6) if signed_return is not None else None)
                benchmark_return = _horizon_return(benchmark_history, horizon)
                setattr(outcome, f"benchmark_return_{horizon}d", benchmark_return)
            if window and entry > 0:
                raw_returns = [(price / entry) - 1.0 for price in window]
                signed_returns = [-item for item in raw_returns] if side == "sell" else raw_returns
                outcome.max_favorable_excursion = round(max(signed_returns), 6)
                outcome.max_adverse_excursion = round(min(signed_returns), 6)
                stop_price = _safe_float(decision.get("stop_price"))
                if stop_price:
                    outcome.hit_stop_loss = min(window) <= stop_price if side == "buy" else max(window) >= stop_price
                target_value = _safe_float(decision.get("target_value")) or 0.0
                outcome.contribution_to_equity = round(target_value * float(outcome.return_30d or outcome.return_7d or 0.0), 2)
            outcome.final_outcome = self._classify(decision, outcome)
            outcomes.append(outcome)
        return outcomes

    def _pending(self, decision: dict[str, Any], symbol: str, reason: str) -> DecisionOutcome:
        return DecisionOutcome(
            decision_id=str(decision.get("id") or ""),
            target_symbol=symbol,
            created_at=str(decision.get("created_at") or ""),
            entry_price=None,
            final_outcome=reason,
            used_evidence_ids=[str(item) for item in decision.get("related_evidence_ids", [])],
        )

    def _classify(self, decision: dict[str, Any], outcome: DecisionOutcome) -> str:
        decision_type = str(decision.get("decision_type") or "").lower()
        return_7d = outcome.return_7d
        return_30d = outcome.return_30d
        benchmark_30d = outcome.benchmark_return_30d
        if "watch" in decision_type or "hold" in decision_type:
            return "loss_avoided_or_pending" if (return_7d is not None and return_7d >= -0.02) else "missed_or_adverse"
        if return_30d is not None and benchmark_30d is not None and return_30d > benchmark_30d:
            return "effective_vs_benchmark"
        if return_7d is not None and return_7d > 0:
            return "short_term_success"
        if return_7d is not None:
            return "short_term_failed"
        return "pending"


class PerformanceRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.outcomes_path = root / "decision_outcomes.jsonl"
        self.equity_points_path = root / "equity_points.jsonl"

    def ensure_storage(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.outcomes_path.touch(exist_ok=True)
        self.equity_points_path.touch(exist_ok=True)

    def save_outcomes(self, outcomes: list[DecisionOutcome]) -> None:
        existing = {str(item.get("decision_id")): item for item in self.read_outcomes(limit=5000)}
        for outcome in outcomes:
            existing[outcome.decision_id] = outcome.to_dict()
        self._rewrite_jsonl(self.outcomes_path, list(existing.values()))

    def append_equity_point(self, point: dict[str, Any]) -> None:
        rows = self.read_equity_points(limit=5000)
        if rows and str(rows[-1].get("timestamp") or rows[-1].get("time"))[:10] == str(point.get("timestamp") or point.get("time"))[:10]:
            rows[-1] = point
        else:
            rows.append(point)
        self._rewrite_jsonl(self.equity_points_path, rows[-5000:])

    def read_outcomes(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._read_jsonl(self.outcomes_path, limit)

    def read_equity_points(self, limit: int = 500) -> list[dict[str, Any]]:
        return self._read_jsonl(self.equity_points_path, limit)

    def _read_jsonl(self, path: Path, limit: int) -> list[dict[str, Any]]:
        self.ensure_storage()
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows[-limit:]

    def _rewrite_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        self.ensure_storage()
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _side(decision: dict[str, Any]) -> str:
    text = str(decision.get("side") or decision.get("decision_type") or "").lower()
    return "sell" if "sell" in text or "risk_reduction" in text or "liquidation" in text else "buy"


def _horizon_return(history: list[dict[str, Any]] | None, horizon: int) -> float | None:
    if not history:
        return None
    closes = [_safe_float(item.get("close") or item.get("value") or item.get("equity")) for item in history]
    closes = [value for value in closes if value is not None and value > 0]
    if len(closes) < 2:
        return None
    start_index = max(0, len(closes) - 31)
    entry = closes[start_index]
    price = closes[min(start_index + horizon, len(closes) - 1)]
    return round((price / entry) - 1.0, 6) if entry > 0 else None


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number
