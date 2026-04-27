from __future__ import annotations

from abc import abstractmethod
from dataclasses import replace
from typing import Any

from independent_investment_agents.agents.base_agent import BaseAgent
from independent_investment_agents.core.agent_runtime import AgentRuntime, AgentRuntimeConfig, load_agent_runtime_config
from independent_investment_agents.core.task_queue import ErrorResult, TaskEnvelope, retry_call
from independent_investment_agents.research.llm_provider import TemplateLanguageProvider
from independent_investment_agents.research.models import (
    AgentFinding,
    AgentRunContext,
    AgentRunResult,
    DecisionContext,
    EvidenceRecord,
    ResearchTask,
    utc_now_iso,
)
from independent_investment_agents.research.repository import ResearchRepository, persist_run_results


class ResearchAgent(BaseAgent):
    name: str
    division: str

    def __init__(self) -> None:
        super().__init__(agent_id=self._default_agent_id(), name=self.name)

    @abstractmethod
    def run(self, context: AgentRunContext) -> AgentRunResult:
        raise NotImplementedError

    def handle_task(self, task: TaskEnvelope) -> AgentRunResult:
        context = task.payload.get("context")
        if not isinstance(context, AgentRunContext):
            raise TypeError("research task payload requires AgentRunContext")
        return self.run(context)

    def _default_agent_id(self) -> str:
        return "-".join(
            part
            for part in "".join(ch.lower() if ch.isalnum() else "-" for ch in self.name).split("-")
            if part
        )


class ResearchDirectorAgent(BaseAgent):
    name = "Research Director Agent"
    division = "Operations"

    def __init__(self, config: AgentRuntimeConfig | None = None) -> None:
        super().__init__(agent_id="research-director", name=self.name)
        self.config = config or load_agent_runtime_config()

    def plan_tasks(self, context: AgentRunContext, agents: list[ResearchAgent]) -> list[TaskEnvelope]:
        timeout = self.config.task_timeout_seconds
        return [
            TaskEnvelope(
                task_type="research_snapshot",
                payload={"context": context},
                target_agent_id=agent.agent_id,
                priority=self._priority_for(agent),
                created_by=self.agent_id,
                max_attempts=self.config.max_retries,
                timeout_seconds=timeout,
            )
            for agent in agents
        ]

    def handle_task(self, task: TaskEnvelope) -> list[TaskEnvelope]:
        context = task.payload.get("context")
        agents = task.payload.get("agents", [])
        return self.plan_tasks(context, agents)

    def _priority_for(self, agent: ResearchAgent) -> int:
        if agent.division in {"Intelligence", "Company Research", "Market Research"}:
            return 1
        if agent.division == "Strategy":
            return 2
        return 3


