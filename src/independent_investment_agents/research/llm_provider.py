from __future__ import annotations

import hashlib
import json
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from independent_investment_agents.research.models import ChatResponse


class LLMProvider(ABC):
    """Evidence-bound language interface.

    LLM output is presentation support only. It is never treated as evidence.
    """

    @abstractmethod
    def generate_chat_response(
        self,
        prompt: str,
        evidence_refs: list[str],
        context: dict[str, Any],
    ) -> ChatResponse:
        raise NotImplementedError


class TemplateLanguageProvider(LLMProvider):
    """Template language layer used until a local LLM provider is connected."""

    def __init__(self, resource_dir: Path | None = None) -> None:
        self.resource_dir = resource_dir or Path(__file__).resolve().parents[3] / "language_resources" / "ja"
        self.templates = self._load("templates.json")

    def generate_chat_response(
        self,
        prompt: str,
        evidence_refs: list[str],
        context: dict[str, Any],
    ) -> ChatResponse:
        symbol = str(context.get("symbol") or "N/A")
        market = str(context.get("market_state") or "市場状態未確認")
        risk = str(context.get("risk_summary") or "リスク評価は更新待ち")
        key = "chat_grounded" if evidence_refs else "chat_missing"
        template = self.pick(key, symbol, market, risk, prompt, len(evidence_refs))
        message = template.format(
            symbol=symbol,
            evidence_count=len(evidence_refs),
            market_state=market,
            risk_summary=risk,
        )
        if evidence_refs:
            message += " 投資助言ではなく、保存済みEvidenceに基づく研究用説明です。"
        return ChatResponse(
            message=message,
            evidence_refs=list(evidence_refs),
            missing_information=[] if evidence_refs else ["evidence_refs"],
            source="template",
        )

    def pick(self, key: str, *seed_parts: Any) -> str:
        choices = self.templates.get(key) or ["{symbol}: Evidenceを確認しています。"]
        seed = int(hashlib.sha256("|".join(str(part) for part in seed_parts).encode("utf-8")).hexdigest()[:12], 16)
        return random.Random(seed).choice(choices)

    def _load(self, name: str) -> dict[str, list[str]]:
        path = self.resource_dir / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {str(key): [str(item) for item in value] for key, value in payload.items() if isinstance(value, list)}
