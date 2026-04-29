from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _base_result(message_ja: str, findings: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "findings": findings,
        "evidence_refs": findings.get("evidence_refs", []),
        "confidence": findings.get("confidence", 0.5),
        "warnings": warnings or [],
        "suggested_actions": findings.get("suggested_actions", []),
        "message_ja": message_ja,
        "score_contribution": findings.get("score_contribution", 0.0),
    }


class MarketStructureAgent:
    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        trend = "up" if float(payload.get("changePct", 0)) >= 0 else "down"
        return _base_result("市場構造を分析しました。", {"trend": trend, "volume": payload.get("volume", 0), "volatility": payload.get("volatility", 0.0), "score_contribution": 0.1})


class NewsReasoningAgent:
    def analyze(self, news: dict[str, Any]) -> dict[str, Any]:
        body_checked = bool(news.get("body_fetched"))
        return _base_result("ニュース材料を評価しました。", {"本文確認済み": body_checked, "見出しのみ": not body_checked, "score_contribution": 0.08}, [] if body_checked else ["見出しのみの根拠です。"])


class FundamentalAnalystAgent:
    def analyze(self, metrics: dict[str, Any]) -> dict[str, Any]:
        unknowns = [k for k in ["PER", "PBR", "ROE", "EPS"] if metrics.get(k) in {None, ""}]
        return _base_result("ファンダメンタルを評価しました。", {"unknowns": unknowns, "score_contribution": 0.07})


class PortfolioManagerAgent:
    def analyze(self, portfolio: dict[str, Any]) -> dict[str, Any]:
        sectors = portfolio.get("sectors", {})
        concentrated = any(v > 0.4 for v in sectors.values())
        return _base_result("ポートフォリオ影響を評価しました。", {"sector_concentration": concentrated, "score_contribution": -0.04 if concentrated else 0.05})


class EnhancedRedTeamAgent:
    def review(self, decision: dict[str, Any]) -> dict[str, Any]:
        weak = not decision.get("stop_loss_plan") or not decision.get("take_profit_plan") or decision.get("headline_only", False)
        return _base_result("レッドチームレビューを実施しました。", {"should_downgrade": weak, "score_contribution": -0.1 if weak else 0.02}, ["重大警告: 根拠または計画が弱い"] if weak else [])


class ExecutionReadinessAgent:
    def check(self, context: dict[str, Any]) -> dict[str, Any]:
        ready = bool(context.get("market_is_open", True)) and float(context.get("liquidity", 1.0)) > 0
        return _base_result("実行可能性を確認しました。", {"execution_ready": ready, "score_contribution": 0.06 if ready else -0.1}, [] if ready else ["市場時間外または流動性不足"])


@dataclass
class AgentScorecard:
    agent_name: str
    role: str
    adopted_decisions: int
    win_rate: float
    average_return: float
    contribution: float
    trust_score: float
    suggestion_ja: str


class AgentSelfEvaluator:
    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        wins = [r for r in rows if r.get("final_outcome") == "short_term_success"]
        avg_ret = sum(float(r.get("return_7d", 0.0)) for r in rows) / max(len(rows), 1)
        return {"task_count": len(rows), "win_rate": len(wins) / max(len(rows), 1), "average_return_7d": avg_ret, "contribution_to_equity": sum(float(r.get("contribution_to_equity", 0.0)) for r in rows)}


class SelfReflectionReport:
    def generate(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        failed = [o for o in outcomes if float(o.get("return_7d", 0)) < 0]
        return {"今回失敗した判断": len(failed), "改善タスク": ["損切り条件の厳格化", "見出しのみEvidenceの比率削減"]}


class OutcomeFeedbackApplier:
    def apply(self, adjustments: dict[str, float], engine_weights: dict[str, float]) -> dict[str, float]:
        updated = dict(engine_weights)
        for key, delta in adjustments.items():
            updated[key] = updated.get(key, 0.0) + delta
        return updated


class InvestmentCommittee:
    def decide(self, votes: list[dict[str, Any]]) -> dict[str, Any]:
        pros = [v for v in votes if v.get("vote") == "approve"]
        cons = [v for v in votes if v.get("vote") != "approve"]
        return {"final_decision": "approve" if len(pros) > len(cons) else "reject", "agent_votes": votes, "disagreement_points": [v.get("reason") for v in cons], "agreement_level": len(pros) / max(len(votes), 1), "final_reason_ja": "合議結果を確定しました。"}


class FinalApprovalGate:
    def check(self, packet: dict[str, Any]) -> bool:
        return bool(packet.get("evidence_ok") and packet.get("execution_ready") and packet.get("stop_loss_plan") and packet.get("take_profit_plan") and not packet.get("red_team_critical"))
