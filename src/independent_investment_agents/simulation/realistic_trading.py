from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _round_money(value: float) -> float:
    return round(value, 4)


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
    expires_at: str | None = None
    id: str = field(default_factory=lambda: f"vord-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    cash_balance_after: float | None = None
    order_status_reason: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CashLedgerEntry:
    order_id: str
    side: str
    amount: float
    balance_after: float
    message_ja: str
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CashLedger:
    def __init__(self, initial_cash: float = 1_000_000.0) -> None:
        self.initial_cash = float(initial_cash)
        self.balance = float(initial_cash)
        self.reserved_cash = 0.0
        self.entries: list[CashLedgerEntry] = []

    @property
    def available_cash(self) -> float:
        return _round_money(max(0.0, self.balance - self.reserved_cash))

    def can_afford(self, amount: float) -> bool:
        return amount <= self.available_cash + 1e-9

    def debit(self, amount: float, *, order_id: str, side: str, message_ja: str) -> CashLedgerEntry:
        self.balance = _round_money(self.balance - amount)
        entry = CashLedgerEntry(order_id, side, -_round_money(amount), self.balance, message_ja)
        self.entries.append(entry)
        return entry

    def credit(self, amount: float, *, order_id: str, side: str, message_ja: str) -> CashLedgerEntry:
        self.balance = _round_money(self.balance + amount)
        entry = CashLedgerEntry(order_id, side, _round_money(amount), self.balance, message_ja)
        self.entries.append(entry)
        return entry

    def snapshot(self) -> dict[str, Any]:
        return {
            "initial_cash": _round_money(self.initial_cash),
            "balance": _round_money(self.balance),
            "reserved_cash": _round_money(self.reserved_cash),
            "available_cash": self.available_cash,
            "entries": [entry.to_dict() for entry in self.entries],
        }


class CommissionModel:
    def __init__(self, rate: float = 0.0005) -> None:
        self.rate = rate

    def calculate(self, notional: float) -> float:
        return _round_money(max(0.0, notional * self.rate))


class SlippageModel:
    def __init__(self, rate: float = 0.0002) -> None:
        self.rate = rate

    def apply(self, price: float, side: str) -> tuple[float, float]:
        signed = price * self.rate
        executed = price + signed if side == "buy" else price - signed
        return _round_money(executed), _round_money(abs(signed))


class PartialFillModel:
    def fill_quantity(self, quantity: float, volume_available: Any | None) -> float:
        if volume_available is None:
            return _round_money(quantity)
        try:
            available = float(volume_available)
        except (TypeError, ValueError):
            return _round_money(quantity)
        return _round_money(min(quantity, max(available, 0.0)))


class OrderLifecycleManager:
    VALID_STATUSES = {"pending", "filled", "partial_fill", "rejected", "expired", "canceled"}

    def is_expired(self, order: VirtualOrderRequest, now: datetime | str | None = None) -> bool:
        expires_at = _parse_dt(order.expires_at)
        if expires_at is None:
            return False
        current = _parse_dt(now) or datetime.now(timezone.utc)
        return expires_at <= current

    def status(
        self,
        *,
        is_open: bool,
        filled: float,
        requested: float,
        rejected: bool = False,
        expired: bool = False,
        canceled: bool = False,
    ) -> str:
        if canceled:
            return "canceled"
        if expired:
            return "expired"
        if rejected:
            return "rejected"
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

    def snapshot(self) -> list[dict[str, Any]]:
        return [position.to_dict() for position in self.all()]


class VirtualBroker:
    def __init__(self, initial_cash: float = 1_000_000.0) -> None:
        self.commission_model = CommissionModel()
        self.slippage_model = SlippageModel()
        self.execution = ExecutionSimulator()
        self.lifecycle = OrderLifecycleManager()
        self.cash = CashLedger(initial_cash)
        self.positions = PositionLedger()
        self.trade_ledger: list[TradeLedgerEntry] = []
        self.pending_orders: list[VirtualOrderRequest] = []
        self._canceled_order_ids: set[str] = set()

    @property
    def open_orders(self) -> list[VirtualOrderRequest]:
        return list(self.pending_orders)

    def submit(
        self,
        order: VirtualOrderRequest,
        candle: dict[str, Any],
        *,
        market_is_open: bool = True,
        current_time: datetime | str | None = None,
    ) -> TradeLedgerEntry:
        if order.id in self._canceled_order_ids:
            return self._record_non_execution(order, "canceled", "キャンセル済み注文のため約定しません。", remove_pending=True)
        if self.lifecycle.is_expired(order, current_time):
            return self._record_non_execution(order, "expired", "注文有効期限を過ぎたため失効しました。", remove_pending=True)

        price = self.execution.trigger_price(order, candle)

        if order.side == "sell":
            held = self.positions.get(order.symbol).quantity if self.positions.get(order.symbol) else 0.0
            if order.quantity > held:
                return self._record_non_execution(order, "rejected", "保有数量を超える売却はできません。", remove_pending=True)

        if order.side == "buy":
            required_cash = self._estimated_buy_cash_required(order, price, candle)
            if required_cash is not None and not self.cash.can_afford(required_cash):
                message = f"買付余力不足のため拒否しました。必要額: {required_cash:.2f}円 / 余力: {self.cash.available_cash:.2f}円。"
                return self._record_non_execution(order, "rejected", message, remove_pending=True)

        fill_qty = self.execution.partial_fill.fill_quantity(order.quantity, candle.get("volume_available")) if price is not None else 0.0
        status = self.lifecycle.status(is_open=market_is_open, filled=fill_qty, requested=order.quantity)
        if status == "pending":
            reason = self._pending_reason(order, candle, market_is_open, price, fill_qty)
            self._remember_pending(order)
            return self._record_non_execution(order, status, reason, remove_pending=False)

        assert price is not None
        exec_price, slip = self.slippage_model.apply(price, order.side)
        notional = _round_money(fill_qty * exec_price)
        commission = self.commission_model.calculate(notional)

        if order.side == "buy":
            total_debit = _round_money(notional + commission)
            if not self.cash.can_afford(total_debit):
                message = f"約定直前の買付余力不足のため拒否しました。必要額: {total_debit:.2f}円 / 余力: {self.cash.available_cash:.2f}円。"
                return self._record_non_execution(order, "rejected", message, remove_pending=True)
            self.cash.debit(total_debit, order_id=order.id, side=order.side, message_ja="仮想買付代金と手数料を現金台帳へ反映しました。")
        else:
            self.cash.credit(_round_money(notional - commission), order_id=order.id, side=order.side, message_ja="仮想売却代金から手数料を控除して現金台帳へ反映しました。")

        realized = self._update_position(order, fill_qty, exec_price, commission, order.id)
        self._remove_pending(order.id)
        message = (
            f"仮想{('買い' if order.side == 'buy' else '売り')}約定: {order.symbol}を{fill_qty:g}株、"
            f"{exec_price:.4f}円で記録しました。手数料{commission:.4f}円、スリッページ{slip:.4f}円を反映済みです。"
        )
        entry = TradeLedgerEntry(
            order_id=order.id,
            execution_id=f"vexec-{uuid4().hex}",
            symbol=order.symbol,
            side=order.side,
            quantity=fill_qty,
            requested_price=order.requested_price,
            execution_price=exec_price,
            commission=commission,
            slippage=slip,
            realized_pnl=realized,
            status=status,
            message_ja=message,
            cash_balance_after=self.cash.balance,
            order_status_reason="全量約定" if status == "filled" else "一部約定",
        )
        self.trade_ledger.append(entry)
        return entry

    def cancel_order(self, order_id: str) -> TradeLedgerEntry | None:
        order = next((item for item in self.pending_orders if item.id == order_id), None)
        self._canceled_order_ids.add(order_id)
        if order is None:
            return None
        return self._record_non_execution(order, "canceled", "ユーザーまたは管理ルールにより未約定注文をキャンセルしました。", remove_pending=True)

    def expire_pending_orders(self, current_time: datetime | str | None = None) -> list[TradeLedgerEntry]:
        expired: list[TradeLedgerEntry] = []
        for order in list(self.pending_orders):
            if self.lifecycle.is_expired(order, current_time):
                expired.append(self._record_non_execution(order, "expired", "注文有効期限を過ぎたため未約定のまま失効しました。", remove_pending=True))
        return expired

    def _estimated_buy_cash_required(self, order: VirtualOrderRequest, price: float | None, candle: dict[str, Any]) -> float | None:
        estimate = price
        if estimate is None:
            estimate = order.limit_price or order.stop_price or order.requested_price or self.execution._candle_float(candle, "close")
        if estimate is None:
            return None
        estimated_exec_price, _ = self.slippage_model.apply(estimate, "buy")
        notional = _round_money(order.quantity * estimated_exec_price)
        return _round_money(notional + self.commission_model.calculate(notional))

    def _pending_reason(self, order: VirtualOrderRequest, candle: dict[str, Any], market_is_open: bool, price: float | None, fill_qty: float) -> str:
        if not market_is_open:
            return "市場時間外のため未約定注文として待機中です。"
        if price is None:
            if order.order_type in {"market", "rebalance", "partial_sell", "risk_reduction"} and self.execution._candle_float(candle, "close") is None:
                return "終値が欠損しているため0円では約定せず、未約定として待機中です。"
            if order.order_type in {"limit", "stop"} and (
                self.execution._candle_float(candle, "high") is None or self.execution._candle_float(candle, "low") is None
            ):
                return "高値または安値が欠損しているため0円では約定せず、未約定として待機中です。"
            return "注文条件が未達のため未約定として待機中です。"
        if fill_qty <= 0:
            return "利用可能出来高がないため未約定として待機中です。"
        return "条件未達または市場時間外のため待機中です。"

    def _record_non_execution(
        self,
        order: VirtualOrderRequest,
        status: str,
        message_ja: str,
        *,
        remove_pending: bool,
    ) -> TradeLedgerEntry:
        if remove_pending:
            self._remove_pending(order.id)
        entry = TradeLedgerEntry(
            order_id=order.id,
            execution_id=f"vexec-{uuid4().hex}",
            symbol=order.symbol,
            side=order.side,
            quantity=0.0,
            requested_price=order.requested_price,
            execution_price=0.0,
            commission=0.0,
            slippage=0.0,
            realized_pnl=0.0,
            status=status,
            message_ja=message_ja,
            cash_balance_after=self.cash.balance,
            order_status_reason=message_ja,
        )
        self.trade_ledger.append(entry)
        return entry

    def _remember_pending(self, order: VirtualOrderRequest) -> None:
        if not any(item.id == order.id for item in self.pending_orders):
            self.pending_orders.append(order)

    def _remove_pending(self, order_id: str) -> None:
        self.pending_orders = [item for item in self.pending_orders if item.id != order_id]

    def _update_position(self, order: VirtualOrderRequest, qty: float, exec_price: float, commission: float, order_id: str) -> float:
        now = utc_now_iso()
        current = self.positions.get(order.symbol)
        if current is None:
            current = PositionLedgerEntry(order.symbol, 0.0, 0.0, 0.0, 0.0, 0.0, now, now, [])
            self.positions._positions[order.symbol] = current

        realized = 0.0
        if order.side == "buy":
            total_cost = current.average_cost * current.quantity + exec_price * qty + commission
            current.quantity = _round_money(current.quantity + qty)
            current.average_cost = _round_money(total_cost / max(current.quantity, 1e-9))
        else:
            realized = _round_money((exec_price - current.average_cost) * qty - commission)
            current.quantity = _round_money(current.quantity - qty)
            current.realized_pnl = _round_money(current.realized_pnl + realized)
            if current.quantity <= 1e-9:
                current.quantity = 0.0
                current.average_cost = 0.0

        current.market_value = _round_money(current.quantity * exec_price)
        current.unrealized_pnl = _round_money((exec_price - current.average_cost) * current.quantity) if current.quantity else 0.0
        current.updated_at = now
        current.source_order_ids.append(order_id)
        return realized
