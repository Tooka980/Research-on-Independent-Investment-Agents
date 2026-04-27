from __future__ import annotations

from typing import Any


class AgentContributionScorer:
    def score(self, outcomes: list[dict[str, Any]], findings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        finding_agent_by_id = {
            str(item.get("id")): str(item.get("agent_name") or "Unknown Agent")
            for item in (findings or [])
        }
        grouped: dict[str, dict[str, Any]] = {}
        for outcome in outcomes:
            agents = [
                finding_agent_by_id.get(str(finding_id), str(finding_id))
                for finding_id in outcome.get("related_agent_findings", [])
                if finding_id
            ] or ["Strategy Synthesis Agent"]
            contribution = float(outcome.get("contribution_to_equity") or 0.0)
            success = str(outcome.get("final_outcome") or "") in {"effective_vs_benchmark", "short_term_success"}
            for agent in agents:
                row = grouped.setdefault(agent, {"agent": agent, "decisions": 0, "wins": 0, "contributionToEquity": 0.0})
                row["decisions"] += 1
                row["wins"] += 1 if success else 0
                row["contributionToEquity"] += contribution / max(len(agents), 1)
        for row in grouped.values():
            row["winRate"] = round(row["wins"] / row["decisions"], 4) if row["decisions"] else 0.0
            row["contributionToEquity"] = round(row["contributionToEquity"], 2)
        return sorted(grouped.values(), key=lambda item: item["contributionToEquity"], reverse=True)
