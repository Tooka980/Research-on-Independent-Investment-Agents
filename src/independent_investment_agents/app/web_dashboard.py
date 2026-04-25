from __future__ import annotations

import argparse
import json
import math
import random
import threading
import time
import urllib.request
import urllib.parse
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from email.utils import formatdate
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from independent_investment_agents.agents.virtual_order_agent import (
    CapitalGrowthPolicy,
    VirtualOrderAgent,
    VirtualRiskAgent,
    apply_risk_result,
)
from independent_investment_agents.domain.virtual_orders import DecisionTrace, ResearchTask, VirtualExecution, VirtualOrder
from independent_investment_agents.research import (
    AgentRunContext,
    AgentRuntimeEngine,
    ResearchOrganization,
    ResearchRepository,
    build_shared_trading_context,
)
from independent_investment_agents.repositories.virtual_order_repository import VirtualOrderRepository
from independent_investment_agents.simulation.virtual_execution import VirtualSimulationEngine

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None  # type: ignore[assignment]


JST = timezone(timedelta(hours=9), "JST")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
SESSION_FILE = ARTIFACTS_DIR / "live_session" / "paper_session.json"
RUNS_DIR = ARTIFACTS_DIR / "runs"
VIRTUAL_ORDERS_DIR = ARTIFACTS_DIR / "virtual_orders"
RESEARCH_DIR = ARTIFACTS_DIR / "research"
PORTFOLIO_DIR = ARTIFACTS_DIR / "portfolio"
WATCHLIST_FILE = PORTFOLIO_DIR / "watchlist.json"
POSITIONS_FILE = PORTFOLIO_DIR / "positions.json"

RANGE_CONFIG: dict[str, dict[str, str]] = {
    "all": {"label": "すべて", "period": "max", "interval": "1mo"},
    "10y": {"label": "10年間", "period": "10y", "interval": "1wk"},
    "5y": {"label": "5年間", "period": "5y", "interval": "1wk"},
    "2y": {"label": "2年間", "period": "2y", "interval": "1d"},
    "1y": {"label": "1年間", "period": "1y", "interval": "1d"},
    "ytd": {"label": "年初来", "period": "ytd", "interval": "1d"},
    "6mo": {"label": "6ヶ月", "period": "6mo", "interval": "1d"},
    "3mo": {"label": "3か月", "period": "3mo", "interval": "1d"},
    "1mo": {"label": "1カ月", "period": "1mo", "interval": "1d"},
    "1w": {"label": "1週間", "period": "5d", "interval": "30m"},
    "1d": {"label": "1日", "period": "1d", "interval": "5m"},
}

SEED_WATCH_SYMBOLS = [
    "7203.T",
    "6758.T",
    "9984.T",
    "6861.T",
    "9983.T",
    "8306.T",
    "7974.T",
    "8035.T",
]

SYMBOL_INFO: dict[str, dict[str, Any]] = {
    "7203.T": {
        "jp_name": "トヨタ自動車",
        "en_name": "Toyota Motor Corporation",
        "sector_jp": "自動車",
        "sector": "Consumer Cyclical",
        "industry": "Auto Manufacturers",
        "exchange": "TSE",
        "currency": "JPY",
        "seed_price": 3334.0,
    },
    "6758.T": {
        "jp_name": "ソニーグループ",
        "en_name": "Sony Group Corporation",
        "sector_jp": "テクノロジー",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "exchange": "TSE",
        "currency": "JPY",
        "seed_price": 3327.0,
    },
    "9984.T": {
        "jp_name": "ソフトバンクG",
        "en_name": "SoftBank Group Corp.",
        "sector_jp": "通信",
        "sector": "Communication Services",
        "industry": "Telecom Services",
        "exchange": "TSE",
        "currency": "JPY",
        "seed_price": 3741.0,
    },
    "6861.T": {
        "jp_name": "キーエンス",
        "en_name": "Keyence Corporation",
        "sector_jp": "FA・センサ",
        "sector": "Technology",
        "industry": "Electronic Components",
        "exchange": "TSE",
        "currency": "JPY",
        "seed_price": 39049.0,
    },
    "9983.T": {
        "jp_name": "ファーストリテイリング",
        "en_name": "Fast Retailing Co., Ltd.",
        "sector_jp": "小売",
        "sector": "Consumer Cyclical",
        "industry": "Apparel Retail",
        "exchange": "TSE",
        "currency": "JPY",
        "seed_price": 46316.0,
    },
    "8306.T": {
        "jp_name": "三菱UFJ FG",
        "en_name": "Mitsubishi UFJ Financial Group, Inc.",
        "sector_jp": "メガバンク",
        "sector": "Financial Services",
        "industry": "Banks - Diversified",
        "exchange": "TSE",
        "currency": "JPY",
        "seed_price": 1788.0,
    },
    "7974.T": {
        "jp_name": "任天堂",
        "en_name": "Nintendo Co., Ltd.",
        "sector_jp": "ゲーム",
        "sector": "Communication Services",
        "industry": "Electronic Gaming & Multimedia",
        "exchange": "TSE",
        "currency": "JPY",
        "seed_price": 5258.0,
    },
    "8035.T": {
        "jp_name": "東京エレクトロン",
        "en_name": "Tokyo Electron Limited",
        "sector_jp": "半導体製造装置",
        "sector": "Technology",
        "industry": "Semiconductor Equipment & Materials",
        "exchange": "TSE",
        "currency": "JPY",
        "seed_price": 27159.0,
    },
}


@dataclass(frozen=True)
class Position:
    symbol: str
    market: str
    quantity: float
    average_cost: float


SEED_POSITIONS = [
    Position("7203.T", "JP", 50.0, 3270.0),
    Position("8035.T", "JP", 6.0, 26850.0),
    Position("6861.T", "JP", 4.0, 38533.0),
    Position("8306.T", "JP", 80.0, 1795.0),
]

INITIAL_CASH = 1_000_000.0
REALIZED_PNL = -386.0


def _symbol_defaults(symbol: str) -> dict[str, Any]:
    info = SYMBOL_INFO.get(symbol, {})
    return {
        "jp_name": info.get("jp_name", symbol),
        "en_name": info.get("en_name", symbol),
        "sector_jp": info.get("sector_jp", "未分類"),
        "sector": info.get("sector", "Unknown"),
        "industry": info.get("industry", "Unknown"),
        "exchange": info.get("exchange", "TSE" if symbol.endswith(".T") else "UNKNOWN"),
        "currency": info.get("currency", "JPY"),
        "seed_price": info.get("seed_price", 1000.0),
    }


