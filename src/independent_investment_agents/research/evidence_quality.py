from __future__ import annotations

from typing import Any

from independent_investment_agents.research.models import EvidenceRecord


class SourceReliabilityTable:
    DEFAULTS: dict[str, tuple[float, str]] = {
        "official_ir": (0.96, "Official IR / TDnet"),
        "tdnet": (0.96, "Official IR / TDnet"),
        "edinet": (0.95, "EDINET filing"),
        "reuters": (0.86, "Reuters"),
        "nikkei": (0.84, "Nikkei"),
        "price_history": (0.82, "market data history"),
        "company_profile": (0.74, "company profile data"),
        "yahoo finance": (0.68, "Yahoo Finance"),
        "google news": (0.62, "Google News RSS"),
        "news": (0.60, "generic news source"),
        "message_board": (0.25, "message board"),
        "unknown": (0.18, "unknown source"),
    }

    def score_for(self, source_type: str, source_name: str) -> tuple[float, str]:
        haystack = f"{source_type} {source_name}".strip().lower()
        for key, value in self.DEFAULTS.items():
            if key in haystack:
                return value
        return self.DEFAULTS["unknown"]


class EvidenceQualityPolicy:
    def __init__(self, reliability_table: SourceReliabilityTable | None = None) -> None:
        self.reliability_table = reliability_table or SourceReliabilityTable()

    def apply(self, evidence: EvidenceRecord) -> EvidenceRecord:
        reliability, basis = self.reliability_table.score_for(evidence.source_type, evidence.source_name)
        impact = float(evidence.impact_score)
        headline_only = evidence.headline_only or (evidence.source_type == "news" and not evidence.body_fetched)
        if headline_only:
            impact = min(impact, 0.62)
        evidence.credibility_score = min(1.0, max(0.0, reliability))
        evidence.impact_score = min(1.0, max(0.0, impact))
        evidence.headline_only = headline_only
        evidence.source_reliability_basis = basis
        evidence.score_reason = (
            f"credibility initialized from {basis}; "
            f"impact capped for headline-only evidence" if headline_only else f"credibility initialized from {basis}"
        )
        return evidence


class EvidenceScoreExplainer:
    def explain(self, evidence: EvidenceRecord | dict[str, Any]) -> str:
        payload = evidence.to_dict() if hasattr(evidence, "to_dict") else dict(evidence)
        markers = []
        if payload.get("headline_only"):
            markers.append("headline_only")
        if payload.get("duplicate_of"):
            markers.append(f"duplicate_of={payload['duplicate_of']}")
        return (
            f"{payload.get('source_name')} credibility={float(payload.get('credibility_score') or 0):.2f} "
            f"impact={float(payload.get('impact_score') or 0):.2f} "
            f"{' '.join(markers)}"
        ).strip()


class EvidenceDeduplicator:
    def effective_evidence_ids(self, evidence_records: list[EvidenceRecord | dict[str, Any]]) -> list[str]:
        output: list[str] = []
        for item in evidence_records:
            payload = item.to_dict() if hasattr(item, "to_dict") else dict(item)
            if payload.get("duplicate_of"):
                continue
            evidence_id = str(payload.get("id") or "")
            if evidence_id and evidence_id not in output:
                output.append(evidence_id)
        return output


class EvidenceConflictDetector:
    def detect(self, evidence_records: list[EvidenceRecord | dict[str, Any]]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for item in evidence_records:
            payload = item.to_dict() if hasattr(item, "to_dict") else dict(item)
            for symbol in payload.get("related_symbols", []):
                by_symbol.setdefault(str(symbol), []).append(payload)
        for symbol, rows in by_symbol.items():
            positive = [row for row in rows if float(row.get("sentiment_score") or 0.0) > 0.4]
            negative = [row for row in rows if float(row.get("sentiment_score") or 0.0) < -0.4]
            if positive and negative:
                conflicts.append({"symbol": symbol, "positive": [row.get("id") for row in positive], "negative": [row.get("id") for row in negative]})
        return conflicts


class EvidenceOutcomeFeedback:
    def apply(self, evidence: EvidenceRecord, outcome_score: float, decision_id: str) -> EvidenceRecord:
        evidence.outcome_score = outcome_score
        if decision_id not in evidence.used_in_decisions:
            evidence.used_in_decisions.append(decision_id)
        return evidence
