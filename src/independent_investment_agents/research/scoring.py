from __future__ import annotations

import math
from dataclasses import asdict, dataclass
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiFactorScoringEngine:
    def score(self, *, symbol_payload: dict[str, Any], portfolio_state: dict[str, Any], evidence_refs: list[str]) -> MultiFactorScore:
        quote = symbol_payload.get("quote", {})
        change_pct = _safe_float(quote.get("changePct"))
        volume = _safe_float(quote.get("volume"))
        beta = _safe_float(quote.get("beta"), default=1.0)
        trailing_pe = _safe_float(quote.get("trailingPE"))
        cash = _safe_float(portfolio_state.get("cash"))
        equity = max(_safe_float(portfolio_state.get("equity"), default=cash or 1.0), 1.0)
        cash_ratio = cash / equity
        market_score = 0.55
        momentum_score = _clamp(0.5 + change_pct / 12.0)
        volume_score = 0.6 if volume > 0 else 0.35
        news_score = _clamp(0.35 + 0.08 * len(evidence_refs))
        fundamental_score = 0.58 if symbol_payload.get("businessSummary") or symbol_payload.get("longName") else 0.45
        valuation_score = 0.55 if trailing_pe <= 0 else _clamp(0.75 - min(trailing_pe, 80) / 160)
        risk_score = _clamp(0.25 + abs(change_pct) / 15.0 + max(0.0, beta - 1.0) / 2.0)
        liquidity_score = 0.65 if volume > 0 else 0.35
        portfolio_fit_score = _clamp(0.45 + cash_ratio)
        confidence_score = _clamp(0.3 + 0.12 * min(len(evidence_refs), 4))
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


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
