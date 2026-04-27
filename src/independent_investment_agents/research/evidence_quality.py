from __future__ import annotations

import re
import urllib.request
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
            impact = min(impact, 0.55)
            evidence.impact_reason_ja = evidence.impact_reason_ja or "ニュース本文が未取得のため、見出しのみの根拠として控えめに評価しました。"
        if evidence.body_fetched and evidence.verified_body:
            impact = NewsImpactScorer().score(evidence)
        evidence.credibility_score = min(1.0, max(0.0, reliability))
        evidence.impact_score = min(1.0, max(0.0, impact))
        evidence.headline_only = headline_only
        evidence.source_reliability_basis = basis
        evidence.score_reason = (
            f"credibility initialized from {basis}; "
            f"impact capped for headline-only evidence" if headline_only else f"credibility initialized from {basis}"
        )
        return evidence


class ArticleBodyFetcher:
    def fetch(self, evidence: EvidenceRecord, *, timeout_seconds: float = 5.0) -> EvidenceRecord:
        if not evidence.url_or_path.startswith(("http://", "https://")):
            evidence.headline_only = True
            evidence.body_fetch_error = "unsupported_url"
            return evidence
        try:
            request = urllib.request.Request(evidence.url_or_path, headers={"User-Agent": "IIA-ResearchBot/1.0"})
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(250_000).decode("utf-8", errors="ignore")
        except Exception as exc:  # pragma: no cover - network behavior is intentionally best effort
            evidence.headline_only = True
            evidence.body_fetched = False
            evidence.body_fetch_error = exc.__class__.__name__
            evidence.impact_reason_ja = "ニュース本文が未取得のため、見出しのみの根拠として扱います。"
            return evidence
        text = _html_to_text(body)
        if len(text) < 160:
            evidence.headline_only = True
            evidence.body_fetch_error = "body_too_short"
            return evidence
        evidence.raw_text_path = evidence.raw_text_path or ""
        evidence.summary = evidence.summary or ArticleSummarizer().summarize(text)
        evidence.extracted_facts = evidence.extracted_facts or [evidence.summary]
        evidence.body_fetched = True
        evidence.verified_body = True
        evidence.headline_only = False
        warning = HeadlineBodyMismatchChecker().warning(evidence.title, text)
        if warning:
            evidence.headline_body_warning = warning
        evidence.materiality_label = MaterialityClassifier().classify(text)
        evidence.horizon_label = ShortTermLongTermClassifier().classify(text)
        return evidence


class ArticleSummarizer:
    def summarize(self, body_text: str, *, max_chars: int = 280) -> str:
        text = " ".join(body_text.split())
        return text[:max_chars]


class HeadlineBodyMismatchChecker:
    def warning(self, headline: str, body_text: str) -> str:
        headline_terms = _keywords(headline)
        body_terms = _keywords(body_text)
        if not headline_terms:
            return ""
        overlap = len(headline_terms & body_terms) / max(len(headline_terms), 1)
        if overlap < 0.25:
            return "見出しと本文の主要語が大きくずれている可能性があります。"
        return ""


class MaterialityClassifier:
    def classify(self, text: str) -> str:
        lowered = text.lower()
        if _has_any(lowered, ("earnings", "guidance", "profit", "loss", "merger", "acquisition", "決算", "業績", "買収", "提携")):
            return "material"
        return "background"


class ShortTermLongTermClassifier:
    def classify(self, text: str) -> str:
        lowered = text.lower()
        if _has_any(lowered, ("today", "tomorrow", "short-term", "near-term", "本日", "短期", "直近")):
            return "short_term"
        if _has_any(lowered, ("long-term", "strategy", "investment", "中期", "長期", "戦略", "投資")):
            return "long_term"
        return "unknown"


class NewsImpactScorer:
    def score(self, evidence: EvidenceRecord | dict[str, Any]) -> float:
        payload = evidence.to_dict() if hasattr(evidence, "to_dict") else dict(evidence)
        base = float(payload.get("impact_score") or 0.0)
        if payload.get("headline_only") or not payload.get("body_fetched"):
            return min(base, 0.55)
        materiality = str(payload.get("materiality_label") or "")
        credibility = float(payload.get("credibility_score") or 0.0)
        if materiality == "material" and credibility >= 0.6:
            return min(1.0, max(base, 0.72))
        return min(0.78, max(base, 0.45))


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
        weight = 0.55 if evidence.headline_only else 1.0
        if evidence.duplicate_of:
            weight = 0.0
        previous = evidence.outcome_score
        weighted_score = outcome_score * weight
        evidence.outcome_score = weighted_score if previous is None else round((previous + weighted_score) / 2.0, 6)
        if decision_id not in evidence.used_in_decisions:
            evidence.used_in_decisions.append(decision_id)
        return evidence

    def apply_decision_outcome(self, evidence_records: list[EvidenceRecord], outcome: dict[str, Any]) -> list[EvidenceRecord]:
        score = _outcome_score(outcome)
        used = {str(item) for item in outcome.get("used_evidence_ids", [])}
        return [self.apply(record, score, str(outcome.get("decision_id") or "")) if record.id in used else record for record in evidence_records]


def _html_to_text(html: str) -> str:
    text = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _keywords(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[A-Za-z0-9一-龥ぁ-んァ-ヶ]{3,}", text or "")}


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle.lower() in text for needle in needles)


def _outcome_score(outcome: dict[str, Any]) -> float:
    final = str(outcome.get("final_outcome") or "")
    if final in {"effective_vs_benchmark", "short_term_success", "risk_reduction_success"}:
        return 1.0
    if final in {"short_term_failed", "missed_or_adverse"}:
        return -1.0
    return 0.0
