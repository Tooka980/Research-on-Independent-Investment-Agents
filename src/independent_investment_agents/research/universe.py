from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
    universe_source_ja: str = ""
    is_seed_universe: bool = False
    is_real_data_confirmed: bool = False
    expected_catalyst: str = ""
    expected_catalyst_ja: str = ""
    risk_notes: list[str] = field(default_factory=list)
    risk_notes_ja: list[str] = field(default_factory=list)
    required_followup: list[str] = field(default_factory=list)
    required_followup_ja: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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
                        universe_source_ja="ユーザー監視銘柄",
                        is_real_data_confirmed=bool(item.get("current") or item.get("dataQuality")),
                        expected_catalyst_ja="監視銘柄として継続確認",
                        required_followup_ja=["最新価格とニュース本文を確認"],
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
                        universe_source_ja="保有銘柄",
                        is_real_data_confirmed=True,
                        expected_catalyst_ja="保有ポジションのリスク・リターン再評価",
                        risk_notes_ja=["保有中のため急落・流動性変化を優先確認"],
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
                        universe_source_ja=_source_label_ja(source),
                        is_seed_universe=True,
                        required_followup=["confirm live liquidity", "collect current evidence"],
                        required_followup_ja=["実データで流動性を確認", "最新 Evidence を収集"],
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
                output.append(
                    UniverseCandidate(
                        str(item.get("symbol")).upper(),
                        "momentum_discovery",
                        "absolute price move >= 3%",
                        min(abs(change) / 10, 1.0),
                        universe_source_ja="値動き起点",
                        is_real_data_confirmed=True,
                        expected_catalyst_ja="短期モメンタム継続または反転",
                        risk_notes_ja=["急変後の反落リスクを確認"],
                    )
                )
        return output


class VolumeSpikeDiscoveryAgent:
    def discover(self, watchlist: list[dict[str, Any]]) -> list[UniverseCandidate]:
        return [
            UniverseCandidate(
                str(item.get("symbol")).upper(),
                "volume_spike_discovery",
                "volume spike candidate requires follow-up",
                0.52,
                universe_source_ja="出来高起点",
                is_real_data_confirmed=True,
                expected_catalyst_ja="出来高急増に伴う材料確認",
                risk_notes_ja=["一時的な出来高増だけで売買候補にしない"],
                required_followup=["fetch volume baseline"],
                required_followup_ja=["平均出来高比を確認"],
            )
            for item in watchlist
            if item.get("symbol") and (item.get("dataQuality") or {}).get("hasAnalysisHistory")
        ]


class NewsDrivenDiscoveryAgent:
    def discover(self, news_items: list[dict[str, Any]]) -> list[UniverseCandidate]:
        return [
            UniverseCandidate(
                str(item.get("symbol") or "").upper(),
                "news_driven_discovery",
                str(item.get("title") or "news mention"),
                0.58,
                universe_source_ja="ニュース起点",
                is_real_data_confirmed=bool(item.get("body_fetched")),
                expected_catalyst_ja=str(item.get("title") or "ニュース材料の影響確認"),
                risk_notes_ja=["本文確認前の見出しだけでは高スコアにしない"],
                required_followup_ja=["ニュース本文と価格反応を確認"],
            )
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


def _source_label_ja(source: str) -> str:
    if source.startswith("nikkei225"):
        return "日経225暫定"
    if source.startswith("etf"):
        return "ETF暫定"
    if "seed" in source:
        return "暫定ユニバース"
    return source