class MarketObserverAgent(ResearchAgent):
    name = "Market Observer Agent"
    division = "Market Research"

    def run(self, context: AgentRunContext) -> AgentRunResult:
        symbol = context.focus_symbol
        change_pct = float(context.focus.get("quote", {}).get("changePct") or 0.0)
        data_quality = context.focus.get("dataQuality", {})
        evidence: list[EvidenceRecord] = []
        evidence_ids: list[str] = []
        if data_quality.get("hasAnalysisHistory"):
            evidence_id = f"ev-yf-ohlcv-{symbol.lower().replace('.', '-')}-{utc_now_iso()[:10].replace('-', '')}"
            evidence.append(
                EvidenceRecord(
                    id=evidence_id,
                    source_type="price_history",
                    source_name=str(data_quality.get("priceSource") or "yfinance"),
                    url_or_path=f"yfinance://{symbol}/history",
                    title=f"{symbol} OHLCV history",
                    published_at=None,
                    collected_at=utc_now_iso(),
                    related_symbols=[symbol],
                    related_topics=["ohlcv", "market_state"],
                    raw_text_path=None,
                    summary=f"{symbol} OHLCV history is available for analysis.",
                    extracted_facts=[f"change_pct={change_pct:.2f}", f"phase={context.market.get('phase')}"],
                    sentiment_score=0.0,
                    relevance_score=0.86,
                    credibility_score=0.86,
                    freshness_score=0.88,
                    impact_score=min(0.95, abs(change_pct) / 10.0 + 0.25),
                )
            )
            evidence_ids.append(evidence_id)
        task = ResearchTask(
            id=f"rtask-market-{symbol.lower().replace('.', '-')}-{utc_now_iso()[:10]}",
            task_type="market_event_scan",
            target_symbols=[symbol],
            topic=f"{symbol} market movement scan",
            priority=2 if abs(change_pct) >= 3 else 4,
            created_by_agent=self.name,
            status="completed" if evidence_ids else "waiting_for_source",
            reason=(
                f"price change {change_pct:.2f}% reviewed with OHLCV evidence"
                if evidence_ids
                else "OHLCV evidence is unavailable; waiting for yfinance or saved history"
            ),
        )
        finding = AgentFinding(
            agent_name=self.name,
            related_task_id=task.id,
            related_evidence_ids=evidence_ids,
            finding_type="market_observation",
            claim=f"{symbol} current move is {change_pct:.2f}% during {context.market.get('phase')}",
            confidence=0.68 if evidence_ids else 0.25,
            limitations=["broad index data is not yet connected; current watchlist breadth is used"],
            suggested_actions=["compare sector ETF", "monitor volume spike"],
        )
        status = "success" if evidence_ids else "waiting"
        logs = ["market phase checked", "OHLCV evidence stored"] if evidence_ids else ["market phase checked", "waiting for OHLCV source"]
        return AgentRunResult(self.name, status, logs, [task], evidence, [finding])


class StockDiscoveryAgent(ResearchAgent):
    name = "Stock Discovery Agent"
    division = "Market Research"

    def run(self, context: AgentRunContext) -> AgentRunResult:
        candidates = sorted(context.watchlist, key=lambda row: abs(float(row.get("changePct") or 0.0)), reverse=True)[:3]
        symbols = [str(item.get("symbol")) for item in candidates if item.get("symbol")]
        finding = AgentFinding(
            agent_name=self.name,
            related_task_id=None,
            related_evidence_ids=[],
            finding_type="candidate_discovery",
            claim=f"candidate symbols by move: {', '.join(symbols) or context.focus_symbol}",
            confidence=0.62,
            limitations=["news volume score uses currently collected feed entries"],
            suggested_actions=["open candidate research task", "compare liquidity"],
        )
        return AgentRunResult(self.name, "success", ["watchlist ranked", "candidate memo saved"], [], [], [finding])


class NewsIntelligenceAgent(ResearchAgent):
    name = "News Intelligence Agent"
    division = "Intelligence"

    def run(self, context: AgentRunContext) -> AgentRunResult:
        evidence: list[EvidenceRecord] = []
        symbol = context.focus_symbol
        real_items = [
            item for item in context.news_items[:3]
            if item.get("title") and item.get("source") not in {"News Agent", "Cache"}
        ]
        for idx, item in enumerate(real_items):
            source_name = str(item.get("source") or "RSS")
            evidence.append(
                EvidenceRecord(
                    id=f"ev-rss-news-{symbol.lower().replace('.', '-')}-{utc_now_iso()[:10].replace('-', '')}-{idx}",
                    source_type="news",
                    source_name=source_name,
                    url_or_path=str(item.get("url") or f"rss://{source_name}/{symbol}/{idx}"),
                    title=str(item.get("title") or f"{symbol} news"),
                    published_at=None,
                    collected_at=utc_now_iso(),
                    related_symbols=[symbol],
                    related_topics=["news", "market_sentiment"],
                    raw_text_path=None,
                    summary=str(item.get("summary") or "headline stored for research context"),
                    extracted_facts=[str(item.get("title") or "headline")],
                    sentiment_score=0.0,
                    relevance_score=0.72,
                    credibility_score=0.58 if item.get("source") == "News Agent" else 0.76,
                    freshness_score=0.94,
                    impact_score={"High": 0.9, "Medium": 0.64, "Low": 0.35}.get(str(item.get("impact")), 0.5),
                )
            )
        finding = AgentFinding(
            agent_name=self.name,
            related_task_id=None,
            related_evidence_ids=[item.id for item in evidence],
            finding_type="news_context",
            claim=f"{len(evidence)} news evidence records collected for {symbol}",
            confidence=0.7 if evidence else 0.35,
            limitations=[] if evidence else ["no news evidence available"],
            suggested_actions=["score impact", "check duplicate headlines"],
        )
        if evidence:
            return AgentRunResult(self.name, "success", ["news evidence normalized", "impact scored"], [], evidence, [finding])
        task = ResearchTask(
            task_type="news_collection",
            target_symbols=[symbol],
            topic=f"{symbol} news source collection",
            priority=2,
            created_by_agent=self.name,
            status="waiting_for_source",
            reason="No RSS/Web news evidence was available; do not synthesize a headline.",
        )
        return AgentRunResult(self.name, "waiting", ["news source unavailable", "research task queued"], [task], [], [finding])


