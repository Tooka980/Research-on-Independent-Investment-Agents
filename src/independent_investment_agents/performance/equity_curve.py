from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from independent_investment_agents.performance.metrics import calculate_performance_metrics


@dataclass(frozen=True)
class EquityPoint:
    equity: float
    cash: float
    holdings_value: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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


class VirtualOrderPerformanceLinker:
    def link(
        self,
        *,
        orders: list[dict[str, Any]],
        executions: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        order_by_id = {str(order.get("id")): order for order in orders}
        decision_by_id = {str(decision.get("id")): decision for decision in decisions}
        outcome_by_decision = {str(outcome.get("decision_id")): outcome for outcome in outcomes}
        rows: list[dict[str, Any]] = []
        for execution in executions:
            order = order_by_id.get(str(execution.get("order_id")), {})
            decision_id = str(order.get("related_decision_context_id") or "")
            rows.append(
                {
                    "order_id": order.get("id"),
                    "execution_id": execution.get("id"),
                    "decision_id": decision_id,
                    "symbol": execution.get("symbol") or order.get("symbol"),
                    "side": execution.get("side") or order.get("side"),
                    "decision_type": decision_by_id.get(decision_id, {}).get("decision_type"),
                    "decision_outcome": outcome_by_decision.get(decision_id, {}).get("final_outcome"),
                    "evidence_ids": order.get("related_evidence_ids") or [],
                }
            )
        return rows


class ExecutionPnLCalculator:
    def calculate(
        self,
        *,
        executions: list[dict[str, Any]],
        current_prices: dict[str, float],
    ) -> dict[str, Any]:
        lots: dict[str, list[dict[str, float]]] = {}
        realized = 0.0
        order_pnl: list[dict[str, Any]] = []
        for execution in executions:
            symbol = str(execution.get("symbol") or "").upper()
            side = str(execution.get("side") or "")
            quantity = float(execution.get("quantity") or 0.0)
            price = float(execution.get("execution_price") or 0.0)
            fees = float(execution.get("commission") or 0.0) + float(execution.get("slippage") or 0.0)
            if not symbol or quantity <= 0 or price <= 0:
                continue
            if side == "buy":
                lots.setdefault(symbol, []).append({"quantity": quantity, "cost": price, "fees": fees})
                order_pnl.append({"execution_id": execution.get("id"), "symbol": symbol, "realized_pnl": 0.0, "unrealized_pnl": 0.0})
                continue
            remaining = quantity
            realized_for_order = -fees
            while remaining > 0 and lots.get(symbol):
                lot = lots[symbol][0]
                used = min(remaining, lot["quantity"])
                realized_for_order += (price - lot["cost"]) * used
                lot["quantity"] -= used
                remaining -= used
                if lot["quantity"] <= 0:
                    lots[symbol].pop(0)
            realized += realized_for_order
            order_pnl.append({"execution_id": execution.get("id"), "symbol": symbol, "realized_pnl": round(realized_for_order, 2), "unrealized_pnl": 0.0})
        unrealized = 0.0
        for symbol, symbol_lots in lots.items():
            current = float(current_prices.get(symbol) or 0.0)
            for lot in symbol_lots:
                if current > 0:
                    unrealized += (current - lot["cost"]) * lot["quantity"]
        return {
            "realizedPnlFromExecutions": round(realized, 2),
            "unrealizedPnlFromExecutions": round(unrealized, 2),
            "orderPnl": order_pnl,
        }


class DecisionContributionCalculator:
    def calculate(self, outcomes: list[dict[str, Any]], links: list[dict[str, Any]]) -> list[dict[str, Any]]:
        linked_execution_by_decision = {str(link.get("decision_id")): link.get("execution_id") for link in links if link.get("decision_id")}
        rows: list[dict[str, Any]] = []
        for outcome in outcomes:
            decision_id = str(outcome.get("decision_id") or "")
            rows.append(
                {
                    "decision_id": decision_id,
                    "symbol": outcome.get("target_symbol"),
                    "final_outcome": outcome.get("final_outcome"),
                    "execution_id": linked_execution_by_decision.get(decision_id),
                    "contribution_to_equity": float(outcome.get("contribution_to_equity") or 0.0),
                    "pending": str(outcome.get("final_outcome") or "").startswith("pending"),
                }
            )
        return rows
