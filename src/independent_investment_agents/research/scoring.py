from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MultiFactorScore:
    market_score: float
    momentum_score: float
    volume_score: float
    news_score: float
    fundamental_score: float
    valuation_score: float
    risk_score: float
    liquidity_score: float
    portfolio_fit_score: float
    confidence_score: float
    total_score: float
    missing_information: list[str] = field(default_factory=list)
    score_reason_ja: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiFactorScoringEngine:
    def score(self, *, symbol_payload: dict[str, Any], portfolio_state: dict[str, Any], evidence_refs: list[Any]) -> MultiFactorScore:
        quote = symbol_payload.get("quote", {})
        metrics = symbol_payload.get("metrics", {}) or {}
        missing: list[str] = []
        reasons: list[str] = []
        change_pct = _metric(quote, metrics, "changePct", "change_pct", default=0.0, missing=missing)
        volume = _metric(quote, metrics, "volume", default=None, missing=missing)
        average_volume = _metric(quote, metrics, "averageVolume", "average_volume", default=None, missing=missing)
        beta = _metric(quote, metrics, "beta", default=None, missing=missing)
        trailing_pe = _metric(quote, metrics, "trailingPE", "trailing_pe", "PER", default=None, missing=missing)
        trailing_eps = _metric(quote, metrics, "trailingEps", "trailingEPS", "EPS", default=None, missing=missing)
        market_cap = _metric(quote, metrics, "marketCap", "market_cap", default=None, missing=missing)
        cash = _safe_float(portfolio_state.get("cash"))
        equity = max(_safe_float(portfolio_state.get("equity"), default=cash or 1.0), 1.0)
        cash_ratio = cash / equity
        market_score = 0.55
        momentum_score = _clamp(0.5 + change_pct / 12.0)
        if volume is None or volume <= 0 or average_volume is None or average_volume <= 0:
            volume_score = 0.28
            liquidity_score = 0.3
            reasons.append("出来高データが不足しているため、流動性スコアを低く評価しました。")
        else:
            volume_ratio = volume / max(average_volume, 1.0)
            volume_score = _clamp(0.35 + min(volume_ratio, 3.0) * 0.18)
            liquidity_score = _clamp(0.35 + min(volume_ratio, 3.0) * 0.14)
        effective_evidence = _effective_evidence(evidence_refs)
        body_checked = sum(1 for item in effective_evidence if isinstance(item, dict) and item.get("body_fetched"))
        headline_only = sum(1 for item in effective_evidence if isinstance(item, dict) and item.get("headline_only"))
        if effective_evidence and any(isinstance(item, dict) for item in effective_evidence):
            news_quality = sum(float((item if isinstance(item, dict) else {}).get("credibility_score") or 0.5) * float((item if isinstance(item, dict) else {}).get("impact_score") or 0.35) for item in effective_evidence)
            news_score = _clamp(0.30 + news_quality / max(len(effective_evidence), 1))
            if headline_only and not body_checked:
                news_score = min(news_score, 0.55)
                reasons.append("本文確認済みニュースがないため、ニューススコアは控えめに評価しました。")
        else:
            news_score = _clamp(0.35 + 0.08 * len(effective_evidence))
        fundamental_score = 0.58 if symbol_payload.get("businessSummary") or symbol_payload.get("longName") or market_cap else 0.42
        if trailing_pe is None:
            valuation_score = 0.42
            reasons.append("PER が取得できないため、バリュエーション評価は保留しました。")
        elif trailing_pe <= 0:
            valuation_score = 0.38
            reasons.append("PER が0以下のため、バリュエーション評価を低めに扱いました。")
        else:
            valuation_score = _clamp(0.75 - min(trailing_pe, 80) / 160)
        beta_for_risk = beta if beta is not None else 1.25
        if beta is None:
            reasons.append("beta が取得できないため、リスクスコアを保守的に評価しました。")
        if trailing_eps is None:
            reasons.append("EPS が取得できないため、収益性の確信度を下げました。")
        risk_score = _clamp(0.25 + abs(change_pct) / 15.0 + max(0.0, beta_for_risk - 1.0) / 2.0)
        portfolio_fit_score = _clamp(0.45 + cash_ratio)
        missing_penalty = min(0.28, 0.04 * len(set(missing)))
        confidence_score = _clamp(0.3 + 0.12 * min(len(effective_evidence), 4) - missing_penalty)
        total = (
            market_score * 0.10
            + momentum_score * 0.15
            + volume_score * 0.10
            + news_score * 0.15
            + fundamental_score * 0.10
            + valuation_score * 0.10
            + portfolio_fit_score * 0.10
            + confidence_score * 0.10
            - risk_score * 0.20
        )
        return MultiFactorScore(
            market_score=round(market_score, 4),
            momentum_score=round(momentum_score, 4),
            volume_score=round(volume_score, 4),
            news_score=round(news_score, 4),
            fundamental_score=round(fundamental_score, 4),
            valuation_score=round(valuation_score, 4),
            risk_score=round(risk_score, 4),
            liquidity_score=round(liquidity_score, 4),
            portfolio_fit_score=round(portfolio_fit_score, 4),
            confidence_score=round(confidence_score, 4),
            total_score=round(total, 4),
            missing_information=sorted(set(missing)),
            score_reason_ja=reasons,
        )


