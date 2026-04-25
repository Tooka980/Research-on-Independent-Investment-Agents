from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from independent_investment_agents.agents.virtual_order_agent import VirtualOrderAgent, VirtualRiskAgent, apply_risk_result
from independent_investment_agents.domain.virtual_orders import DecisionTrace, OrderStatus, ResearchTask, VirtualExecution
from independent_investment_agents.repositories.virtual_order_repository import VirtualOrderRepository
from independent_investment_agents.simulation.virtual_execution import VirtualSimulationEngine


class VirtualOrderTests(unittest.TestCase):
    def test_missing_evidence_creates_research_task(self) -> None:
        result = VirtualOrderAgent().create_order(
            {"id": "dc-1", "target_symbol": "6758.T"},
            {"cash": 100_000},
            {"symbol": "6758.T", "close": 3000},
        )
        self.assertIsInstance(result, ResearchTask)

    def test_virtual_order_risk_and_market_fill(self) -> None:
        order = VirtualOrderAgent().create_order(
            {
                "id": "dc-2",
                "target_symbol": "6758.T",
                "side": "buy",
                "order_type": "market",
                "related_evidence_ids": ["ev-price", "ev-news"],
                "reason": "テスト用の根拠付き仮想注文。",
            },
            {"cash": 200_000},
            {"symbol": "6758.T", "close": 3000},
        )
        self.assertNotIsInstance(order, ResearchTask)
        risk = VirtualRiskAgent(max_order_value=120_000).check_virtual_order(order, {"cash": 200_000}, {"close": 3000, "has_ohlcv": True})
        self.assertTrue(risk.passed)
        apply_risk_result(order, risk)
        self.assertEqual(order.status, OrderStatus.APPROVED_FOR_SIMULATION)
        execution = VirtualSimulationEngine().process_virtual_order(order, {"open": 2990, "high": 3050, "low": 2980, "close": 3000}, {"cash": 200_000, "positions": {}})
        self.assertIsInstance(execution, VirtualExecution)
        self.assertEqual(order.status, OrderStatus.SIMULATED_FILLED)

    def test_virtual_order_waits_when_market_closed(self) -> None:
        order = VirtualOrderAgent().create_order(
            {
                "id": "dc-closed",
                "target_symbol": "6758.T",
                "side": "buy",
                "order_type": "market",
                "related_evidence_ids": ["ev-price", "ev-news"],
            },
            {"cash": 200_000},
            {"symbol": "6758.T", "close": 3000},
        )
        self.assertNotIsInstance(order, ResearchTask)
        risk = VirtualRiskAgent().check_virtual_order(order, {"cash": 200_000}, {"close": 3000, "has_ohlcv": True})
        apply_risk_result(order, risk)
        processed = VirtualSimulationEngine().process_virtual_order(
            order,
            {"open": 2990, "high": 3050, "low": 2980, "close": 3000, "market_is_open": False, "market_phase": "closed"},
            {"cash": 200_000, "positions": {}},
        )
        self.assertNotIsInstance(processed, VirtualExecution)
        self.assertEqual(order.status, OrderStatus.SCHEDULED_FOR_NEXT_SESSION)

    def test_repository_appends_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = VirtualOrderRepository(Path(tmp))
            order = VirtualOrderAgent().create_order(
                {
                    "id": "dc-3",
                    "target_symbol": "7203.T",
                    "related_evidence_ids": ["ev-1"],
                },
                {"cash": 100_000},
                {"symbol": "7203.T", "close": 2500},
            )
            self.assertNotIsInstance(order, ResearchTask)
            repo.append_order(order)
            repo.append_decision_trace(DecisionTrace("dc-3", ["ev-1"], order.id, None, "proposed", "仮想注文を作成。"))
            self.assertEqual(len(repo.read_orders()), 1)
            self.assertEqual(len(repo.read_decision_traces()), 1)
            self.assertIn("Virtual Order History", repo.read_markdown())


if __name__ == "__main__":
    unittest.main()
