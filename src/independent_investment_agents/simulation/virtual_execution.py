from __future__ import annotations

from copy import deepcopy
from typing import Any

from independent_investment_agents.domain.virtual_orders import (
    OrderStatus,
    VirtualExecution,
    VirtualOrder,
    utc_now_iso,
)


class MarketSessionPolicy:
    """Keeps simulated fills close to real-market timing.

    This does not connect to any exchange. It only decides whether an in-app
    virtual order may be filled by the simulator at the current market phase.
    """

    def may_simulate_fill(self, market_data: dict[str, Any]) -> bool:
        return bool(market_data.get("market_is_open", True))

    def waiting_note(self, market_data: dict[str, Any]) -> str:
        phase = str(market_data.get("market_phase") or "closed")
        return f"Waiting for next market session; simulated fills are disabled while phase={phase}."


class VirtualSimulationEngine:
    """Processes in-app virtual orders against historical OHLCV data."""

    def __init__(self, market_session_policy: MarketSessionPolicy | None = None) -> None:
        self.market_session_policy = market_session_policy or MarketSessionPolicy()

    def process_virtual_order(
        self,
        order: VirtualOrder,
        market_data: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> VirtualExecution | VirtualOrder:
        if not self.market_session_policy.may_simulate_fill(market_data):
            order.status = OrderStatus.SCHEDULED_FOR_NEXT_SESSION
            order.notes = self.market_session_policy.waiting_note(market_data)
            return order

        fill_price = self._fill_price(order, market_data)
        if fill_price is None:
            order.status = OrderStatus.EXPIRED
            order.notes = "Virtual order expired because simulated price conditions were not reached."
            return order

        before = deepcopy(portfolio_state)
        after = deepcopy(portfolio_state)
        notional = round(order.quantity * fill_price, 2)
        commission = round(max(0.0, notional * 0.0005), 2)
        slippage = round(max(0.0, notional * 0.0002), 2)
        positions = dict(after.get("positions") or {})
        current_quantity = _position_quantity(positions.get(order.symbol))

        if order.side == "buy":
            after["cash"] = round(float(after.get("cash", 0.0)) - notional - commission - slippage, 2)
            positions[order.symbol] = {
                "quantity": round(current_quantity + order.quantity, 4),
                "last_price": fill_price,
            }
        else:
            after["cash"] = round(float(after.get("cash", 0.0)) + notional - commission - slippage, 2)
            positions[order.symbol] = {
                "quantity": round(max(0.0, current_quantity - order.quantity), 4),
                "last_price": fill_price,
            }

        after["positions"] = positions
        order.status = OrderStatus.SIMULATED_FILLED
        order.simulated_executed_at = utc_now_iso()
        order.simulated_execution_price = fill_price
        return VirtualExecution(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            execution_price=fill_price,
            commission=commission,
            slippage=slippage,
            simulation_rule=self._rule_label(order),
            portfolio_before=before,
            portfolio_after=after,
        )

    def _fill_price(self, order: VirtualOrder, market_data: dict[str, Any]) -> float | None:
        open_price = _to_float(market_data.get("open"))
        high = _to_float(market_data.get("high"))
        low = _to_float(market_data.get("low"))
        close = _to_float(market_data.get("close"))
        if order.order_type in {"market", "rebalance", "liquidation"}:
            return close or open_price or order.expected_price
        if order.order_type == "limit":
            if order.limit_price is None:
                return None
            if order.side == "buy" and low is not None and low <= order.limit_price:
                return order.limit_price
            if order.side == "sell" and high is not None and high >= order.limit_price:
                return order.limit_price
            return None
        if order.order_type == "stop":
            if order.stop_price is None:
                return None
            if order.side == "sell" and low is not None and low <= order.stop_price:
                return order.stop_price
            if order.side == "buy" and high is not None and high >= order.stop_price:
                return order.stop_price
            return None
        return None

    def _rule_label(self, order: VirtualOrder) -> str:
        labels = {
            "market": "simulated_market_close_fill",
            "limit": "simulated_limit_touch_fill",
            "stop": "simulated_stop_trigger_fill",
            "rebalance": "simulated_rebalance_close_fill",
            "liquidation": "simulated_liquidation_close_fill",
        }
        return labels.get(order.order_type, "simulated_unknown_rule")


def _position_quantity(position: Any) -> float:
    if isinstance(position, dict):
        return float(position.get("quantity", 0.0) or 0.0)
    return float(position or 0.0)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
