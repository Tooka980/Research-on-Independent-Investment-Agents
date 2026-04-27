from __future__ import annotations

from typing import Any


class EvidenceContributionScorer:
    def score(self, outcomes: list[dict[str, Any]], evidence_records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        evidence_by_id = {str(item.get("id")): item for item in (evidence_records or [])}
        grouped: dict[str, dict[str, Any]] = {}
        for outcome in outcomes:
            evidence_ids = [str(item) for item in outcome.get("used_evidence_ids", []) if item]
            contribution = float(outcome.get("contribution_to_equity") or 0.0)
            success = str(outcome.get("final_outcome") or "") in {"effective_vs_benchmark", "short_term_success"}
            for evidence_id in evidence_ids:
                evidence = evidence_by_id.get(evidence_id, {})
                source_type = str(evidence.get("source_type") or evidence.get("sourceType") or "unknown")
                row = grouped.setdefault(
                    source_type,
                    {"sourceType": source_type, "evidenceCount": 0, "wins": 0, "contributionToEquity": 0.0},
                )
                row["evidenceCount"] += 1
                row["wins"] += 1 if success else 0
                row["contributionToEquity"] += contribution / max(len(evidence_ids), 1)
        for row in grouped.values():
            row["hitRate"] = round(row["wins"] / row["evidenceCount"], 4) if row["evidenceCount"] else 0.0
            row["contributionToEquity"] = round(row["contributionToEquity"], 2)
        return sorted(grouped.values(), key=lambda item: item["contributionToEquity"], reverse=True)
