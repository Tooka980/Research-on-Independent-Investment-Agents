from __future__ import annotations

import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from independent_investment_agents.agents.base_agent import BaseAgent
from independent_investment_agents.core.agent_runtime import AgentRuntime, AgentRuntimeConfig
from independent_investment_agents.core.task_queue import ErrorResult, TaskEnvelope
from independent_investment_agents.core.watchdog import AgentWatchdog


class FastAgent(BaseAgent):
    name = "Fast Agent"

    def handle_task(self, task: TaskEnvelope) -> dict[str, str]:
        return {"handled": task.task_type}


class FrozenAgent(BaseAgent):
    name = "Frozen Agent"

    def handle_task(self, task: TaskEnvelope) -> dict[str, str]:
        time.sleep(1.0)
        return {"handled": task.task_type}


class FailingAgent(BaseAgent):
    name = "Failing Agent"

    def handle_task(self, task: TaskEnvelope) -> dict[str, str]:
        raise RuntimeError("planned failure")


class AgentRuntimeTests(unittest.TestCase):
    def test_normal_agent_updates_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AgentRuntime(
                AgentRuntimeConfig(
                    task_timeout_seconds=0.2,
                    heartbeat_timeout_seconds=2.0,
                    log_dir=Path(tmp) / "logs",
                )
            )
            agent = FastAgent(agent_id="fast", heartbeat_interval_seconds=0.02)
            runtime.register_agent(agent, factory=lambda: FastAgent(agent_id="fast", heartbeat_interval_seconds=0.02))
            runtime.start()
            try:
                first = agent.snapshot()["last_heartbeat"]
                time.sleep(0.08)
                second = agent.snapshot()["last_heartbeat"]
            finally:
                runtime.stop()
        self.assertNotEqual(first, second)
        self.assertEqual(agent.snapshot()["status"], "stopped")

    def test_watchdog_detects_stale_heartbeat_with_cooldown(self) -> None:
        restarted: list[str] = []
        watchdog = AgentWatchdog(
            heartbeat_timeout_seconds=1.0,
            cooldown_seconds=30.0,
            max_restart_count=2,
            restart_callback=restarted.append,
        )
        stale_at = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
        events = watchdog.check([{"agent_id": "frozen", "status": "busy", "last_heartbeat": stale_at}])
        cooldown_events = watchdog.check([{"agent_id": "frozen", "status": "busy", "last_heartbeat": stale_at}])
        self.assertEqual(events[0].action, "restart")
        self.assertEqual(cooldown_events[0].action, "cooldown")
        self.assertEqual(restarted, ["frozen"])

    def test_timeout_returns_error_result_without_blocking_other_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AgentRuntime(
                AgentRuntimeConfig(
                    task_timeout_seconds=0.05,
                    heartbeat_timeout_seconds=2.0,
                    log_dir=Path(tmp) / "logs",
                )
            )
            fast = FastAgent(agent_id="fast")
            frozen = FrozenAgent(agent_id="frozen")
            runtime.register_agent(fast, factory=lambda: FastAgent(agent_id="fast"))
            runtime.register_agent(frozen, factory=lambda: FrozenAgent(agent_id="frozen"))
            runtime.start()
            try:
                task_ids = runtime.submit_tasks(
                    [
                        TaskEnvelope("fast_task", {}, target_agent_id="fast", timeout_seconds=0.1, max_attempts=1),
                        TaskEnvelope("frozen_task", {}, target_agent_id="frozen", timeout_seconds=0.05, max_attempts=1),
                    ]
                )
                results = runtime.wait_for_results(task_ids, timeout_seconds=1.0)
            finally:
                runtime.stop()

        by_agent = {result.agent_id: result for result in results}
        self.assertTrue(by_agent["fast"].ok)
        self.assertFalse(by_agent["frozen"].ok)
        self.assertIsInstance(by_agent["frozen"].error, ErrorResult)
        self.assertEqual(by_agent["frozen"].error.error_type, "timeout")
        self.assertEqual(by_agent["frozen"].attempts, 1)

    def test_failed_agent_does_not_stop_other_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AgentRuntime(
                AgentRuntimeConfig(
                    task_timeout_seconds=0.2,
                    heartbeat_timeout_seconds=2.0,
                    log_dir=Path(tmp) / "logs",
                )
            )
            runtime.register_agent(FailingAgent(agent_id="bad"), factory=lambda: FailingAgent(agent_id="bad"))
            runtime.register_agent(FastAgent(agent_id="good"), factory=lambda: FastAgent(agent_id="good"))
            runtime.start()
            try:
                task_ids = runtime.submit_tasks(
                    [
                        TaskEnvelope("bad_task", {}, target_agent_id="bad", timeout_seconds=0.1, max_attempts=1),
                        TaskEnvelope("good_task", {}, target_agent_id="good", timeout_seconds=0.1, max_attempts=1),
                    ]
                )
                results = runtime.wait_for_results(task_ids, timeout_seconds=1.0)
            finally:
                runtime.stop()
        by_agent = {result.agent_id: result for result in results}
        self.assertFalse(by_agent["bad"].ok)
        self.assertTrue(by_agent["good"].ok)
        self.assertEqual(by_agent["bad"].error.error_type, "RuntimeError")

    def test_restart_agent_restarts_only_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AgentRuntime(
                AgentRuntimeConfig(
                    task_timeout_seconds=0.2,
                    heartbeat_timeout_seconds=2.0,
                    log_dir=Path(tmp) / "logs",
                )
            )
            target = FastAgent(agent_id="target")
            other = FastAgent(agent_id="other")
            runtime.register_agent(target, factory=lambda: FastAgent(agent_id="target"))
            runtime.register_agent(other, factory=lambda: FastAgent(agent_id="other"))
            runtime.start()
            try:
                self.assertTrue(runtime.restart_agent("target"))
                replacement = runtime.agents["target"]
                untouched = runtime.agents["other"]
            finally:
                runtime.stop()
        self.assertIsNot(replacement, target)
        self.assertIs(untouched, other)
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["restartCounts"]["target"], 1)


if __name__ == "__main__":
    unittest.main()
