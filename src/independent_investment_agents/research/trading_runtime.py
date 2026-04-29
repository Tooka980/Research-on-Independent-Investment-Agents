from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from independent_investment_agents.core.agent_runtime import load_agent_runtime_config
from independent_investment_agents.research.agent_reality import AgentRealityLayer
from independent_investment_agents.research.llm_provider import TemplateLanguageProvider


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / "artifacts" / "agent_runtime"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


@dataclass(frozen=True)
class SharedTradingContext:
    market_state: dict[str, Any]
    portfolio_state: dict[str, Any]
    evidence_refs: list[str]
    latest_prices: dict[str, float]
    candidate_symbols: list[str]
    risk_limits: dict[str, float]
    data_quality_by_symbol: dict[str, dict[str, Any]] = field(default_factory=dict)
    price_timestamp_by_symbol: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TradeProposal:
    trader_id: str
    symbol: str
    side: str
    order_type: str
    confidence: float
    expected_edge: float
    risk_notes: list[str]
    evidence_refs: list[str]
    id: str = field(default_factory=lambda: f"tprop-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TradingConsensus:
    status: str
    selected_proposal: TradeProposal | None
    rejected_proposals: list[TradeProposal]
    reason: str
    required_research_tasks: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: f"cons-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "selected_proposal": self.selected_proposal.to_dict() if self.selected_proposal else None,
            "rejected_proposals": [proposal.to_dict() for proposal in self.rejected_proposals],
        }


@dataclass
class AgentTask:
    task_id: str
    agent_id: str
    company: str
    task: str
    status: str
    reason: str
    priority: int
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    next_task: str | None = None
    message_ja: str = ""
    message_en: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentEvent:
    event_id: str
    agent_id: str
    event_type: str
    message: str
    created_at: str
    message_ja: str = ""
    message_en: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentRuntimeState:
    agent_id: str
    company: str
    label_ja: str
    label_en: str
    role: str
    status: str
    latest_task: str
    heartbeat_at: str
    last_run_at: str
    next_run_at: str
    duration_ms: int
    queue_depth: int
    logs: list[str]
    principles: list[str] = field(default_factory=list)
    completed_task_count: int = 0
    active_task_count: int = 0
    agent_reality_type: str = "simulated_status"
    agent_reality_label_ja: str = ""
    fetched_real_data: bool = False
    created_evidence: bool = False
    created_decision_context: bool = False
    virtual_asset_contribution: float = 0.0
    last_real_task_at: str | None = None
    last_real_evidence_id: str | None = None
    last_real_decision_id: str | None = None
    actual_processing_enabled: bool = False
    reality_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


COMPANY_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": "market-intelligence",
        "labelJa": "市場情報事業部",
        "labelEn": "Market Intelligence Company",
        "descriptionJa": "市場観測エージェント1体を中核に、補助分析員が広域価格、セクター、流動性を監視します。",
    },
    {
        "id": "research",
        "labelJa": "調査事業部",
        "labelEn": "Research Company",
        "descriptionJa": "ニュース取得、企業情報、候補銘柄探索、マクロ情報の収集を分担します。",
    },
    {
        "id": "quant-analysis",
        "labelJa": "分析事業部",
        "labelEn": "Quant Analysis Company",
        "descriptionJa": "全期間データ、ボラティリティ、相関、出来高比を分析します。",
    },
    {
        "id": "strategy",
        "labelJa": "意思決定支援事業部",
        "labelEn": "Strategy Company",
        "descriptionJa": "Evidenceと分析結果からDecisionContextとStrategy Outputを組み立てます。",
    },
    {
        "id": "virtual-trading",
        "labelJa": "仮想売買事業部",
        "labelEn": "Virtual Trading Company",
        "descriptionJa": "2名の仮想売買担当が共有情報を読み、Consensus Gateで一意に統合します。",
    },
    {
        "id": "operations",
        "labelJa": "運用管理事業部",
        "labelEn": "Operations Company",
        "descriptionJa": "常駐Runtime、タスクキュー、監査ログ、UI同期を管理します。",
    },
]