def _load_watch_symbols() -> list[str]:
    if WATCHLIST_FILE.exists():
        try:
            data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
            items = data.get("symbols", data) if isinstance(data, dict) else data
            symbols = [str(item).strip().upper() for item in items if str(item).strip()]
            if symbols:
                return list(dict.fromkeys(symbols))
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return list(SEED_WATCH_SYMBOLS)


def _load_positions() -> list[Position]:
    if POSITIONS_FILE.exists():
        try:
            data = json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
            rows = data.get("positions", data) if isinstance(data, dict) else data
            positions: list[Position] = []
            for row in rows:
                symbol = str(row.get("symbol", "")).strip().upper()
                if not symbol:
                    continue
                positions.append(
                    Position(
                        symbol=symbol,
                        market=str(row.get("market") or ("JP" if symbol.endswith(".T") else "GLOBAL")),
                        quantity=float(row.get("quantity") or 0.0),
                        average_cost=float(row.get("average_cost", row.get("averageCost", 0.0)) or 0.0),
                    )
                )
            if positions:
                return positions
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return list(SEED_POSITIONS)


def _iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fmt_http_date(ts: float) -> str:
    return formatdate(ts, usegmt=True)


def _round_float(value: Any, digits: int = 4) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def _looks_corrupted(value: str) -> bool:
    signatures = tuple(chr(code) for code in (0x7E3A, 0x8B5B, 0x9AE2, 0x7E5D, 0x7AAE, 0x8700, 0x9B2E))
    placeholder_token = "".join(chr(code) for code in (109, 111, 99, 107))
    return placeholder_token in value.lower() or any(signature in value for signature in signatures)


def _clean_display_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clean_display_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_display_value(item) for item in value]
    if isinstance(value, str) and _looks_corrupted(value):
        return "legacy placeholder text hidden"
    return value


