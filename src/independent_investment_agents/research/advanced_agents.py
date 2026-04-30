from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


SUCCESS_OUTCOMES = {"short_term_success", "effective_vs_benchmark", "success", "win"}


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


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _first_number(payload: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _as_float(payload.get(key))
        if value is not None:
            return value
    return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def _history_series(payload: dict[str, Any], key: str) -> list[float]:
    direct = payload.get(key) or payload.get(f"{key}_prices")
    if isinstance(direct, list):
        return [number for item in direct if (number := _as_float(item)) is not None]
    rows = payload.get("history") or payload.get("candles") or payload.get("ohlcv") or []
    if not isinstance(rows, list):
        return []
    series: list[float] = []
    for row in rows:
        if isinstance(row, dict):
            value = _as_float(row.get(key))
            if value is not None:
                series.append(value)
    return series


def _success(row: dict[str, Any]) -> bool:
    return str(row.get("final_outcome") or row.get("outcome") or "") in SUCCESS_OUTCOMES


class MarketStructureAgent:
    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        closes = _history_series(payload, "close")
        highs = _history_series(payload, "high")
        lows = _history_series(payload, "low")
        volumes = _history_series(payload, "volume")
        current_close = closes[-1] if closes else _first_number(payload.get("quote", payload), ["current", "close", "price"])
        change_pct = _first_number(payload, ["changePct", "change_pct", "daily_change_pct"]) or 0.0

        ma5 = _average(closes[-5:])
        ma20 = _average(closes[-20:])
        volume_average = _average(volumes[-20:])
        current_volume = _first_number(payload, ["volume", "current_volume"]) or (volumes[-1] if volumes else None)
        volume_average_ratio = (current_volume / volume_average) if current_volume is not None and volume_average else 1.0

        returns = [
            (closes[idx] / closes[idx - 1]) - 1.0
            for idx in range(1, len(closes))
            if closes[idx - 1] != 0
        ]
        volatility = _first_number(payload, ["volatility"])
        if volatility is None:
            volatility = (_stddev(returns[-20:]) or 0.0) * math.sqrt(252)
        recent_high = max(highs[-20:] or closes[-20:] or ([current_close] if current_close is not None else [0.0]))
        recent_low = min(lows[-20:] or closes[-20:] or ([current_close] if current_close is not None else [0.0]))

        if ma5 is not None and ma20 is not None:
            if ma5 > ma20 * 1.01:
                trend = "up"
            elif ma5 < ma20 * 0.99:
                trend = "down"
            else:
                trend = "range"
        else:
            trend = "up" if change_pct >= 0 else "down"
        trend_or_range = "trend" if trend in {"up", "down"} and abs(change_pct) >= 0.5 else "range"
        overheating = bool(
            (current_close is not None and ma20 is not None and current_close > ma20 * 1.08)
            or change_pct >= 5.0
            or volume_average_ratio >= 2.5
        )

        findings = {
            "trend": trend,
            "trend_or_range": trend_or_range,
            "moving_average": {"ma5": ma5, "ma20": ma20},
            "moving_average_5": ma5,
            "moving_average_20": ma20,
            "volume": current_volume or 0.0,
            "volume_average": volume_average,
            "volume_average_ratio": round(volume_average_ratio, 4),
            "volatility": round(volatility or 0.0, 6),
            "recent_high": round(recent_high, 4),
            "recent_low": round(recent_low, 4),
            "overheating": overheating,
            "overheat_label": "過熱" if overheating else "通常",
            "confidence": 0.72 if closes else 0.48,
            "score_contribution": 0.12 if trend == "up" and not overheating else (-0.08 if trend == "down" or overheating else 0.02),
        }
        return _base_result("市場構造を分析しました。", findings, ["過熱感があり、追いかけ買いは慎重に扱います。"] if overheating else [])


class NewsReasoningAgent:
    SOURCE_RELIABILITY = {
        "tdnet": 0.92,
        "nikkei": 0.86,
        "reuters": 0.84,
        "bloomberg": 0.84,
        "yahoo finance": 0.68,
        "google news": 0.58,
    }

    def analyze(self, news: dict[str, Any]) -> dict[str, Any]:
        body_fetched = bool(news.get("body_fetched"))
        headline_only = bool(news.get("headline_only", not body_fetched))
        impact_score = _first_number(news, ["impact_score", "impactScore", "materiality_score"]) or (0.35 if headline_only else 0.65)
        source_name = str(news.get("source") or news.get("source_name") or "unknown")
        source_reliability = _as_float(news.get("source_reliability"))
        if source_reliability is None:
            source_reliability = next((score for key, score in self.SOURCE_RELIABILITY.items() if key in source_name.lower()), 0.5)

        materiality_label = str(news.get("materiality_label") or ("high" if impact_score >= 0.7 else "medium" if impact_score >= 0.4 else "low"))
        title = str(news.get("title") or news.get("headline") or "")
        horizon_label = str(news.get("horizon_label") or ("long_term" if any(token in title for token in ["中期", "長期", "設備投資", "構造"]) else "short_term"))
        related_symbols = news.get("related_symbols") or []
        market_wide = bool(news.get("market_wide")) or len(related_symbols) > 2 or any(token in title for token in ["金利", "為替", "指数", "市場全体"])
        scope_label = "market_wide" if market_wide else "company_specific"
        warnings = ["見出しのみの根拠です。本文確認まで確信度を抑制します。"] if headline_only else []

        findings = {
            "本文確認済み": body_fetched,
            "見出しのみ": headline_only,
            "body_fetched": body_fetched,
            "headline_only": headline_only,
            "materiality_label": materiality_label,
            "horizon_label": horizon_label,
            "source": source_name,
            "source_reliability": round(source_reliability, 4),
            "scope_label": scope_label,
            "company_specific": scope_label == "company_specific",
            "market_wide": scope_label == "market_wide",
            "impact_score": round(impact_score * (0.75 if headline_only else 1.0), 4),
            "confidence": round(_clamp(source_reliability * (0.7 if headline_only else 1.0), 0.1, 0.95), 4),
            "score_contribution": round((impact_score - 0.5) * source_reliability, 4),
        }
        return _base_result("ニュース材料を評価しました。", findings, warnings)


class FundamentalAnalystAgent:
    METRIC_KEYS = {
        "PER": ["PER", "per", "trailingPE", "forwardPE"],
        "PBR": ["PBR", "pbr", "priceToBook"],
        "ROE": ["ROE", "roe", "returnOnEquity"],
        "EPS": ["EPS", "eps", "trailingEps"],
        "revenue_growth": ["revenue_growth", "revenueGrowth", "sales_growth", "売上成長"],
        "profit_margin": ["profit_margin", "profitMargins", "operating_margin", "利益率"],
        "dividend_yield": ["dividend_yield", "dividendYield", "配当利回り"],
        "market_cap": ["market_cap", "marketCap", "時価総額"],
    }

    def analyze(self, metrics: dict[str, Any]) -> dict[str, Any]:
        normalized = {name: _first_number(metrics, keys) for name, keys in self.METRIC_KEYS.items()}
        unknowns = [name for name, value in normalized.items() if value is None]
        roe = normalized.get("ROE") or 0.0
        profit_margin = normalized.get("profit_margin") or 0.0
        revenue_growth = normalized.get("revenue_growth") or 0.0
        score = 0.0
        score += 0.05 if roe > 0.08 else -0.02
        score += 0.04 if profit_margin > 0.08 else -0.01
        score += 0.04 if revenue_growth > 0.03 else 0.0
        findings = {
            **normalized,
            "unknowns": unknowns,
            "missing_data_count": len(unknowns),
            "valuation_label": "割安寄り" if (normalized.get("PER") or 99) < 15 and (normalized.get("PBR") or 99) < 1.5 else "中立",
            "profitability_label": "高収益" if roe > 0.12 or profit_margin > 0.12 else "要確認",
            "confidence": round(_clamp(1.0 - len(unknowns) * 0.09, 0.25, 0.9), 4),
            "score_contribution": round(score - len(unknowns) * 0.005, 4),
        }
        warnings = [f"不足データ: {', '.join(unknowns)}"] if unknowns else []
        return _base_result("ファンダメンタルを評価しました。", findings, warnings)


class PortfolioManagerAgent:
    def analyze(self, portfolio: dict[str, Any]) -> dict[str, Any]:
        cash = _as_float(portfolio.get("cash"), 0.0) or 0.0
        equity = _as_float(portfolio.get("equity"), None)
        positions = portfolio.get("positions") or []
        sectors = dict(portfolio.get("sectors") or {})

        if equity is None:
            holdings_value = sum(_as_float(row.get("market_value") or row.get("marketValue") or row.get("value"), 0.0) or 0.0 for row in positions if isinstance(row, dict))
            equity = cash + holdings_value
        cash_ratio = cash / equity if equity else 0.0

        symbol_weights: dict[str, float] = {}
        unrealized_pnl = 0.0
        for row in positions if isinstance(positions, list) else []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "unknown")
            value = _as_float(row.get("market_value") or row.get("marketValue") or row.get("value"))
            if value is None:
                quantity = _as_float(row.get("quantity"), 0.0) or 0.0
                current_price = _as_float(row.get("current_price") or row.get("current"), 0.0) or 0.0
                value = quantity * current_price
            weight = _as_float(row.get("weight")) or (value / equity if equity else 0.0)
            symbol_weights[symbol] = weight
            sector = str(row.get("sector") or row.get("sector_jp") or "unknown")
            sectors[sector] = sectors.get(sector, 0.0) + weight
            row_pnl = _as_float(row.get("unrealized_pnl") or row.get("openPnl"))
            if row_pnl is None:
                avg_cost = _as_float(row.get("average_cost") or row.get("averageCost"), 0.0) or 0.0
                quantity = _as_float(row.get("quantity"), 0.0) or 0.0
                current_price = _as_float(row.get("current_price") or row.get("current"), avg_cost) or avg_cost
                row_pnl = (current_price - avg_cost) * quantity
            unrealized_pnl += row_pnl

        max_sector = max(sectors.values(), default=0.0)
        max_symbol = max(symbol_weights.values(), default=0.0)
        equity_curve = [_as_float(item.get("equity") if isinstance(item, dict) else item) for item in (portfolio.get("equity_curve") or [])]
        clean_curve = [value for value in equity_curve if value is not None]
        max_drawdown = self._max_drawdown(clean_curve)
        sector_concentration = max_sector > float(portfolio.get("max_sector_weight", 0.4))
        symbol_concentration = max_symbol > float(portfolio.get("max_symbol_weight", 0.25))
        rebalance_needed = sector_concentration or symbol_concentration or cash_ratio < float(portfolio.get("min_cash_ratio", 0.05)) or max_drawdown < -0.12
        warnings = []
        if sector_concentration:
            warnings.append("セクター集中が高いため買い増しは小さくするか再調査が必要です。")
        if symbol_concentration:
            warnings.append("銘柄集中が高いためポジションサイズを抑制します。")

        findings = {
            "cash_ratio": round(cash_ratio, 4),
            "sector_weights": {key: round(float(value), 4) for key, value in sectors.items()},
            "sector_concentration": sector_concentration,
            "symbol_weights": {key: round(value, 4) for key, value in symbol_weights.items()},
            "symbol_concentration": symbol_concentration,
            "unrealized_pnl": round(unrealized_pnl, 4),
            "max_drawdown": round(max_drawdown, 4),
            "rebalance_needed": rebalance_needed,
            "confidence": 0.72,
            "score_contribution": -0.08 if rebalance_needed else 0.05,
        }
        return _base_result("ポートフォリオ影響を評価しました。", findings, warnings)

    @staticmethod
    def _max_drawdown(values: list[float]) -> float:
        peak: float | None = None
        worst = 0.0
        for value in values:
            peak = value if peak is None else max(peak, value)
            if peak:
                worst = min(worst, (value / peak) - 1.0)
        return worst