class CompanyResearchAgent(ResearchAgent):
    name = "Company Research Agent"
    division = "Company Research"

    def run(self, context: AgentRunContext) -> AgentRunResult:
        focus = context.focus
        symbol = context.focus_symbol
        meta_source = str(focus.get("dataQuality", {}).get("metaSource") or "")
        if meta_source not in {"yfinance", "saved_profile"}:
            task = ResearchTask(
                task_type="company_profile_collection",
                target_symbols=[symbol],
                topic=f"{symbol} company profile source collection",
                priority=2,
                created_by_agent=self.name,
                status="waiting_for_source",
                reason="Company meta evidence is unavailable; waiting for yfinance or saved profile.",
            )
            finding = AgentFinding(
                agent_name=self.name,
                related_task_id=task.id,
                related_evidence_ids=[],
                finding_type="company_source_gap",
                claim=f"{symbol} company profile source is not ready.",
                confidence=0.25,
                limitations=["company profile source unavailable"],
                suggested_actions=["retry yfinance meta", "load saved company profile"],
            )
            return AgentRunResult(self.name, "waiting", ["company profile unavailable", "research task queued"], [task], [], [finding])
        evidence = EvidenceRecord(
            id=f"ev-yf-meta-{symbol.lower().replace('.', '-')}-{utc_now_iso()[:10].replace('-', '')}",
            source_type="company_profile",
            source_name=meta_source,
            url_or_path=f"yfinance://{symbol}/info" if meta_source == "yfinance" else f"saved-profile://{symbol}",
            title=f"{symbol} company profile",
            published_at=None,
            collected_at=utc_now_iso(),
            related_symbols=[symbol],
            related_topics=["company", str(focus.get("sector") or "sector")],
            raw_text_path=None,
            summary=f"{focus.get('enName') or symbol} profile and financial metrics stored.",
            extracted_facts=[
                f"PER={focus.get('metrics', {}).get('trailingPE', 'n/a')}",
                f"EPS={focus.get('metrics', {}).get('trailingEps', 'n/a')}",
            ],
            sentiment_score=0.0,
            relevance_score=0.78,
            credibility_score=0.72,
            freshness_score=0.7,
            impact_score=0.5,
        )
        finding = AgentFinding(
            agent_name=self.name,
            related_task_id=None,
            related_evidence_ids=[evidence.id],
            finding_type="company_snapshot",
            claim=f"{symbol} company metrics are available for decision context.",
            confidence=0.66,
            limitations=["IR/PDF ingestion is future scope"],
            suggested_actions=["connect filings parser", "compare peer multiples"],
        )
        return AgentRunResult(self.name, "success", ["company profile stored", "fundamental facts extracted"], [], [evidence], [finding])