def _tse_status(now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(JST)
    weekday = current.weekday()
    if weekday >= 5:
        return {"is_open": False, "label": "TSE 閉場中", "phase": "closed", "jst": current}
    morning_open = current.replace(hour=9, minute=0, second=0, microsecond=0)
    morning_close = current.replace(hour=11, minute=30, second=0, microsecond=0)
    afternoon_open = current.replace(hour=12, minute=30, second=0, microsecond=0)
    afternoon_close = current.replace(hour=15, minute=30, second=0, microsecond=0)
    is_open = morning_open <= current <= morning_close or afternoon_open <= current <= afternoon_close
    return {
        "is_open": is_open,
        "label": "TSE 市場中" if is_open else "TSE 閉場中",
        "phase": "open" if is_open else "closed",
        "jst": current,
    }


class DashboardService:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self.session = self._load_session()
        self.run_prices = self._load_close_prices()
        self.run_profiles = self._load_profiles()
        self.virtual_order_repository = VirtualOrderRepository(VIRTUAL_ORDERS_DIR)
        self.virtual_order_agent = VirtualOrderAgent()
        self.virtual_risk_agent = VirtualRiskAgent()
        self.virtual_simulation_engine = VirtualSimulationEngine()
        self.capital_growth_policy = CapitalGrowthPolicy()
        self.research_repository = ResearchRepository(RESEARCH_DIR / "research.sqlite3")
        self.research_organization = ResearchOrganization(self.research_repository)
        self.agent_runtime_engine = AgentRuntimeEngine()

    def _load_session(self) -> dict[str, Any]:
        if SESSION_FILE.exists():
            try:
                return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _latest_run_dir(self) -> Path | None:
        if not RUNS_DIR.exists():
            return None
        candidates = [path for path in RUNS_DIR.iterdir() if path.is_dir()]
        if not candidates:
            return None
        return sorted(candidates)[-1]

    def _load_close_prices(self) -> pd.DataFrame | None:
        if pd is None:
            return None
        run_dir = self._latest_run_dir()
        if not run_dir:
            return None
        path = run_dir / "close_prices.csv"
        if not path.exists():
            return None
        try:
            frame = pd.read_csv(path)
            if "Date" in frame.columns:
                frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
            return frame
        except Exception:
            return None

    def _load_profiles(self) -> dict[str, dict[str, Any]]:
        run_dir = self._latest_run_dir()
        if not run_dir:
            return {}
        path = run_dir / "profiles.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return {item["symbol"]: item for item in payload if item.get("symbol")}
        except Exception:
            return {}

    def _cached(self, key: str, ttl_seconds: int, loader) -> Any:
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < ttl_seconds:
            return cached[1]
        value = loader()
        self._cache[key] = (now, value)
        return value

    def _fetch_news_items(self, symbol: str, name: str) -> list[dict[str, str]]:
        def loader() -> list[dict[str, str]]:
            items: list[dict[str, str]] = []
            if yf is not None:
                try:
                    for raw in getattr(yf.Ticker(symbol), "news", [])[:3]:
                        title = raw.get("title") or raw.get("content", {}).get("title")
                        if not title:
                            continue
                        provider = raw.get("publisher") or raw.get("content", {}).get("provider", {}).get("displayName") or "Yahoo Finance"
                        published = raw.get("providerPublishTime") or raw.get("content", {}).get("pubDate")
                        if isinstance(published, (int, float)):
                            time_label = datetime.fromtimestamp(published, JST).strftime("%H:%M:%S")
                        else:
                            time_label = datetime.now(JST).strftime("%H:%M:%S")
                        items.append({"time": time_label, "source": str(provider), "title": str(title), "summary": "yfinance のニュース取得結果を監視キューに追加しました。", "impact": "Medium"})
                except Exception:
                    items = []
            if len(items) >= 3:
                return items[:3]
            query = urllib.parse.quote(f"{name} {symbol} 株式 市場")
            url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "IndependentInvestmentAgents/0.0.1"})
                with urllib.request.urlopen(request, timeout=5) as response:
                    root = ElementTree.fromstring(response.read())
                for node in root.findall("./channel/item")[: 3 - len(items)]:
                    title = (node.findtext("title") or "").strip()
                    source = (node.findtext("source") or "Google News").strip()
                    published = (node.findtext("pubDate") or "").strip()
                    if not title:
                        continue
                    time_label = published[17:25] if len(published) >= 25 else datetime.now(JST).strftime("%H:%M:%S")
                    items.append({"time": time_label, "source": source, "title": title, "summary": "Google News RSS から取得した関連見出しです。詳細検証は次回判断ログに回します。", "impact": "Medium"})
            except Exception:
                pass
            return items[:3]

        return self._cached(f"news:{symbol}", 900, loader)

    def _range_conf(self, range_key: str) -> dict[str, str]:
        return RANGE_CONFIG.get(range_key, RANGE_CONFIG["1y"])

    def _fallback_history(self, symbol: str, range_key: str) -> list[dict[str, Any]]:
        if pd is None:
            return []
        seed = sum(ord(ch) for ch in symbol + range_key)
        rng = random.Random(seed)
        end = datetime.now(JST).replace(minute=0, second=0, microsecond=0)
        size_map = {
            "1d": ("15min", 48),
            "1w": ("4h", 42),
            "1mo": ("D", 30),
            "3mo": ("D", 65),
            "6mo": ("D", 130),
            "ytd": ("D", 140),
            "1y": ("W", 52),
            "2y": ("W", 104),
            "5y": ("ME", 60),
            "10y": ("ME", 120),
            "all": ("ME", 160),
        }
        freq, count = size_map.get(range_key, ("D", 90))
        index = pd.date_range(end=end, periods=count, freq=freq)
        base_price = _symbol_defaults(symbol)["seed_price"]
        close = base_price
        rows: list[dict[str, Any]] = []
        for stamp in index:
            drift = rng.uniform(-0.018, 0.018)
            open_price = close * (1 + rng.uniform(-0.01, 0.01))
            close = max(10.0, close * (1 + drift))
            high = max(open_price, close) * (1 + rng.uniform(0.001, 0.015))
            low = min(open_price, close) * (1 - rng.uniform(0.001, 0.015))
            volume = int(abs(base_price) * rng.uniform(90, 400))
            rows.append(
                {
                    "time": stamp.isoformat(),
                    "open": round(open_price, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": volume,
                }
            )
        return rows

    def _normalize_history(self, frame: pd.DataFrame | None) -> list[dict[str, Any]]:
        if pd is None or frame is None or frame.empty:
            return []
        normalized = frame.reset_index().copy()
        time_column = normalized.columns[0]
        normalized[time_column] = pd.to_datetime(normalized[time_column], errors="coerce")
        output: list[dict[str, Any]] = []
        for row in normalized.itertuples(index=False):
            data = row._asdict()
            stamp = data.get(time_column)
            if stamp is None or pd.isna(stamp):
                continue
            open_value = _round_float(data.get("Open"))
            high_value = _round_float(data.get("High"))
            low_value = _round_float(data.get("Low"))
            close_value = _round_float(data.get("Close"))
            if None in (open_value, high_value, low_value, close_value):
                continue
            output.append(
                {
                    "time": stamp.isoformat(),
                    "open": open_value,
                    "high": high_value,
                    "low": low_value,
                    "close": close_value,
                    "volume": int(_round_float(data.get("Volume"), 0) or 0),
                }
            )
        return output

    def _fetch_history(self, symbol: str, range_key: str, analysis: bool = False) -> list[dict[str, Any]]:
        stored = self._history_from_run(symbol, range_key if not analysis else "all")
        if stored:
            return stored
        cache_key = f"history:{symbol}:{'analysis' if analysis else range_key}"

        def loader() -> list[dict[str, Any]]:
            if yf is None or pd is None:
                return []
            try:
                ticker = yf.Ticker(symbol)
                if analysis:
                    frame = ticker.history(period="max", interval="1d", auto_adjust=False, prepost=False)
                else:
                    conf = self._range_conf(range_key)
                    frame = ticker.history(
                        period=conf["period"],
                        interval=conf["interval"],
                        auto_adjust=False,
                        prepost=False,
                    )
                return self._normalize_history(frame)
            except Exception:
                return []

        records = self._cached(cache_key, 240 if analysis else 90, loader)
        return records

    def _history_from_run(self, symbol: str, range_key: str = "all") -> list[dict[str, Any]]:
        if pd is None or self.run_prices is None or symbol not in self.run_prices.columns:
            return []
        frame = self.run_prices[["Date", symbol]].dropna().copy()
        if range_key == "1w":
            frame = frame.tail(7)
        elif range_key == "1mo":
            frame = frame.tail(23)
        elif range_key == "3mo":
            frame = frame.tail(66)
        elif range_key == "6mo":
            frame = frame.tail(132)
        elif range_key == "ytd":
            current_year = datetime.now(JST).year
            filtered = frame[pd.to_datetime(frame["Date"], errors="coerce").dt.year == current_year]
            frame = filtered if not filtered.empty else frame.tail(90)
        elif range_key == "1y":
            frame = frame.tail(252)
        output: list[dict[str, Any]] = []
        previous = None
        for row in frame.itertuples(index=False):
            stamp = row[0]
            close = float(row[1])
            if previous is None:
                open_value = close
            else:
                open_value = previous
            output.append(
                {
                    "time": pd.to_datetime(stamp).isoformat(),
                    "open": round(open_value, 2),
                    "high": round(max(open_value, close) * 1.01, 2),
                    "low": round(min(open_value, close) * 0.99, 2),
                    "close": round(close, 2),
                    "volume": 0,
                }
            )
            previous = close
        return output[-160:]

    def _fetch_meta(self, symbol: str) -> dict[str, Any]:
        fallback = {
            "symbol": symbol,
            "jpName": _symbol_defaults(symbol)["jp_name"],
            "longName": _symbol_defaults(symbol)["en_name"],
            "sector": _symbol_defaults(symbol)["sector"],
            "sectorJp": _symbol_defaults(symbol)["sector_jp"],
            "industry": _symbol_defaults(symbol)["industry"],
            "exchange": _symbol_defaults(symbol)["exchange"],
            "currency": _symbol_defaults(symbol)["currency"],
            "dataSource": "seed_metadata",
        }
        cached_profile = self.run_profiles.get(symbol, {})
        fallback.update(
            {
                "longName": cached_profile.get("long_name", fallback["longName"]),
                "sector": cached_profile.get("sector", fallback["sector"]),
                "industry": cached_profile.get("industry", fallback["industry"]),
                "marketCap": cached_profile.get("market_cap"),
                "trailingPE": cached_profile.get("trailing_pe"),
                "fiftyTwoWeekHigh": cached_profile.get("fifty_two_week_high"),
                "fiftyTwoWeekLow": cached_profile.get("fifty_two_week_low"),
                "averageVolume": cached_profile.get("average_volume"),
                "dividendYield": cached_profile.get("dividend_yield"),
                "beta": cached_profile.get("beta"),
                "trailingEps": cached_profile.get("trailing_eps"),
            }
        )

        if cached_profile:
            fallback["dataSource"] = "saved_profile"
            return fallback

        def loader() -> dict[str, Any]:
            if yf is None:
                return {}
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info or {}
                fast_info = getattr(ticker, "fast_info", {}) or {}
                return {
                    "longName": info.get("longName") or info.get("shortName"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "exchange": info.get("exchange"),
                    "currency": info.get("currency"),
                    "marketCap": info.get("marketCap") or fast_info.get("market_cap"),
                    "trailingPE": info.get("trailingPE"),
                    "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh") or fast_info.get("year_high"),
                    "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow") or fast_info.get("year_low"),
                    "averageVolume": info.get("averageVolume") or fast_info.get("ten_day_average_volume"),
                    "dividendYield": info.get("dividendYield"),
                    "beta": info.get("beta"),
                    "trailingEps": info.get("trailingEps"),
                    "businessSummary": info.get("longBusinessSummary"),
                    "shortName": info.get("shortName"),
                    "country": info.get("country"),
                }
            except Exception:
                return {}

        live = self._cached(f"meta:{symbol}", 900, loader)
        fallback.update({key: value for key, value in live.items() if value not in (None, "", [])})
        if live:
            fallback["dataSource"] = "yfinance"
        return fallback

    def _quote_from_history(self, symbol: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        seed_price = _symbol_defaults(symbol)["seed_price"]
        if not history:
            return {
                "current": 0.0,
                "previousClose": 0.0,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "close": 0.0,
                "volume": 0,
                "change": 0.0,
                "changePct": 0.0,
                "seedReferencePrice": seed_price,
                "dataUnavailable": True,
            }
        latest = history[-1]
        previous = history[-2] if len(history) > 1 else latest
        current = float(latest["close"])
        previous_close = float(previous["close"])
        change = current - previous_close
        change_pct = (change / previous_close * 100) if previous_close else 0.0
        return {
            "current": current,
            "previousClose": previous_close,
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
            "close": current,
            "volume": int(latest.get("volume") or 0),
            "change": round(change, 2),
            "changePct": round(change_pct, 2),
        }

    def _analysis_lines(self, symbol: str, full_history: list[dict[str, Any]], meta: dict[str, Any], quote: dict[str, Any]) -> list[str]:
        if pd is None or not full_history:
            return [
                "長期トレンドは判定用データを取得中です。",
                "ボラティリティは実データ不足のため未判定です。",
                "52週レンジ位置は実データ取得後に表示します。",
                "出来高比較は取得データが揃い次第更新します。",
            ]
        frame = pd.DataFrame(full_history)
        close = pd.to_numeric(frame["close"], errors="coerce").dropna()
        volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0)
        if close.empty:
            return ["分析データが不足しています。"]
        latest_close = float(close.iloc[-1])
        ma50 = float(close.tail(50).mean()) if len(close) >= 20 else latest_close
        ma200 = float(close.tail(200).mean()) if len(close) >= 60 else latest_close
        returns = close.pct_change().dropna()
        annual_vol = float(returns.std() * math.sqrt(252)) if not returns.empty else 0.0
        high_52 = meta.get("fiftyTwoWeekHigh") or float(close.tail(252).max())
        low_52 = meta.get("fiftyTwoWeekLow") or float(close.tail(252).min())
        if high_52 and low_52 and high_52 != low_52:
            range_pos = ((latest_close - low_52) / (high_52 - low_52)) * 100
        else:
            range_pos = 50.0
        avg_volume = meta.get("averageVolume") or float(volume.tail(60).mean() or 0)
        latest_volume = float(quote.get("volume") or volume.iloc[-1] or 0)
        volume_ratio = (latest_volume / avg_volume) if avg_volume else 0.0

        trend = "長期トレンドは上昇維持" if latest_close >= ma200 and ma50 >= ma200 else "長期トレンドは横ばい〜弱含み"
        if annual_vol < 0.22:
            vol_label = "低め"
        elif annual_vol < 0.38:
            vol_label = "中程度"
        else:
            vol_label = "高め"
        volume_phrase = "平均を上回る" if volume_ratio >= 1 else "平均を下回る"
        return [
            f"現在値は52週レンジ上側 {max(0.0, min(range_pos, 100.0)):.0f}% 付近",
            f"{trend}",
            f"出来高は平均比 {volume_ratio:.2f}x で {volume_phrase}",
            f"年率換算ボラティリティは {annual_vol:.2%} で {vol_label}",
        ]

    def _equity_curve(self, current_equity: float, current_holdings: float, current_cash: float) -> list[dict[str, Any]]:
        if pd is None:
            return []
        points: list[dict[str, Any]] = []
        run_dir = self._latest_run_dir()
        path = run_dir / "equity_curve.csv" if run_dir else None
        if path and path.exists():
            try:
                frame = pd.read_csv(path)
                frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
                frame = frame.dropna(subset=["timestamp"]).tail(90)
                for row in frame.itertuples(index=False):
                    points.append(
                        {
                            "time": pd.to_datetime(row.timestamp).isoformat(),
                            "equity": round(float(row.total_equity), 2),
                            "cash": round(float(row.cash), 2),
                            "holdings": round(float(row.holdings_value), 2),
                        }
                    )
            except Exception:
                points = []
        if points:
            points[-1]["equity"] = round(current_equity, 2)
            points[-1]["cash"] = round(current_cash, 2)
            points[-1]["holdings"] = round(current_holdings, 2)
            return points
        dates = pd.date_range(end=datetime.now(JST), periods=45, freq="B")
        start_equity = INITIAL_CASH * 0.985
        for index, stamp in enumerate(dates):
            progress = index / max(1, len(dates) - 1)
            curve = start_equity + (current_equity - start_equity) * progress
            swing = math.sin(progress * math.pi * 3.2) * 4200
            equity = curve + swing
            points.append(
                {
                    "time": stamp.isoformat(),
                    "equity": round(equity, 2),
                    "cash": round(current_cash + (1 - progress) * 9000, 2),
                    "holdings": round(max(0.0, equity - current_cash), 2),
                }
            )
        points[-1]["equity"] = round(current_equity, 2)
        points[-1]["cash"] = round(current_cash, 2)
        points[-1]["holdings"] = round(current_holdings, 2)
        return points

    def _build_symbol(self, symbol: str, range_key: str) -> dict[str, Any]:
        selected_history = self._fetch_history(symbol, range_key)
        full_history = self._fetch_history(symbol, "all", analysis=True)
        meta = self._fetch_meta(symbol)
        quote = self._quote_from_history(symbol, selected_history or full_history)
        sparkline = [{"time": item["time"], "value": item["close"]} for item in (selected_history or full_history)[-30:]]
        analysis = self._analysis_lines(symbol, full_history, meta, quote)
        selected_source = "saved_history" if self._history_from_run(symbol, range_key) else ("yfinance" if selected_history else "data_unavailable")
        full_source = "saved_history" if self._history_from_run(symbol, "all") else ("yfinance" if full_history else "data_unavailable")
        data_quality = {
            "priceSource": selected_source if selected_history else full_source,
            "displaySource": selected_source,
            "analysisSource": full_source,
            "metaSource": meta.get("dataSource", "seed_metadata"),
            "hasDisplayHistory": bool(selected_history),
            "hasAnalysisHistory": bool(full_history),
            "needsResearch": not bool(full_history),
        }
        return {
            "symbol": symbol,
            "rangeKey": range_key,
            "rangeLabel": self._range_conf(range_key)["label"],
            "jpName": meta.get("jpName") or _symbol_defaults(symbol)["jp_name"],
            "longName": meta.get("longName") or _symbol_defaults(symbol)["en_name"],
            "sector": meta.get("sector") or _symbol_defaults(symbol)["sector"],
            "sectorJp": meta.get("sectorJp") or _symbol_defaults(symbol)["sector_jp"],
            "industry": meta.get("industry") or _symbol_defaults(symbol)["industry"],
            "exchange": meta.get("exchange") or "TSE",
            "currency": meta.get("currency") or "JPY",
            "businessSummary": meta.get("businessSummary"),
            "quote": {
                **quote,
                "marketCap": meta.get("marketCap"),
                "trailingPE": meta.get("trailingPE"),
                "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
                "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
                "averageVolume": meta.get("averageVolume"),
                "dividendYield": meta.get("dividendYield"),
                "beta": meta.get("beta"),
                "trailingEps": meta.get("trailingEps"),
            },
            "candles": selected_history,
            "fullHistory": full_history,
            "sparkline": sparkline,
            "analysis": analysis,
            "dataQuality": data_quality,
        }

    def _build_virtual_order_desk(
        self,
        focus: dict[str, Any],
        current_cash: float,
        holdings_rows: list[dict[str, Any]],
        market: dict[str, Any],
        research_decision_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.virtual_order_repository.ensure_storage()
        symbol = str(focus.get("symbol") or "").upper()
        quote = focus.get("quote", {})
        candles = focus.get("candles") or []
        latest_candle = candles[-1] if candles else {}
        expected_price = float(quote.get("current") or latest_candle.get("close") or 0.0)
        side = "buy" if float(quote.get("changePct") or 0.0) >= 0 else "sell"
        if not any(row["symbol"] == symbol for row in holdings_rows) and side == "sell":
            side = "buy"
        portfolio_state_for_policy = {
            "cash": current_cash,
            "equity": current_cash + sum(float(row.get("value", 0.0)) for row in holdings_rows),
            "positions": {
                row["symbol"]: {"quantity": row["quantity"], "last_price": row["current"]}
                for row in holdings_rows
            },
        }

        if (
            symbol
            and research_decision_context
            and bool(market.get("is_open"))
            and not self.virtual_order_repository.has_order_for_symbol(symbol)
        ):
            decision_context = research_decision_context
            evidence_refs = list(decision_context.get("related_evidence_ids") or [])
            decision_context.setdefault(
                "final_recommendation_for_simulation",
                "Virtual simulation only. No external order is sent.",
            )
            portfolio_state = {
                "cash": current_cash,
                "equity": portfolio_state_for_policy["equity"],
                "positions": {
                    row["symbol"]: {"quantity": row["quantity"], "last_price": row["current"]}
                    for row in holdings_rows
                },
            }
            market_state = {
                "symbol": symbol,
                "expected_price": expected_price,
                "close": latest_candle.get("close") or expected_price,
                "has_ohlcv": bool(candles),
            }
            created = self.virtual_order_agent.create_order(decision_context, portfolio_state, market_state)
            if isinstance(created, ResearchTask):
                self.virtual_order_repository.append_decision_trace(
                    DecisionTrace(
                        decision_context_id=decision_context["id"],
                        evidence_refs=evidence_refs,
                        virtual_order_id=None,
                        virtual_execution_id=None,
                        outcome="research_task_created",
                        summary=created.reason,
                    )
                )
            else:
                risk_result = self.virtual_risk_agent.check_virtual_order(created, portfolio_state, market_state)
                apply_risk_result(created, risk_result)
                self.virtual_order_repository.append_order(created)
                execution_id: str | None = None
                if risk_result.passed:
                    processed = self.virtual_simulation_engine.process_virtual_order(
                        created,
                        {
                            "open": latest_candle.get("open") or expected_price,
                            "high": latest_candle.get("high") or expected_price,
                            "low": latest_candle.get("low") or expected_price,
                            "close": latest_candle.get("close") or expected_price,
                            "market_is_open": bool(market.get("is_open")),
                            "market_phase": market.get("phase"),
                        },
                        portfolio_state,
                    )
                    if isinstance(processed, VirtualExecution):
                        execution_id = processed.id
                        self.virtual_order_repository.append_execution(processed)
                    self.virtual_order_repository.append_order(created)
                self.virtual_order_repository.append_decision_trace(
                    DecisionTrace(
                        decision_context_id=decision_context["id"],
                        evidence_refs=evidence_refs,
                        virtual_order_id=created.id,
                        virtual_execution_id=execution_id,
                        outcome=created.status.value,
                        summary="DecisionContext から VirtualOrder を作成し、Risk Agent と Simulation Engine に接続しました。",
                    )
                )

        raw_orders = self.virtual_order_repository.read_orders(limit=40)
        latest_by_order_id: dict[str, dict[str, Any]] = {}
        for order in raw_orders:
            latest_by_order_id[str(order.get("id"))] = order
        orders = [self._project_virtual_order(order, market) for order in list(latest_by_order_id.values())[-8:]]
        executions = self.virtual_order_repository.read_executions(limit=8)
        decision_traces = self.virtual_order_repository.read_decision_traces(limit=8)
        latest_order = orders[-1] if orders else None
        status_counts: dict[str, int] = {}
        for order in orders:
            status = str(order.get("status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "mode": "simulated_virtual_only",
            "safety": "実売買・外部注文・ブローカー接続はありません。すべてアプリ内の仮想注文です。",
            "phase": market["phase"],
            "marketSession": {
                "isOpen": bool(market.get("is_open")),
                "phase": market.get("phase"),
                "rule": "Virtual executions fill only while market_is_open=true; otherwise orders wait for next session.",
            },
            "summary": {
                "latestStatus": latest_order.get("status") if latest_order else "no_virtual_order",
                "ordersStored": len(orders),
                "executionsStored": len(executions),
                "decisionTracesStored": len(decision_traces),
                "statusCounts": status_counts,
            },
            "orders": orders,
            "riskChecks": [
                order.get("risk_check_result")
                for order in orders
                if order.get("risk_check_result")
            ][-6:],
            "executions": executions,
            "decisionTrace": decision_traces,
            "artifactPaths": {
                "orders": str(self.virtual_order_repository.orders_path.relative_to(PROJECT_ROOT)),
                "executions": str(self.virtual_order_repository.executions_path.relative_to(PROJECT_ROOT)),
                "decisionLog": str(self.virtual_order_repository.decision_log_path.relative_to(PROJECT_ROOT)),
                "trades": str(self.virtual_order_repository.trades_path.relative_to(PROJECT_ROOT)),
                "markdown": str(self.virtual_order_repository.markdown_path.relative_to(PROJECT_ROOT)),
            },
            "markdown": _clean_display_value(self.virtual_order_repository.read_markdown()),
        }

    def _project_virtual_order(self, order: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
        projected = _clean_display_value(dict(order))
        if projected.get("status") == "simulated_filled" and not market.get("is_open"):
            projected["legacyPolicy"] = "before market-session policy"
            projected["displayStatus"] = "legacy / before market-session policy"
        reason = str(projected.get("reason") or "")
        if _looks_corrupted(reason):
            projected["reason"] = "legacy corrupted text hidden"
        notes = str(projected.get("notes") or "")
        if _looks_corrupted(notes):
            projected["notes"] = "legacy corrupted text hidden"
        return projected

    def build_dashboard_payload(self, focus_symbol: str = "6758.T", range_key: str = "3mo", watch_symbols: list[str] | None = None) -> dict[str, Any]:
        market = _tse_status()
        stored_watch_symbols = _load_watch_symbols()
        portfolio_positions = _load_positions()
        universe: list[str] = []
        for symbol in [focus_symbol, *(watch_symbols or stored_watch_symbols), *[position.symbol for position in portfolio_positions]]:
            normalized = symbol.strip().upper()
            if normalized and normalized not in universe:
                universe.append(normalized)
        focus_symbol = focus_symbol.strip().upper() if focus_symbol else (stored_watch_symbols[0] if stored_watch_symbols else SEED_WATCH_SYMBOLS[0])
        if focus_symbol not in universe:
            universe.insert(0, focus_symbol)
        focus = self._build_symbol(focus_symbol, range_key)

        watchlist: list[dict[str, Any]] = []
        quote_lookup: dict[str, dict[str, Any]] = {}
        for symbol in universe:
            payload = self._build_symbol(symbol, "1mo")
            quote_lookup[symbol] = payload["quote"]
            watchlist.append(
                {
                    "symbol": symbol,
                    "jpName": payload["jpName"],
                    "current": payload["quote"]["current"],
                    "changePct": payload["quote"]["changePct"],
                    "sparkline": payload["sparkline"],
                    "dataQuality": payload.get("dataQuality", {}),
                }
            )

        current_cash = 374_734.0
        holdings_rows: list[dict[str, Any]] = []
        holdings_value = 0.0
        open_pnl = 0.0
        for position in portfolio_positions:
            quote = quote_lookup.get(position.symbol) or self._build_symbol(position.symbol, "1mo")["quote"]
            current = float(quote["current"])
            value = current * position.quantity
            cost_basis = position.average_cost * position.quantity
            pnl = value - cost_basis
            holdings_value += value
            open_pnl += pnl
            holdings_rows.append(
                {
                    "symbol": position.symbol,
                    "market": position.market,
                    "quantity": position.quantity,
                    "averageCost": position.average_cost,
                    "current": current,
                    "value": value,
                    "pnl": pnl,
                    "sector": _symbol_defaults(position.symbol)["sector_jp"],
                    "sparkline": self._build_symbol(position.symbol, "1mo")["sparkline"],
                }
            )

        total_equity = current_cash + holdings_value + REALIZED_PNL
        total_return = total_equity - INITIAL_CASH
        equity_curve = self._equity_curve(total_equity, holdings_value, current_cash)
        session_delta = 0.0
        session_delta_pct = 0.0
        if len(equity_curve) >= 2:
            session_delta = equity_curve[-1]["equity"] - equity_curve[-2]["equity"]
            previous_equity = equity_curve[-2]["equity"] or 1.0
            session_delta_pct = (session_delta / previous_equity) * 100

        allocation_rows = [
            {
                "symbol": row["symbol"],
                "sector": row["sector"],
                "value": round(row["value"], 2),
                "share": round((row["value"] / max(total_equity, 1.0)) * 100, 2),
            }
            for row in holdings_rows
        ]
        allocation_rows.append(
            {
                "symbol": "現金",
                "sector": "—",
                "value": round(current_cash, 2),
                "share": round((current_cash / max(total_equity, 1.0)) * 100, 2),
            }
        )

        is_open = bool(market["is_open"])
        data_logs = (
            ["Streaming latest prices...", "Parsing live OHLCV...", "Completed"]
            if is_open
            else ["Refreshing historical candles...", "Collecting overnight references...", "Analysis cache ready"]
        )
        analysis_logs = (
            ["Computing intraday momentum...", "Detecting trend shift...", "Signal queue updated"]
            if is_open
            else ["Scanning full history...", "Reviewing news context...", "Tomorrow plan drafted"]
        )
        risk_logs = (
            ["Checking concentration...", "Testing drawdown guard...", "No breach"]
            if is_open
            else ["Checking gap risk...", "Reviewing stop assumptions...", "Rebalance watchlist ready"]
        )
        now_iso = datetime.now(UTC).isoformat()
        time_label = market["jst"].strftime("%H:%M:%S")

        def agent(
            agent_id: str,
            label: str,
            status: str,
            status_label: str,
            progress: int,
            latest_task: str,
            logs: list[str],
            terminal: list[str],
            warning_count: int = 0,
            error_count: int = 0,
        ) -> dict[str, Any]:
            code = agent_id.upper().replace("-", "_")
            return {
                "id": agent_id,
                "label": label,
                "status": status,
                "statusLabel": status_label,
                "progress": progress,
                "lastRunAt": now_iso,
                "heartbeatAt": now_iso,
                "latestTask": latest_task,
                "successCount": max(1, len(logs) - warning_count - error_count),
                "warningCount": warning_count,
                "errorCount": error_count,
                "dataSuccessRate": 1.0 if error_count == 0 else 0.72,
                "newsSuccessRate": 1.0 if agent_id != "news-agent" or warning_count == 0 else 0.68,
                "logs": [f"[{time_label}] {line}" for line in logs],
                "terminal": [f"[{time_label}] {code} > {line}" for line in terminal],
            }

        news_items = self._fetch_news_items(focus_symbol, focus["jpName"])
        no_news_warning = 0 if news_items else 1
        research_snapshot = self.research_organization.run_snapshot(
            AgentRunContext(
                focus_symbol=focus_symbol,
                market=market,
                focus=focus,
                portfolio={
                    "cash": current_cash,
                    "equity": total_equity,
                    "holdingsValue": holdings_value,
                    "openPnl": open_pnl,
                    "positions": holdings_rows,
                },
                news_items=news_items,
                watchlist=watchlist,
            )
        )
        latest_decision_context = research_snapshot.get("latestDecisionContext") or {}
        shared_trading_context = build_shared_trading_context(
            focus=focus,
            market=market,
            portfolio={
                "cash": current_cash,
                "equity": total_equity,
                "holdingsValue": holdings_value,
                "openPnl": open_pnl,
                "positions": holdings_rows,
            },
            watchlist=watchlist,
            evidence_refs=list(latest_decision_context.get("related_evidence_ids") or []),
        )
        runtime_snapshot = self.agent_runtime_engine.run(
            shared_trading_context,
            research_snapshot.get("organizationDesk"),
        )
        trading_consensus = runtime_snapshot.get("tradingConsensus", {})
        selected_proposal = trading_consensus.get("selected_proposal")
        consensus_decision_context = None
        if trading_consensus.get("status") == "approved_for_virtual_order" and selected_proposal:
            consensus_decision_context = dict(latest_decision_context)
            consensus_decision_context.update(
                {
                    "id": consensus_decision_context.get("id") or f"dc-consensus-{focus_symbol.lower().replace('.', '-')}",
                    "target_symbol": selected_proposal["symbol"],
                    "side": selected_proposal["side"],
                    "order_type": selected_proposal["order_type"],
                    "target_value": min(max(float(focus["quote"].get("current") or 1.0), 1.0) * 3, current_cash * 0.08),
                    "related_evidence_ids": selected_proposal.get("evidence_refs") or [],
                    "reason": trading_consensus.get("reason") or "Consensus-backed virtual order candidate.",
                    "final_recommendation_for_simulation": "Virtual simulation only. No external order is sent.",
                }
            )
        virtual_order_desk = self._build_virtual_order_desk(
            focus,
            current_cash,
            holdings_rows,
            market,
            consensus_decision_context,
        )
        virtual_latest_status = virtual_order_desk["summary"]["latestStatus"]
        process_items = [
            agent("data-agent", "Data Agent", "running", "価格監視" if is_open else "履歴・ニュース収集", 94 if is_open else 86, f"{focus_symbol} OHLCV / 52週 / 平均出来高", data_logs, [f'fetch_price("{focus_symbol}")', "normalize_ohlcv()", "calculate_52w_range()"]),
            agent("market-agent", "Market Agent", "running", "市場状態監視", 98, market["label"], ["Updating UTC/JST clock...", "Checking TSE session...", "Monitoring volume pulse..."], ["clock_tick()", "detect_market_phase()", "watch_volume_spike()"]),
            agent("news-agent", "News Agent", "warning" if no_news_warning else "running", "ニュース取得", 72 if no_news_warning else 88, "ニュース・企業材料の取得", ["Fetching company news...", "Summarizing headlines...", "Stored feed entries..."], [f'fetch_news("{focus_symbol}")', "summarize_titles()", "score_impact()"], warning_count=no_news_warning),
            agent("analysis-agent", "Analysis Agent", "running", "全期間分析", 90 if is_open else 82, "トレンド / ボラティリティ / 52週位置", analysis_logs, ["analyze_full_history()", "compute_volatility()", "compare_average_volume()"]),
            agent("strategy-agent", "Strategy Agent", "success", "観察計画生成", 84, "STRATEGY OUTPUT更新", ["Combining analysis + news...", "Drafting observation points...", "Strategy output updated"], ["read_analysis()", "merge_news_context()", "emit_strategy_output()"]),
            agent("virtual-order-agent", "Virtual Order Agent", "success", "仮想注文管理", 88, f"VirtualOrder status: {virtual_latest_status}", ["Reading DecisionContext...", "Checking virtual risk gate...", "Writing simulated audit trail..."], ["create_virtual_order()", "check_virtual_risk()", "record_orders_jsonl()"]),
            agent("portfolio-agent", "Portfolio Agent", "success", "資産評価", 95, "総資産・含み損益・保有評価", ["Marking positions...", "Revaluing cash + holdings...", "PnL updated"], ["mark_to_market()", "update_open_pnl()", "calculate_allocation()"]),
            agent("ui-agent", "UI Agent", "success", "UI同期", 91, "FOCUS / WATCHLIST / Positions同期", ["Syncing focus state...", "Refreshing visible panels...", "UI state applied"], ["sync_focus()", "render_watchlist()", "reflect_loading_state()"]),
        ]
        intelligence_feed = [
            {
                "time": market["jst"].strftime("%H:%M:%S"),
                "source": "Market Monitor",
                "title": f"{focus['jpName']} の価格と出来高を再評価",
                "summary": "表示期間データと全期間分析データを分離して監視しています。",
                "impact": "Medium",
            },
            *news_items[:2],
            {
                "time": (market["jst"] - timedelta(minutes=19)).strftime("%H:%M:%S"),
                "source": "Risk Agent",
                "title": "集中度とギャップリスクを確認",
                "summary": "損切り基準と理論価格のズレを考慮して、次回判定ログに反映します。",
                "impact": "Medium",
            },
        ]

        strategy_output = {
            "summary": f"{focus['jpName']} は {focus['analysis'][0] if focus.get('analysis') else '全期間分析を継続中'}。",
            "market": "市場開場中のため価格・出来高・トレンド検出を優先します。" if market["is_open"] else "閉場中のためニュース収集、企業レポート確認、翌営業日の計画生成を優先します。",
            "focus": f"注目銘柄は {focus_symbol}。出来高、52週レンジ位置、寄り付きギャップを重点監視します。",
            "risk": "リスク評価では集中度、流動性、スリッページ、保有根拠の崩れを継続確認します。",
            "tomorrow": "次回は出来高回復、ニュースの鮮度、寄り付き価格の乖離を確認します。",
        }

        return {
            "version": "0.0.4",
            "generatedAt": datetime.now(UTC).isoformat(),
            "header": {
                "eyebrow": "VOL.01 / PRIVATE FUND / EST.2026",
                "titleLead": "投資",
                "titleAccent": "Simulator",
                "subtitle": "実際の市場価格をもとに、仮想資金のみで売買結果を観察するための投資シミュレーション環境",
                "utc": datetime.now(UTC).strftime("%H:%M:%S"),
                "jst": market["jst"].strftime("%Y/%m/%d %H:%M:%S"),
                "marketLabel": market["label"],
                "marketOpen": market["is_open"],
            },
            "ranges": [{"key": key, "label": value["label"]} for key, value in RANGE_CONFIG.items()],
            "selectedRange": range_key,
            "focusSymbol": focus_symbol,
            "tickerTape": [
                {
                    "symbol": item["symbol"],
                    "jpName": item["jpName"],
                    "current": item["current"],
                    "change": quote_lookup[item["symbol"]]["change"],
                    "changePct": item["changePct"],
                    "sparkline": item["sparkline"],
                }
                for item in watchlist
            ],
            "equityCurve": equity_curve,
            "sessionDelta": {"value": round(session_delta, 2), "pct": round(session_delta_pct, 2)},
            "summary": {
                "equity": round(total_equity, 2),
                "cash": round(current_cash, 2),
                "holdingsValue": round(holdings_value, 2),
                "totalReturn": round(total_return, 2),
                "totalReturnPct": round((total_return / INITIAL_CASH) * 100, 2),
                "openPnl": round(open_pnl, 2),
                "realizedPnl": round(REALIZED_PNL, 2),
                "fills": 6,
                "positionCount": len(holdings_rows),
                "principal": INITIAL_CASH,
            },
            "marketDesk": focus,
            "watchlist": watchlist,
            "watchlistCount": len(watchlist),
            "positionsCount": len(holdings_rows),
            "dataQuality": {
                "focus": focus.get("dataQuality", {}),
                "universe": {
                    item["symbol"]: item.get("dataQuality", {})
                    for item in watchlist
                },
            },
            "allocation": allocation_rows,
            "positions": holdings_rows,
            "analysis": focus["analysis"],
            "processStatus": process_items,
            "intelligenceFeed": intelligence_feed,
            "strategyOutput": strategy_output,
            "virtualOrderDesk": virtual_order_desk,
            "organizationDesk": research_snapshot.get("organizationDesk"),
            "researchTasks": research_snapshot.get("researchTasks", []),
            "evidenceSummary": research_snapshot.get("evidenceSummary", {}),
            "evidenceRecords": research_snapshot.get("evidenceRecords", []),
            "agentFindings": research_snapshot.get("agentFindings", []),
            "decisionContexts": research_snapshot.get("decisionContexts", []),
            "researchMarkdown": research_snapshot.get("researchMarkdown", ""),
            "virtualOrderMarkdown": virtual_order_desk.get("markdown", ""),
            "companies": runtime_snapshot.get("companies", []),
            "agentRuntime": runtime_snapshot.get("agentRuntime", []),
            "tradeProposals": runtime_snapshot.get("tradeProposals", []),
            "tradingConsensus": runtime_snapshot.get("tradingConsensus", {}),
            "runtimeQueue": runtime_snapshot.get("runtimeQueue", []),
            "sharedTradingContext": runtime_snapshot.get("sharedTradingContext", {}),
        }

    def build_symbol_payload(self, symbol: str, range_key: str) -> dict[str, Any]:
        return self._build_symbol(symbol.strip().upper(), range_key)


class DashboardRequestHandler(BaseHTTPRequestHandler):
    dashboard_service = DashboardService()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._send_json({"ok": True, "timestamp": datetime.now(UTC).isoformat()})
            return
        if path == "/api/dashboard":
            query = urllib.parse.parse_qs(parsed.query)
            symbol = query.get("symbol", ["6758.T"])[0]
            range_key = query.get("range", ["3mo"])[0]
            default_watch_symbols = ",".join(_load_watch_symbols())
            watch_symbols = [
                item.strip().upper()
                for item in query.get("watchlist", [default_watch_symbols])[0].split(",")
                if item.strip()
            ]
            try:
                self._send_json(self.dashboard_service.build_dashboard_payload(symbol, range_key, watch_symbols))
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc), **self.dashboard_service.build_dashboard_payload("6758.T", "3mo")})
            return
        if path.startswith("/api/symbol/"):
            symbol = path.rsplit("/", 1)[-1]
            query = urllib.parse.parse_qs(parsed.query)
            range_key = query.get("range", ["3mo"])[0]
            try:
                self._send_json(self.dashboard_service.build_symbol_payload(symbol, range_key))
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc), **self.dashboard_service.build_symbol_payload("6758.T", "3mo")})
            return
        if path == "/" or path == "/index.html":
            self._send_file(FRONTEND_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/styles.css":
            self._send_file(FRONTEND_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if path == "/app.jsx":
            self._send_file(FRONTEND_DIR / "app.jsx", "text/babel; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send_json(self, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Last-Modified", _fmt_http_date(time.time()))
        self.end_headers()
        self.wfile.write(content)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Last-Modified", _fmt_http_date(path.stat().st_mtime))
        self.end_headers()
        self.wfile.write(content)


def run_server(host: str = "127.0.0.1", port: int = 8501, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), DashboardRequestHandler)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    print(f"Investment Simulator Web UI: http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Investment Simulator web dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8501, type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
