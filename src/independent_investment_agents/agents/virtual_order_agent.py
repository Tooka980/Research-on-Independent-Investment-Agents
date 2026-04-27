from __future__ import annotations

import math
from typing import Any

from independent_investment_agents.domain.virtual_orders import (
    OrderStatus,
    ResearchTask,
    RiskCheckResult,
    VirtualOrder,
)


class VirtualOrderAgent:
    """Creates only in-app virtual orders from evidence-backed decisions."""

    name = "Virtual Order Agent"

    def create_order(
        self,
        decision_context: dict[str, Any],
        portfolio_state: dict[str, Any],
        market_state: dict[str, Any],
    ) -> VirtualOrder | ResearchTask:
        evidence_refs = list(decision_context.get("related_evidence_ids") or decision_context.get("evidence_refs") or [])
        symbol = str(decision_context.get("target_symbol") or market_state.get("symbol") or "").upper()
        price = _safe_float(market_state.get("expected_price") or market_state.get("close"))

        if not symbol or not evidence_refs:
            return ResearchTask(
                task_type="missing_evidence_for_virtual_order",
                target_symbols=[symbol] if symbol else [],
                topic="virtual order evidence check",
                reason="DecisionContext has no evidence_refs, so no virtual order is created.",
                priority=1,
            )
        if _requires_trade_plan(decision_context) and (
            not decision_context.get("stop_loss_plan")
            or not decision_context.get("take_profit_plan")
            or not decision_context.get("position_size_reason")
        ):
            return ResearchTask(
                task_type="missing_trade_plan_for_virtual_order",
                target_symbols=[symbol],
                topic="virtual order risk controls",
                reason="Actionable buy/sell candidates require stop_loss_plan, take_profit_plan, and position_size_reason.",
                priority=1,
            )
        if not price or price <= 0:
            return ResearchTask(
                task_type="missing_price_for_virtual_order",
                target_symbols=[symbol],
                topic="virtual order price check",
                reason="Market price is missing, so no virtual order is created.",
                priority=1,
            )

        side = _normalize_side(decision_context.get("side") or decision_context.get("decision_type"))
        order_type = _normalize_order_type(decision_context.get("order_type"))
        cash = _safe_float(portfolio_state.get("cash")) or 0.0
        requested_value = _safe_float(decision_context.get("target_value"))
        target_value = min(requested_value or cash * 0.08, cash * 0.12)
        quantity = max(1.0, math.floor(target_value / price))
        target_value = round(quantity * price, 2)

        limit_price = _safe_float(decision_context.get("limit_price"))
        stop_price = _safe_float(decision_context.get("stop_price"))
        if order_type == "limit" and not limit_price:
            limit_price = round(price * (0.995 if side == "buy" else 1.005), 2)
        if order_type == "stop" and not stop_price:
            stop_price = round(price * (0.97 if side == "sell" else 1.03), 2)

        return VirtualOrder(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            target_value=target_value,
            limit_price=limit_price,
            stop_price=stop_price,
            expected_price=round(price, 2),
            created_by_agent=self.name,
            related_decision_context_id=str(decision_context.get("id") or f"dc-{symbol.lower()}"),
            related_evidence_ids=evidence_refs,
            reason=str(decision_context.get("reason") or decision_context.get("final_recommendation_for_simulation") or "Evidence-backed virtual order candidate."),
            notes="Application-local virtual simulation only. No broker API or real order is used.",
            position_size_reason=str(decision_context.get("position_size_reason") or ""),
            stop_loss_plan=str(decision_context.get("stop_loss_plan") or ""),
            take_profit_plan=str(decision_context.get("take_profit_plan") or ""),
            expected_return=_safe_float(decision_context.get("expected_return")),
            expected_risk=_safe_float(decision_context.get("expected_risk")),
            risk_reward_ratio=_safe_float(decision_context.get("risk_reward_ratio")),
            confidence=_safe_float(decision_context.get("confidence")),
        )