class EnhancedRedTeamAgent:
    def review(self, decision: dict[str, Any]) -> dict[str, Any]:
        missing_plan = not decision.get("stop_loss_plan") or not decision.get("take_profit_plan")
        headline_only = bool(decision.get("headline_only", False))
        leverage = _as_float(decision.get("leverage"), 1.0) or 1.0
        liquidity = _as_float(decision.get("liquidity"), 1.0) or 1.0
        critical = bool(decision.get("red_team_critical")) or leverage > 2.0 or liquidity <= 0
        weak = missing_plan or headline_only or critical
        warnings = []
        if missing_plan:
            warnings.append("重大警告: 損切りまたは利確計画が不足しています。")
        if headline_only:
            warnings.append("重大警告: 見出しのみEvidenceに依存しています。")
        if critical:
            warnings.append("重大警告: レバレッジまたは流動性リスクが許容外です。")
        return _base_result(
            "レッドチームレビューを実施しました。",
            {
                "should_downgrade": weak,
                "red_team_critical": critical or bool(warnings),
                "confidence": 0.82,
                "score_contribution": -0.14 if weak else 0.02,
            },
            warnings,
        )


class ExecutionReadinessAgent:
    def check(self, context: dict[str, Any]) -> dict[str, Any]:
        ready = bool(context.get("market_is_open", True)) and float(context.get("liquidity", 1.0)) > 0 and not bool(context.get("broker_api_enabled", False))
        warnings = [] if ready else ["市場時間外、流動性不足、または安全制約により仮想注文不可です。"]
        return _base_result(
            "実行可能性を確認しました。",
            {"execution_ready": ready, "order_allowed": ready, "confidence": 0.8, "score_contribution": 0.06 if ready else -0.12},
            warnings,
        )


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentVote:
    agent_name: str
    vote: str
    confidence: float
    trust_score: float
    reason_ja: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommitteeDecision:
    final_decision: str
    weighted_score: float
    agent_votes: list[dict[str, Any]]
    agreement_level: float
    disagreement_points: list[str]
    minority_opinion: str
    final_reason_ja: str
    order_allowed: bool
    decision_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentSelfEvaluator:
    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        wins = [row for row in rows if _success(row)]
        avg_ret = sum(float(row.get("return_7d", 0.0) or 0.0) for row in rows) / max(len(rows), 1)
        return {
            "task_count": len(rows),
            "win_rate": len(wins) / max(len(rows), 1),
            "average_return_7d": avg_ret,
            "contribution_to_equity": sum(float(row.get("contribution_to_equity", 0.0) or 0.0) for row in rows),
        }


