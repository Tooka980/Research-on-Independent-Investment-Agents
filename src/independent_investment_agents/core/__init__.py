from independent_investment_agents.core.task_queue import ErrorResult, TaskEnvelope, TaskQueue, TaskResult, retry_call
from independent_investment_agents.core.watchdog import AgentWatchdog, WatchdogEvent

__all__ = [
    "AgentRuntime",
    "AgentRuntimeConfig",
    "AgentWatchdog",
    "ErrorResult",
    "TaskEnvelope",
    "TaskQueue",
    "TaskResult",
    "WatchdogEvent",
    "load_agent_runtime_config",
    "retry_call",
]


def __getattr__(name: str):
    if name in {"AgentRuntime", "AgentRuntimeConfig", "load_agent_runtime_config"}:
        from independent_investment_agents.core.agent_runtime import (
            AgentRuntime,
            AgentRuntimeConfig,
            load_agent_runtime_config,
        )

        values = {
            "AgentRuntime": AgentRuntime,
            "AgentRuntimeConfig": AgentRuntimeConfig,
            "load_agent_runtime_config": load_agent_runtime_config,
        }
        return values[name]
    raise AttributeError(name)
