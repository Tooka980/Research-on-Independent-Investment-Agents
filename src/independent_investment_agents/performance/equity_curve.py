from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from independent_investment_agents.performance.metrics import calculate_performance_metrics


@dataclass(frozen=True)
class EquityPoint:
    equity: float
    cash: float
    holdings_value: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    id: str = field(default_factory=lambda: f"eq-{uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VirtualTradePerformanceTracker:
    def build_point(self, *, equity: float, cash: float, holdings_value: float) -> EquityPoint:
        return EquityPoint(equity=round(float(equity), 2), cash=round(float(cash), 2), holdings_value=round(float(holdings_value), 2))

    def summarize(
        self,
        equity_points: list[dict[str, Any]],
        *,
        benchmark_points: list[dict[str, Any]] | None = None,
        initial_equity: float | None = None,
    ) -> dict[str, Any]:
        return calculate_performance_metrics(equity_points, benchmark_points=benchmark_points, initial_equity=initial_equity)