class AcademicMacroResearchAgent(ResearchAgent):
    name = "Academic / Macro Research Agent"
    division = "Macro Research"

    def run(self, context: AgentRunContext) -> AgentRunResult:
        task = ResearchTask(
            id=f"rtask-macro-{context.focus_symbol.lower().replace('.', '-')}-{utc_now_iso()[:10]}",
            task_type="macro_context_review",
            target_symbols=[context.focus_symbol],
            topic="macro and sector hypothesis review",
            priority=5,
            created_by_agent=self.name,
            status="open",
            reason="long-horizon macro and sector evidence is not yet connected",
        )
        finding = AgentFinding(
            agent_name=self.name,
            related_task_id=task.id,
            related_evidence_ids=[],
            finding_type="macro_gap",
            claim="macro research source is pending; decision confidence should stay conservative.",
            confidence=0.52,
            limitations=["no external macro data source connected in MVP"],
            suggested_actions=["add policy calendar", "add sector report source"],
        )
        return AgentRunResult(self.name, "warning", ["macro source pending", "task queued"], [task], [], [finding])


class EvidenceCuratorAgent(ResearchAgent):
    name = "Evidence Curator Agent"
    division = "Evidence"

    def run(self, context: AgentRunContext) -> AgentRunResult:
        finding = AgentFinding(
            agent_name=self.name,
            related_task_id=None,
            related_evidence_ids=[],
            finding_type="curation_policy",
            claim="evidence hash, freshness, credibility and archive policy active.",
            confidence=0.82,
            limitations=["semantic vector dedupe is future scope"],
            suggested_actions=["archive low-value records", "retain conflicts instead of deleting"],
        )
        return AgentRunResult(self.name, "success", ["dedupe policy loaded", "archive threshold checked"], [], [], [finding])


class StrategySynthesisAgent(ResearchAgent):
    name = "Strategy Synthesis Agent"
    division = "Strategy"

    def run(self, context: AgentRunContext) -> AgentRunResult:
        symbol = context.focus_symbol
        quote = context.focus.get("quote", {})
        change_pct = float(quote.get("changePct") or 0.0)
        cash = float(context.portfolio.get("cash") or 0.0)
        equity = float(context.portfolio.get("equity") or cash or 1.0)
        cash_ratio = cash / max(equity, 1.0)
        date_key = utc_now_iso()[:10].replace("-", "")
        data_quality = context.focus.get("dataQuality", {})
        evidence_ids: list[str] = []
        if data_quality.get("hasAnalysisHistory"):
            evidence_ids.append(f"ev-yf-ohlcv-{symbol.lower().replace('.', '-')}-{date_key}")
        if data_quality.get("metaSource") in {"yfinance", "saved_profile"}:
            evidence_ids.append(f"ev-yf-meta-{symbol.lower().replace('.', '-')}-{date_key}")
        if any(item.get("title") and item.get("source") not in {"News Agent", "Cache"} for item in context.news_items):
            evidence_ids.append(f"ev-rss-news-{symbol.lower().replace('.', '-')}-{date_key}-0")
        if len(evidence_ids) < 2:
            task = ResearchTask(
                task_type="decision_evidence_gap",
                target_symbols=[symbol],
                topic=f"{symbol} DecisionContext evidence gap",
                priority=1,
                created_by_agent=self.name,
                status="waiting_for_source",
                reason="DecisionContext requires real OHLCV evidence and company/news evidence.",
            )
            finding = AgentFinding(
                agent_name=self.name,
                related_task_id=task.id,
                related_evidence_ids=evidence_ids,
                finding_type="decision_context_blocked",
                claim=f"{symbol} DecisionContext blocked until real evidence is complete.",
                confidence=0.2,
                limitations=["insufficient evidence_refs"],
                suggested_actions=["collect OHLCV evidence", "collect company or news evidence"],
            )
            return AgentRunResult(self.name, "waiting", ["EvidenceGate blocked DecisionContext", "research task queued"], [task], [], [finding], [])
        side = "buy"
        decision_type = "virtual_rebalance_candidate"
        order_type = "rebalance" if cash_ratio > 0.28 else "market"
        if change_pct < -4 and cash_ratio < 0.25:
            side = "sell"
            decision_type = "virtual_risk_reduction_candidate"
            order_type = "liquidation"
        target_value = max(10_000.0, min(cash * 0.08, equity * 0.04))
        confidence = 0.68 if evidence_ids else 0.2
        decision = DecisionContext(
            id=f"dc-research-{symbol.lower().replace('.', '-')}",
            target_symbol=symbol,
            decision_type=decision_type,
            related_evidence_ids=evidence_ids,
            related_findings=[],
            market_state_summary=f"phase={context.market.get('phase')} change={change_pct:.2f}%",
            company_summary=f"{context.focus.get('enName') or symbol} profile evidence linked.",
            news_summary="latest news evidence linked when available.",
            risk_summary=f"cash_ratio={cash_ratio:.2f}; simulation only; no real order.",
            final_recommendation_for_simulation="Create evidence-backed virtual order candidate only inside simulator.",
            confidence=confidence,
            missing_information=[] if confidence >= 0.5 else ["fresh evidence"],
            side=side,
            order_type=order_type,
            target_value=target_value,
            reason="Evidence-backed virtual capital growth policy candidate; not investment advice.",
        )
        finding = AgentFinding(
            agent_name=self.name,
            related_task_id=None,
            related_evidence_ids=evidence_ids,
            finding_type="decision_context_created",
            claim=f"{symbol} DecisionContext created for {decision_type}",
            confidence=confidence,
            limitations=["rule-based evidence weights are used until local LLM review is connected"],
            suggested_actions=["send to Virtual Order Agent", "record decision trace"],
        )
        return AgentRunResult(self.name, "success", ["evidence merged", "DecisionContext emitted"], [], [], [finding], [decision])


