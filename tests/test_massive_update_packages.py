from independent_investment_agents.simulation.realistic_trading import VirtualBroker, VirtualOrderRequest
from independent_investment_agents.research.advanced_agents import (
    AgentSelfEvaluator,
    EnhancedRedTeamAgent,
    FinalApprovalGate,
    FundamentalAnalystAgent,
    InvestmentCommittee,
    MarketStructureAgent,
    NewsReasoningAgent,
    OutcomeFeedbackApplier,
    PortfolioManagerAgent,
    SelfReflectionReport,
)


def test_market_and_limit_and_stop_and_partial_fill() -> None:
    broker = VirtualBroker()
    market = broker.submit(VirtualOrderRequest(symbol="7203.T", side="buy", order_type="market", quantity=100), {"close": 1000, "high": 1010, "low": 995, "volume_available": 1000}, market_is_open=True)
    assert market.status == "filled"
    pending = broker.submit(VirtualOrderRequest(symbol="7203.T", side="buy", order_type="limit", quantity=10, limit_price=900), {"close": 1000, "high": 1020, "low": 950}, market_is_open=True)
    assert pending.status == "pending"
    stop = broker.submit(VirtualOrderRequest(symbol="7203.T", side="sell", order_type="stop", quantity=20, stop_price=990), {"close": 995, "high": 1002, "low": 980}, market_is_open=True)
    assert stop.status in {"filled", "partial_fill"}
    partial = broker.submit(VirtualOrderRequest(symbol="7203.T", side="buy", order_type="market", quantity=100), {"close": 1010, "high": 1015, "low": 1000, "volume_available": 25}, market_is_open=True)
    assert partial.status == "partial_fill"


def test_commission_slippage_average_cost_and_pnl_and_sell_rejection() -> None:
    broker = VirtualBroker()
    broker.submit(VirtualOrderRequest(symbol="6758.T", side="buy", order_type="market", quantity=10), {"close": 1000, "high": 1001, "low": 999}, market_is_open=True)
    second = broker.submit(VirtualOrderRequest(symbol="6758.T", side="buy", order_type="market", quantity=10), {"close": 1100, "high": 1101, "low": 1099}, market_is_open=True)
    pos = broker.positions.get("6758.T")
    assert pos is not None and pos.average_cost > 1000
    assert second.commission > 0 and second.slippage > 0
    sell = broker.submit(VirtualOrderRequest(symbol="6758.T", side="sell", order_type="market", quantity=5), {"close": 1200, "high": 1205, "low": 1190}, market_is_open=True)
    assert sell.realized_pnl > 0
    rejected = broker.submit(VirtualOrderRequest(symbol="6758.T", side="sell", order_type="market", quantity=1000), {"close": 1200, "high": 1205, "low": 1190}, market_is_open=True)
    assert rejected.status == "rejected"


def test_reject_when_required_candle_prices_are_missing() -> None:
    broker = VirtualBroker()

    no_close = broker.submit(VirtualOrderRequest(symbol="7203.T", side="buy", order_type="market", quantity=10), {"high": 1010, "low": 995}, market_is_open=True)
    assert no_close.status == "pending"
    assert no_close.execution_price == 0.0

    no_low_for_limit_buy = broker.submit(VirtualOrderRequest(symbol="7203.T", side="buy", order_type="limit", quantity=10, limit_price=1000), {"high": 1010, "close": 1005}, market_is_open=True)
    assert no_low_for_limit_buy.status == "pending"

    no_high_for_stop_buy = broker.submit(VirtualOrderRequest(symbol="7203.T", side="buy", order_type="stop", quantity=10, stop_price=1000), {"low": 990, "close": 995}, market_is_open=True)
    assert no_high_for_stop_buy.status == "pending"


def test_agent_intelligence_and_self_eval_and_committee() -> None:
    assert "trend" in MarketStructureAgent().analyze({"changePct": 1.2, "volume": 100, "volatility": 0.2})["findings"]
    assert NewsReasoningAgent().analyze({"body_fetched": False})["findings"]["見出しのみ"] is True
    assert "PER" in FundamentalAnalystAgent().analyze({"PBR": 1.1})["findings"]["unknowns"]
    assert PortfolioManagerAgent().analyze({"sectors": {"tech": 0.7}})["findings"]["sector_concentration"] is True
    assert EnhancedRedTeamAgent().review({"headline_only": True})["findings"]["should_downgrade"] is True

    summary = AgentSelfEvaluator().summarize([
        {"final_outcome": "short_term_success", "return_7d": 0.02, "contribution_to_equity": 100},
        {"final_outcome": "miss", "return_7d": -0.01, "contribution_to_equity": -50},
    ])
    assert summary["win_rate"] == 0.5
    report = SelfReflectionReport().generate([{"return_7d": -0.02}])
    assert report["改善タスク"]
    adjusted = OutcomeFeedbackApplier().apply({"news": 0.1}, {"news": 0.3})
    assert adjusted["news"] == 0.4

    decision = InvestmentCommittee().decide([
        {"agent": "market", "vote": "approve", "reason": "trend"},
        {"agent": "red", "vote": "reject", "reason": "risk"},
        {"agent": "exec", "vote": "approve", "reason": "ready"},
    ])
    assert decision["disagreement_points"]
    assert FinalApprovalGate().check({"evidence_ok": True, "execution_ready": True, "stop_loss_plan": True, "take_profit_plan": True, "red_team_critical": False}) is True
    assert FinalApprovalGate().check({"evidence_ok": True, "execution_ready": True, "stop_loss_plan": True, "take_profit_plan": True, "red_team_critical": True}) is False
