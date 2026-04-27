from __future__ import annotations

import math
from typing import Any

from independent_investment_agents.domain.virtual_orders import (
    OrderStatus,
    ResearchTask,
    RiskCheckResult,
    VirtualOrder,
)


ACTIONABLE_DECISION_TYPES = {
    "small_buy_candidate",
    "buy_candidate",
    "rebalance_candidate",
    "sell_candidate",
    "risk_reduction_candidate",
}
NON_ACTIONABLE_DECISION_TYPES = {
    "",
    "research_more",
    "watch_only",
    "hold",
    "blocked",
    "waiting",
    "decision_evidence_gap",
    "unknown",
}


class VirtualOrderAgent:
    """Creates only in-app virtual orders from evidence-backed decisions."""

    name = "Virtual Order Agent"

    def create_order(
        self,
        decision_context: dict[str, Any],
        portfolio_state: dict[str, Any],
        market_state: dict[str, Any],
    ) -> VirtualOrder | ResearchTask:
        decision_type = _normalize_decision_type(decision_context.get("decision_type"))
        symbol = str(decision_context.get("target_symbol") or market_state.get("symbol") or "").upper()
        if _is_manual_research_mode(decision_context, market_state) or not _is_actionable_decision(decision_type):
            return _research_task(
                task_type="non_actionable_decision",
                symbols=[symbol],
                topic="仮想注文対象外の判断",
                reason="この判断は調査継続または見送りであり、仮想注文は作成しません。",
                message_ja="この判断は調査継続または見送りのため、仮想注文は作成されません。",
            )

        side = _normalize_side(decision_context.get("side") or decision_type)
        if side not in {"buy", "sell"}:
            return _research_task(
                task_type="invalid_order_side_for_virtual_order",
                symbols=[symbol],
                topic="仮想注文方向の確認",
                reason="Virtual order side must be buy or sell.",
                message_ja="売買方向が買い・売り以外のため、仮想注文は作成されません。",
            )

        evidence_refs = list(decision_context.get("related_evidence_ids") or decision_context.get("evidence_refs") or [])
        price = _safe_float(market_state.get("expected_price") or market_state.get("close"))

        if not symbol or not evidence_refs:
            return _research_task(
                task_type="missing_evidence_for_virtual_order",
                symbols=[symbol] if symbol else [],
                topic="virtual order evidence check",
                reason="DecisionContext has no evidence_refs, so no virtual order is created.",
                message_ja="仮想注文の根拠が不足しているため、注文は作成されませんでした。",
            )
        trade_plan_result = TradePlanValidator().validate(decision_context, side=side)
        if _requires_trade_plan(decision_context) and not trade_plan_result.passed:
            return _research_task(
                task_type="missing_trade_plan_for_virtual_order",
                symbols=[symbol],
                topic="virtual order risk controls",
                reason="Actionable buy/sell candidates require a valid stop_loss_plan, take_profit_plan, and position_size_reason.",
                message_ja=trade_plan_result.message_ja,
            )
        risk_reward_result = RiskRewardValidator().validate(decision_context)
        if not risk_reward_result.passed:
            return _research_task(
                task_type=risk_reward_result.task_type,
                symbols=[symbol],
                topic="仮想注文リスクリワード確認",
                reason=risk_reward_result.reason,
                message_ja=risk_reward_result.message_ja,
            )
        if not price or price <= 0:
            return _research_task(
                task_type="missing_price_for_virtual_order",
                symbols=[symbol],
                topic="virtual order price check",
                reason="Market price is missing, so no virtual order is created.",
                message_ja="市場価格が取得できないため、仮想注文は作成されません。",
            )

        size_result = PositionSizeValidator().build_size(
            decision_context=decision_context,
            portfolio_state=portfolio_state,
            price=price,
            side=side,
        )
        if not size_result.passed:
            return _research_task(
                task_type=size_result.task_type,
                symbols=[symbol],
                topic="仮想注文ポジションサイズ確認",
                reason=size_result.reason,
                message_ja=size_result.message_ja,
            )

        order_type = _normalize_order_type(decision_context.get("order_type"))
        quantity = size_result.quantity
        target_value = size_result.target_value

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
            risk_notes_ja=[*trade_plan_result.notes_ja, *risk_reward_result.notes_ja, *size_result.notes_ja],
            message_ja="リスク条件を確認したうえで、アプリ内の仮想注文候補を作成しました。",
            message_en="Created an application-local virtual order candidate after risk checks.",
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

        expected_risk_check = order.expected_risk is not None and order.expected_risk > 0
        if not expected_risk_check:
            failed.append("invalid_expected_risk")

        risk_reward_check = order.risk_reward_ratio is not None and order.risk_reward_ratio >= 1.0
        if not risk_reward_check:
            failed.append("risk_reward_ratio_below_minimum")

        held_quantity = _held_quantity(portfolio_state.get("positions"), order.symbol)
        sell_quantity_check = order.side != "sell" or order.quantity <= held_quantity
        if not sell_quantity_check:
            failed.append("sell_quantity_exceeds_position")

        if order.order_type == "market":
            warnings.append("market_simulation_uses_configured_close_price")

        passed = not failed
        message_ja = "仮想注文のリスク確認を通過しました。"
        if "risk_reward_ratio_below_minimum" in failed:
            message_ja = "リスクリワード比が不足しているため、仮想注文を作成しませんでした。"
        elif "sell_quantity_exceeds_position" in failed:
            message_ja = "保有数量を超える売却になるため、仮想売却注文を停止しました。"
        elif "missing_virtual_trade_plan" in failed:
            message_ja = "損切り・利確・ポジションサイズ理由が不足しています。"
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
            message_ja=message_ja,
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
        decision_type = "buy_candidate"
        if change_pct < -4.0 and cash_ratio < 0.25:
            side = "sell"
            order_type = "liquidation"
            decision_type = "risk_reduction_candidate"
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
            "message_ja": "根拠とリスク制約を確認する仮想運用ポリシーです。実注文は行いません。",
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
    if risk.message_ja:
        order.risk_notes_ja.append(risk.message_ja)
    return order


