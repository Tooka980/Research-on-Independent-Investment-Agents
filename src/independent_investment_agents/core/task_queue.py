from __future__ import annotations

import queue
import threading
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_payload(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _safe_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    return value


@dataclass
class ErrorResult:
    agent_id: str
    task_id: str
    error_type: str
    message: str
    retryable: bool = True
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    ok: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskEnvelope:
    task_type: str
    payload: dict[str, Any]
    target_agent_id: str | None = None
    priority: int = 5
    created_by: str = "system"
    max_attempts: int = 2
    timeout_seconds: float = 12.0
    task_id: str = field(default_factory=lambda: f"task-{uuid4().hex}")
    attempts: int = 0
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "payload": _safe_payload(self.payload),
            "target_agent_id": self.target_agent_id,
            "priority": self.priority,
            "created_by": self.created_by,
            "max_attempts": self.max_attempts,
            "timeout_seconds": self.timeout_seconds,
            "task_id": self.task_id,
            "attempts": self.attempts,
            "created_at": self.created_at,
        }


@dataclass
class TaskResult:
    task_id: str
    agent_id: str
    status: str
    ok: bool
    output: Any = None
    logs: list[str] = field(default_factory=list)
    error: ErrorResult | None = None
    started_at: str | None = None
    completed_at: str = field(default_factory=utc_now_iso)
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "ok": self.ok,
            "output": _safe_payload(self.output),
            "logs": list(self.logs),
            "error": self.error.to_dict() if self.error else None,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": self.attempts,
        }


