from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from independent_investment_agents.research.models import (
    AgentFinding,
    DecisionContext,
    EvidenceRecord,
    KnowledgeMemory,
    ResearchTask,
    json_dumps,
    json_loads_list,
)
from independent_investment_agents.research.task_policies import TaskDeduplicator, TaskTTL


class ResearchRepository:
    """SQLite-backed repository for research evidence and decisions."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.markdown_path = database_path.parent / "research_summary.md"

    def ensure_schema(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_tasks (
                    id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    target_symbols TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_by_agent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_records (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    url_or_path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    published_at TEXT,
                    collected_at TEXT NOT NULL,
                    related_symbols TEXT NOT NULL,
                    related_topics TEXT NOT NULL,
                    raw_text_path TEXT,
                    summary TEXT NOT NULL,
                    extracted_facts TEXT NOT NULL,
                    sentiment_score REAL NOT NULL,
                    relevance_score REAL NOT NULL,
                    credibility_score REAL NOT NULL,
                    freshness_score REAL NOT NULL,
                    impact_score REAL NOT NULL,
                    duplicate_of TEXT,
                    archived INTEGER NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    conflict_with TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(
                conn,
                "evidence_records",
                {
                    "score_reason": "TEXT NOT NULL DEFAULT ''",
                    "source_reliability_basis": "TEXT NOT NULL DEFAULT ''",
                    "verified_body": "INTEGER NOT NULL DEFAULT 0",
                    "body_fetched": "INTEGER NOT NULL DEFAULT 0",
                    "headline_only": "INTEGER NOT NULL DEFAULT 0",
                    "used_in_decisions": "TEXT NOT NULL DEFAULT '[]'",
                    "outcome_score": "REAL",
                    "available_at": "TEXT",
                },
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_hash ON evidence_records(evidence_hash)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_findings (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    related_task_id TEXT,
                    related_evidence_ids TEXT NOT NULL,
                    finding_type TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    limitations TEXT NOT NULL,
                    suggested_actions TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_contexts (
                    id TEXT PRIMARY KEY,
                    target_symbol TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    related_evidence_ids TEXT NOT NULL,
                    related_findings TEXT NOT NULL,
                    market_state_summary TEXT NOT NULL,
                    company_summary TEXT NOT NULL,
                    news_summary TEXT NOT NULL,
                    risk_summary TEXT NOT NULL,
                    final_recommendation_for_simulation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    missing_information TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    target_value REAL,
                    limit_price REAL,
                    stop_price REAL,
                    reason TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(
                conn,
                "decision_contexts",
                {
                    "bullish_reasons": "TEXT NOT NULL DEFAULT '[]'",
                    "bearish_reasons": "TEXT NOT NULL DEFAULT '[]'",
                    "counterarguments": "TEXT NOT NULL DEFAULT '[]'",
                    "invalidation_conditions": "TEXT NOT NULL DEFAULT '[]'",
                    "alternative_scenarios": "TEXT NOT NULL DEFAULT '[]'",
                    "what_would_change_our_mind": "TEXT NOT NULL DEFAULT '[]'",
                    "recommended_holding_period": "TEXT NOT NULL DEFAULT ''",
                    "stop_loss_plan": "TEXT NOT NULL DEFAULT ''",
                    "take_profit_plan": "TEXT NOT NULL DEFAULT ''",
                    "position_size_reason": "TEXT NOT NULL DEFAULT ''",
                    "expected_return": "REAL",
                    "expected_risk": "REAL",
                    "risk_reward_ratio": "REAL",
                    "data_as_of": "TEXT",
                },
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_memory (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    related_symbols TEXT NOT NULL,
                    related_topics TEXT NOT NULL,
                    source_evidence_ids TEXT NOT NULL,
                    importance_score REAL NOT NULL,
                    last_used_at TEXT,
                    expires_at TEXT,
                    archived INTEGER NOT NULL
                )
                """
            )

    def save_task(self, task: ResearchTask) -> ResearchTask:
        self.ensure_schema()
        with self._connect() as conn:
            if task.status not in {"completed", "blocked", "stale"}:
                existing_rows = list(
                    conn.execute(
                        "SELECT * FROM research_tasks WHERE status NOT IN ('completed', 'blocked', 'stale')"
                    )
                )
                existing_tasks = [self._row_to_task(row) for row in existing_rows]
                merge = TaskDeduplicator().is_duplicate(task, existing_tasks)
                if merge.action == "merge" and merge.existing_task_id:
                    match = next((item for item in existing_tasks if item.id == merge.existing_task_id), None)
                    if match is not None:
                        return match
            conn.execute(
                """
                INSERT OR REPLACE INTO research_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.task_type,
                    json_dumps(task.target_symbols),
                    task.topic,
                    task.priority,
                    task.created_by_agent,
                    task.status,
                    task.reason,
                    task.created_at,
                    task.completed_at,
                ),
            )
        return task

    def save_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        self.ensure_schema()
        duplicate = self.find_evidence_by_hash(evidence.evidence_hash)
        if duplicate and duplicate.id != evidence.id:
            evidence.duplicate_of = duplicate.id
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO evidence_records (
                    id, source_type, source_name, url_or_path, title, published_at, collected_at,
                    related_symbols, related_topics, raw_text_path, summary, extracted_facts,
                    sentiment_score, relevance_score, credibility_score, freshness_score, impact_score,
                    duplicate_of, archived, evidence_hash, conflict_with, score_reason,
                    source_reliability_basis, verified_body, body_fetched, headline_only,
                    used_in_decisions, outcome_score, available_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    evidence.id,
                    evidence.source_type,
                    evidence.source_name,
                    evidence.url_or_path,
                    evidence.title,
                    evidence.published_at,
                    evidence.collected_at,
                    json_dumps(evidence.related_symbols),
                    json_dumps(evidence.related_topics),
                    evidence.raw_text_path,
                    evidence.summary,
                    json_dumps(evidence.extracted_facts),
                    evidence.sentiment_score,
                    evidence.relevance_score,
                    evidence.credibility_score,
                    evidence.freshness_score,
                    evidence.impact_score,
                    evidence.duplicate_of,
                    1 if evidence.archived else 0,
                    evidence.evidence_hash,
                    json_dumps(evidence.conflict_with),
                    evidence.score_reason,
                    evidence.source_reliability_basis,
                    1 if evidence.verified_body else 0,
                    1 if evidence.body_fetched else 0,
                    1 if evidence.headline_only else 0,
                    json_dumps(evidence.used_in_decisions),
                    evidence.outcome_score,
                    evidence.available_at,
                ),
            )
        return evidence

    def save_finding(self, finding: AgentFinding) -> AgentFinding:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agent_findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    finding.id,
                    finding.agent_name,
                    finding.related_task_id,
                    json_dumps(finding.related_evidence_ids),
                    finding.finding_type,
                    finding.claim,
                    finding.confidence,
                    json_dumps(finding.limitations),
                    json_dumps(finding.suggested_actions),
                    finding.created_at,
                ),
            )
        return finding

    def save_decision_context(self, decision: DecisionContext) -> DecisionContext:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO decision_contexts (
                    id, target_symbol, decision_type, related_evidence_ids, related_findings,
                    market_state_summary, company_summary, news_summary, risk_summary,
                    final_recommendation_for_simulation, confidence, missing_information, created_at,
                    side, order_type, target_value, limit_price, stop_price, reason,
                    bullish_reasons, bearish_reasons, counterarguments, invalidation_conditions,
                    alternative_scenarios, what_would_change_our_mind, recommended_holding_period,
                    stop_loss_plan, take_profit_plan, position_size_reason, expected_return,
                    expected_risk, risk_reward_ratio, data_as_of
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    decision.id,
                    decision.target_symbol,
                    decision.decision_type,
                    json_dumps(decision.related_evidence_ids),
                    json_dumps(decision.related_findings),
                    decision.market_state_summary,
                    decision.company_summary,
                    decision.news_summary,
                    decision.risk_summary,
                    decision.final_recommendation_for_simulation,
                    decision.confidence,
                    json_dumps(decision.missing_information),
                    decision.created_at,
                    decision.side,
                    decision.order_type,
                    decision.target_value,
                    decision.limit_price,
                    decision.stop_price,
                    decision.reason,
                    json_dumps(decision.bullish_reasons),
                    json_dumps(decision.bearish_reasons),
                    json_dumps(decision.counterarguments),
                    json_dumps(decision.invalidation_conditions),
                    json_dumps(decision.alternative_scenarios),
                    json_dumps(decision.what_would_change_our_mind),
                    decision.recommended_holding_period,
                    decision.stop_loss_plan,
                    decision.take_profit_plan,
                    decision.position_size_reason,
                    decision.expected_return,
                    decision.expected_risk,
                    decision.risk_reward_ratio,
                    decision.data_as_of,
                ),
            )
        return decision

    def save_memory(self, memory: KnowledgeMemory) -> KnowledgeMemory:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO knowledge_memory VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory.id,
                    memory.memory_type,
                    memory.content,
                    json_dumps(memory.related_symbols),
                    json_dumps(memory.related_topics),
                    json_dumps(memory.source_evidence_ids),
                    memory.importance_score,
                    memory.last_used_at,
                    memory.expires_at,
                    1 if memory.archived else 0,
                ),
            )
        return memory

    def find_evidence_by_hash(self, evidence_hash: str) -> EvidenceRecord | None:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_records WHERE evidence_hash = ? ORDER BY collected_at ASC LIMIT 1",
                (evidence_hash,),
            ).fetchone()
        return self._row_to_evidence(row) if row else None

    def list_tasks(self, limit: int = 20) -> list[ResearchTask]:
        self._mark_stale_tasks()
        return [self._row_to_task(row) for row in self._fetch("research_tasks", "created_at", limit)]

    def list_evidence(self, limit: int = 20) -> list[EvidenceRecord]:
        return [self._row_to_evidence(row) for row in self._fetch("evidence_records", "collected_at", limit)]

    def list_findings(self, limit: int = 20) -> list[AgentFinding]:
        return [self._row_to_finding(row) for row in self._fetch("agent_findings", "created_at", limit)]

    def list_decision_contexts(self, limit: int = 20) -> list[DecisionContext]:
        return [self._row_to_decision(row) for row in self._fetch("decision_contexts", "created_at", limit)]

    def archive_low_value_evidence(self, threshold: float = 0.25) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE evidence_records
                SET archived = 1
                WHERE archived = 0
                  AND ((relevance_score + credibility_score + freshness_score + impact_score) / 4.0) < ?
                """,
                (threshold,),
            )
        return int(cursor.rowcount or 0)

    def summary(self) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn:
            evidence_total = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
            archived_total = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE archived = 1").fetchone()[0]
            duplicate_total = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE duplicate_of IS NOT NULL").fetchone()[0]
            task_total = conn.execute("SELECT COUNT(*) FROM research_tasks WHERE status != 'completed'").fetchone()[0]
            decision_total = conn.execute("SELECT COUNT(*) FROM decision_contexts").fetchone()[0]
        return {
            "evidenceTotal": evidence_total,
            "archivedTotal": archived_total,
            "duplicateTotal": duplicate_total,
            "openTaskTotal": task_total,
            "decisionContextTotal": decision_total,
            "markdownPath": str(self.markdown_path),
        }

    def export_markdown(self, limit: int = 12) -> str:
        evidence = self.list_evidence(limit=limit)
        tasks = self.list_tasks(limit=limit)
        decisions = self.list_decision_contexts(limit=limit)
        lines = [
            "# Research Organization Summary",
            "",
            "## Evidence",
        ]
        for item in evidence:
            dup = f" duplicate_of={item.duplicate_of}" if item.duplicate_of else ""
            lines.append(f"- `{item.id}` {item.title} [{', '.join(item.related_symbols)}]{dup}")
        lines.extend(["", "## Open Research Tasks"])
        for item in tasks:
            lines.append(f"- `{item.id}` P{item.priority} {item.topic} / {item.status}")
        lines.extend(["", "## Decision Contexts"])
        for item in decisions:
            lines.append(
                f"- `{item.id}` {item.target_symbol} {item.decision_type} "
                f"confidence={item.confidence:.2f} evidence={', '.join(item.related_evidence_ids)}"
            )
        text = "\n".join(lines) + "\n"
        self.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        self.markdown_path.write_text(text, encoding="utf-8")
        return text

    def _fetch(self, table: str, order_column: str, limit: int) -> list[sqlite3.Row]:
        self.ensure_schema()
        with self._connect() as conn:
            return list(conn.execute(f"SELECT * FROM {table} ORDER BY {order_column} ASC LIMIT ?", (limit,)))

    def _ensure_columns(self, conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _mark_stale_tasks(self) -> None:
        self.ensure_schema()
        ttl = TaskTTL()
        with self._connect() as conn:
            rows = list(conn.execute("SELECT * FROM research_tasks WHERE status IN ('open', 'waiting', 'waiting_for_source')"))
            for row in rows:
                task = self._row_to_task(row)
                status = ttl.status_for(task)
                if status != task.status:
                    conn.execute("UPDATE research_tasks SET status = ? WHERE id = ?", (status, task.id))

    @contextmanager
    def _connect(self) -> Any:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _row_to_task(self, row: sqlite3.Row) -> ResearchTask:
        return ResearchTask(
            id=row["id"],
            task_type=row["task_type"],
            target_symbols=[str(item) for item in json_loads_list(row["target_symbols"])],
            topic=row["topic"],
            priority=int(row["priority"]),
            created_by_agent=row["created_by_agent"],
            status=row["status"],
            reason=row["reason"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def _row_to_evidence(self, row: sqlite3.Row) -> EvidenceRecord:
        return EvidenceRecord(
            id=row["id"],
            source_type=row["source_type"],
            source_name=row["source_name"],
            url_or_path=row["url_or_path"],
            title=row["title"],
            published_at=row["published_at"],
            collected_at=row["collected_at"],
            related_symbols=[str(item) for item in json_loads_list(row["related_symbols"])],
            related_topics=[str(item) for item in json_loads_list(row["related_topics"])],
            raw_text_path=row["raw_text_path"],
            summary=row["summary"],
            extracted_facts=[str(item) for item in json_loads_list(row["extracted_facts"])],
            sentiment_score=float(row["sentiment_score"]),
            relevance_score=float(row["relevance_score"]),
            credibility_score=float(row["credibility_score"]),
            freshness_score=float(row["freshness_score"]),
            impact_score=float(row["impact_score"]),
            duplicate_of=row["duplicate_of"],
            archived=bool(row["archived"]),
            evidence_hash=row["evidence_hash"],
            conflict_with=[str(item) for item in json_loads_list(row["conflict_with"])],
            score_reason=row["score_reason"],
            source_reliability_basis=row["source_reliability_basis"],
            verified_body=bool(row["verified_body"]),
            body_fetched=bool(row["body_fetched"]),
            headline_only=bool(row["headline_only"]),
            used_in_decisions=[str(item) for item in json_loads_list(row["used_in_decisions"])],
            outcome_score=row["outcome_score"],
            available_at=row["available_at"],
        )

    def _row_to_finding(self, row: sqlite3.Row) -> AgentFinding:
        return AgentFinding(
            id=row["id"],
            agent_name=row["agent_name"],
            related_task_id=row["related_task_id"],
            related_evidence_ids=[str(item) for item in json_loads_list(row["related_evidence_ids"])],
            finding_type=row["finding_type"],
            claim=row["claim"],
            confidence=float(row["confidence"]),
            limitations=[str(item) for item in json_loads_list(row["limitations"])],
            suggested_actions=[str(item) for item in json_loads_list(row["suggested_actions"])],
            created_at=row["created_at"],
        )

    def _row_to_decision(self, row: sqlite3.Row) -> DecisionContext:
        return DecisionContext(
            id=row["id"],
            target_symbol=row["target_symbol"],
            decision_type=row["decision_type"],
            related_evidence_ids=[str(item) for item in json_loads_list(row["related_evidence_ids"])],
            related_findings=[str(item) for item in json_loads_list(row["related_findings"])],
            market_state_summary=row["market_state_summary"],
            company_summary=row["company_summary"],
            news_summary=row["news_summary"],
            risk_summary=row["risk_summary"],
            final_recommendation_for_simulation=row["final_recommendation_for_simulation"],
            confidence=float(row["confidence"]),
            missing_information=[str(item) for item in json_loads_list(row["missing_information"])],
            created_at=row["created_at"],
            side=row["side"],
            order_type=row["order_type"],
            target_value=row["target_value"],
            limit_price=row["limit_price"],
            stop_price=row["stop_price"],
            reason=row["reason"],
            bullish_reasons=[str(item) for item in json_loads_list(row["bullish_reasons"])],
            bearish_reasons=[str(item) for item in json_loads_list(row["bearish_reasons"])],
            counterarguments=[str(item) for item in json_loads_list(row["counterarguments"])],
            invalidation_conditions=[str(item) for item in json_loads_list(row["invalidation_conditions"])],
            alternative_scenarios=[str(item) for item in json_loads_list(row["alternative_scenarios"])],
            what_would_change_our_mind=[str(item) for item in json_loads_list(row["what_would_change_our_mind"])],
            recommended_holding_period=row["recommended_holding_period"],
            stop_loss_plan=row["stop_loss_plan"],
            take_profit_plan=row["take_profit_plan"],
            position_size_reason=row["position_size_reason"],
            expected_return=row["expected_return"],
            expected_risk=row["expected_risk"],
            risk_reward_ratio=row["risk_reward_ratio"],
            data_as_of=row["data_as_of"],
        )


def persist_run_results(repository: ResearchRepository, results: Iterable[Any]) -> None:
    for result in results:
        for task in result.tasks:
            repository.save_task(task)
        for evidence in result.evidence:
            repository.save_evidence(evidence)
        for finding in result.findings:
            repository.save_finding(finding)
        for decision in result.decisions:
            repository.save_decision_context(decision)
