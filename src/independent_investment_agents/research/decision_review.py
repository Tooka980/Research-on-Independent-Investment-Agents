from __future__ import annotations

from typing import Any


class DecisionRedTeamAgent:
    def review(self, decision: dict[str, Any]) -> dict[str, Any]:
        bearish = list(decision.get("bearish_reasons") or [])
        invalidation = list(decision.get("invalidation_conditions") or [])
        stop_loss = str(decision.get("stop_loss_plan") or "")
        take_profit = str(decision.get("take_profit_plan") or "")
        blocked_reasons = []
        if _is_actionable(decision) and not bearish:
            blocked_reasons.append("missing_bearish_reasons")
        if _is_actionable(decision) and not invalidation:
            blocked_reasons.append("missing_invalidation_conditions")
        if _is_actionable(decision) and not stop_loss:
            blocked_reasons.append("missing_stop_loss_plan")
        if _is_actionable(decision) and not take_profit:
            blocked_reasons.append("missing_take_profit_plan")
        reviewed = dict(decision)
        reviewed["review_blocked_reasons"] = blocked_reasons
        if blocked_reasons:
            reviewed["decision_type"] = "blocked"
            reviewed["side"] = "hold"
        elif len(bearish) >= 3 and "buy" in str(decision.get("decision_type", "")).lower():
            reviewed["decision_type"] = "research_more"
        return reviewed


class BearishCaseAnalyzer:
    def analyze(self, symbol_payload: dict[str, Any]) -> list[str]:
        quote = symbol_payload.get("quote", {})
        reasons = []
        if float(quote.get("changePct") or 0.0) < -2:
            reasons.append("recent price action is negative")
        if not symbol_payload.get("dataQuality", {}).get("hasAnalysisHistory"):
            reasons.append("analysis price history is unavailable")
        if not reasons:
            reasons.append("bearish case exists but is not dominant; monitor evidence freshness")
        return reasons


class InvalidationConditionBuilder:
    def build(self, *, symbol: str, stop_loss_plan: str) -> list[str]:
        output = [f"{symbol} thesis invalidates if evidence freshness expires or source reliability falls"]
        if stop_loss_plan:
            output.append(stop_loss_plan)
        return output


class DecisionReviewAgent(DecisionRedTeamAgent):
    pass


def _is_actionable(decision: dict[str, Any]) -> bool:
    text = f"{decision.get('decision_type')} {decision.get('side')}".lower()
    return "buy" in text or "sell" in text or "risk_reduction" in text or "rebalance" in text
