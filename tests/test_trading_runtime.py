from __future__ import annotations

import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from independent_investment_agents.research.trading_runtime import (
    AgentRuntimeEngine,
    SharedTradingContext,
    TradeProposal,
    TradingConsensusGate,
    VirtualTrader,
)


def context(is_open: bool = True, cash: float = 500_000) -> SharedTradingContext:
    return SharedTradingContext(
        market_state={"is_open": is_open, "phase": "open" if is_open else "closed", "label": "TSE"},
        portfolio_state={"cash": cash, "equity": 1_000_000, "positions": []},
        evidence_refs=["ev-price-6758.T", "ev-company-6758.T"],
        latest_prices={"6758.T": 3300.0},
        candidate_symbols=["6758.T", "7203.T"],
        risk_limits={"max_order_value": 120_000, "min_cash_ratio": 0.12},
    )


class TradingRuntimeTests(unittest.TestCase):
    def test_two_virtual_traders_share_context(self) -> None:
        shared = context(is_open=True, cash=500_000)
        proposal_a = VirtualTrader("virtual-trader-a", "growth").propose(shared)
        proposal_b = VirtualTrader("virtual-trader-b", "risk").propose(shared)
        self.assertIsNotNone(proposal_a)
        self.assertIsNone(proposal_b)
        self.assertEqual(proposal_a.evidence_refs, shared.evidence_refs)
        self.assertEqual(proposal_a.symbol, shared.candidate_symbols[0])

    def test_conflict_returns_review_without_selected_order(self) -> None:
        shared = context(is_open=True)
        proposals = [
            TradeProposal("virtual-trader-a", "6758.T", "buy", "rebalance", 0.7, 0.02, [], shared.evidence_refs),
            TradeProposal("virtual-trader-b", "6758.T", "sell", "liquidation", 0.7, 0.02, [], shared.evidence_refs),
        ]
        consensus = TradingConsensusGate().decide(proposals, shared)
        self.assertEqual(consensus.status, "needs_review")
        self.assertIsNone(consensus.selected_proposal)

    def test_market_closed_blocks_proposals_and_execution_path(self) -> None:
        snapshot = AgentRuntimeEngine().run(context(is_open=False))
        self.assertEqual(snapshot["tradingConsensus"]["status"], "waiting_for_market")
        self.assertEqual(snapshot["tradeProposals"], [])
        trading_states = [item for item in snapshot["agentRuntime"] if item["company"] == "virtual-trading"]
        research_states = [item for item in snapshot["agentRuntime"] if item["company"] in {"research", "quant-analysis"}]
        self.assertTrue(all(item["status"] == "waiting_for_market" for item in trading_states))
        self.assertTrue(any(item["status"] in {"running", "success"} for item in research_states))

    def test_data_unavailable_blocks_consensus(self) -> None:
        shared = context(is_open=True)
        shared.data_quality_by_symbol["6758.T"] = {
            "priceSource": "data_unavailable",
            "hasDisplayHistory": False,
            "hasAnalysisHistory": False,
            "needsResearch": True,
        }
        consensus = TradingConsensusGate().decide([], shared)
        self.assertEqual(consensus.status, "blocked")
        self.assertIn("refresh_price_source", consensus.required_research_tasks)

    def test_companies_are_bilingual_and_include_added_agents(self) -> None:
        snapshot = AgentRuntimeEngine().run(context(is_open=True))
        companies = snapshot["companies"]
        labels = [agent["label_ja"] for company in companies for agent in company["agents"]]
        self.assertIn("市場スキャナー", labels)
        self.assertIn("セクター観測員", labels)
        self.assertIn("流動性監視員", labels)
        self.assertIn("相関・分散分析員", labels)
        self.assertIn("候補銘柄選別員", labels)
        self.assertTrue(all(company["labelJa"] and company["labelEn"] for company in companies))

    def test_runtime_payload_has_no_mock_trading_data(self) -> None:
        snapshot = AgentRuntimeEngine().run(context(is_open=True))
        self.assertNotIn("mock", json.dumps(snapshot, ensure_ascii=False).lower())


if __name__ == "__main__":
    unittest.main()
