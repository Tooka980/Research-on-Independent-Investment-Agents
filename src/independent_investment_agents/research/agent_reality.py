from __future__ import annotations

from typing import Any


REAL_WORKERS = {
    "virtual-trader-a",
    "virtual-trader-b",
    "trading-consensus-gate",
    "runtime-scheduler",
    "portfolio-agent",
}

DISPLAY_ONLY = {"ui-agent"}
PLANNED = {"academic-macro-research"}


class AgentRealityLayer:
    def describe(self, agent_id: str, *, latest_task: str = "", evidence_id: str | None = None, decision_id: str | None = None) -> dict[str, Any]:
        if agent_id in REAL_WORKERS:
            reality_type = "real_worker"
            enabled = True
        elif agent_id in DISPLAY_ONLY:
            reality_type = "display_only"
            enabled = False
        elif agent_id in PLANNED:
            reality_type = "planned"
            enabled = False
        else:
            reality_type = "simulated_status"
            enabled = False
        return {
            "agent_reality_type": reality_type,
            "last_real_task_at": None if not enabled else "runtime_tick",
            "last_real_evidence_id": evidence_id,
            "last_real_decision_id": decision_id,
            "actual_processing_enabled": enabled,
            "reality_note": "executes runtime logic" if enabled else "status surface only until a concrete worker is connected",
        }
