from __future__ import annotations

import tempfile
from pathlib import Path

from independent_investment_agents.performance.outcome_feedback import OutcomeFeedbackEngine
from independent_investment_agents.research.decision_review import DecisionRedTeamAgent
from independent_investment_agents.research.models import EvidenceRecord, utc_now_iso
from independent_investment_agents.research.repository import ResearchRepository
from independent_investment_agents.research.scoring import MultiFactorScoringEngine


def test_duplicate_evidence_does_not_inflate_confidence() -> None:
    score = MultiFactorScoringEngine().score(
        symbol_payload={"quote": {"changePct": 1.0}, "metrics": {}},
        portfolio_state={"cash": 1000, "equity": 1000},
        evidence_refs=[
            {"id": "ev-1", "duplicate_of": None, "body_fetched": True, "headline_only": False, "credibility_score": 0.8, "impact_score": 0.7},
            {"id": "ev-2", "duplicate_of": "ev-1", "body_fetched": True, "headline_only": False, "credibility_score": 0.8, "impact_score": 0.7},
        ],
    )
    assert score.confidence_score <= 0.46


def test_body_fetched_evidence_reflects_news_score() -> None:
    score = MultiFactorScoringEngine().score(
        symbol_payload={"quote": {"changePct": 0.5}, "metrics": {}},
        portfolio_state={"cash": 1000, "equity": 1000},
        evidence_refs=[{"id": "ev-1", "body_fetched": True, "headline_only": False, "credibility_score": 1.0, "impact_score": 1.0}],
    )
    assert score.news_score > 0.9


def test_red_team_downgrades_when_trade_plan_missing() -> None:
    reviewed = DecisionRedTeamAgent().review({"decision_type": "buy_candidate", "side": "buy", "bearish_reasons": [], "invalidation_conditions": []})
    assert reviewed["should_downgrade"] is True
    assert reviewed["decision_type"] == "blocked"


def test_outcome_feedback_engine_aggregates_factor_performance() -> None:
    profiles = OutcomeFeedbackEngine().aggregate([
        {"factor_name": "news", "final_outcome": "short_term_success", "return_7d": 0.03, "return_30d": 0.05, "contribution_to_equity": 1000},
        {"factor_name": "news", "final_outcome": "miss", "return_7d": -0.01, "return_30d": 0.01, "contribution_to_equity": -200},
    ])
    assert profiles[0].factor_name == "news"
    assert profiles[0].decision_count == 2


def test_repository_stores_extended_decision_fields() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = ResearchRepository(Path(tmp) / "research.sqlite3")
        ev = EvidenceRecord("news", "Fixture", "u", "t", None, utc_now_iso(), ["6758.T"], ["news"], None, "s", ["f"], 0, 0.8, 0.8, 0.9, 0.6)
        repo.save_evidence(ev)
        assert repo.list_evidence(limit=1)[0].id == ev.id