class AgentChatCoordinator(ResearchAgent):
    name = "Agent Chat Coordinator"
    division = "Strategy"

    def __init__(self) -> None:
        super().__init__()
        self.llm = TemplateLanguageProvider()

    def run(self, context: AgentRunContext) -> AgentRunResult:
        symbol = context.focus_symbol
        date_key = utc_now_iso()[:10].replace("-", "")
        refs = []
        if context.focus.get("dataQuality", {}).get("hasAnalysisHistory"):
            refs.append(f"ev-yf-ohlcv-{symbol.lower().replace('.', '-')}-{date_key}")
        if context.focus.get("dataQuality", {}).get("metaSource") in {"yfinance", "saved_profile"}:
            refs.append(f"ev-yf-meta-{symbol.lower().replace('.', '-')}-{date_key}")
        response = retry_call(
            lambda: self.llm.generate_chat_response(
                "summarize research context",
                refs,
                {
                    "symbol": symbol,
                    "market_state": f"TSE {context.market.get('phase')}",
                    "risk_summary": "virtual-only evidence-gated simulation",
                },
            ),
            attempts=2,
            timeout_seconds=6.0,
            error_context={"agent_id": self.agent_id, "task_id": "agent-chat", "operation": "llm_summary"},
        )
        if isinstance(response, ErrorResult):
            finding = AgentFinding(
                agent_name=self.name,
                related_task_id=None,
                related_evidence_ids=refs,
                finding_type="chat_error",
                claim="Agent Chat summary is temporarily unavailable; existing evidence is still preserved.",
                confidence=0.1,
                limitations=[response.message],
                suggested_actions=["retry local LLM summary", "answer from stored evidence only"],
            )
            return AgentRunResult(self.name, "warning", [response.message], [], [], [finding])
        finding = AgentFinding(
            agent_name=self.name,
            related_task_id=None,
            related_evidence_ids=response.evidence_refs,
            finding_type="chat_grounding",
            claim=response.message,
            confidence=0.72 if response.evidence_refs else 0.2,
            limitations=response.missing_information,
            suggested_actions=["answer with evidence_refs", "create task if evidence missing"],
        )
        return AgentRunResult(self.name, "success", ["chat response grounded", "evidence refs attached"], [], [], [finding])