class VirtualRiskAgent:
    """Checks a virtual order before it can enter simulation."""

    name = "Risk Agent"

    def __init__(self, max_order_value: float = 120_000.0) -> None:
        self.max_order_value = max_order_value

    def check_virtual_order(
        self,
        order: VirtualOrder,
        portfolio_state: dict[str, Any],
        market_state: dict[str, Any],
    ) -> RiskCheckResult:
        failed: list[str] = []
        warnings: list[str] = []
        cash = _safe_float(portfolio_state.get("cash")) or 0.0
        price = _safe_float(market_state.get("close") or order.expected_price)

        evidence_check = bool(order.related_evidence_ids)
        if not evidence_check:
            failed.append("missing_evidence_refs")

        cash_check = order.side != "buy" or order.target_value <= cash
        if not cash_check:
            failed.append("insufficient_virtual_cash")

        max_order_value_check = order.target_value <= self.max_order_value
        if not max_order_value_check:
            failed.append("max_virtual_order_value_exceeded")

        price_sanity_check = bool(price and price > 0 and math.isfinite(price))
        if not price_sanity_check:
            failed.append("invalid_virtual_price")

        data_quality_check = bool(market_state.get("has_ohlcv", True))
        if not data_quality_check:
            failed.append("missing_ohlcv")

        trade_plan_check = bool(order.stop_loss_plan and order.take_profit_plan and order.position_size_reason)
        if not trade_plan_check and order.related_decision_context_id.startswith(("dc-research", "dc-consensus")):
            failed.append("missing_virtual_trade_plan")

        if order.order_type == "market":
            warnings.append("market_simulation_uses_configured_close_price")

        passed = not failed
        return RiskCheckResult(
            order_id=order.id,
            passed=passed,
            failed_rules=failed,
            warnings=warnings,
            max_order_value_check=max_order_value_check,
            cash_check=cash_check,
            evidence_check=evidence_check,
            price_sanity_check=price_sanity_check,
            data_quality_check=data_quality_check,
            trade_plan_check=trade_plan_check,
            explanation="virtual order passed risk checks" if passed else "virtual order rejected by risk controls",
        )


class CapitalGrowthPolicy:
    """Builds virtual-only decision contexts for constrained capital growth."""

    def build_decision_context(
        self,
        symbol: str,
        quote: dict[str, Any],
        portfolio_state: dict[str, Any],
        evidence_refs: list[str],
    ) -> dict[str, Any]:
        cash = _safe_float(portfolio_state.get("cash")) or 0.0
        equity = _safe_float(portfolio_state.get("equity")) or max(cash, 1.0)
        cash_ratio = cash / max(equity, 1.0)
        change_pct = _safe_float(quote.get("changePct")) or 0.0
        side = "buy"
        order_type = "rebalance" if cash_ratio > 0.28 else "market"
        decision_type = "virtual_capital_growth"
        if change_pct < -4.0 and cash_ratio < 0.25:
            side = "sell"
            order_type = "liquidation"
            decision_type = "virtual_risk_reduction"
        target_value = max(10_000.0, min(cash * 0.08, equity * 0.04))
        return {
            "id": f"dc-policy-{symbol.lower().replace('.', '-')}",
            "target_symbol": symbol,
            "decision_type": decision_type,
            "side": side,
            "order_type": order_type,
            "target_value": target_value,
            "related_evidence_ids": evidence_refs,
            "reason": "Virtual-only capital growth policy with risk and evidence gates. No real order.",
            "final_recommendation_for_simulation": "Create a simulated order candidate only when evidence and risk gates pass.",
            "position_size_reason": "policy default: capped by cash and equity",
            "stop_loss_plan": "policy default: stop if thesis fails or price breaks risk band",
            "take_profit_plan": "policy default: review after favorable move or target band",
            "expected_return": 0.03,
            "expected_risk": 0.02,
            "risk_reward_ratio": 1.5,
            "confidence": 0.55,
        }


def apply_risk_result(order: VirtualOrder, risk: RiskCheckResult) -> VirtualOrder:
    order.risk_check_result = risk.to_dict()
    order.status = OrderStatus.APPROVED_FOR_SIMULATION if risk.passed else OrderStatus.REJECTED_BY_RISK
    return order


def _normalize_side(value: Any) -> str:
    text = str(value or "buy").lower()
    return "sell" if "sell" in text or "liquidation" in text or "risk_reduction" in text else "buy"


def _normalize_order_type(value: Any) -> str:
    text = str(value or "market").lower()
    if text in {"limit", "stop", "rebalance", "liquidation"}:
        return text
    return "market"


def _requires_trade_plan(decision_context: dict[str, Any]) -> bool:
    text = f"{decision_context.get('decision_type')} {decision_context.get('side')}".lower()
    return (
        "buy_candidate" in text
        or "sell_candidate" in text
        or "risk_reduction_candidate" in text
        or "rebalance_candidate" in text
    )


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number
