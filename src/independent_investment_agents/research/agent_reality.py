from __future__ import annotations

from typing import Any


DATA_FETCHING_WORKERS = {"market-observer", "news-source-collector", "company-research"}
ANALYSIS_WORKERS = {
    "virtual-trader-a",
    "virtual-trader-b",
    "trading-consensus-gate",
    "runtime-scheduler",
    "portfolio-agent",
    "full-history-analyst",
    "correlation-risk-analyst",
    "strategy-synthesis",
    "evidence-curator",
}
TEMPLATE_WORKERS = {"agent-chat-coordinator"}

DISPLAY_ONLY = {"ui-agent"}
PLANNED = {"academic-macro-research"}


class AgentRealityLayer:
    def describe(self, agent_id: str, *, latest_task: str = "", evidence_id: str | None = None, decision_id: str | None = None) -> dict[str, Any]:
        if agent_id in DATA_FETCHING_WORKERS:
            reality_type = "data_fetching_worker"
            enabled = True
            label_ja = "実データ取得あり"
        elif agent_id in ANALYSIS_WORKERS:
            reality_type = "analysis_worker"
            enabled = True
            label_ja = "分析処理あり"
        elif agent_id in TEMPLATE_WORKERS:
            reality_type = "template_worker"
            enabled = True
            label_ja = "テンプレート応答のみ"
        elif agent_id in DISPLAY_ONLY:
            reality_type = "display_only"
            enabled = False
            label_ja = "表示専用"
        elif agent_id in PLANNED:
            reality_type = "planned"
            enabled = False
            label_ja = "実装予定"
        else:
            reality_type = "idle_worker"
            enabled = False
            label_ja = "待機中"
        return {
            "agent_reality_type": reality_type,
            "agent_reality_label_ja": label_ja,
            "fetched_real_data": agent_id in DATA_FETCHING_WORKERS,
            "created_evidence": bool(evidence_id),
            "created_decision_context": bool(decision_id),
            "last_real_task_at": None if not enabled else "runtime_tick",
            "last_real_evidence_id": evidence_id,
            "last_real_decision_id": decision_id,
            "actual_processing_enabled": enabled,
            "reality_note": "executes runtime logic" if enabled else "status surface only until a concrete worker is connected",
        }