class AgentTrustScoreManager:
    def calculate(self, outcomes: list[dict[str, Any]]) -> dict[str, float]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in outcomes:
            agent = str(row.get("agent_name") or row.get("agent") or row.get("agentName") or "Strategy Synthesis Agent")
            buckets.setdefault(agent, []).append(row)
        scores: dict[str, float] = {}
        total_abs_contribution = sum(abs(float(row.get("contribution_to_equity") or 0.0)) for row in outcomes) or 1.0
        for agent, rows in buckets.items():
            win_rate = sum(1 for row in rows if _success(row)) / max(len(rows), 1)
            avg_return = sum(float(row.get("return_7d") or row.get("return_30d") or 0.0) for row in rows) / max(len(rows), 1)
            contribution = sum(float(row.get("contribution_to_equity") or 0.0) for row in rows)
            score = 0.25 + win_rate * 0.45 + _clamp(avg_return * 4.0, -0.12, 0.18) + _clamp(contribution / total_abs_contribution, -0.15, 0.15)
            scores[agent] = round(_clamp(score, 0.1, 0.95), 4)
        return scores

    def scorecards(self, outcomes: list[dict[str, Any]], roles: dict[str, str] | None = None) -> list[dict[str, Any]]:
        scores = self.calculate(outcomes)
        cards: list[AgentScorecard] = []
        for agent, trust_score in scores.items():
            rows = [row for row in outcomes if str(row.get("agent_name") or row.get("agent") or row.get("agentName") or "Strategy Synthesis Agent") == agent]
            summary = AgentSelfEvaluator().summarize(rows)
            suggestion = "判断重みを維持" if trust_score >= 0.45 else "判断重みを下げて根拠品質を再点検"
            if trust_score >= 0.7:
                suggestion = "判断重みをやや上げる候補"
            cards.append(
                AgentScorecard(
                    agent,
                    (roles or {}).get(agent, "analysis"),
                    summary["task_count"],
                    round(summary["win_rate"], 4),
                    round(summary["average_return_7d"], 4),
                    round(summary["contribution_to_equity"], 4),
                    trust_score,
                    suggestion,
                )
            )
        return [card.to_dict() for card in sorted(cards, key=lambda item: item.trust_score, reverse=True)]