class ValidationResult:
    def __init__(
        self,
        *,
        passed: bool,
        task_type: str = "",
        reason: str = "",
        message_ja: str = "",
        notes_ja: list[str] | None = None,
        quantity: float = 0.0,
        target_value: float = 0.0,
    ) -> None:
        self.passed = passed
        self.task_type = task_type
        self.reason = reason
        self.message_ja = message_ja
        self.notes_ja = notes_ja or []
        self.quantity = quantity
        self.target_value = target_value


class TradePlanValidator:
    def validate(self, decision_context: dict[str, Any], *, side: str) -> ValidationResult:
        stop_plan = str(decision_context.get("stop_loss_plan") or "").strip()
        take_plan = str(decision_context.get("take_profit_plan") or "").strip()
        position_reason = str(decision_context.get("position_size_reason") or "").strip()
        stop_price = _safe_float(decision_context.get("stop_price"))
        failed: list[str] = []
        if not stop_price and not _has_any(stop_plan, ("stop", "below", "loss", "invalidation", "break", "損切", "下回", "割れ", "無効")):
            failed.append("missing_clear_stop_loss_condition")
        if not _has_any(take_plan, ("take", "profit", "review", "target", "利確", "利益", "再評価", "見直", "目標")):
            failed.append("missing_clear_take_profit_or_review_condition")
        if len(position_reason) < 8:
            failed.append("missing_position_size_reason")
        if failed:
            if "missing_clear_stop_loss_condition" in failed:
                message_ja = "損切り条件が不明確なため、仮想注文は保留されました。"
            elif "missing_clear_take_profit_or_review_condition" in failed:
                message_ja = "利確または再評価条件が不明確なため、仮想注文は保留されました。"
            else:
                message_ja = "ポジションサイズ理由が不足しているため、仮想注文は保留されました。"
            return ValidationResult(
                passed=False,
                task_type="missing_trade_plan_for_virtual_order",
                reason=", ".join(failed),
                message_ja=message_ja,
            )
        return ValidationResult(
            passed=True,
            notes_ja=[f"{'売り' if side == 'sell' else '買い'}注文の損切り・利確・サイズ理由を確認しました。"],
        )


