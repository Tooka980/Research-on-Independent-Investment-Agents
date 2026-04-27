from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class SimulationMode:
    name: str
    data_as_of: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BacktestMode(SimulationMode):
    def __init__(self, data_as_of: str) -> None:
        super().__init__("BacktestMode", data_as_of)


class PaperLiveMode(SimulationMode):
    def __init__(self) -> None:
        super().__init__("PaperLiveMode", datetime.now(UTC).isoformat())


class ReplayMode(SimulationMode):
    def __init__(self, data_as_of: str) -> None:
        super().__init__("ReplayMode", data_as_of)


class ManualResearchMode(SimulationMode):
    def __init__(self) -> None:
        super().__init__("ManualResearchMode", datetime.now(UTC).isoformat())


class TimestampGuard:
    def allowed(self, *, available_at: str | None, data_as_of: str) -> bool:
        if not available_at:
            return False
        available = _parse_dt(available_at)
        as_of = _parse_dt(data_as_of)
        return bool(available and as_of and available <= as_of)


class LookAheadBiasChecker:
    def filter_evidence(self, evidence_records: list[dict[str, Any]], *, data_as_of: str) -> list[dict[str, Any]]:
        guard = TimestampGuard()
        return [
            item
            for item in evidence_records
            if guard.allowed(available_at=item.get("available_at") or item.get("published_at") or item.get("collected_at"), data_as_of=data_as_of)
        ]


class DataAvailabilityChecker(TimestampGuard):
    pass


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
