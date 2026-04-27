from __future__ import annotations

import math
from typing import Any


def calculate_performance_metrics(
    equity_points: list[dict[str, Any]],
    *,
    benchmark_points: list[dict[str, Any]] | None = None,
    initial_equity: float | None = None,
) -> dict[str, Any]:
    values = [_safe_float(item.get("equity")) for item in equity_points]
    values = [value for value in values if value is not None and value > 0]
    if not values:
        return _empty_metrics("data_unavailable")

    start = float(initial_equity or values[0])
    end = values[-1]
    returns = [
        (values[index] / values[index - 1]) - 1.0
        for index in range(1, len(values))
        if values[index - 1] > 0
    ]
    total_return = (end / start) - 1.0 if start > 0 else 0.0
    annualized_return = _annualized_return(total_return, len(values))
    max_drawdown = _max_drawdown(values)
    sharpe = _sharpe(returns)

    positive = [item for item in returns if item > 0]
    negative = [item for item in returns if item < 0]
    gross_profit = sum(positive)
    gross_loss = abs(sum(negative))
    benchmark_return = _benchmark_return(benchmark_points)
    benchmark_status = "ok" if benchmark_return is not None else "data_unavailable"

    return {
        "portfolioEquity": round(end, 2),
        "virtualTotalAssets": round(end, 2),
        "totalReturn": round(total_return, 6),
        "totalReturnPct": round(total_return * 100, 2),
        "annualizedReturn": round(annualized_return, 6),
        "annualizedReturnPct": round(annualized_return * 100, 2),
        "maxDrawdown": round(max_drawdown, 6),
        "maxDrawdownPct": round(max_drawdown * 100, 2),
        "sharpeRatio": round(sharpe, 4),
        "winRate": round((len(positive) / len(returns)) if returns else 0.0, 4),
        "profitFactor": round((gross_profit / gross_loss) if gross_loss else (gross_profit if gross_profit else 0.0), 4),
        "benchmarkReturn": round(benchmark_return, 6) if benchmark_return is not None else None,
        "benchmarkReturnPct": round(benchmark_return * 100, 2) if benchmark_return is not None else None,
        "benchmarkExcessReturn": round(total_return - benchmark_return, 6) if benchmark_return is not None else None,
        "benchmarkExcessReturnPct": round((total_return - benchmark_return) * 100, 2) if benchmark_return is not None else None,
        "benchmarkStatus": benchmark_status,
        "tradeExpectancy": round((sum(returns) / len(returns)) if returns else 0.0, 6),
        "sampleCount": len(values),
    }


def _empty_metrics(status: str) -> dict[str, Any]:
    return {
        "portfolioEquity": 0.0,
        "virtualTotalAssets": 0.0,
        "totalReturn": 0.0,
        "totalReturnPct": 0.0,
        "annualizedReturn": 0.0,
        "annualizedReturnPct": 0.0,
        "maxDrawdown": 0.0,
        "maxDrawdownPct": 0.0,
        "sharpeRatio": 0.0,
        "winRate": 0.0,
        "profitFactor": 0.0,
        "benchmarkReturn": None,
        "benchmarkReturnPct": None,
        "benchmarkExcessReturn": None,
        "benchmarkExcessReturnPct": None,
        "benchmarkStatus": status,
        "tradeExpectancy": 0.0,
        "sampleCount": 0,
    }


def _annualized_return(total_return: float, sample_count: int) -> float:
    if sample_count <= 1:
        return total_return
    years = max(sample_count - 1, 1) / 252.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0 if total_return > -1.0 else -1.0


def _max_drawdown(values: list[float]) -> float:
    peak = values[0]
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, (value / peak) - 1.0)
    return abs(max_dd)


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    stdev = math.sqrt(variance)
    return (mean / stdev) * math.sqrt(252) if stdev > 0 else 0.0


def _benchmark_return(points: list[dict[str, Any]] | None) -> float | None:
    if not points:
        return None
    values = [_safe_float(item.get("close") or item.get("equity") or item.get("value")) for item in points]
    values = [value for value in values if value is not None and value > 0]
    if len(values) < 2:
        return None
    return (values[-1] / values[0]) - 1.0


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number