class RiskRewardValidator:
    def validate(self, decision_context: dict[str, Any]) -> ValidationResult:
        expected_risk = _safe_float(decision_context.get("expected_risk"))
        if expected_risk is None or expected_risk <= 0:
            return ValidationResult(
                passed=False,
                task_type="invalid_expected_risk_for_virtual_order",
                reason="expected_risk must be greater than zero.",
                message_ja="想定リスクが0以下のため、仮想注文を作成しませんでした。",
            )
        ratio = _safe_float(decision_context.get("risk_reward_ratio"))
        if ratio is None:
            expected_return = _safe_float(decision_context.get("expected_return"))
            ratio = expected_return / expected_risk if expected_return is not None and expected_risk > 0 else None
        if ratio is None or ratio < 1.0:
            return ValidationResult(
                passed=False,
                task_type="risk_reward_too_low_for_virtual_order",
                reason="risk_reward_ratio is missing or below 1.0.",
                message_ja="リスクリワード比が不足しているため、仮想注文を作成しませんでした。",
            )
        return ValidationResult(
            passed=True,
            notes_ja=[f"リスクリワード比 {ratio:.2f} を確認しました。"],
        )


class PositionSizeValidator:
    def build_size(
        self,
        *,
        decision_context: dict[str, Any],
        portfolio_state: dict[str, Any],
        price: float,
        side: str,
    ) -> ValidationResult:
        cash = _safe_float(portfolio_state.get("cash")) or 0.0
        equity = _safe_float(portfolio_state.get("equity")) or max(cash, 1.0)
        risk_limits = portfolio_state.get("risk_limits") if isinstance(portfolio_state.get("risk_limits"), dict) else {}
        max_order_value = (
            _safe_float(portfolio_state.get("max_order_value"))
            or _safe_float(portfolio_state.get("max_virtual_order_value"))
            or _safe_float(risk_limits.get("max_order_value"))
            or 120_000.0
        )
        expected_risk = _safe_float(decision_context.get("expected_risk")) or 0.0
        max_loss_allowed = (
            _safe_float(portfolio_state.get("max_loss_allowed"))
            or _safe_float(risk_limits.get("max_loss_allowed"))
            or equity * (_safe_float(risk_limits.get("max_loss_pct")) or 0.01)
        )
        requested_value = _safe_float(decision_context.get("target_value"))
        requested_quantity = _safe_float(decision_context.get("quantity"))
        notes: list[str] = []
        if side == "sell":
            held_quantity = _held_quantity(portfolio_state.get("positions"), str(decision_context.get("target_symbol") or ""))
            if held_quantity <= 0:
                return ValidationResult(
                    passed=False,
                    task_type="sell_without_position_for_virtual_order",
                    reason="No virtual position is available for this sell order.",
                    message_ja="保有数量がないため、仮想売却注文を停止しました。",
                )
            if requested_quantity is not None:
                quantity = requested_quantity
            elif requested_value is not None:
                quantity = math.floor(requested_value / price)
            else:
                quantity = max(1.0, math.floor(held_quantity * 0.25))
            if quantity > held_quantity:
                return ValidationResult(
                    passed=False,
                    task_type="sell_quantity_exceeds_position_for_virtual_order",
                    reason="Sell quantity exceeds current virtual position.",
                    message_ja="保有数量を超える売却になるため、仮想売却注文を停止しました。",
                )
            max_quantity_by_value = max_order_value / price
            quantity = max(0.0, min(quantity, held_quantity, max_quantity_by_value))
            if quantity <= 0:
                return ValidationResult(
                    passed=False,
                    task_type="position_size_too_small_for_virtual_order",
                    reason="Validated sell quantity is zero.",
                    message_ja="売却数量が0になるため、仮想注文は作成されません。",
                )
            target_value = round(quantity * price, 2)
            notes.append("保有数量と最大注文額の範囲内で仮想売却数量を確認しました。")
            return ValidationResult(passed=True, quantity=round(quantity, 4), target_value=target_value, notes_ja=notes)

        max_loss_value = max_loss_allowed / expected_risk if expected_risk > 0 else 0.0
        max_value = max(0.0, min(cash, max_order_value, max_loss_value))
        target_value = requested_value if requested_value is not None else min(cash * 0.08, max_value)
        if target_value > max_value:
            notes.append("現金・最大注文額・最大損失許容額に合わせて注文額を縮小しました。")
            target_value = max_value
        quantity = math.floor(target_value / price)
        target_value = round(quantity * price, 2)
        if quantity <= 0 or target_value <= 0:
            return ValidationResult(
                passed=False,
                task_type="position_size_too_small_for_virtual_order",
                reason="Target value is below one tradable unit after risk caps.",
                message_ja="現金または最大損失許容額を超えるため、仮想注文は作成されません。",
            )
        notes.append("現金・最大注文額・最大損失許容額の範囲内で仮想購入額を確認しました。")
        return ValidationResult(passed=True, quantity=float(quantity), target_value=target_value, notes_ja=notes)


