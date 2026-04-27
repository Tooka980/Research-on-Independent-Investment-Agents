from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


DEFAULT_UNIVERSE = {
    "nikkei225_seed": ["7203.T", "6758.T", "9984.T", "6861.T", "9983.T", "8306.T", "7974.T", "8035.T"],
    "topix_core30_seed": ["9432.T", "9433.T", "4502.T", "4063.T", "6501.T", "8058.T", "8316.T"],
    "etf_seed": ["1321.T", "1306.T", "1475.T", "1570.T"],
    "semiconductor_seed": ["8035.T", "6857.T", "6723.T", "6146.T"],
    "auto_seed": ["7203.T", "7267.T", "6902.T", "7201.T"],
    "bank_seed": ["8306.T", "8316.T", "8411.T"],
    "game_seed": ["7974.T", "7832.T", "3659.T", "9684.T"],
}


@dataclass(frozen=True)
class UniverseCandidate:
    symbol: str
    discovered_by: str
    reason: str
    score: float
    expected_catalyst: str = ""
    risk_notes: list[str] = field(default_factory=list)
    required_followup: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    id: str = field(default_factory=lambda: f"ucand-{uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UniverseManager:
    def build_universe(
        self,
        *,
        watchlist: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        discovered: list[UniverseCandidate] | None = None,
    ) -> list[UniverseCandidate]:
        candidates: list[UniverseCandidate] = []
        for item in watchlist:
            symbol = str(item.get("symbol") or "").upper()
            if symbol:
                candidates.append(
                    UniverseCandidate(
                        symbol=symbol,
                        discovered_by="user_watchlist",
                        reason="user supplied watchlist symbol; never dropped",
                        score=1.0,
                    )
                )
        for item in positions:
            symbol = str(item.get("symbol") or "").upper()
            if symbol:
                candidates.append(
                    UniverseCandidate(
                        symbol=symbol,
                        discovered_by="current_position",
                        reason="currently held virtual position; never dropped",
                        score=1.0,
                    )
                )
        for source, symbols in DEFAULT_UNIVERSE.items():
            for symbol in symbols:
                candidates.append(
                    UniverseCandidate(
                        symbol=symbol,
                        discovered_by=source,
                        reason=f"seed universe membership: {source}",
                        score=0.55,
                        required_followup=["confirm live liquidity", "collect current evidence"],
                    )
                )
        candidates.extend(discovered or [])
        return self._dedupe(candidates)

    def _dedupe(self, candidates: list[UniverseCandidate]) -> list[UniverseCandidate]:
        best_by_symbol: dict[str, UniverseCandidate] = {}
        for candidate in candidates:
            existing = best_by_symbol.get(candidate.symbol)
            if existing is None or candidate.score > existing.score:
                best_by_symbol[candidate.symbol] = candidate
        return sorted(best_by_symbol.values(), key=lambda item: (-item.score, item.symbol))


class MomentumDiscoveryAgent:
    def discover(self, watchlist: list[dict[str, Any]]) -> list[UniverseCandidate]:
        output = []
        for item in watchlist:
            change = _safe_float(item.get("changePct"))
            if abs(change) >= 3.0:
                output.append(UniverseCandidate(str(item.get("symbol")).upper(), "momentum_discovery", "absolute price move >= 3%", min(abs(change) / 10, 1.0)))
        return output


class VolumeSpikeDiscoveryAgent:
    def discover(self, watchlist: list[dict[str, Any]]) -> list[UniverseCandidate]:
        return [
            UniverseCandidate(str(item.get("symbol")).upper(), "volume_spike_discovery", "volume spike candidate requires follow-up", 0.52, required_followup=["fetch volume baseline"])
            for item in watchlist
            if item.get("symbol") and (item.get("dataQuality") or {}).get("hasAnalysisHistory")
        ]


class NewsDrivenDiscoveryAgent:
    def discover(self, news_items: list[dict[str, Any]]) -> list[UniverseCandidate]:
        return [
            UniverseCandidate(str(item.get("symbol") or "").upper(), "news_driven_discovery", str(item.get("title") or "news mention"), 0.58)
            for item in news_items
            if item.get("symbol")
        ]


class FundamentalDiscoveryAgent:
    def discover(self, universe: list[UniverseCandidate]) -> list[UniverseCandidate]:
        return [candidate for candidate in universe if "seed" in candidate.discovered_by and candidate.score >= 0.55]


class SectorRotationAgent(FundamentalDiscoveryAgent):
    pass


class AnomalyDetectionAgent(MomentumDiscoveryAgent):
    pass


class LiquidityScreeningAgent(VolumeSpikeDiscoveryAgent):
    pass


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
