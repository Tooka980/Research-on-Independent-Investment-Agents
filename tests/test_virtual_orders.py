from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from independent_investment_agents.agents.virtual_order_agent import VirtualOrderAgent, VirtualRiskAgent, apply_risk_result
from independent_investment_agents.domain.virtual_orders import DecisionTrace, OrderStatus, ResearchTask, VirtualExecution, VirtualOrder
from independent_investment_agents.repositories.virtual_order_repository import VirtualOrderRepository
from independent_investment_agents.simulation.virtual_execution import VirtualSimulationEngine


class VirtualOrderTests(unittest.TestCase):
    def test_non_actionable_decisions_create_research_tasks(self) -> None:
        agent = VirtualOrderAgent()
        for decision_type in ("research_more", "hold", "watch_only", "blocked"):
            result = agent.create_order(
                {
                    "id": f"dc-{decision_type}",
                    "target_symbol": "6758.T",
                    "decision_type": decision_type,
                    "related_evidence_ids": ["ev-1"],
                },
                {"cash": 100_000},
                {"symbol": "6758.T", "close": 3000},
            )
            self.assertIsInstance(result, ResearchTask)
            self.assertEqual(result.task_type, "non_actionable_decision")

    def test_actionable_buy_candidate_creates_virtual_order_when_guards_pass(self) -> None:
        order = VirtualOrderAgent().create_order(
            {
                "id": "dc-2",
                "target_symbol": "6758.T",
                "decision_type": "buy_candidate",
                "side": "buy",
                "order_type": "market",
                "related_evidence_ids": ["ev-price", "ev-news"],
                "reason": "テスト用の根拠付き仮想注文。",
                "position_size_reason": "cash cap and conviction",
                "stop_loss_plan": "cut loss when support breaks",
                "take_profit_plan": "review and partial take profit near target",
                "expected_return": 0.03,
                "expected_risk": 0.02,
                "risk_reward_ratio": 1.5,
            },
            {"cash": 200_000},
            {"symbol": "6758.T", "close": 3000},
        )
        self.assertIsInstance(order, VirtualOrder)
        risk = VirtualRiskAgent(max_order_value=120_000).check_virtual_order(order, {"cash": 200_000}, {"close": 3000, "has_ohlcv": True})
        self.assertTrue(risk.passed)
        apply_risk_result(order, risk)
        self.assertEqual(order.status, OrderStatus.APPROVED_FOR_SIMULATION)
        execution = VirtualSimulationEngine().process_virtual_order(order, {"open": 2990, "high": 3050, "low": 2980, "close": 3000}, {"cash": 200_000, "positions": {}})
        self.assertIsInstance(execution, VirtualExecution)
        self.assertEqual(order.status, OrderStatus.SIMULATED_FILLED)

    def test_actionable_sell_candidate_creates_virtual_order_when_guards_pass(self) -> None:
        order = VirtualOrderAgent().create_order(
            {
                "id": "dc-sell",
                "target_symbol": "6758.T",
                "decision_type": "sell_candidate",
                "side": "sell",
                "order_type": "market",
                "related_evidence_ids": ["ev-price"],
                "position_size_reason": "reduce exposure",
                "stop_loss_plan": "hard stop above invalidation",
                "take_profit_plan": "take profit in tranches",
                "expected_return": 0.02,
                "expected_risk": 0.01,
                "risk_reward_ratio": 1.4,
            },
            {"cash": 200_000, "positions": [{"symbol": "6758.T", "quantity": 100}]},
            {"symbol": "6758.T", "close": 3000},
        )
        self.assertIsInstance(order, VirtualOrder)

    def test_small_buy_candidate_without_trade_plan_is_research_task(self) -> None:
        result = VirtualOrderAgent().create_order(
            {
                "id": "dc-small-buy-missing-plan",
                "target_symbol": "6758.T",
                "decision_type": "small_buy_candidate",
                "side": "buy",
                "related_evidence_ids": ["ev-1"],
                "expected_return": 0.03,
                "expected_risk": 0.02,
                "risk_reward_ratio": 1.2,
            },
            {"cash": 100_000},
            {"symbol": "6758.T", "close": 3000},
        )
        self.assertIsInstance(result, ResearchTask)
        self.assertEqual(result.task_type, "missing_trade_plan_for_virtual_order")

    def test_buy_candidate_with_bad_risk_reward_is_research_task(self) -> None:
        result = VirtualOrderAgent().create_order(
            {
                "id": "dc-buy-bad-rr",
                "target_symbol": "6758.T",
                "decision_type": "buy_candidate",
                "side": "buy",
                "related_evidence_ids": ["ev-1"],
                "position_size_reason": "position sizing rationale",
                "stop_loss_plan": "stop below support",
                "take_profit_plan": "take at resistance",
                "expected_return": 0.01,
                "expected_risk": 0.02,
                "risk_reward_ratio": 0.5,
            },
            {"cash": 100_000},
            {"symbol": "6758.T", "close": 3000},
        )
        self.assertIsInstance(result, ResearchTask)

    def test_virtual_order_waits_when_market_closed(self) -> None:
        order = VirtualOrderAgent().create_order(
            {
                "id": "dc-closed",
                "target_symbol": "6758.T",
                "decision_type": "buy_candidate",
                "side": "buy",
                "order_type": "market",
                "related_evidence_ids": ["ev-price", "ev-news"],
                "position_size_reason": "cash cap and conviction",
                "stop_loss_plan": "cut loss when support breaks",
                "take_profit_plan": "review and partial take profit near target",
                "expected_return": 0.03,
                "expected_risk": 0.02,
                "risk_reward_ratio": 1.5,
            },
            {"cash": 200_000},
            {"symbol": "6758.T", "close": 3000},
        )
        self.assertIsInstance(order, VirtualOrder)
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
                    "decision_type": "buy_candidate",
                    "side": "buy",
                    "related_evidence_ids": ["ev-1"],
                    "position_size_reason": "position sizing rationale",
                    "stop_loss_plan": "stop below support",
                    "take_profit_plan": "take at resistance",
                    "expected_return": 0.03,
                    "expected_risk": 0.02,
                    "risk_reward_ratio": 1.3,
                },
                {"cash": 100_000},
                {"symbol": "7203.T", "close": 2500},
            )
            self.assertIsInstance(order, VirtualOrder)
            repo.append_order(order)
            repo.append_decision_trace(DecisionTrace("dc-3", ["ev-1"], order.id, None, "proposed", "仮想注文を作成。"))
            self.assertEqual(len(repo.read_orders()), 1)
            self.assertEqual(len(repo.read_decision_traces()), 1)
            self.assertIn("Virtual Order History", repo.read_markdown())


if __name__ == "__main__":
    unittest.main()