def _normalize_decision_type(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_actionable_decision(decision_type: str) -> bool:
    return decision_type in ACTIONABLE_DECISION_TYPES and decision_type not in NON_ACTIONABLE_DECISION_TYPES


def _is_manual_research_mode(decision_context: dict[str, Any], market_state: dict[str, Any]) -> bool:
    mode = str(
        decision_context.get("mode")
        or decision_context.get("simulation_mode")
        or market_state.get("mode")
        or market_state.get("simulation_mode")
        or ""
    )
    return mode == "ManualResearchMode"


def _normalize_side(value: Any) -> str | None:
    text = str(value or "").lower().strip()
    if text in {"hold", "research_more", "watch_only", "blocked", "waiting", "unknown", ""}:
        return None
    if text in {"buy", "small_buy_candidate", "buy_candidate", "rebalance_candidate"}:
        return "buy"
    if text in {"sell", "sell_candidate", "risk_reduction_candidate", "liquidation"}:
        return "sell"
    if "sell" in text or "liquidation" in text or "risk_reduction" in text:
        return "sell"
    if "buy" in text or "rebalance" in text:
        return "buy"
    return None


def _normalize_order_type(value: Any) -> str:
    text = str(value or "market").lower()
    if text in {"limit", "stop", "rebalance", "liquidation"}:
        return text
    return "market"


def _requires_trade_plan(decision_context: dict[str, Any]) -> bool:
    decision_type = _normalize_decision_type(decision_context.get("decision_type"))
    return decision_type in ACTIONABLE_DECISION_TYPES


def _research_task(
    *,
    task_type: str,
    symbols: list[str],
    topic: str,
    reason: str,
    message_ja: str,
    priority: int = 1,
) -> ResearchTask:
    return ResearchTask(
        task_type=task_type,
        target_symbols=[symbol for symbol in symbols if symbol],
        topic=topic,
        reason=reason,
        priority=priority,
        message_ja=message_ja,
        message_en=reason,
    )


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _held_quantity(positions: Any, symbol: str) -> float:
    target = str(symbol or "").upper()
    if isinstance(positions, dict):
        if target in positions:
            item = positions.get(target)
            if isinstance(item, dict):
                return _safe_float(item.get("quantity")) or 0.0
            return _safe_float(item) or 0.0
        return 0.0
    if isinstance(positions, list):
        for item in positions:
            if not isinstance(item, dict):
                continue
            if str(item.get("symbol") or "").upper() == target:
                return _safe_float(item.get("quantity")) or 0.0
    return 0.0


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number
