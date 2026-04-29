from __future__ import annotations

import tempfile
import unittest
from datetime import timezone
from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from independent_investment_agents.agents.virtual_order_agent import VirtualOrderAgent
from independent_investment_agents.core.agent_runtime import AgentRuntimeConfig
from independent_investment_agents.domain.virtual_orders import ResearchTask
from independent_investment_agents.performance import (
    AgentContributionScorer,
    DecisionOutcomeTracker,
    EvidenceContributionScorer,
    PerformanceRepository,
    calculate_performance_metrics,
)
from independent_investment_agents.research import AgentRunContext, ResearchOrganization, ResearchRepository
from independent_investment_agents.research.agents import NewsIntelligenceAgent
from independent_investment_agents.research.evidence_quality import EvidenceDeduplicator, EvidenceQualityPolicy
from independent_investment_agents.research.models import EvidenceRecord, ResearchTask as StoredResearchTask, utc_now_iso
from independent_investment_agents.research.news_analysis import NewsArticleAnalyzer
from independent_investment_agents.research.scoring import MultiFactorScoringEngine
from independent_investment_agents.research.simulation_modes import BacktestMode, LookAheadBiasChecker
from independent_investment_agents.research.symbol_queue import build_symbol_processing_plan
from independent_investment_agents.research.trading_runtime import AgentRuntimeEngine, SharedTradingContext


