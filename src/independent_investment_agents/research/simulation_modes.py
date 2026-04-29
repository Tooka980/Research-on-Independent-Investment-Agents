from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class SimulationMode:
    name: str
    data_as_of: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(_mode_metadata(self.name))
        return payload


class BacktestMode(SimulationMode):
    def __init__(self, data_as_of: str) -> None:
        super().__init__("BacktestMode", data_as_of)


class PaperLiveMode(SimulationMode):
    def __init__(self) -> None:
        super().__init__("PaperLiveMode", datetime.now(timezone.utc).isoformat())


class ReplayMode(SimulationMode):
    def __init__(self, data_as_of: str) -> None:
        super().__init__("ReplayMode", data_as_of)


class ManualResearchMode(SimulationMode):
    def __init__(self) -> None:
        super().__init__("ManualResearchMode", datetime.now(timezone.utc).isoformat())


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


def _mode_metadata(name: str) -> dict[str, Any]:
    metadata = {
        "PaperLiveMode": {
            "label_ja": "仮想ライブ運用モード",
            "description_ja": "現在取得可能なデータで仮想運用します。",
            "allowed_processes": ["現在データ取得", "仮想注文候補", "仮想約定"],
        },
        "BacktestMode": {
            "label_ja": "バックテストモード",
            "description_ja": "過去時点で利用可能だったデータだけを使います。",
            "allowed_processes": ["指定日時以前のデータ取得", "過去判断評価"],
        },
        "ReplayMode": {
            "label_ja": "リプレイ検証モード",
            "description_ja": "過去の市場を時系列で再生します。",
            "allowed_processes": ["時系列再生", "逐次評価"],
        },
        "ManualResearchMode": {
            "label_ja": "手動調査モード",
            "description_ja": "売買候補を作らず調査結果のみ表示します。",
            "allowed_processes": ["調査表示", "Evidence確認"],
        },
    }
    return metadata.get(name, {"label_ja": name, "description_ja": "", "allowed_processes": []})


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
