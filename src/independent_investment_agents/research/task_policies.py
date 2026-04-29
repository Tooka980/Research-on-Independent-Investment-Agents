from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class TaskMergeDecision:
    action: str
    reason: str
    existing_task_id: str | None = None


class TaskDeduplicator:
    def is_duplicate(self, new_task: Any, existing_tasks: list[Any], *, within_minutes: int = 120) -> TaskMergeDecision:
        new_key = self._key(new_task)
        now = datetime.now(timezone.utc)
        for task in existing_tasks:
            if self._key(task) != new_key:
                continue
            created = _parse_dt(_get(task, "created_at"))
            if created and now - created <= timedelta(minutes=within_minutes) and _get(task, "status") not in {"completed", "blocked", "stale"}:
                return TaskMergeDecision("merge", "duplicate symbol/task/topic within TTL", _get(task, "id"))
        return TaskMergeDecision("create", "no duplicate open task")

    def _key(self, task: Any) -> tuple[str, str, str]:
        symbols = ",".join(sorted(str(item).upper() for item in (_get(task, "target_symbols") or [])))
        return (symbols, str(_get(task, "task_type") or ""), str(_get(task, "topic") or "").lower())


class TaskTTL:
    def status_for(self, task: Any, *, stale_hours: int = 24, blocked_hours: int = 72) -> str:
        created = _parse_dt(_get(task, "created_at"))
        if not created:
            return str(_get(task, "status") or "open")
        age = datetime.now(timezone.utc) - created
        if age >= timedelta(hours=blocked_hours):
            return "blocked"
        if age >= timedelta(hours=stale_hours):
            return "stale"
        return str(_get(task, "status") or "open")


class TaskMergePolicy(TaskDeduplicator):
    pass


class TaskStaleDetector(TaskTTL):
    pass


class TaskPriorityRebalancer:
    def priority_for(self, task: Any) -> int:
        status = str(_get(task, "status") or "")
        priority = int(_get(task, "priority") or 5)
        if status in {"stale", "blocked"}:
            return min(9, priority + 2)
        return priority


def _get(task: Any, key: str) -> Any:
    if isinstance(task, dict):
        return task.get(key)
    return getattr(task, key, None)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