class TaskQueue:
    """Small in-process priority queue for agent work.

    The queue is deliberately dependency-free so it can be introduced beside the
    current synchronous research flow. Lower priority numbers run first.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._sequence = 0
        self._pending: list[tuple[int, int, TaskEnvelope]] = []
        self._active: dict[str, TaskEnvelope] = {}
        self._completed: list[TaskResult] = []
        self._completed_by_task_id: dict[str, TaskResult] = {}

    def put(self, task: TaskEnvelope) -> str:
        with self._condition:
            self._sequence += 1
            self._pending.append((task.priority, self._sequence, task))
            self._pending.sort(key=lambda item: (item[0], item[1]))
            self._condition.notify_all()
        return task.task_id

    def put_many(self, tasks: list[TaskEnvelope]) -> list[str]:
        return [self.put(task) for task in tasks]

    def pop_for_agent(self, agent_id: str, timeout: float = 1.0) -> TaskEnvelope | None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                for index, (_priority, _sequence, task) in enumerate(self._pending):
                    if task.target_agent_id in (None, agent_id):
                        self._pending.pop(index)
                        task.attempts += 1
                        self._active[task.task_id] = task
                        return task
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def task_done(self, result: TaskResult) -> None:
        with self._condition:
            self._active.pop(result.task_id, None)
            self._completed.append(result)
            self._completed_by_task_id[result.task_id] = result
            self._condition.notify_all()

    def cancel_pending(self, reason: str = "runtime stopped") -> list[TaskResult]:
        with self._condition:
            pending = [task for _priority, _sequence, task in self._pending]
            self._pending.clear()
            results = [
                TaskResult(
                    task_id=task.task_id,
                    agent_id=task.target_agent_id or "unassigned",
                    status="cancelled",
                    ok=False,
                    error=ErrorResult(
                        agent_id=task.target_agent_id or "unassigned",
                        task_id=task.task_id,
                        error_type="cancelled",
                        message=reason,
                        retryable=False,
                    ),
                    logs=[reason],
                    attempts=task.attempts,
                )
                for task in pending
            ]
            for result in results:
                self._completed.append(result)
                self._completed_by_task_id[result.task_id] = result
            self._condition.notify_all()
            return results

    def requeue(self, task: TaskEnvelope) -> None:
        with self._condition:
            self._active.pop(task.task_id, None)
        self.put(task)

    def wait_for_results(self, task_ids: list[str], timeout_seconds: float) -> list[TaskResult]:
        wanted = set(task_ids)
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while True:
                found = [self._completed_by_task_id[task_id] for task_id in task_ids if task_id in self._completed_by_task_id]
                if len(found) == len(wanted):
                    return found
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return found
                self._condition.wait(remaining)

    def qsize(self) -> int:
        with self._condition:
            return len(self._pending)

    def active_count(self) -> int:
        with self._condition:
            return len(self._active)

    def queued_count_by_agent(self) -> dict[str, int]:
        with self._condition:
            counts: dict[str, int] = {}
            for _priority, _sequence, task in self._pending:
                key = task.target_agent_id or "unassigned"
                counts[key] = counts.get(key, 0) + 1
            return counts

    def active_count_by_agent(self) -> dict[str, int]:
        with self._condition:
            counts: dict[str, int] = {}
            for task in self._active.values():
                key = task.target_agent_id or "unassigned"
                counts[key] = counts.get(key, 0) + 1
            return counts

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            completed = self._completed[-20:]
            state_counts = {
                "pending": len(self._pending),
                "active": len(self._active),
                "completed": sum(1 for result in self._completed if result.ok),
                "failed": sum(1 for result in self._completed if not result.ok and result.status != "cancelled"),
                "cancelled": sum(1 for result in self._completed if result.status == "cancelled"),
            }
            return {
                "pending": [task.to_dict() for _priority, _sequence, task in self._pending],
                "active": [task.to_dict() for task in self._active.values()],
                "completed": [result.to_dict() for result in completed],
                "pendingCount": len(self._pending),
                "activeCount": len(self._active),
                "completedCount": len(self._completed),
                "failedCount": state_counts["failed"],
                "stateCounts": state_counts,
                "queuedTaskCountByAgent": self.queued_count_by_agent(),
                "activeTaskCountByAgent": self.active_count_by_agent(),
            }


def call_with_timeout(
    func: Callable[[], Any],
    *,
    timeout_seconds: float,
    error_context: dict[str, Any] | None = None,
) -> Any | ErrorResult:
    result_queue: queue.Queue[Any] = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            result_queue.put(("ok", func()))
        except Exception as exc:  # pragma: no cover - exact exception depends on external service
            result_queue.put(("error", exc))

    worker = threading.Thread(target=target, name="agent-timeout-call", daemon=True)
    worker.start()
    context = error_context or {}
    agent_id = str(context.get("agent_id") or "system")
    task_id = str(context.get("task_id") or "external-call")
    try:
        kind, value = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        return ErrorResult(
            agent_id=agent_id,
            task_id=task_id,
            error_type="timeout",
            message=f"operation exceeded {timeout_seconds:.1f}s",
            retryable=True,
            details=dict(context),
        )
    if kind == "ok":
        return value
    exc = value
    return ErrorResult(
        agent_id=agent_id,
        task_id=task_id,
        error_type=exc.__class__.__name__,
        message=str(exc),
        retryable=True,
        details=dict(context),
    )


def retry_call(
    func: Callable[[], Any],
    *,
    attempts: int = 2,
    timeout_seconds: float = 10.0,
    retry_delay_seconds: float = 0.25,
    error_context: dict[str, Any] | None = None,
) -> Any | ErrorResult:
    last_error: ErrorResult | None = None
    for attempt in range(max(1, attempts)):
        context = dict(error_context or {})
        context["attempt"] = attempt + 1
        result = call_with_timeout(func, timeout_seconds=timeout_seconds, error_context=context)
        if not isinstance(result, ErrorResult):
            return result
        last_error = result
        if not result.retryable or attempt >= attempts - 1:
            break
        time.sleep(retry_delay_seconds)
    return last_error or ErrorResult(
        agent_id=str((error_context or {}).get("agent_id") or "system"),
        task_id=str((error_context or {}).get("task_id") or "external-call"),
        error_type="unknown",
        message="operation failed without a result",
    )
