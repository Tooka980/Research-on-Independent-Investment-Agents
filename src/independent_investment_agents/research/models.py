from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def stable_hash(*parts: Any) -> str:
    raw = "\n".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


@dataclass
class ResearchTask:
    task_type: str
    target_symbols: list[str]
    topic: str
    priority: int
    created_by_agent: str
    status: str
    reason: str
    id: str = field(default_factory=lambda: f"rtask-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchTask":
        data = dict(payload)
        data["target_symbols"] = _list(data.get("target_symbols"))
        return cls(**data)


@dataclass
class EvidenceRecord:
    source_type: str
    source_name: str
    url_or_path: str
    title: str
    published_at: str | None
    collected_at: str
    related_symbols: list[str]
    related_topics: list[str]
    raw_text_path: str | None
    summary: str
    extracted_facts: list[str]
    sentiment_score: float
    relevance_score: float
    credibility_score: float
    freshness_score: float
    impact_score: float
    id: str = field(default_factory=lambda: f"ev-{uuid4().hex}")
    duplicate_of: str | None = None
    archived: bool = False
    evidence_hash: str = ""
    conflict_with: list[str] = field(default_factory=list)
    score_reason: str = ""
    source_reliability_basis: str = ""
    verified_body: bool = False
    body_fetched: bool = False
    headline_only: bool = False
    used_in_decisions: list[str] = field(default_factory=list)
    outcome_score: float | None = None
    available_at: str | None = None

    def __post_init__(self) -> None:
        self.related_symbols = [str(item).upper() for item in _list(self.related_symbols)]
        self.related_topics = [str(item) for item in _list(self.related_topics)]
        self.extracted_facts = [str(item) for item in _list(self.extracted_facts)]
        self.conflict_with = [str(item) for item in _list(self.conflict_with)]
        self.used_in_decisions = [str(item) for item in _list(self.used_in_decisions)]
        if self.available_at is None:
            self.available_at = self.published_at or self.collected_at
        if not self.evidence_hash:
            self.evidence_hash = stable_hash(
                self.source_type,
                self.source_name,
                self.url_or_path,
                self.title,
                self.summary,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceRecord":
        data = dict(payload)
        for key in ["related_symbols", "related_topics", "extracted_facts", "conflict_with", "used_in_decisions"]:
            data[key] = _list(data.get(key))
        data["archived"] = bool(data.get("archived"))
        return cls(**data)


@dataclass
class AgentFinding:
    agent_name: str
    related_task_id: str | None
    related_evidence_ids: list[str]
    finding_type: str
    claim: str
    confidence: float
    limitations: list[str]
    suggested_actions: list[str]
    id: str = field(default_factory=lambda: f"find-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentFinding":
        data = dict(payload)
        data["related_evidence_ids"] = _list(data.get("related_evidence_ids"))
        data["limitations"] = _list(data.get("limitations"))
        data["suggested_actions"] = _list(data.get("suggested_actions"))
        return cls(**data)


@dataclass
class DecisionContext:
    target_symbol: str
    decision_type: str
    related_evidence_ids: list[str]
    related_findings: list[str]
    market_state_summary: str
    company_summary: str
    news_summary: str
    risk_summary: str
    final_recommendation_for_simulation: str
    confidence: float
    missing_information: list[str]
    id: str = field(default_factory=lambda: f"dc-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)
    side: str = "buy"
    order_type: str = "market"
    target_value: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    reason: str = ""
    bullish_reasons: list[str] = field(default_factory=list)
    bearish_reasons: list[str] = field(default_factory=list)
    counterarguments: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    alternative_scenarios: list[str] = field(default_factory=list)
    what_would_change_our_mind: list[str] = field(default_factory=list)
    recommended_holding_period: str = ""
    stop_loss_plan: str = ""
    take_profit_plan: str = ""
    position_size_reason: str = ""
    expected_return: float | None = None
    expected_risk: float | None = None
    risk_reward_ratio: float | None = None
    data_as_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DecisionContext":
        data = dict(payload)
        for key in [
            "related_evidence_ids",
            "related_findings",
            "missing_information",
            "bullish_reasons",
            "bearish_reasons",
            "counterarguments",
            "invalidation_conditions",
            "alternative_scenarios",
            "what_would_change_our_mind",
        ]:
            data[key] = _list(data.get(key))
        data["target_symbol"] = str(data.get("target_symbol", "")).upper()
        return cls(**data)


@dataclass
class KnowledgeMemory:
    memory_type: str
    content: str
    related_symbols: list[str]
    related_topics: list[str]
    source_evidence_ids: list[str]
    importance_score: float
    id: str = field(default_factory=lambda: f"mem-{uuid4().hex}")
    last_used_at: str | None = None
    expires_at: str | None = None
    archived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatResponse:
    message: str
    evidence_refs: list[str]
    missing_information: list[str] = field(default_factory=list)
    source: str = "template"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentRunContext:
    focus_symbol: str
    market: dict[str, Any]
    focus: dict[str, Any]
    portfolio: dict[str, Any]
    news_items: list[dict[str, Any]]
    watchlist: list[dict[str, Any]]
    symbol_processing: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunResult:
    agent_name: str
    status: str
    logs: list[str]
    tasks: list[ResearchTask] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    findings: list[AgentFinding] = field(default_factory=list)
    decisions: list[DecisionContext] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tasks"] = [task.to_dict() for task in self.tasks]
        payload["evidence"] = [record.to_dict() for record in self.evidence]
        payload["findings"] = [finding.to_dict() for finding in self.findings]
        payload["decisions"] = [decision.to_dict() for decision in self.decisions]
        return payload


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