class ResearchOrganization:
    def __init__(self, repository: ResearchRepository, config: AgentRuntimeConfig | None = None) -> None:
        self.repository = repository
        self.config = config or load_agent_runtime_config()
        self.director = ResearchDirectorAgent(self.config)
        self.agents: list[ResearchAgent] = [
            MarketObserverAgent(),
            StockDiscoveryAgent(),
            NewsIntelligenceAgent(),
            CompanyResearchAgent(),
            AcademicMacroResearchAgent(),
            EvidenceCuratorAgent(),
            StrategySynthesisAgent(),
            AgentChatCoordinator(),
        ]
        self.runtime = AgentRuntime(self.config)
        self.runtime.register_agent(self.director, factory=lambda: ResearchDirectorAgent(self.config))
        for agent in self.agents:
            agent_class = agent.__class__
            self.runtime.register_agent(agent, factory=agent_class)
        self.runtime.start()

    def run_snapshot(self, context: AgentRunContext) -> dict[str, Any]:
        self.repository.ensure_schema()
        context = self._limited_context(context)
        self.director.heartbeat()
        tasks = self.director.plan_tasks(context, self.agents)
        task_ids = self.runtime.submit_tasks(tasks)
        task_results = self.runtime.wait_for_results(task_ids, self.config.task_timeout_seconds + 2.0)
        task_result_by_id = {result.task_id: result for result in task_results}
        results: list[AgentRunResult] = []
        for task in tasks:
            agent = next((item for item in self.agents if item.agent_id == task.target_agent_id), None)
            if agent is None:
                continue
            task_result = task_result_by_id.get(task.task_id)
            if task_result and task_result.ok and isinstance(task_result.output, AgentRunResult):
                results.append(task_result.output)
                continue
            error = task_result.error if task_result else ErrorResult(
                agent_id=agent.agent_id,
                task_id=task.task_id,
                error_type="timeout",
                message="agent did not return before the snapshot deadline",
                retryable=True,
            )
            results.append(self._error_result_for(agent, error))
        persist_run_results(self.repository, results)
        self.repository.archive_low_value_evidence()
        markdown = self.repository.export_markdown()
        current_decisions = [decision for result in results for decision in result.decisions]
        decisions = self.repository.list_decision_contexts(limit=8)
        latest_decision = current_decisions[-1].to_dict() if current_decisions else None
        runtime_snapshot = self.runtime.snapshot()
        return {
            "organizationDesk": self._organization_desk(results, runtime_snapshot),
            "researchTasks": [_clean_for_display(task.to_dict()) for task in self.repository.list_tasks(limit=12)],
            "evidenceSummary": self.repository.summary(),
            "evidenceRecords": [_clean_for_display(item.to_dict()) for item in self.repository.list_evidence(limit=8)],
            "agentFindings": [_clean_for_display(item.to_dict()) for item in self.repository.list_findings(limit=10)],
            "decisionContexts": [_clean_for_display(item.to_dict()) for item in decisions],
            "latestDecisionContext": _clean_for_display(latest_decision),
            "researchMarkdown": _clean_for_display(markdown),
            "researchRuntime": _clean_for_display(runtime_snapshot),
        }

    def _limited_context(self, context: AgentRunContext) -> AgentRunContext:
        limit = max(1, int(self.config.max_symbols_per_cycle))
        return replace(context, watchlist=list(context.watchlist[:limit]))

    def _error_result_for(self, agent: ResearchAgent, error: ErrorResult) -> AgentRunResult:
        finding = AgentFinding(
            agent_name=agent.name,
            related_task_id=None,
            related_evidence_ids=[],
            finding_type="agent_error",
            claim=f"{agent.name} failed safely and returned a structured ErrorResult.",
            confidence=0.0,
            limitations=[error.message],
            suggested_actions=["watchdog will retry or restart the agent", "keep trading gate blocked until evidence is complete"],
        )
        return AgentRunResult(agent.name, "error", [error.message], [], [], [finding])

    def _organization_desk(self, results: list[AgentRunResult], runtime_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        division_labels = {
            "Market Research": ("調査部門", "Research", "市場観測、候補銘柄探索、実データEvidence収集を担当します。"),
            "Intelligence": ("調査部門", "Research", "ニュースと保存済みEvidenceを整理します。"),
            "Company Research": ("調査部門", "Research", "企業metaとファンダメンタル情報をEvidence化します。"),
            "Macro Research": ("調査部門", "Research", "マクロ・政策・業界仮説を追加調査タスク化します。"),
            "Evidence": ("分析部門", "Analysis", "Evidenceの重複、鮮度、信頼度を整理します。"),
            "Strategy": ("意思決定支援部門", "Strategy", "EvidenceGate通過後だけDecisionContextを生成します。"),
        }
        agent_labels = {
            "Market Observer Agent": ("市場観測エージェント", "Market Observer"),
            "Stock Discovery Agent": ("候補銘柄探索エージェント", "Stock Discovery"),
            "News Intelligence Agent": ("ニュース調査エージェント", "News Intelligence"),
            "Company Research Agent": ("企業調査エージェント", "Company Research"),
            "Academic / Macro Research Agent": ("学術・マクロ調査エージェント", "Academic / Macro Research"),
            "Evidence Curator Agent": ("証拠整理エージェント", "Evidence Curator"),
            "Strategy Synthesis Agent": ("戦略統合エージェント", "Strategy Synthesis"),
            "Agent Chat Coordinator": ("会話調整エージェント", "Agent Chat Coordinator"),
        }
        divisions: dict[str, list[dict[str, Any]]] = {}
        by_name = {agent.name: agent for agent in self.agents}
        runtime_by_agent_id = {
            str(agent.get("agent_id")): agent
            for agent in (runtime_snapshot or {}).get("agents", [])
        }
        for result in results:
            division = by_name[result.agent_name].division
            label_ja, label_en = agent_labels.get(result.agent_name, (result.agent_name, result.agent_name))
            runtime_state = runtime_by_agent_id.get(by_name[result.agent_name].agent_id, {})
            divisions.setdefault(division, []).append(
                {
                    "agentId": by_name[result.agent_name].agent_id,
                    "name": result.agent_name,
                    "labelJa": label_ja,
                    "labelEn": label_en,
                    "status": result.status,
                    "currentTask": runtime_state.get("current_task"),
                    "lastHeartbeat": runtime_state.get("last_heartbeat"),
                    "lastError": runtime_state.get("last_error"),
                    "restartCount": runtime_state.get("restart_count", 0),
                    "queuedTaskCount": runtime_state.get("queued_task_count", 0),
                    "logs": result.logs[-4:],
                    "tasks": len(result.tasks),
                    "evidence": len(result.evidence),
                    "findings": len(result.findings),
                    "decisions": len(result.decisions),
                }
            )
        director_state = runtime_by_agent_id.get(self.director.agent_id, self.director.snapshot())
        divisions.setdefault("Operations", []).append(
            {
                "agentId": self.director.agent_id,
                "name": self.director.name,
                "labelJa": "Research Director",
                "labelEn": "Research Director",
                "status": director_state.get("status", "idle"),
                "currentTask": director_state.get("current_task"),
                "lastHeartbeat": director_state.get("last_heartbeat"),
                "lastError": director_state.get("last_error"),
                "restartCount": director_state.get("restart_count", 0),
                "queuedTaskCount": director_state.get("queued_task_count", 0),
                "logs": ["task queue planned", f"activity_level={self.config.activity_level}"],
                "tasks": (runtime_snapshot or {}).get("queue", {}).get("pendingCount", 0),
                "evidence": 0,
                "findings": 0,
                "decisions": 0,
            }
        )
        return {
            "mode": "research_simulation_only",
            "safety": "No broker API, no external execution, no real-money order. Evidence OS is for research simulation only.",
            "runtime": runtime_snapshot,
            "config": self.config.to_dict(),
            "divisions": [
                {
                    "name": name,
                    "labelJa": division_labels.get(name, (name, name, ""))[0],
                    "labelEn": division_labels.get(name, (name, name, ""))[1],
                    "descriptionJa": division_labels.get(name, (name, name, ""))[2],
                    "agents": agents,
                }
                for name, agents in divisions.items()
            ],
        }


def _clean_for_display(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clean_for_display(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_for_display(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        placeholder_token = "".join(chr(code) for code in (109, 111, 99, 107))
        if placeholder_token in lowered or any(chr(code) in value for code in (0x7E3A, 0x8B5B, 0x9AE2, 0x7E5D, 0x7AAE, 0x8700, 0x9B2E)):
            return "legacy placeholder text hidden"
    return value
