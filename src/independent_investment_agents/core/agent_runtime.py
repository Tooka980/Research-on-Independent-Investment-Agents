from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from independent_investment_agents.agents.base_agent import BaseAgent
from independent_investment_agents.core.task_queue import TaskEnvelope, TaskQueue, TaskResult
from independent_investment_agents.core.watchdog import AgentWatchdog


@dataclass(frozen=True)
class AgentRuntimeConfig:
    activity_level: str = "active"
    research_frequency_minutes: int = 5
    max_symbols_per_cycle: int = 8
    min_confidence_to_trade: float = 0.60
    task_timeout_seconds: float = 12.0
    heartbeat_timeout_seconds: float = 30.0
    max_retries: int = 2
    auto_restart: bool = True
    max_restart_count: int = 3
    restart_cooldown_seconds: float = 60.0
    log_dir: Path = Path("logs") / "agents"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["log_dir"] = str(self.log_dir)
        return payload


def load_agent_runtime_config() -> AgentRuntimeConfig:
    def int_env(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, default))
        except (TypeError, ValueError):
            return default

    def float_env(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, default))
        except (TypeError, ValueError):
            return default

    return AgentRuntimeConfig(
        activity_level=os.environ.get("IIA_ACTIVITY_LEVEL", "active"),
        research_frequency_minutes=int_env("IIA_RESEARCH_FREQUENCY_MINUTES", 5),
        max_symbols_per_cycle=int_env("IIA_MAX_SYMBOLS_PER_CYCLE", 8),
        min_confidence_to_trade=float_env("IIA_MIN_CONFIDENCE_TO_TRADE", 0.60),
        task_timeout_seconds=float_env("IIA_TASK_TIMEOUT_SECONDS", 12.0),
        heartbeat_timeout_seconds=float_env("IIA_HEARTBEAT_TIMEOUT_SECONDS", 30.0),
        max_retries=int_env("IIA_MAX_RETRIES", 2),
        auto_restart=os.environ.get("IIA_AUTO_RESTART", "1").strip().lower() not in {"0", "false", "no"},
        max_restart_count=int_env("IIA_MAX_RESTART_COUNT", 3),
        restart_cooldown_seconds=float_env("IIA_RESTART_COOLDOWN_SECONDS", 60.0),
        log_dir=Path(os.environ.get("IIA_AGENT_LOG_DIR", str(Path("logs") / "agents"))),
    )


class AgentRuntime:
    """Lifecycle manager for multiple autonomous agents."""

    def __init__(self, config: AgentRuntimeConfig | None = None) -> None:
        self.config = config or load_agent_runtime_config()
        self.task_queue = TaskQueue()
        self.agents: dict[str, BaseAgent] = {}
        self._factories: dict[str, Callable[[], BaseAgent]] = {}
        self._lock = threading.RLock()
        self._restart_counts: dict[str, int] = {}
        self._restart_history: list[dict[str, Any]] = []
        self.watchdog = AgentWatchdog(
            heartbeat_timeout_seconds=self.config.heartbeat_timeout_seconds,
            auto_restart=self.config.auto_restart,
            max_restart_count=self.config.max_restart_count,
            cooldown_seconds=self.config.restart_cooldown_seconds,
            restart_callback=self.restart_agent,
        )
        self._started = False

    def register_agent(self, agent: BaseAgent, factory: Callable[[], BaseAgent] | None = None) -> None:
        with self._lock:
            agent.task_timeout_seconds = self.config.task_timeout_seconds
            agent.log_dir = self.config.log_dir
            self.agents[agent.agent_id] = agent
            self._restart_counts.setdefault(agent.agent_id, 0)
            if factory is not None:
                self._factories[agent.agent_id] = factory

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            agents = list(self.agents.values())
        for agent in agents:
            try:
                agent.start(self.task_queue)
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                agent.log_event("start_error", {"error_type": exc.__class__.__name__, "message": str(exc)})
        self.watchdog.start(self.agent_snapshots)

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                self.task_queue.cancel_pending("runtime stopped")
                return
            self._started = False
            agents = list(self.agents.values())
        self.watchdog.stop()
        self.task_queue.cancel_pending("runtime stopped")
        for agent in agents:
            agent.stop()

    def restart_agent(self, agent_id: str) -> bool:
        with self._lock:
            current = self.agents.get(agent_id)
            factory = self._factories.get(agent_id)
            started = self._started
            if current is None:
                return False
            self._restart_counts[agent_id] = self._restart_counts.get(agent_id, 0) + 1
            event = {
                "agent_id": agent_id,
                "restart_count": self._restart_counts[agent_id],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._restart_history.append(event)
            current.mark_restarting()
        if current is not None:
            current.stop()
        if factory is not None:
            replacement = factory()
            replacement.agent_id = agent_id
            replacement.state.agent_id = agent_id
            replacement.task_timeout_seconds = self.config.task_timeout_seconds
            replacement.log_dir = self.config.log_dir
        else:
            replacement = current
        with self._lock:
            self.agents[agent_id] = replacement
        if started:
            try:
                replacement.start(self.task_queue)
                replacement.log_event("restarted", {"restart_count": self._restart_counts.get(agent_id, 0)})
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                replacement.log_event("restart_error", {"error_type": exc.__class__.__name__, "message": str(exc)})
                return False
        return True

    def submit_task(self, task: TaskEnvelope) -> str:
        with self._lock:
            started = self._started
        if not started:
            self.start()
        return self.task_queue.put(task)

    def submit_tasks(self, tasks: list[TaskEnvelope]) -> list[str]:
        return self.task_queue.put_many(tasks)

    def wait_for_results(self, task_ids: list[str], timeout_seconds: float | None = None) -> list[TaskResult]:
        timeout = timeout_seconds if timeout_seconds is not None else self.config.task_timeout_seconds + 1.0
        return self.task_queue.wait_for_results(task_ids, timeout)

    def agent_snapshots(self) -> list[dict[str, Any]]:
        queue_counts = self.task_queue.queued_count_by_agent()
        active_counts = self.task_queue.active_count_by_agent()
        with self._lock:
            agents = list(self.agents.values())
            restart_counts = dict(self._restart_counts)
        snapshots: list[dict[str, Any]] = []
        for agent in agents:
            snapshot = agent.snapshot()
            agent_id = str(snapshot.get("agent_id") or agent.agent_id)
            snapshot["restart_count"] = restart_counts.get(agent_id, 0)
            snapshot["queued_task_count"] = queue_counts.get(agent_id, 0)
            snapshot["active_task_count"] = active_counts.get(agent_id, 0)
            snapshots.append(snapshot)
        return snapshots

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            started = self._started
            restart_history = list(self._restart_history[-20:])
            restart_counts = dict(self._restart_counts)
        return {
            "config": self.config.to_dict(),
            "agents": self.agent_snapshots(),
            "queue": self.task_queue.snapshot(),
            "watchdog": self.watchdog.snapshot(),
            "started": started,
            "restartCounts": restart_counts,
            "restartHistory": restart_history,
        }
