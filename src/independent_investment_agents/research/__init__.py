"""Research organization models and orchestration for the simulator."""

from independent_investment_agents.research.agents import ResearchOrganization
from independent_investment_agents.core import AgentRuntime, AgentRuntimeConfig, ErrorResult, TaskEnvelope, TaskQueue, TaskResult
from independent_investment_agents.research.llm_provider import LLMProvider, TemplateLanguageProvider
from independent_investment_agents.research.models import (
    AgentFinding,
    AgentRunContext,
    AgentRunResult,
    ChatResponse,
    DecisionContext,
    EvidenceRecord,
    KnowledgeMemory,
    ResearchTask,
)
from independent_investment_agents.research.repository import ResearchRepository
from independent_investment_agents.research.evidence_quality import EvidenceQualityPolicy, SourceReliabilityTable
from independent_investment_agents.research.scoring import MultiFactorScoringEngine, PositionSizingEngine, StopLossTakeProfitEngine
from independent_investment_agents.research.simulation_modes import BacktestMode, PaperLiveMode, ReplayMode, ManualResearchMode
from independent_investment_agents.research.symbol_queue import SymbolProcessingPlan, build_symbol_processing_plan
from independent_investment_agents.research.strategy_output import StrategyOutputEngine
from independent_investment_agents.research.trading_runtime import (
    AgentEvent,
    AgentRuntimeEngine,
    AgentRuntimeStore,
    AgentRuntimeState,
    AgentTask,
    SharedTradingContext,
    TradeProposal,
    TradingConsensus,
    build_shared_trading_context,
)

__all__ = [
    "AgentFinding",
    "AgentEvent",
    "AgentRuntimeEngine",
    "AgentRuntime",
    "AgentRuntimeConfig",
    "AgentRuntimeStore",
    "AgentRuntimeState",
    "AgentRunContext",
    "AgentRunResult",
    "AgentTask",
    "ChatResponse",
    "BacktestMode",
    "DecisionContext",
    "EvidenceRecord",
    "EvidenceQualityPolicy",
    "ErrorResult",
    "KnowledgeMemory",
    "LLMProvider",
    "ManualResearchMode",
    "MultiFactorScoringEngine",
    "PaperLiveMode",
    "PositionSizingEngine",
    "ReplayMode",
    "ResearchOrganization",
    "ResearchRepository",
    "ResearchTask",
    "SharedTradingContext",
    "SourceReliabilityTable",
    "StrategyOutputEngine",
    "StopLossTakeProfitEngine",
    "SymbolProcessingPlan",
    "TemplateLanguageProvider",
    "TaskEnvelope",
    "TaskQueue",
    "TaskResult",
    "TradeProposal",
    "TradingConsensus",
    "build_symbol_processing_plan",
    "build_shared_trading_context",
]