AGENT_DEFINITIONS: list[dict[str, Any]] = [
    {"id": "market-observer", "company": "market-intelligence", "labelJa": "市場観測エージェント", "labelEn": "Market Observer", "role": "official_observer", "principles": ["実データ優先", "市場フェーズ確認", "推測禁止"]},
    {"id": "market-breadth-scanner", "company": "market-intelligence", "labelJa": "市場スキャナー", "labelEn": "Market Breadth Scanner", "role": "support_analyst", "principles": ["広範囲監視", "優先度キュー", "上限なし"]},
    {"id": "sector-rotation-analyst", "company": "market-intelligence", "labelJa": "セクター観測員", "labelEn": "Sector Rotation Analyst", "role": "support_analyst", "principles": ["相対強弱確認", "テーマ過熱検知"]},
    {"id": "liquidity-volume-monitor", "company": "market-intelligence", "labelJa": "流動性監視員", "labelEn": "Liquidity & Volume Monitor", "role": "support_analyst", "principles": ["出来高検証", "薄商い警戒"]},
    {"id": "news-source-collector", "company": "research", "labelJa": "ニュース収集員", "labelEn": "News Source Collector", "role": "news_collector", "principles": ["RSSと保存済みEvidenceを優先", "見出しEvidenceを保存"]},
    {"id": "news-intelligence", "company": "research", "labelJa": "ニュース調査員", "labelEn": "News Intelligence", "role": "news_parser", "principles": ["本文未確認なら断定しない", "関連銘柄と論点を抽出"]},
    {"id": "news-impact-analyst", "company": "research", "labelJa": "ニュース影響評価員", "labelEn": "News Impact Analyst", "role": "news_impact", "principles": ["鮮度と影響度を採点", "過剰反応を警戒"]},
    {"id": "company-research", "company": "research", "labelJa": "企業調査員", "labelEn": "Company Research", "role": "company_profile", "principles": ["yfinance meta優先", "IR解析は将来拡張"]},
    {"id": "academic-macro-research", "company": "research", "labelJa": "学術・マクロ調査員", "labelEn": "Academic / Macro Research", "role": "macro_research", "principles": ["根拠不足はwaiting", "政策・業界仮説を保存"]},
    {"id": "opportunity-screener", "company": "research", "labelJa": "候補銘柄選別員", "labelEn": "Opportunity Screener", "role": "candidate_screening", "principles": ["候補理由を保存", "上限なし"]},
    {"id": "full-history-analyst", "company": "quant-analysis", "labelJa": "全期間分析員", "labelEn": "Full History Analyst", "role": "history_analysis", "principles": ["全期間データ使用", "表示期間と分析期間を分離"]},
    {"id": "correlation-risk-analyst", "company": "quant-analysis", "labelJa": "相関・分散分析員", "labelEn": "Correlation Risk Analyst", "role": "correlation_risk", "principles": ["集中リスク確認", "分散効果確認"]},
    {"id": "evidence-curator", "company": "strategy", "labelJa": "証拠整理員", "labelEn": "Evidence Curator", "role": "evidence_curation", "principles": ["重複排除", "低品質はアーカイブ"]},
    {"id": "strategy-synthesis", "company": "strategy", "labelJa": "戦略統合員", "labelEn": "Strategy Synthesis", "role": "strategy_output", "principles": ["EvidenceGate必須", "見送りも判断"]},
    {"id": "virtual-trader-a", "company": "virtual-trading", "labelJa": "仮想売買担当A", "labelEn": "Virtual Trader A", "role": "growth_trader", "principles": ["共有Contextのみ使用", "買い・リバランス候補"]},
    {"id": "virtual-trader-b", "company": "virtual-trading", "labelJa": "仮想売買担当B", "labelEn": "Virtual Trader B", "role": "risk_trader", "principles": ["共有Contextのみ使用", "売り・リスク削減候補"]},
    {"id": "trading-consensus-gate", "company": "virtual-trading", "labelJa": "売買合意ゲート", "labelEn": "Trading Consensus Gate", "role": "consensus_gate", "principles": ["意見割れは注文しない", "一意に統合"]},
    {"id": "runtime-scheduler", "company": "operations", "labelJa": "実行管理員", "labelEn": "Runtime Scheduler", "role": "runtime_scheduler", "principles": ["完了後即enqueue", "rate limit尊重"]},
    {"id": "portfolio-agent", "company": "operations", "labelJa": "仮想資産管理員", "labelEn": "Portfolio Agent", "role": "portfolio_sync", "principles": ["VirtualExecutionのみ反映", "実資金なし"]},
    {"id": "ui-agent", "company": "operations", "labelJa": "表示同期員", "labelEn": "UI Agent", "role": "ui_sync", "principles": ["状態をUIへ反映", "デザイン維持"]},
]


class AgentRuntimeStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DEFAULT_RUNTIME_DIR
        self.database_path = self.root / "runtime.sqlite3"
        self.events_path = self.root / "runtime_events.jsonl"

    def ensure_schema(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_states (
                    agent_id TEXT PRIMARY KEY,
                    company TEXT NOT NULL,
                    label_ja TEXT NOT NULL,
                    label_en TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latest_task TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    last_run_at TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    queue_depth INTEGER NOT NULL,
                    logs TEXT NOT NULL,
                    principles TEXT NOT NULL,
                    completed_task_count INTEGER NOT NULL,
                    active_task_count INTEGER NOT NULL
                )
                """
            )
            self._ensure_columns(
                conn,
                "runtime_states",
                {
                    "agent_reality_type": "TEXT NOT NULL DEFAULT 'simulated_status'",
                    "agent_reality_label_ja": "TEXT NOT NULL DEFAULT ''",
                    "fetched_real_data": "INTEGER NOT NULL DEFAULT 0",
                    "created_evidence": "INTEGER NOT NULL DEFAULT 0",
                    "created_decision_context": "INTEGER NOT NULL DEFAULT 0",
                    "virtual_asset_contribution": "REAL NOT NULL DEFAULT 0.0",
                    "last_real_task_at": "TEXT",
                    "last_real_evidence_id": "TEXT",
                    "last_real_decision_id": "TEXT",
                    "actual_processing_enabled": "INTEGER NOT NULL DEFAULT 0",
                    "reality_note": "TEXT NOT NULL DEFAULT ''",
                },
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_tasks (
                    task_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    company TEXT NOT NULL,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    next_task TEXT
                )
                """
            )
            self._ensure_columns(
                conn,
                "runtime_tasks",
                {
                    "message_ja": "TEXT NOT NULL DEFAULT ''",
                    "message_en": "TEXT NOT NULL DEFAULT ''",
                },
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_events (
                    event_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(
                conn,
                "runtime_events",
                {
                    "message_ja": "TEXT NOT NULL DEFAULT ''",
                    "message_en": "TEXT NOT NULL DEFAULT ''",
                },
            )

    def save_state(self, state: AgentRuntimeState) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runtime_states (
                    agent_id, company, label_ja, label_en, role, status, latest_task,
                    heartbeat_at, last_run_at, next_run_at, duration_ms, queue_depth,
                    logs, principles, completed_task_count, active_task_count,
                    agent_reality_type, agent_reality_label_ja, fetched_real_data,
                    created_evidence, created_decision_context, virtual_asset_contribution,
                    last_real_task_at, last_real_evidence_id, last_real_decision_id,
                    actual_processing_enabled, reality_note
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    state.agent_id,
                    state.company,
                    state.label_ja,
                    state.label_en,
                    state.role,
                    state.status,
                    state.latest_task,
                    state.heartbeat_at,
                    state.last_run_at,
                    state.next_run_at,
                    state.duration_ms,
                    state.queue_depth,
                    _json(state.logs),
                    _json(state.principles),
                    state.completed_task_count,
                    state.active_task_count,
                    state.agent_reality_type,
                    state.agent_reality_label_ja,
                    1 if state.fetched_real_data else 0,
                    1 if state.created_evidence else 0,
                    1 if state.created_decision_context else 0,
                    state.virtual_asset_contribution,
                    state.last_real_task_at,
                    state.last_real_evidence_id,
                    state.last_real_decision_id,
                    1 if state.actual_processing_enabled else 0,
                    state.reality_note,
                ),
            )

    def save_task(self, task: AgentTask) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runtime_tasks (
                    task_id, agent_id, company, task, status, reason, priority,
                    created_at, started_at, completed_at, next_task, message_ja, message_en
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.agent_id,
                    task.company,
                    task.task,
                    task.status,
                    task.reason,
                    task.priority,
                    task.created_at,
                    task.started_at,
                    task.completed_at,
                    task.next_task,
                    task.message_ja,
                    task.message_en or task.reason,
                ),
            )

    def save_event(self, event: AgentEvent) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runtime_events (
                    event_id, agent_id, event_type, message, created_at, message_ja, message_en
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event.event_id, event.agent_id, event.event_type, event.message, event.created_at, event.message_ja, event.message_en or event.message),
            )
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(_json(event.to_dict()) + "\n")

    def list_states(self) -> list[AgentRuntimeState]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = list(conn.execute("SELECT * FROM runtime_states ORDER BY rowid ASC"))
        return [self._row_to_state(row) for row in rows]

    def list_tasks(self, limit: int = 20) -> list[AgentTask]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = list(conn.execute("SELECT * FROM runtime_tasks ORDER BY created_at DESC LIMIT ?", (limit,)))
        return [self._row_to_task(row) for row in rows]

    def count_completed(self, agent_id: str) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM runtime_tasks WHERE agent_id = ? AND status = 'completed'",
                (agent_id,),
            ).fetchone()
        return int(row[0] if row else 0)

    def _ensure_columns(self, conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @contextmanager
    def _connect(self) -> Any:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _row_to_state(self, row: sqlite3.Row) -> AgentRuntimeState:
        return AgentRuntimeState(
            agent_id=row["agent_id"],
            company=row["company"],
            label_ja=row["label_ja"],
            label_en=row["label_en"],
            role=row["role"],
            status=row["status"],
            latest_task=row["latest_task"],
            heartbeat_at=row["heartbeat_at"],
            last_run_at=row["last_run_at"],
            next_run_at=row["next_run_at"],
            duration_ms=int(row["duration_ms"]),
            queue_depth=int(row["queue_depth"]),
            logs=[str(item) for item in _json_list(row["logs"])],
            principles=[str(item) for item in _json_list(row["principles"])],
            completed_task_count=int(row["completed_task_count"]),
            active_task_count=int(row["active_task_count"]),
            agent_reality_type=row["agent_reality_type"],
            agent_reality_label_ja=row["agent_reality_label_ja"],
            fetched_real_data=bool(row["fetched_real_data"]),
            created_evidence=bool(row["created_evidence"]),
            created_decision_context=bool(row["created_decision_context"]),
            virtual_asset_contribution=float(row["virtual_asset_contribution"]),
            last_real_task_at=row["last_real_task_at"],
            last_real_evidence_id=row["last_real_evidence_id"],
            last_real_decision_id=row["last_real_decision_id"],
            actual_processing_enabled=bool(row["actual_processing_enabled"]),
            reality_note=row["reality_note"],
        )

    def _row_to_task(self, row: sqlite3.Row) -> AgentTask:
        return AgentTask(
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            company=row["company"],
            task=row["task"],
            status=row["status"],
            reason=row["reason"],
            priority=int(row["priority"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            next_task=row["next_task"],
            message_ja=row["message_ja"],
            message_en=row["message_en"],
        )


def _price_ready(context: SharedTradingContext, symbol: str) -> bool:
    price = float(context.latest_prices.get(symbol) or 0.0)
    if price <= 0 or not math.isfinite(price):
        return False
    data_quality = context.data_quality_by_symbol.get(symbol) or {}
    if not data_quality:
        return True
    source = str(data_quality.get("priceSource") or data_quality.get("displaySource") or "")
    if source == "data_unavailable":
        return False
    if data_quality.get("needsResearch") and not data_quality.get("hasAnalysisHistory"):
        return False
    timestamp = context.price_timestamp_by_symbol.get(symbol) or data_quality.get("latestPriceAt")
    if context.market_state.get("is_open") and timestamp:
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - parsed.astimezone(timezone.utc) > timedelta(days=3):
            return False
    return True


def _message_ja_for_status(task_status: str, agent_status: str) -> str:
    if task_status == "running":
        return "実処理を実行しています。"
    if agent_status == "blocked":
        return "必要なデータまたは根拠が不足しているため停止中です。"
    if agent_status.startswith("waiting"):
        return "次の市場データまたは処理順を待機しています。"
    if task_status == "completed":
        return "処理を完了し、次の判断材料へ反映しました。"
    return "エージェント状態を更新しました。"


def _score_trade_candidate(context: SharedTradingContext, bias: str) -> dict[str, Any]:
    cash = float(context.portfolio_state.get("cash") or 0.0)
    equity = float(context.portfolio_state.get("equity") or max(cash, 1.0))
    cash_ratio = cash / max(equity, 1.0)
    max_notional = float(context.risk_limits.get("max_order_value") or 120_000.0)
    if bias == "risk":
        side = "sell" if cash_ratio < 0.18 else "hold"
        return {
            "side": side,
            "order_type": "liquidation",
            "expected_edge": 0.01 if side == "sell" else 0.0,
            "confidence": 0.58 if side == "sell" else 0.42,
            "risk_notes": ["現金比率ガード", "リスク削減寄り", "SharedTradingContext共通スコア"],
        }
    side = "buy" if cash_ratio > 0.22 else "hold"
    return {
        "side": side,
        "order_type": "rebalance",
        "expected_edge": min(0.035, max_notional / max(equity, 1.0)),
        "confidence": 0.62 if side == "buy" else 0.44,
        "risk_notes": ["資金配分余地あり", "EvidenceGate通過", "SharedTradingContext共通スコア"],
    }


class VirtualTrader:
    def __init__(self, trader_id: str, bias: str) -> None:
        self.trader_id = trader_id
        self.bias = bias

    def propose(self, context: SharedTradingContext) -> TradeProposal | None:
        if not context.market_state.get("is_open"):
            return None
        if not context.evidence_refs:
            return None
        symbol = context.candidate_symbols[0] if context.candidate_symbols else ""
        price = float(context.latest_prices.get(symbol) or 0.0)
        if not symbol or price <= 0 or not math.isfinite(price) or not _price_ready(context, symbol):
            return None
        score = _score_trade_candidate(context, self.bias)
        side = score["side"]

        if side == "hold":
            return None
        return TradeProposal(
            trader_id=self.trader_id,
            symbol=symbol,
            side=side,
            order_type=score["order_type"],
            confidence=score["confidence"],
            expected_edge=score["expected_edge"],
            risk_notes=score["risk_notes"],
            evidence_refs=list(context.evidence_refs),
        )


class TradingConsensusGate:
    def decide(self, proposals: list[TradeProposal], context: SharedTradingContext) -> TradingConsensus:
        if not context.market_state.get("is_open"):
            return TradingConsensus(
                status="waiting_for_market",
                selected_proposal=None,
                rejected_proposals=proposals,
                reason="市場外のため、仮想注文は作成せず次の市場中監視を待機します。",
                required_research_tasks=["market_open_recheck"],
            )
        if not context.evidence_refs:
            return TradingConsensus(
                status="blocked",
                selected_proposal=None,
                rejected_proposals=proposals,
                reason="Evidenceが不足しているため、追加調査へ戻します。",
                required_research_tasks=["collect_trade_evidence"],
            )
        symbols_to_check = list(dict.fromkeys([proposal.symbol for proposal in proposals] or context.candidate_symbols[:1]))
        stale_symbols = [symbol for symbol in symbols_to_check if not _price_ready(context, symbol)]
        if stale_symbols:
            return TradingConsensus(
                status="blocked",
                selected_proposal=None,
                rejected_proposals=proposals,
                reason=f"価格鮮度または実データが不足しています: {', '.join(stale_symbols)}。追加調査へ戻します。",
                required_research_tasks=["refresh_price_source"],
            )

        min_confidence = float(context.risk_limits.get("min_confidence_to_trade") or 0.0)
        confidence_rejected = [
            proposal
            for proposal in proposals
            if proposal.side in {"buy", "sell"} and proposal.confidence < min_confidence
        ]
        actionable = [
            proposal
            for proposal in proposals
            if proposal.side in {"buy", "sell"} and proposal.confidence >= min_confidence
        ]
        if not actionable:
            return TradingConsensus(
                status="hold_watch",
                selected_proposal=None,
                rejected_proposals=confidence_rejected,
                reason="2名の仮想売買担当が見送り判定。観測を継続します。",
                required_research_tasks=["refresh_price_and_volume"],
            )

        sides = {proposal.side for proposal in actionable}
        if len(sides) > 1:
            return TradingConsensus(
                status="needs_review",
                selected_proposal=None,
                rejected_proposals=actionable,
                reason="買いと売りの方向が割れたため、注文せず追加分析へ戻します。",
                required_research_tasks=["resolve_trade_direction_conflict"],
            )

        selected = sorted(actionable, key=lambda item: (item.confidence, item.expected_edge), reverse=True)[0]
        return TradingConsensus(
            status="approved_for_virtual_order",
            selected_proposal=selected,
            rejected_proposals=[proposal for proposal in actionable if proposal.id != selected.id],
            reason="共有情報とConsensus Gateにより、仮想注文候補を一意に統合しました。",
        )


class AgentRuntimeEngine:
    def __init__(
        self,
        runtime_dir: Path | None = None,
        *,
        tick_interval: float = 2.0,
        start_background: bool = False,
    ) -> None:
        self.store = AgentRuntimeStore(runtime_dir)
        self.tick_interval = tick_interval
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_context: SharedTradingContext | None = None
        self._latest_snapshot: dict[str, Any] | None = None
        self._tick_count = 0
        self.language = TemplateLanguageProvider()
        if start_background:
            self.start()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="agent-runtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def run(
        self,
        context: SharedTradingContext,
        organization_desk: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._latest_context = context
            self._latest_snapshot = self._tick(context, organization_desk, trigger="api")
            return self._latest_snapshot

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                if self._latest_context is not None:
                    self._latest_snapshot = self._tick(self._latest_context, None, trigger="background")
            self._stop_event.wait(self.tick_interval)

    def _tick(
        self,
        context: SharedTradingContext,
        organization_desk: dict[str, Any] | None,
        *,
        trigger: str,
    ) -> dict[str, Any]:
        self.store.ensure_schema()
        trader_a = VirtualTrader("virtual-trader-a", "growth")
        trader_b = VirtualTrader("virtual-trader-b", "risk")
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="virtual-trader") as executor:
            proposals = [
                proposal
                for proposal in executor.map(lambda trader: trader.propose(context), [trader_a, trader_b])
                if proposal
            ]
        consensus = TradingConsensusGate().decide(proposals, context)
        self._tick_count += 1
        queue = self._queue(context, consensus)
        states = self._states(context, consensus, queue, trigger)
        companies = self._companies(states)
        snapshot = {
            "sharedTradingContext": context.to_dict(),
            "companies": companies,
            "agentRuntime": [state.to_dict() for state in states],
            "tradeProposals": [proposal.to_dict() for proposal in proposals],
            "tradingConsensus": consensus.to_dict(),
            "runtimeQueue": queue,
            "runtimeEvents": [event.to_dict() for event in self._events_for(states, consensus)],
            "organizationLinked": bool(organization_desk),
        }
        return snapshot

    def _states(
        self,
        context: SharedTradingContext,
        consensus: TradingConsensus,
        queue: list[dict[str, Any]],
        trigger: str,
    ) -> list[AgentRuntimeState]:
        now = datetime.now(timezone.utc)
        active_agent = _agent_for_task(queue[0]["task"] if queue else "")
        states: list[AgentRuntimeState] = []
        reality_layer = AgentRealityLayer()
        for index, definition in enumerate(AGENT_DEFINITIONS):
            status = _status_for(definition, context, consensus, active_agent)
            latest_task = _latest_task_for(definition["id"], context, consensus, queue)
            reality = reality_layer.describe(
                definition["id"],
                latest_task=latest_task,
                evidence_id=context.evidence_refs[0] if context.evidence_refs else None,
                decision_id=None,
            )
            duration_ms = 28 + ((self._tick_count + index) % 11) * 9
            task_status = "running" if definition["id"] == active_agent else ("waiting" if status.startswith("waiting") else "completed")
            completed_at = None if task_status in {"running", "waiting"} else utc_now_iso()
            task = AgentTask(
                task_id=f"rt-{definition['id']}-{self._tick_count}",
                agent_id=definition["id"],
                company=definition["company"],
                task=latest_task,
                status=task_status,
                reason=_reason_for(definition["id"], context, consensus),
                priority=1 if definition["id"] == active_agent else 3,
                created_at=utc_now_iso(),
                started_at=utc_now_iso(),
                completed_at=completed_at,
                next_task=_next_task_for(definition["id"], context),
                message_ja=_message_ja_for_status(task_status, status),
            )
            self.store.save_task(task)
            self.store.save_event(
                AgentEvent(
                    event_id=f"evt-{definition['id']}-{self._tick_count}",
                    agent_id=definition["id"],
                    event_type=task_status,
                    message=task.reason,
                    created_at=utc_now_iso(),
                    message_ja=task.message_ja,
                )
            )
            completed_count = self.store.count_completed(definition["id"])
            state = AgentRuntimeState(
                agent_id=definition["id"],
                company=definition["company"],
                label_ja=definition["labelJa"],
                label_en=definition["labelEn"],
                role=definition["role"],
                status=status,
                latest_task=latest_task,
                heartbeat_at=utc_now_iso(),
                last_run_at=(now - timedelta(milliseconds=duration_ms)).isoformat(),
                next_run_at=(now + timedelta(seconds=1 + ((self._tick_count + index) % 5))).isoformat(),
                duration_ms=duration_ms,
                queue_depth=max(0, len(queue) - (index % 4)),
                logs=_logs_for(definition["id"], context, consensus, trigger, self.language),
                principles=list(definition.get("principles", [])),
                completed_task_count=completed_count,
                active_task_count=1 if task_status == "running" else 0,
                agent_reality_type=reality["agent_reality_type"],
                agent_reality_label_ja=reality["agent_reality_label_ja"],
                fetched_real_data=bool(reality["fetched_real_data"]),
                created_evidence=bool(reality["created_evidence"]),
                created_decision_context=bool(reality["created_decision_context"]),
                last_real_task_at=reality["last_real_task_at"],
                last_real_evidence_id=reality["last_real_evidence_id"],
                last_real_decision_id=reality["last_real_decision_id"],
                actual_processing_enabled=bool(reality["actual_processing_enabled"]),
                reality_note=reality["reality_note"],
            )
            self.store.save_state(state)
            states.append(state)
        return states

    def _companies(self, states: list[AgentRuntimeState]) -> list[dict[str, Any]]:
        by_company: dict[str, list[dict[str, Any]]] = {}
        for state in states:
            by_company.setdefault(state.company, []).append(state.to_dict())
        companies: list[dict[str, Any]] = []
        for company in COMPANY_DEFINITIONS:
            agents = by_company.get(company["id"], [])
            companies.append(
                {
                    **company,
                    "agents": agents,
                    "activeTaskCount": sum(int(agent.get("active_task_count") or 0) for agent in agents),
                    "completedTaskCount": sum(int(agent.get("completed_task_count") or 0) for agent in agents),
                    "waitingReason": _company_waiting_reason(company["id"], agents),
                }
            )
        return companies

    def _queue(self, context: SharedTradingContext, consensus: TradingConsensus) -> list[dict[str, Any]]:
        if context.market_state.get("is_open"):
            sequence = [
                "price_scan",
                "evidence_update",
                "analysis_update",
                "decision_context",
                "virtual_trader_consensus",
                "risk_gate",
                "virtual_order_simulation",
            ]
        else:
            sequence = [
                "news_source_collect",
                "news_impact_score",
                "company_research",
                "full_history_analysis",
                "tomorrow_scenario",
                "watchlist_priority_update",
            ]
        if sequence:
            rotate = self._tick_count % len(sequence)
            sequence = sequence[rotate:] + sequence[:rotate]
        return [
            {
                "id": f"queue-{self._tick_count}-{idx}-{item}",
                "task": item,
                "status": "running" if idx == 0 else "queued",
                "reason": consensus.reason if idx == 0 else "前段タスク完了後に即時実行します。",
            }
            for idx, item in enumerate(sequence)
        ]

    def _events_for(self, states: list[AgentRuntimeState], consensus: TradingConsensus) -> list[AgentEvent]:
        now = utc_now_iso()
        active = [state for state in states if state.status == "running"][:4]
        return [
            AgentEvent(
                event_id=f"event-view-{state.agent_id}-{idx}",
                agent_id=state.agent_id,
                event_type=state.status,
                message=state.logs[-1] if state.logs else consensus.reason,
                created_at=now,
            )
            for idx, state in enumerate(active)
        ]


def build_shared_trading_context(
    *,
    focus: dict[str, Any],
    market: dict[str, Any],
    portfolio: dict[str, Any],
    watchlist: list[dict[str, Any]],
    evidence_refs: list[str],
) -> SharedTradingContext:
    runtime_config = load_agent_runtime_config()
    candidates = _candidate_symbols(focus, watchlist)
    latest_prices = {
        str(item.get("symbol")).upper(): float(item.get("current") or 0.0)
        for item in watchlist
        if item.get("symbol")
    }
    data_quality_by_symbol = {
        str(item.get("symbol")).upper(): dict(item.get("dataQuality") or {})
        for item in watchlist
        if item.get("symbol")
    }
    price_timestamp_by_symbol = {
        symbol: str(quality.get("latestPriceAt"))
        for symbol, quality in data_quality_by_symbol.items()
        if quality.get("latestPriceAt")
    }
    focus_symbol = str(focus.get("symbol") or "").upper()
    if focus_symbol:
        latest_prices[focus_symbol] = float(focus.get("quote", {}).get("current") or latest_prices.get(focus_symbol) or 0.0)
        data_quality_by_symbol[focus_symbol] = dict(focus.get("dataQuality") or data_quality_by_symbol.get(focus_symbol) or {})
        timestamp = focus.get("quote", {}).get("asOf") or data_quality_by_symbol[focus_symbol].get("latestPriceAt")
        if timestamp:
            price_timestamp_by_symbol[focus_symbol] = str(timestamp)

    return SharedTradingContext(
        market_state={
            "is_open": bool(market.get("is_open")),
            "phase": market.get("phase"),
            "label": market.get("label"),
        },
        portfolio_state=portfolio,
        evidence_refs=[ref for ref in evidence_refs if ref],
        latest_prices=latest_prices,
        candidate_symbols=candidates,
        risk_limits={
            "max_order_value": 120_000.0,
            "min_cash_ratio": 0.12,
            "max_single_symbol_share": 0.28,
            "min_confidence_to_trade": runtime_config.min_confidence_to_trade,
        },
        data_quality_by_symbol=data_quality_by_symbol,
        price_timestamp_by_symbol=price_timestamp_by_symbol,
    )


def _candidate_symbols(focus: dict[str, Any], watchlist: list[dict[str, Any]]) -> list[str]:
    rows = sorted(watchlist, key=lambda item: abs(float(item.get("changePct") or 0.0)), reverse=True)
    symbols = [str(focus.get("symbol") or "").upper()]
    symbols.extend(str(row.get("symbol") or "").upper() for row in rows)
    deduped: list[str] = []
    for symbol in symbols:
        if symbol and symbol not in deduped:
            deduped.append(symbol)
    return deduped


def _agent_for_task(task: str) -> str:
    mapping = {
        "price_scan": "market-observer",
        "evidence_update": "evidence-curator",
        "analysis_update": "full-history-analyst",
        "decision_context": "strategy-synthesis",
        "virtual_trader_consensus": "trading-consensus-gate",
        "risk_gate": "virtual-trader-b",
        "virtual_order_simulation": "virtual-trader-a",
        "news_source_collect": "news-source-collector",
        "news_impact_score": "news-impact-analyst",
        "company_research": "company-research",
        "full_history_analysis": "full-history-analyst",
        "tomorrow_scenario": "strategy-synthesis",
        "watchlist_priority_update": "opportunity-screener",
    }
    return mapping.get(task, "runtime-scheduler")


def _status_for(
    definition: dict[str, Any],
    context: SharedTradingContext,
    consensus: TradingConsensus,
    active_agent: str,
) -> str:
    agent_id = definition["id"]
    if agent_id == active_agent:
        return "running"
    if definition["company"] == "virtual-trading" and not context.market_state.get("is_open"):
        return "waiting_for_market"
    if agent_id == "trading-consensus-gate":
        return {
            "approved_for_virtual_order": "success",
            "hold_watch": "ready",
            "needs_review": "warning",
            "blocked": "blocked",
            "waiting_for_market": "waiting_for_market",
        }.get(consensus.status, "waiting")
    if agent_id == "academic-macro-research" and not context.evidence_refs:
        return "waiting"
    return "success"


def _latest_task_for(
    agent_id: str,
    context: SharedTradingContext,
    consensus: TradingConsensus,
    queue: list[dict[str, Any]],
) -> str:
    first_task = queue[0]["task"] if queue else "runtime_idle"
    if agent_id == "market-observer":
        return f"{len(context.candidate_symbols)}銘柄の市場状態を再確認"
    if agent_id == "market-breadth-scanner":
        return f"{len(context.candidate_symbols)}銘柄の広域価格監視"
    if agent_id == "news-source-collector":
        return "RSS・yfinance news・保存済みEvidenceの取得"
    if agent_id == "news-intelligence":
        return "ニュース見出しから関連銘柄と論点を抽出"
    if agent_id == "news-impact-analyst":
        return "ニュース鮮度・信頼度・影響度を採点"
    if agent_id == "academic-macro-research":
        return "マクロ情報源を確認し、根拠不足ならResearchTaskへ戻す"
    if agent_id == "strategy-synthesis":
        return f"Strategy Output更新 / active={first_task}"
    if agent_id == "virtual-trader-a":
        return "共有情報から買い・リバランス候補を検査"
    if agent_id == "virtual-trader-b":
        return "共有情報から売り・リスク削減候補を検査"
    if agent_id == "trading-consensus-gate":
        return f"Consensus: {consensus.status}"
    if agent_id == "runtime-scheduler":
        return f"次タスク投入: {first_task}"
    if agent_id == "portfolio-agent":
        return "VirtualExecutionのみを資産へ反映"
    if agent_id == "ui-agent":
        return "Runtime状態をUIへ同期"
    return "完了結果を保存し、次タスクを準備"


def _next_task_for(agent_id: str, context: SharedTradingContext) -> str:
    if context.market_state.get("is_open"):
        return "price_scan"
    if agent_id.startswith("news"):
        return "news_impact_score"
    if agent_id == "strategy-synthesis":
        return "tomorrow_scenario"
    return "next_ready_task"


def _reason_for(agent_id: str, context: SharedTradingContext, consensus: TradingConsensus) -> str:
    if agent_id.startswith("news"):
        return "ニュース調査3体制で取得・抽出・影響評価を分担しています。"
    if agent_id.startswith("virtual") or agent_id == "trading-consensus-gate":
        return consensus.reason
    if context.market_state.get("is_open"):
        return "市場中のため価格監視と意思決定更新を優先しています。"
    return "閉場中のため調査、Evidence整理、翌営業日シナリオを優先しています。"


def _logs_for(
    agent_id: str,
    context: SharedTradingContext,
    consensus: TradingConsensus,
    trigger: str,
    language: TemplateLanguageProvider | None = None,
) -> list[str]:
    phase = context.market_state.get("phase") or "unknown"
    symbol = context.candidate_symbols[0] if context.candidate_symbols else "N/A"
    evidence_line = (
        f"evidence_refs={','.join(context.evidence_refs[:4])}"
        if context.evidence_refs
        else "根拠不足: evidence_refsなし"
    )
    template_line = (
        language.pick("agent_logs", symbol, phase, agent_id, trigger, len(context.evidence_refs))
        if language is not None
        else f"{symbol}: Runtime heartbeatを更新しました。"
    )
    if agent_id == "trading-consensus-gate":
        return [template_line, consensus.reason, evidence_line, f"required_tasks={','.join(consensus.required_research_tasks) or 'none'}"]
    if agent_id == "virtual-trader-a":
        return [template_line, "SharedTradingContextを読込", "買い・リバランス制約を評価", evidence_line, f"trigger={trigger}"]
    if agent_id == "virtual-trader-b":
        return [template_line, "SharedTradingContextを読込", "売り・リスク削減制約を評価", evidence_line, f"trigger={trigger}"]
    if agent_id == "news-source-collector":
        return [template_line, "ニュースソースを確認", "RSS / yfinance news / 保存Evidenceを照合", evidence_line, f"phase={phase}"]
    if agent_id == "news-intelligence":
        return [template_line, "見出しEvidenceを正規化", "関連銘柄と論点を抽出", evidence_line]
    if agent_id == "news-impact-analyst":
        return [template_line, "ニュース鮮度を採点", "影響度をStrategy Outputへ渡す", evidence_line, f"phase={phase}"]
    if agent_id == "academic-macro-research":
        return [template_line, "マクロ情報源を確認", "根拠不足ならwaiting_for_sourceへ戻す", evidence_line]
    if context.market_state.get("is_open"):
        return [template_line, "市場中モード: 価格監視を優先", "完了後すぐに次タスクへ移行", evidence_line]
    return [template_line, "閉場後モード: 調査・分析を優先", "次回市場中の監視準備を更新", evidence_line]


def _company_waiting_reason(company_id: str, agents: list[dict[str, Any]]) -> str:
    waiting = [agent for agent in agents if str(agent.get("status", "")).startswith("waiting")]
    if not waiting:
        return ""
    if company_id == "virtual-trading":
        return "市場外のため仮想約定は待機しています。"
    return "実データまたはEvidenceの追加取得を待っています。"
