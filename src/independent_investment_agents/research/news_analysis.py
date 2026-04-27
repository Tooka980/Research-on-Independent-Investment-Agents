from __future__ import annotations

import re
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArticleAnalysis:
    url: str
    title: str
    body: str = ""
    summary: str = ""
    body_fetched: bool = False
    headline_only: bool = True
    materiality: str = "unknown"
    horizon: str = "unknown"
    mismatch_warning: str = ""
    risk_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArticleBodyFetcher:
    def fetch(self, url: str, *, timeout_seconds: float = 5.0) -> tuple[bool, str]:
        if not url or not url.startswith(("http://", "https://")):
            return False, ""
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "IndependentInvestmentAgents/0.0.1"})
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read(300_000).decode("utf-8", errors="ignore")
        except Exception:
            return False, ""
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return bool(text), text


class ArticleSummarizer:
    def summarize(self, body: str, *, max_chars: int = 420) -> str:
        cleaned = re.sub(r"\s+", " ", body or "").strip()
        return cleaned[:max_chars]


class MaterialityClassifier:
    KEYWORDS = {
        "earnings": ("earnings", "決算", "profit", "revenue", "guidance"),
        "guidance": ("forecast", "見通し", "guidance"),
        "macro": ("boj", "日銀", "inflation", "gdp", "macro"),
        "policy": ("policy", "regulation", "政府", "規制"),
        "fx": ("yen", "dollar", "為替", "円"),
        "sector": ("sector", "industry", "業界"),
        "m&a": ("acquisition", "merger", "買収", "合併"),
        "product": ("product", "launch", "製品", "発売"),
        "lawsuit": ("lawsuit", "訴訟"),
        "supply_chain": ("supply", "supplier", "供給"),
    }

    def classify(self, text: str) -> str:
        lowered = (text or "").lower()
        for label, keywords in self.KEYWORDS.items():
            if any(keyword.lower() in lowered for keyword in keywords):
                return label
        return "unknown"


class ShortTermLongTermClassifier:
    def classify(self, text: str) -> str:
        lowered = (text or "").lower()
        if any(token in lowered for token in ("today", "short-term", "temporary", "本日", "短期")):
            return "short_term"
        if any(token in lowered for token in ("strategy", "multi-year", "long-term", "中期", "長期")):
            return "long_term"
        return "medium_term"


class HeadlineBodyMismatchChecker:
    def check(self, title: str, body: str) -> str:
        if not body:
            return ""
        title_negative = _negative(title)
        body_negative = _negative(body[:1200])
        if title_negative != body_negative:
            return "headline_body_tone_mismatch"
        return ""


class NewsImpactScorer:
    def score(self, analysis: ArticleAnalysis) -> float:
        if analysis.headline_only:
            return 0.45
        if analysis.materiality in {"earnings", "guidance", "m&a", "lawsuit"}:
            return 0.78
        if analysis.materiality in {"macro", "policy", "fx", "sector"}:
            return 0.62
        return 0.52


class NewsArticleAnalyzer:
    def __init__(self) -> None:
        self.fetcher = ArticleBodyFetcher()
        self.summarizer = ArticleSummarizer()
        self.materiality = MaterialityClassifier()
        self.horizon = ShortTermLongTermClassifier()
        self.mismatch = HeadlineBodyMismatchChecker()

    def analyze(self, *, title: str, url: str) -> ArticleAnalysis:
        fetched, body = self.fetcher.fetch(url)
        summary = self.summarizer.summarize(body) if fetched else ""
        text = f"{title} {body}"
        return ArticleAnalysis(
            url=url,
            title=title,
            body=body,
            summary=summary,
            body_fetched=fetched,
            headline_only=not fetched,
            materiality=self.materiality.classify(text),
            horizon=self.horizon.classify(text),
            mismatch_warning=self.mismatch.check(title, body),
            risk_notes=[] if fetched else ["body_not_fetched"],
        )


def _negative(text: str) -> bool:
    lowered = (text or "").lower()
    return any(token in lowered for token in ("fall", "drop", "loss", "lawsuit", "decline", "下落", "減益", "訴訟"))