class ExpectedReturnModel:
    def estimate(self, score: MultiFactorScore) -> float:
        return round((score.total_score - 0.45) * 0.20, 6)


class RiskRewardScorer:
    def ratio(self, expected_return: float, expected_risk: float) -> float:
        risk = abs(expected_risk)
        return round(expected_return / risk, 4) if risk > 0 else 0.0


class PositionSizingEngine:
    def target_value(self, *, equity: float, cash: float, score: MultiFactorScore, expected_risk: float) -> tuple[float, str]:
        max_loss_budget = max(equity * 0.01, 0.0)
        risk_based = max_loss_budget / max(abs(expected_risk), 0.01)
        score_based = equity * max(0.01, min(score.total_score, 0.08))
        target = min(cash * 0.12, risk_based, score_based)
        return round(max(0.0, target), 2), "sized by 1% max loss budget, cash cap, and multi-factor score"


class StopLossTakeProfitEngine:
    def build(self, *, current_price: float, expected_return: float, expected_risk: float) -> tuple[str, str, float | None]:
        if current_price <= 0:
            return "", "", None
        stop_pct = min(max(abs(expected_risk), 0.03), 0.12)
        take_pct = max(expected_return, stop_pct * 1.5, 0.04)
        stop_price = round(current_price * (1.0 - stop_pct), 2)
        return (
            f"stop if price closes below {stop_price}",
            f"take profit or review near {round(current_price * (1.0 + take_pct), 2)}",
            stop_price,
        )


class PortfolioOptimizer:
    def allowed(self, score: MultiFactorScore) -> bool:
        return score.total_score > 0.42 and score.risk_score < 0.85


class CorrelationRiskModel:
    def estimate(self, symbol: str, portfolio_state: dict[str, Any]) -> float:
        positions = portfolio_state.get("positions") or []
        if isinstance(positions, dict):
            held = set(positions)
        else:
            held = {str(item.get("symbol")) for item in positions if isinstance(item, dict)}
        return 0.65 if symbol in held else 0.35


class DrawdownGuard:
    def blocked(self, max_drawdown: float, *, threshold: float = 0.20) -> bool:
        return max_drawdown >= threshold


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _metric(quote: dict[str, Any], metrics: dict[str, Any], *keys: str, default: float | None, missing: list[str]) -> float | None:
    for key in keys:
        if key in quote and quote.get(key) not in {None, ""}:
            return _safe_float(quote.get(key), default=default or 0.0)
        if key in metrics and metrics.get(key) not in {None, ""}:
            return _safe_float(metrics.get(key), default=default or 0.0)
    missing.append(keys[0])
    return default


def _effective_evidence(evidence_refs: list[Any]) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for item in evidence_refs:
        if isinstance(item, dict):
            if item.get("duplicate_of"):
                continue
            evidence_id = str(item.get("id") or item.get("url_or_path") or len(output))
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            output.append(item)
        else:
            text = str(item)
            if text and text not in seen:
                seen.add(text)
                output.append(text)
    return output


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
