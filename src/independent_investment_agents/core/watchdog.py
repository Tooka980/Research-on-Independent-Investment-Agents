from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Iterable


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass
class WatchdogEvent:
    agent_id: str
    status: str
    message: str
    stale_seconds: float
    action: str = "warn"
    restart_count: int = 0
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentWatchdog:
    def __init__(
        self,
        *,
        heartbeat_timeout_seconds: float = 30.0,
        check_interval_seconds: float = 5.0,
        auto_restart: bool = True,
        max_restart_count: int = 3,
        cooldown_seconds: float = 60.0,
        restart_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.check_interval_seconds = check_interval_seconds
        self.auto_restart = auto_restart
        self.max_restart_count = max_restart_count
        self.cooldown_seconds = cooldown_seconds
        self.restart_callback = restart_callback
        self.events: list[WatchdogEvent] = []
        self.restart_counts: dict[str, int] = {}
        self._last_restart_monotonic: dict[str, float] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def check(self, agent_snapshots: Iterable[dict[str, Any]]) -> list[WatchdogEvent]:
        now = datetime.now(UTC)
        emitted: list[WatchdogEvent] = []
        for snapshot in agent_snapshots:
            agent_id = str(snapshot.get("agent_id") or "")
            status = str(snapshot.get("status") or "unknown")
            if not agent_id or status in {"stopped"}:
                continue
            heartbeat_at = _parse_iso(str(snapshot.get("last_heartbeat") or snapshot.get("heartbeat_at") or ""))
            stale_seconds = (now - heartbeat_at).total_seconds() if heartbeat_at else self.heartbeat_timeout_seconds + 1
            if stale_seconds <= self.heartbeat_timeout_seconds:
                continue
            action = self._action_for(agent_id)
            event = WatchdogEvent(
                agent_id=agent_id,
                status=status,
                stale_seconds=round(stale_seconds, 3),
                action=action,
                restart_count=self.restart_counts.get(agent_id, 0),
                message=f"heartbeat stale for {stale_seconds:.1f}s",
            )
            emitted.append(event)
            with self._lock:
                self.events.append(event)
            if action == "restart":
                try:
                    assert self.restart_callback is not None
                    self.restart_callback(agent_id)
                    with self._lock:
                        self.restart_counts[agent_id] = self.restart_counts.get(agent_id, 0) + 1
                        self._last_restart_monotonic[agent_id] = time.monotonic()
                        event.restart_count = self.restart_counts[agent_id]
                except Exception as exc:  # pragma: no cover - defensive watchdog guard
                    failure = WatchdogEvent(
                        agent_id=agent_id,
                        status=status,
                        stale_seconds=round(stale_seconds, 3),
                        action="restart_failed",
                        restart_count=self.restart_counts.get(agent_id, 0),
                        message=str(exc),
                    )
                    emitted.append(failure)
                    with self._lock:
                        self.events.append(failure)
        return emitted

    def _action_for(self, agent_id: str) -> str:
        if not self.auto_restart or self.restart_callback is None:
            return "warn"
        with self._lock:
            restart_count = self.restart_counts.get(agent_id, 0)
            if restart_count >= self.max_restart_count:
                return "max_restart_count_reached"
            last_restart = self._last_restart_monotonic.get(agent_id)
            if last_restart is not None and time.monotonic() - last_restart < self.cooldown_seconds:
                return "cooldown"
        return "restart"

    def start(self, snapshot_provider: Callable[[], Iterable[dict[str, Any]]]) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()

        def loop() -> None:
            while not self._stop_event.wait(self.check_interval_seconds):
                self.check(snapshot_provider())

        self._thread = threading.Thread(target=loop, name="agent-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "heartbeatTimeoutSeconds": self.heartbeat_timeout_seconds,
                "autoRestart": self.auto_restart,
                "maxRestartCount": self.max_restart_count,
                "cooldownSeconds": self.cooldown_seconds,
                "restartCounts": dict(self.restart_counts),
                "events": [event.to_dict() for event in self.events[-20:]],
            }