class FactorWeightProfileManager:
    def suggest(self, outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in outcomes:
            factor = str(row.get("factor_name") or row.get("factor") or row.get("source_type") or "unknown")
            buckets.setdefault(factor, []).append(row)
        profiles: list[dict[str, Any]] = []
        for factor, rows in buckets.items():
            count = len(rows)
            win_rate = sum(1 for row in rows if _success(row)) / max(count, 1)
            avg_return = sum(float(row.get("return_7d") or row.get("return_30d") or 0.0) for row in rows) / max(count, 1)
            contribution = sum(float(row.get("contribution_to_equity") or 0.0) for row in rows)
            delta = _clamp((win_rate - 0.5) * 0.12 + avg_return * 0.6, -0.12, 0.12)
            profiles.append(
                {
                    "factor_name": factor,
                    "decision_count": count,
                    "win_rate": round(win_rate, 4),
                    "average_return": round(avg_return, 4),
                    "contribution_to_equity": round(contribution, 4),
                    "suggested_weight_adjustment": round(delta, 4),
                    "suggestion_ja": "推奨重みを上げる候補" if delta > 0 else "推奨重みを下げる候補" if delta < 0 else "推奨重みを維持",
                    "auto_applied": False,
                }
            )
        return sorted(profiles, key=lambda item: item["suggested_weight_adjustment"], reverse=True)


class EvidenceReliabilityMemory:
    def suggest(self, outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in outcomes:
            source = str(row.get("source_name") or row.get("source") or row.get("sourceType") or row.get("source_type") or "unknown")
            buckets.setdefault(source, []).append(row)
        suggestions: list[dict[str, Any]] = []
        for source, rows in buckets.items():
            win_rate = sum(1 for row in rows if _success(row)) / max(len(rows), 1)
            avg_return = sum(float(row.get("return_7d") or row.get("return_30d") or 0.0) for row in rows) / max(len(rows), 1)
            reliability = _clamp(0.5 + (win_rate - 0.5) * 0.35 + avg_return * 1.2, 0.1, 0.95)
            suggestions.append(
                {
                    "source_name": source,
                    "decision_count": len(rows),
                    "suggested_reliability": round(reliability, 4),
                    "suggestion_ja": "信頼度を上げる候補" if reliability >= 0.58 else "信頼度を下げる候補" if reliability <= 0.42 else "信頼度を維持",
                    "auto_applied": False,
                }
            )
        return sorted(suggestions, key=lambda item: item["suggested_reliability"], reverse=True)


class DecisionPatternMemory:
    def summarize(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        failed = [row for row in outcomes if not _success(row)]
        winners = [row for row in outcomes if _success(row)]
        weak_patterns = sorted({str(row.get("decision_type") or row.get("pattern") or "unknown") for row in failed})
        strong_patterns = sorted({str(row.get("decision_type") or row.get("pattern") or "unknown") for row in winners})
        return {
            "failed_decision_count": len(failed),
            "successful_decision_count": len(winners),
            "weak_patterns": weak_patterns,
            "strong_patterns": strong_patterns,
            "suggestions_ja": [
                "失敗パターンは次回合議で反対理由として提示",
                "成功パターンは推奨重みの候補として保存",
            ],
            "auto_applied": False,
        }


class SelfReflectionReport:
    def generate(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        failed = [outcome for outcome in outcomes if float(outcome.get("return_7d", 0) or 0.0) < 0 or not _success(outcome)]
        return {
            "今回失敗した判断": len(failed),
            "改善タスク": ["損切り条件の厳格化", "見出しのみEvidenceの比率削減"],
            "agent_trust_suggestions": AgentTrustScoreManager().scorecards(outcomes),
            "factor_weight_suggestions": FactorWeightProfileManager().suggest(outcomes),
            "decision_pattern_memory": DecisionPatternMemory().summarize(outcomes),
        }


class OutcomeFeedbackApplier:
    def apply(self, adjustments: dict[str, float], engine_weights: dict[str, float]) -> dict[str, float]:
        updated = dict(engine_weights)
        for key, delta in adjustments.items():
            updated[key] = updated.get(key, 0.0) + delta
        return updated


class InvestmentCommittee:
    def decide(
        self,
        votes: list[dict[str, Any] | AgentVote],
        *,
        trust_scores: dict[str, float] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = [self._normalize_vote(vote, trust_scores or {}) for vote in votes]
        weighted_score = 0.0
        positive_weight = 0.0
        negative_weight = 0.0
        for vote in normalized:
            direction = self._vote_direction(vote.vote)
            weight = vote.confidence * vote.trust_score
            weighted_score += direction * weight
            if direction >= 0:
                positive_weight += weight
            else:
                negative_weight += abs(weight)

        context = context or {}
        execution_ready = bool(context.get("execution_ready", True)) and not any(vote.vote == "execution_not_ready" for vote in normalized)
        red_team_critical = bool(context.get("red_team_critical")) or any(
            "RedTeam" in vote.agent_name or "Red Team" in vote.agent_name or "レッド" in vote.agent_name
            for vote in normalized
            if "重大" in vote.reason_ja and vote.vote != "approve"
        )
        portfolio_concentration = bool(context.get("portfolio_concentration")) or any(
            ("Portfolio" in vote.agent_name or "ポートフォリオ" in vote.agent_name)
            and (vote.vote != "approve" or "集中" in vote.reason_ja)
            for vote in normalized
        )

        if red_team_critical:
            final_decision = "reject"
            decision_type = "blocked"
            order_allowed = False
            final_reason = "RedTeamの重大警告があるためFinalApprovalGateで停止しました。"
        elif not execution_ready:
            final_decision = "reject"
            decision_type = "research_more"
            order_allowed = False
            final_reason = "ExecutionReadinessがfalseのため、仮想注文は作成しません。"
        elif weighted_score > 0:
            proposed = str(context.get("proposed_decision") or "approve")
            if portfolio_concentration and proposed == "buy_candidate":
                final_decision = "small_buy_candidate"
                decision_type = "small_buy_candidate"
                order_allowed = True
                final_reason = "重み付き合議は賛成ですが、過集中警告により小口買いへ降格しました。"
            else:
                final_decision = "approve"
                decision_type = proposed
                order_allowed = True
                final_reason = "trust_scoreとconfidenceを反映した重み付き合議で承認しました。"
        else:
            final_decision = "reject"
            decision_type = "research_more"
            order_allowed = False
            final_reason = "trust_scoreとconfidenceを反映した重み付き合議で見送りました。"

        total_weight = positive_weight + negative_weight
        agreement_level = max(positive_weight, negative_weight) / total_weight if total_weight else 0.0
        disagreement_points = [vote.reason_ja for vote in normalized if vote.vote != "approve"]
        minority = self._minority_opinion(normalized, positive_weight, negative_weight)
        decision = CommitteeDecision(
            final_decision=final_decision,
            weighted_score=round(weighted_score, 4),
            agent_votes=[vote.to_dict() for vote in normalized],
            agreement_level=round(agreement_level, 4),
            disagreement_points=disagreement_points,
            minority_opinion=minority,
            final_reason_ja=final_reason,
            order_allowed=order_allowed,
            decision_type=decision_type,
        )
        return decision.to_dict()

    @staticmethod
    def _normalize_vote(vote: dict[str, Any] | AgentVote, trust_scores: dict[str, float]) -> AgentVote:
        if isinstance(vote, AgentVote):
            return vote
        agent_name = str(vote.get("agent_name") or vote.get("agent") or vote.get("name") or "unknown_agent")
        confidence = _clamp(float(vote.get("confidence", 0.5) or 0.5), 0.0, 1.0)
        trust_score = _clamp(float(vote.get("trust_score", trust_scores.get(agent_name, 0.5)) or 0.5), 0.0, 1.0)
        return AgentVote(
            agent_name=agent_name,
            vote=str(vote.get("vote") or "reject"),
            confidence=confidence,
            trust_score=trust_score,
            reason_ja=str(vote.get("reason_ja") or vote.get("reason") or ""),
        )

    @staticmethod
    def _vote_direction(vote: str) -> float:
        if vote in {"approve", "buy_candidate", "small_buy_candidate"}:
            return 1.0
        if vote in {"hold", "research_more", "watch"}:
            return -0.35
        return -1.0

    @staticmethod
    def _minority_opinion(votes: list[AgentVote], positive_weight: float, negative_weight: float) -> str:
        if not votes:
            return ""
        if positive_weight >= negative_weight:
            minority = [vote.reason_ja for vote in votes if vote.vote != "approve" and vote.reason_ja]
        else:
            minority = [vote.reason_ja for vote in votes if vote.vote == "approve" and vote.reason_ja]
        return " / ".join(minority[:2])


class FinalApprovalGate:
    def check(self, packet: dict[str, Any]) -> bool:
        red_team_warnings = [str(item) for item in packet.get("red_team_warnings", [])]
        red_team_critical = bool(packet.get("red_team_critical")) or any("重大" in warning for warning in red_team_warnings)
        return bool(
            packet.get("evidence_ok")
            and packet.get("execution_ready")
            and packet.get("stop_loss_plan")
            and packet.get("take_profit_plan")
            and not red_team_critical
        )

    def review(self, packet: dict[str, Any]) -> dict[str, Any]:
        approved = self.check(packet)
        reasons = []
        if not packet.get("evidence_ok"):
            reasons.append("Evidence品質が不足")
        if not packet.get("execution_ready"):
            reasons.append("ExecutionReadinessがfalse")
        if not packet.get("stop_loss_plan"):
            reasons.append("損切り計画が不足")
        if not packet.get("take_profit_plan"):
            reasons.append("利確計画が不足")
        if packet.get("red_team_critical"):
            reasons.append("RedTeam重大警告")
        return {
            "approved": approved,
            "order_allowed": approved,
            "blocked_reasons": reasons,
            "message_ja": "最終承認しました。" if approved else "FinalApprovalGateで停止しました。",
        }
