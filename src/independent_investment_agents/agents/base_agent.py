from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from independent_investment_agents.core.task_queue import (
    ErrorResult,
    TaskEnvelope,
    TaskQueue,
    TaskResult,
    call_with_timeout,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs" / "agents"
AGENT_STATUSES = {"initialized", "running", "idle", "busy", "error", "stopped", "restarting"}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _agent_id_from_name(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in name.strip())
    return "-".join(part for part in cleaned.split("-") if part) or "agent"


@dataclass
class AgentState:
    agent_id: str
    name: str
    status: str = "initialized"
    current_task: str | None = None
    last_heartbeat: str = field(default_factory=utc_now_iso)
    last_error: dict[str, Any] | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    last_task: str | None = None
    last_task_status: str | None = None
    last_task_completed_at: str | None = None
    task_count: int = 0
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseAgent:
    """Base lifecycle contract for autonomous agents."""

    name = "Base Agent"

    def __init__(
        self,
        *,
        agent_id: str | None = None,
        name: str | None = None,
        task_timeout_seconds: float = 12.0,
        heartbeat_interval_seconds: float = 2.0,
        log_dir: Path | None = None,
    ) -> None:
        resolved_name = name or self.name
        self.agent_id = agent_id or _agent_id_from_name(resolved_name)
        self.name = resolved_name
        self.task_timeout_seconds = task_timeout_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.state = AgentState(agent_id=self.agent_id, name=self.name)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: TaskQueue | None = None
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self._state_lock = threading.RLock()

    @property
    def status(self) -> str:
        return self.state.status

    @property
    def current_task(self) -> str | None:
        return self.state.current_task

    @property
    def last_heartbeat(self) -> str:
        return self.state.last_heartbeat

    @property
    def last_error(self) -> dict[str, Any] | None:
        return self.state.last_error

    def start(self, task_queue: TaskQueue) -> None:
        with self._state_lock:
            self._queue = task_queue
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self.state.started_at = utc_now_iso()
            self.state.stopped_at = None
            self.state.status = "running"
            self.state.current_task = None
            self._thread = threading.Thread(target=self._worker_loop, name=f"agent-{self.agent_id}", daemon=True)
            self._thread.start()
        self._write_log("started", {"status": self.state.status})

    def run(self) -> None:
        self._worker_loop()

    def stop(self) -> None:
        self._stop_event.set()
        with self._state_lock:
            self.state.status = "stopped"
            self.state.stopped_at = utc_now_iso()
            self.state.current_task = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.5, self.task_timeout_seconds + 0.5))
        self._write_log("stopped", {"status": self.state.status})

    def heartbeat(self) -> str:
        with self._state_lock:
            self.state.last_heartbeat = utc_now_iso()
            return self.state.last_heartbeat

    def mark_restarting(self) -> None:
        with self._state_lock:
            self.state.status = "restarting"
            self.state.current_task = None
        self._write_log("restarting", {"status": self.state.status})

    def handle_task(self, task: TaskEnvelope) -> Any:
        raise NotImplementedError

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            payload = self.state.to_dict()
        payload["thread_alive"] = bool(self._thread and self._thread.is_alive())
        payload["allowed_statuses"] = sorted(AGENT_STATUSES)
        payload["heartbeat_age_seconds"] = self._heartbeat_age_seconds(payload.get("last_heartbeat"))
        return payload

    def _worker_loop(self) -> None:
        if self._queue is None:
            self._record_error(
                ErrorResult(
                    agent_id=self.agent_id,
                    task_id="agent-startup",
                    error_type="RuntimeError",
                    message="task queue is not attached",
                    retryable=False,
                )
            )
            return
        while not self._stop_event.is_set():
            self.heartbeat()
            task = self._queue.pop_for_agent(self.agent_id, timeout=self.heartbeat_interval_seconds)
            if task is None:
                with self._state_lock:
                    if self.state.status not in {"stopped", "error", "restarting"}:
                        self.state.status = "idle"
                        self.state.current_task = None
                continue
            try:
                result = self._execute_task(task)
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                error = ErrorResult(
                    agent_id=self.agent_id,
                    task_id=task.task_id,
                    error_type=exc.__class__.__name__,
                    message=str(exc),
                    retryable=False,
                    details={"task_type": task.task_type},
                )
                self._record_error(error)
                result = TaskResult(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    status="error",
                    ok=False,
                    error=error,
                    logs=[error.message],
                    attempts=task.attempts,
                )
            self._queue.task_done(result)

    def _execute_task(self, task: TaskEnvelope) -> TaskResult:
        with self._state_lock:
            self.state.status = "busy"
            self.state.current_task = task.task_type
            self.state.last_task = task.task_type
        self.heartbeat()
        started_at = utc_now_iso()
        self._write_log("task_started", {"task": task.to_dict()})

        timeout = task.timeout_seconds or self.task_timeout_seconds
        max_attempts = max(1, int(task.max_attempts or 1))
        last_error: ErrorResult | None = None
        for attempt in range(1, max_attempts + 1):
            task.attempts = attempt
            result = call_with_timeout(
                lambda: self.handle_task(task),
                timeout_seconds=timeout,
                error_context={
                    "agent_id": self.agent_id,
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                },
            )
            self.heartbeat()
            if not isinstance(result, ErrorResult):
                return self._complete_success(task, result, started_at, attempt)

            result.details.update({"attempt": attempt, "max_attempts": max_attempts})
            last_error = result
            if result.retryable and attempt < max_attempts and not self._stop_event.is_set():
                self._write_log("task_retry", {"error": result.to_dict()})
                time.sleep(min(1.0, 0.2 * attempt))
                continue
            break

        error = last_error or ErrorResult(
            agent_id=self.agent_id,
            task_id=task.task_id,
            error_type="unknown",
            message="task failed without an error result",
            retryable=False,
        )
        self._record_error(error, task)
        self._write_log("task_error", {"error": error.to_dict()})
        return TaskResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status="error",
            ok=False,
            logs=[error.message],
            error=error,
            started_at=started_at,
            attempts=task.attempts,
        )

    def _complete_success(self, task: TaskEnvelope, result: Any, started_at: str, attempts: int) -> TaskResult:
        if isinstance(result, TaskResult):
            with self._state_lock:
                self.state.status = "stopped" if self._stop_event.is_set() else ("idle" if result.ok else "error")
                self.state.current_task = None
                self.state.last_task_status = result.status
                self.state.last_task_completed_at = result.completed_at
                self.state.task_count += 1
            if result.error:
                self._record_error(result.error, task)
            result.attempts = attempts
            self._write_log("task_completed", result.to_dict())
            return result

        with self._state_lock:
            self.state.status = "stopped" if self._stop_event.is_set() else "idle"
            self.state.current_task = None
            self.state.last_task_status = "success"
            self.state.last_task_completed_at = utc_now_iso()
            self.state.task_count += 1
        self._write_log("task_completed", {"task_id": task.task_id, "status": "success"})
        return TaskResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status="success",
            ok=True,
            output=result,
            started_at=started_at,
            attempts=attempts,
        )

    def _record_error(self, error: ErrorResult, task: TaskEnvelope | None = None) -> None:
        with self._state_lock:
            self.state.status = "stopped" if self._stop_event.is_set() else "error"
            self.state.current_task = None
            self.state.last_task_status = "error"
            self.state.last_task_completed_at = utc_now_iso()
            self.state.last_error = {
                "error_type": error.error_type,
                "message": error.message,
                "occurred_at": error.created_at,
                "task_id": error.task_id,
                "task_type": task.task_type if task else error.details.get("task_type"),
                "retryable": error.retryable,
                "details": dict(error.details),
            }
            self.state.error_count += 1

    def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._write_log(event_type, payload)

    def _heartbeat_age_seconds(self, value: str | None) -> float | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return round((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds(), 3)

    def _write_log(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "created_at": utc_now_iso(),
                "agent_id": self.agent_id,
                "name": self.name,
                "event_type": event_type,
                "status": self.state.status,
                "current_task": self.state.current_task,
                "payload": payload,
            }
            with (self.log_dir / f"{self.agent_id}.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass
