from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from independent_investment_agents.research import (
    AgentRunContext,
    EvidenceRecord,
    ResearchOrganization,
    ResearchRepository,
    TemplateLanguageProvider,
)
from independent_investment_agents.research.models import utc_now_iso


class ResearchOrganizationTests(unittest.TestCase):
    def test_evidence_duplicate_and_markdown_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = ResearchRepository(Path(tmp) / "research.sqlite3")
            first = EvidenceRecord(
                source_type="news",
                source_name="Fixture",
                url_or_path="fixture://same",
                title="Same headline",
                published_at=None,
                collected_at=utc_now_iso(),
                related_symbols=["6758.T"],
                related_topics=["news"],
                raw_text_path=None,
                summary="Same body",
                extracted_facts=["fact"],
                sentiment_score=0.0,
                relevance_score=0.8,
                credibility_score=0.8,
                freshness_score=0.8,
                impact_score=0.8,
            )
            second = EvidenceRecord(
                source_type="news",
                source_name="Fixture",
                url_or_path="fixture://same",
                title="Same headline",
                published_at=None,
                collected_at=utc_now_iso(),
                related_symbols=["6758.T"],
                related_topics=["news"],
                raw_text_path=None,
                summary="Same body",
                extracted_facts=["fact"],
                sentiment_score=0.0,
                relevance_score=0.8,
                credibility_score=0.8,
                freshness_score=0.8,
                impact_score=0.8,
            )
            repo.save_evidence(first)
            repo.save_evidence(second)
            records = repo.list_evidence()
            self.assertEqual(records[-1].duplicate_of, first.id)
            markdown = repo.export_markdown()
            self.assertIn("Research Organization Summary", markdown)

    def test_research_organization_creates_decision_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = ResearchRepository(Path(tmp) / "research.sqlite3")
            snapshot = ResearchOrganization(repo).run_snapshot(
                AgentRunContext(
                    focus_symbol="6758.T",
                    market={"phase": "closed", "is_open": False},
                    focus={
                        "symbol": "6758.T",
                        "quote": {"changePct": 1.2},
                        "enName": "Sony Group",
                        "metrics": {},
                        "dataQuality": {
                            "hasAnalysisHistory": True,
                            "metaSource": "yfinance",
                        },
                    },
                    portfolio={"cash": 300_000, "equity": 1_000_000},
                    news_items=[{"source": "Fixture", "title": "Sony test", "summary": "summary", "impact": "Medium"}],
                    watchlist=[{"symbol": "6758.T", "changePct": 1.2}],
                )
            )
            self.assertGreaterEqual(snapshot["evidenceSummary"]["evidenceTotal"], 1)
            self.assertTrue(snapshot["decisionContexts"])
            self.assertTrue(snapshot["latestDecisionContext"]["related_evidence_ids"])

    def test_template_language_provider_requires_evidence_refs(self) -> None:
        provider = TemplateLanguageProvider()
        missing = provider.generate_chat_response("test", [], {"symbol": "6758.T"})
        self.assertEqual(missing.evidence_refs, [])
        self.assertIn("evidence_refs", missing.missing_information)
        grounded = provider.generate_chat_response("test", ["ev-1"], {"symbol": "6758.T"})
        self.assertEqual(grounded.evidence_refs, ["ev-1"])


if __name__ == "__main__":
    unittest.main()
