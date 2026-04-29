from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class VirtualOrderRequest:
    symbol: str
    side: str
    order_type: str
    quantity: float
    requested_price: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    trailing_amount: float | None = None
    id: str = field(default_factory=lambda: f"vord-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class TradeLedgerEntry:
    order_id: str
    execution_id: str
    symbol: str
    side: str
    quantity: float
    requested_price: float | None
    execution_price: float
    commission: float
    slippage: float
    realized_pnl: float
    status: str
    message_ja: str


@dataclass
class PositionLedgerEntry:
    symbol: str
    quantity: float
    average_cost: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    opened_at: str
    updated_at: str
    source_order_ids: list[str]


class CommissionModel:
    def __init__(self, rate: float = 0.0005) -> None:
        self.rate = rate

    def calculate(self, notional: float) -> float:
        return round(max(0.0, notional * self.rate), 4)


class SlippageModel:
    def __init__(self, rate: float = 0.0002) -> None:
        self.rate = rate

    def apply(self, price: float, side: str) -> tuple[float, float]:
        signed = price * self.rate
        executed = price + signed if side == "buy" else price - signed
        return round(executed, 4), round(abs(signed), 4)


class PartialFillModel:
    def fill_quantity(self, quantity: float, volume_available: float | None) -> float:
        if volume_available is None:
            return quantity
        return round(min(quantity, max(volume_available, 0.0)), 4)


class OrderLifecycleManager:
    def status(self, *, is_open: bool, filled: float, requested: float) -> str:
        if not is_open:
            return "pending"
        if filled <= 0:
            return "pending"
        if filled < requested:
            return "partial_fill"
        return "filled"


class ExecutionSimulator:
    def __init__(self) -> None:
        self.partial_fill = PartialFillModel()

    @staticmethod
    def _candle_float(candle: dict[str, Any], key: str) -> float | None:
        value = candle.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def trigger_price(self, order: VirtualOrderRequest, candle: dict[str, Any]) -> float | None:
        high = self._candle_float(candle, "high")
        low = self._candle_float(candle, "low")
        close = self._candle_float(candle, "close")
        if order.order_type in {"market", "rebalance", "partial_sell", "risk_reduction"}:
            return close
        if order.order_type == "limit":
            if low is None or high is None:
                return None
            if order.side == "buy" and order.limit_price is not None and low <= order.limit_price:
                return order.limit_price
            if order.side == "sell" and order.limit_price is not None and high >= order.limit_price:
                return order.limit_price
            return None
        if order.order_type == "stop":
            if low is None or high is None:
                return None
            if order.side == "sell" and order.stop_price is not None and low <= order.stop_price:
                return order.stop_price
            if order.side == "buy" and order.stop_price is not None and high >= order.stop_price:
                return order.stop_price
            return None
        return None


class PositionLedger:
    def __init__(self) -> None:
        self._positions: dict[str, PositionLedgerEntry] = {}

    def get(self, symbol: str) -> PositionLedgerEntry | None:
        return self._positions.get(symbol)

    def all(self) -> list[PositionLedgerEntry]:
        return list(self._positions.values())


class VirtualBroker:
    def __init__(self) -> None:
        self.commission_model = CommissionModel()
        self.slippage_model = SlippageModel()
        self.execution = ExecutionSimulator()
        self.lifecycle = OrderLifecycleManager()
        self.positions = PositionLedger()
        self.trade_ledger: list[TradeLedgerEntry] = []

    def submit(self, order: VirtualOrderRequest, candle: dict[str, Any], *, market_is_open: bool = True) -> TradeLedgerEntry:
        price = self.execution.trigger_price(order, candle)
        fill_qty = self.execution.partial_fill.fill_quantity(order.quantity, candle.get("volume_available")) if price is not None else 0.0
        status = self.lifecycle.status(is_open=market_is_open, filled=fill_qty, requested=order.quantity)
        if order.side == "sell":
            held = (self.positions.get(order.symbol).quantity if self.positions.get(order.symbol) else 0.0)
            if order.quantity > held:
                entry = TradeLedgerEntry(order.id, f"vexec-{uuid4().hex}", order.symbol, order.side, 0.0, order.requested_price, 0.0, 0.0, 0.0, 0.0, "rejected", "保有数量を超える売却はできません。")
                self.trade_ledger.append(entry)
                return entry
        if status == "pending":
            entry = TradeLedgerEntry(order.id, f"vexec-{uuid4().hex}", order.symbol, order.side, 0.0, order.requested_price, 0.0, 0.0, 0.0, 0.0, status, "条件未達または市場時間外のため待機中です。")
            self.trade_ledger.append(entry)
            return entry
        assert price is not None
        exec_price, slip = self.slippage_model.apply(price, order.side)
        notional = fill_qty * exec_price
        commission = self.commission_model.calculate(notional)
        realized = self._update_position(order, fill_qty, exec_price, order.id)
        entry = TradeLedgerEntry(order.id, f"vexec-{uuid4().hex}", order.symbol, order.side, fill_qty, order.requested_price, exec_price, commission, slip, realized - commission, status, "仮想約定を記録しました。")
        self.trade_ledger.append(entry)
        return entry

    def _update_position(self, order: VirtualOrderRequest, qty: float, exec_price: float, order_id: str) -> float:
        now = utc_now_iso()
        current = self.positions.get(order.symbol)
        if current is None:
            current = PositionLedgerEntry(order.symbol, 0.0, 0.0, 0.0, 0.0, 0.0, now, now, [])
            self.positions._positions[order.symbol] = current
        realized = 0.0
        if order.side == "buy":
            total_cost = current.average_cost * current.quantity + exec_price * qty
            current.quantity += qty
            current.average_cost = total_cost / max(current.quantity, 1e-9)
        else:
            realized = (exec_price - current.average_cost) * qty
            current.quantity -= qty
            current.realized_pnl += realized
        current.market_value = round(current.quantity * exec_price, 4)
        current.unrealized_pnl = round((exec_price - current.average_cost) * current.quantity, 4)
        current.updated_at = now
        current.source_order_ids.append(order_id)
        return round(realized, 4)
