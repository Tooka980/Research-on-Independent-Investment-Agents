from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class FactorWeightProfile:
    factor_name: str
    decision_count: int
    win_rate: float
    average_return_7d: float
    average_return_30d: float
    contribution_to_equity: float
    suggested_weight_adjustment: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OutcomeFeedbackEngine:
    def aggregate(self, outcomes: list[dict[str, Any]]) -> list[FactorWeightProfile]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in outcomes:
            factor = str(item.get("factor_name") or "unknown")
            buckets.setdefault(factor, []).append(item)
        profiles: list[FactorWeightProfile] = []
        for factor, rows in buckets.items():
            wins = sum(1 for row in rows if str(row.get("final_outcome") or "") in {"short_term_success", "effective_vs_benchmark"})
            count = len(rows)
            avg7 = sum(float(row.get("return_7d") or 0.0) for row in rows) / max(1, count)
            avg30 = sum(float(row.get("return_30d") or 0.0) for row in rows) / max(1, count)
            cte = sum(float(row.get("contribution_to_equity") or 0.0) for row in rows)
            profiles.append(FactorWeightProfile(factor, count, wins / max(1, count), avg7, avg30, cte, (avg30 * 0.5) + (wins / max(1, count) - 0.5) * 0.2))
        return sorted(profiles, key=lambda p: p.contribution_to_equity, reverse=True)


class EvidenceSourceReliabilityUpdater:
    def suggested_reliability(self, outcomes: list[dict[str, Any]]) -> dict[str, float]:
        result: dict[str, float] = {}
        for row in outcomes:
            src = str(row.get("source_name") or "unknown")
            result[src] = result.get(src, 0.5) + (0.02 if str(row.get("final_outcome")) in {"short_term_success", "effective_vs_benchmark"} else -0.01)
        return {k: max(0.1, min(0.95, v)) for k, v in result.items()}


class AgentPerformanceWeighting:
    def weight(self, outcomes: list[dict[str, Any]]) -> dict[str, float]:
        perf: dict[str, float] = {}
        for row in outcomes:
            agent = str(row.get("agent_name") or "unknown")
            perf[agent] = perf.get(agent, 0.0) + float(row.get("contribution_to_equity") or 0.0)
        total = sum(abs(v) for v in perf.values()) or 1.0
        return {k: round(v / total, 4) for k, v in perf.items()}
