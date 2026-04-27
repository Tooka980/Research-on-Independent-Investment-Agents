from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class OrderStatus(StrEnum):
    PROPOSED = "proposed"
    RISK_CHECKED = "risk_checked"
    APPROVED_FOR_SIMULATION = "approved_for_simulation"
    REJECTED_BY_RISK = "rejected_by_risk"
    SCHEDULED_FOR_NEXT_SESSION = "scheduled_for_next_session"
    SIMULATED_FILLED = "simulated_filled"
    SIMULATED_PARTIAL_FILLED = "simulated_partial_filled"
    SIMULATED_CANCELLED = "simulated_cancelled"
    EXPIRED = "expired"


@dataclass
class ResearchTask:
    task_type: str
    topic: str
    reason: str
    target_symbols: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: f"rtask-{uuid4().hex}")
    priority: int = 3
    created_by_agent: str = "Virtual Order Agent"
    status: str = "open"
    created_at: str = field(default_factory=utc_now_iso)
    message_ja: str = ""
    message_en: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload["message_en"]:
            payload["message_en"] = payload["reason"]
        return payload


@dataclass
class RiskCheckResult:
    order_id: str
    passed: bool
    failed_rules: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    explanation: str = ""
    message_ja: str = ""
    message_en: str = ""
    max_order_value_check: bool = True
    cash_check: bool = True
    evidence_check: bool = True
    price_sanity_check: bool = True
    data_quality_check: bool = True
    trade_plan_check: bool = True
    id: str = field(default_factory=lambda: f"vrisk-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload["message_en"]:
            payload["message_en"] = payload["explanation"]
        return payload


@dataclass
class VirtualOrder:
    symbol: str
    side: str
    order_type: str
    quantity: float
    target_value: float
    expected_price: float
    created_by_agent: str
    related_decision_context_id: str
    related_evidence_ids: list[str]
    reason: str
    id: str = field(default_factory=lambda: f"vord-{uuid4().hex}")
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.PROPOSED
    risk_check_result: dict[str, Any] | None = None
    created_at: str = field(default_factory=utc_now_iso)
    simulated_executed_at: str | None = None
    simulated_execution_price: float | None = None
    notes: str = ""
    position_size_reason: str = ""
    stop_loss_plan: str = ""
    take_profit_plan: str = ""
    expected_return: float | None = None
    expected_risk: float | None = None
    risk_reward_ratio: float | None = None
    confidence: float | None = None
    risk_notes_ja: list[str] = field(default_factory=list)
    message_ja: str = ""
    message_en: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        if not payload["message_en"]:
            payload["message_en"] = payload["reason"]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VirtualOrder":
        data = dict(payload)
        data["status"] = OrderStatus(data.get("status", OrderStatus.PROPOSED))
        return cls(**data)


@dataclass
class VirtualExecution:
    order_id: str
    symbol: str
    side: str
    quantity: float
    execution_price: float
    commission: float
    slippage: float
    simulation_rule: str
    portfolio_before: dict[str, Any]
    portfolio_after: dict[str, Any]
    id: str = field(default_factory=lambda: f"vexec-{uuid4().hex}")
    executed_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VirtualExecution":
        return cls(**payload)


@dataclass
class DecisionTrace:
    decision_context_id: str
    evidence_refs: list[str]
    virtual_order_id: str | None
    virtual_execution_id: str | None
    outcome: str
    summary: str
    id: str = field(default_factory=lambda: f"dlog-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
