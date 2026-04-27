from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidencePack:
    evidence_refs: list[str]
    facts: list[str]
    missing_information: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidencePackBuilder:
    def build(self, evidence_records: list[dict[str, Any]]) -> EvidencePack:
        refs = [str(item.get("id")) for item in evidence_records if item.get("id")]
        facts = []
        for item in evidence_records:
            facts.extend(str(fact) for fact in item.get("extracted_facts", []) if fact)
        missing = [] if refs else ["evidence_refs"]
        return EvidencePack(refs, facts, missing)


class PromptContract:
    required_fields = {"evidence_refs", "claims", "limitations"}

    def describe(self) -> dict[str, Any]:
        return {
            "required_fields": sorted(self.required_fields),
            "forbidden": ["uncited numeric claims", "guaranteed price forecasts", "real order instructions"],
        }


class OutputSchemaValidator:
    def validate(self, output: dict[str, Any]) -> tuple[bool, list[str]]:
        errors = [field for field in PromptContract.required_fields if field not in output]
        if not output.get("evidence_refs"):
            errors.append("empty_evidence_refs")
        return not errors, errors


class CitationChecker:
    def validate(self, output: dict[str, Any]) -> bool:
        refs = output.get("evidence_refs") or []
        claims = output.get("claims") or []
        return bool(refs) and all(refs for _claim in claims)


class NumericClaimChecker:
    NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?%?")

    def validate(self, output: dict[str, Any], evidence_pack: EvidencePack) -> tuple[bool, list[str]]:
        evidence_text = " ".join(evidence_pack.facts)
        unsupported = []
        for claim in output.get("claims", []):
            for number in self.NUMBER_PATTERN.findall(str(claim)):
                if number not in evidence_text:
                    unsupported.append(number)
        return not unsupported, unsupported


class HallucinationGuard:
    def validate(self, output: dict[str, Any], evidence_pack: EvidencePack) -> bool:
        valid_schema, _errors = OutputSchemaValidator().validate(output)
        numeric_ok, _unsupported = NumericClaimChecker().validate(output, evidence_pack)
        return valid_schema and numeric_ok


class InvestmentAdviceGuard:
    FORBIDDEN = ("絶対買い", "必ず上がる", "guaranteed", "must buy", "real order")

    def validate(self, text: str) -> bool:
        lowered = text.lower()
        return not any(token.lower() in lowered for token in self.FORBIDDEN)


class LLMFallbackPolicy:
    def should_fallback(self, output: dict[str, Any], evidence_pack: EvidencePack) -> bool:
        if not HallucinationGuard().validate(output, evidence_pack):
            return True
        text = " ".join(str(item) for item in output.get("claims", []))
        return not InvestmentAdviceGuard().validate(text)