class AssetMaximizationExpansionTests(unittest.TestCase):
    def test_research_organization_does_not_truncate_watchlist_over_eight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = ResearchRepository(Path(tmp) / "research.sqlite3")
            watchlist = [{"symbol": f"{1300 + idx}.T", "changePct": idx} for idx in range(12)]
            context = AgentRunContext(
                focus_symbol="1300.T",
                market={"phase": "closed", "is_open": False},
                focus={
                    "symbol": "1300.T",
                    "quote": {"changePct": 1.2, "current": 1000, "asOf": utc_now_iso()},
                    "enName": "Test",
                    "metrics": {},
                    "dataQuality": {"hasAnalysisHistory": True, "metaSource": "yfinance"},
                },
                portfolio={"cash": 300_000, "equity": 1_000_000, "positions": []},
                news_items=[{"source": "Fixture", "title": "Test news", "summary": "summary", "impact": "Medium"}],
                watchlist=watchlist,
            )
            snapshot = ResearchOrganization(
                repo,
                AgentRuntimeConfig(max_symbols_per_cycle=8, task_timeout_seconds=0.5),
            ).run_snapshot(context)
            self.assertEqual(snapshot["symbolProcessing"]["total_watchlist_symbols"], 12)
            self.assertEqual(snapshot["symbolProcessing"]["pendingCount"], 4)
            self.assertEqual(len(context.watchlist), 12)

    def test_symbol_queue_batches_without_dropping_pending_symbols(self) -> None:
        plan = build_symbol_processing_plan(
            focus_symbol="1000.T",
            watchlist=[{"symbol": f"{1000 + idx}.T", "changePct": idx} for idx in range(20)],
            positions=[{"symbol": f"{2000 + idx}.T"} for idx in range(5)],
            batch_size=8,
        )
        self.assertEqual(plan.total_unique_symbols, 25)
        self.assertEqual(len(plan.processing_symbols), 8)
        self.assertEqual(len(plan.pending_symbols), 17)
        self.assertTrue({item.status for item in plan.queue}.issuperset({"selected", "queued"}))
        self.assertIn("2000.T", plan.processing_symbols + plan.pending_symbols)
        self.assertIn("1019.T", plan.processing_symbols + plan.pending_symbols)

    def test_positions_json_loads_all_rows_without_limit(self) -> None:
        from independent_investment_agents.app import web_dashboard

        with tempfile.TemporaryDirectory() as tmp:
            positions_path = Path(tmp) / "positions.json"
            positions_path.write_text(
                json.dumps(
                    {
                        "positions": [
                            {"symbol": f"{3000 + idx}.T", "market": "JP", "quantity": idx + 1, "average_cost": 1000}
                            for idx in range(20)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            original = web_dashboard.POSITIONS_FILE
            web_dashboard.POSITIONS_FILE = positions_path
            try:
                rows = web_dashboard._load_positions()
            finally:
                web_dashboard.POSITIONS_FILE = original
            self.assertEqual(len(rows), 20)

    def test_decision_outcome_tracker_persists_all_horizons(self) -> None:
        decision = {
            "id": "dc-test",
            "target_symbol": "6758.T",
            "created_at": utc_now_iso(),
            "side": "buy",
            "target_value": 100_000,
            "related_evidence_ids": ["ev-1"],
            "related_findings": ["find-1"],
        }
        prices = [{"close": 100 + idx} for idx in range(40)]
        outcomes = DecisionOutcomeTracker().evaluate(
            [decision],
            price_history_by_symbol={"6758.T": prices},
            benchmark_history=[{"close": 100 + idx * 0.5} for idx in range(40)],
        )
        self.assertIsNotNone(outcomes[0].return_1d)
        self.assertIsNotNone(outcomes[0].return_3d)
        self.assertIsNotNone(outcomes[0].return_7d)
        self.assertIsNotNone(outcomes[0].return_30d)
        with tempfile.TemporaryDirectory() as tmp:
            repo = PerformanceRepository(Path(tmp))
            repo.save_outcomes(outcomes)
            self.assertEqual(repo.read_outcomes()[0]["decision_id"], "dc-test")

    def test_evidence_quality_policy_marks_headline_only_and_source_reliability(self) -> None:
        evidence = EvidenceQualityPolicy().apply(
            EvidenceRecord(
                source_type="news",
                source_name="Google News RSS",
                url_or_path="https://example.invalid",
                title="Headline",
                published_at=None,
                collected_at=utc_now_iso(),
                related_symbols=["6758.T"],
                related_topics=["news"],
                raw_text_path=None,
                summary="headline only",
                extracted_facts=["headline"],
                sentiment_score=0.0,
                relevance_score=0.7,
                credibility_score=0.1,
                freshness_score=0.9,
                impact_score=0.9,
            )
        )
        self.assertTrue(evidence.headline_only)
        self.assertLessEqual(evidence.impact_score, 0.62)
        self.assertIn("Google News", evidence.source_reliability_basis)

    def test_buy_candidate_without_trade_plan_is_blocked(self) -> None:
        result = VirtualOrderAgent().create_order(
            {
                "id": "dc-research-missing-plan",
                "target_symbol": "6758.T",
                "decision_type": "buy_candidate",
                "side": "buy",
                "related_evidence_ids": ["ev-1"],
            },
            {"cash": 100_000},
            {"symbol": "6758.T", "close": 3000},
        )
        self.assertIsInstance(result, ResearchTask)
        self.assertEqual(result.task_type, "missing_trade_plan_for_virtual_order")

    def test_display_only_agent_is_not_reported_as_real_worker(self) -> None:
        context = SharedTradingContext(
            market_state={"is_open": True, "phase": "open", "label": "TSE"},
            portfolio_state={"cash": 500_000, "equity": 1_000_000, "positions": []},
            evidence_refs=["ev-price", "ev-company"],
            latest_prices={"6758.T": 3000.0},
            candidate_symbols=["6758.T"],
            risk_limits={"min_confidence_to_trade": 0.5},
        )
        snapshot = AgentRuntimeEngine().run(context)
        ui_agent = next(item for item in snapshot["agentRuntime"] if item["agent_id"] == "ui-agent")
        self.assertEqual(ui_agent["agent_reality_type"], "display_only")
        self.assertFalse(ui_agent["actual_processing_enabled"])

    def test_task_deduplicator_prevents_duplicate_open_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = ResearchRepository(Path(tmp) / "research.sqlite3")
            task = StoredResearchTask("news_collection", ["6758.T"], "same topic", 1, "test", "open", "reason")
            repo.save_task(task)
            repo.save_task(StoredResearchTask("news_collection", ["6758.T"], "same topic", 1, "test", "open", "reason"))
            rows = repo.list_tasks(limit=20)
            self.assertEqual(len([row for row in rows if row.topic == "same topic"]), 1)

    def test_backtest_mode_filters_future_evidence(self) -> None:
        mode = BacktestMode("2026-01-02T00:00:00+00:00")
        filtered = LookAheadBiasChecker().filter_evidence(
            [
                {"id": "past", "available_at": "2026-01-01T00:00:00+00:00"},
                {"id": "future", "available_at": "2026-01-03T00:00:00+00:00"},
            ],
            data_as_of=mode.data_as_of,
        )
        self.assertEqual([item["id"] for item in filtered], ["past"])

    def test_duplicate_evidence_does_not_inflate_effective_ids(self) -> None:
        ids = EvidenceDeduplicator().effective_evidence_ids(
            [
                {"id": "ev-1", "duplicate_of": None},
                {"id": "ev-2", "duplicate_of": "ev-1"},
            ]
        )
        self.assertEqual(ids, ["ev-1"])

    def test_contribution_scorers_reflect_decision_outcomes(self) -> None:
        outcomes = [
            {
                "decision_id": "dc-1",
                "target_symbol": "6758.T",
                "final_outcome": "short_term_success",
                "contribution_to_equity": 1200.0,
                "used_evidence_ids": ["ev-1"],
                "related_agent_findings": ["find-1"],
            }
        ]
        agents = AgentContributionScorer().score(outcomes, [{"id": "find-1", "agent_name": "Strategy"}])
        evidence = EvidenceContributionScorer().score(outcomes, [{"id": "ev-1", "source_type": "news"}])
        self.assertEqual(agents[0]["contributionToEquity"], 1200.0)
        self.assertEqual(evidence[0]["sourceType"], "news")

    def test_performance_metrics_include_drawdown_and_benchmark_excess(self) -> None:
        metrics = calculate_performance_metrics(
            [{"equity": 100}, {"equity": 120}, {"equity": 90}, {"equity": 130}],
            benchmark_points=[{"close": 100}, {"close": 110}],
            initial_equity=100,
        )
        self.assertIn("maxDrawdownPct", metrics)
        self.assertIn("benchmarkExcessReturnPct", metrics)
        self.assertGreater(metrics["portfolioEquity"], 0)

    def test_news_article_analyzer_failed_fetch_is_headline_only(self) -> None:
        result = NewsArticleAnalyzer().analyze(title="Test headline", url="https://invalid.invalid/not-found")
        self.assertTrue(result.headline_only)
        self.assertFalse(result.body_fetched)

    def test_news_without_url_skips_body_fetch_and_remains_headline_only(self) -> None:
        context = AgentRunContext(
            focus_symbol="6758.T",
            market={"phase": "open"},
            focus={"quote": {}, "dataQuality": {}},
            portfolio={"cash": 100000, "equity": 100000},
            news_items=[{"source": "Google News", "title": "見出しのみニュース", "url_missing": True}],
            watchlist=[],
        )
        output = NewsIntelligenceAgent().run(context)
        self.assertTrue(output.evidence[0].headline_only)
        self.assertFalse(output.evidence[0].body_fetched)

    def test_headline_only_news_caps_news_and_confidence_score(self) -> None:
        score = MultiFactorScoringEngine().score(
            symbol_payload={"quote": {"changePct": 1.0}, "metrics": {}},
            portfolio_state={"cash": 1000, "equity": 1000},
            evidence_refs=[{"id": "news-1", "headline_only": True, "body_fetched": False, "credibility_score": 1.0, "impact_score": 1.0}],
        )
        self.assertLessEqual(score.news_score, 0.55)
        self.assertLessEqual(score.confidence_score, 0.42)


    def test_iso_parsers_normalize_naive_and_aware_to_utc(self) -> None:
        from independent_investment_agents.core.watchdog import _parse_iso
        from independent_investment_agents.performance.outcome_tracker import _parse_dt as outcome_parse_dt
        from independent_investment_agents.research.simulation_modes import _parse_dt as sim_parse_dt

        naive = "2026-01-01T09:00:00"
        aware = "2026-01-01T09:00:00+09:00"

        for parser in (_parse_iso, outcome_parse_dt, sim_parse_dt):
            parsed_naive = parser(naive)
            parsed_aware = parser(aware)
            self.assertIsNotNone(parsed_naive)
            self.assertIsNotNone(parsed_aware)
            assert parsed_naive is not None and parsed_aware is not None
            self.assertEqual(parsed_naive.tzinfo, timezone.utc)
            self.assertEqual(parsed_aware.tzinfo, timezone.utc)

    def test_decision_outcome_tracker_accepts_naive_created_at_and_data_as_of(self) -> None:
        decision = {
            "id": "dc-naive",
            "target_symbol": "6758.T",
            "created_at": "2026-01-01T00:00:00",
            "data_as_of": "2026-01-01T00:00:00",
            "side": "buy",
            "target_value": 10_000,
        }
        prices = [{"time": "2026-01-01T00:00:00+00:00", "close": 100.0}, {"time": "2026-01-02T00:00:00+00:00", "close": 101.0}]
        outcomes = DecisionOutcomeTracker().evaluate([decision], price_history_by_symbol={"6758.T": prices})
        self.assertEqual(outcomes[0].decision_id, "dc-naive")

    def test_symbol_rotation_policy_accepts_naive_next_process_at(self) -> None:
        from independent_investment_agents.research.symbol_queue import SymbolRotationPolicy

        selected = SymbolRotationPolicy().select([
            {"symbol": "6758.T", "status": "queued", "priority": 1, "next_process_at": "2026-01-01T00:00:00"},
            {"symbol": "7203.T", "status": "queued", "priority": 2, "next_process_at": None},
        ], 2)
        self.assertIn("6758.T", selected)


if __name__ == "__main__":
    unittest.main()
