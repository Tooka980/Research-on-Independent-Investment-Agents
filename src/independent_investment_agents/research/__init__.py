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
    "DecisionContext",
    "EvidenceRecord",
    "ErrorResult",
    "KnowledgeMemory",
    "LLMProvider",
    "ResearchOrganization",
    "ResearchRepository",
    "ResearchTask",
    "SharedTradingContext",
    "StrategyOutputEngine",
    "TemplateLanguageProvider",
    "TaskEnvelope",
    "TaskQueue",
    "TaskResult",
    "TradeProposal",
    "TradingConsensus",
    "build_shared_trading_context",
]
