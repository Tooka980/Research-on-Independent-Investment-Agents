from __future__ import annotations

from typing import Any


class StrategyOutputEngine:
    """Builds evidence-linked strategy text for the simulator UI."""

    def build(
        self,
        *,
        focus: dict[str, Any],
        market: dict[str, Any],
        news_items: list[dict[str, Any]],
        research_snapshot: dict[str, Any],
        runtime_snapshot: dict[str, Any],
        virtual_order_desk: dict[str, Any],
    ) -> dict[str, Any]:
        symbol = str(focus.get("symbol") or "")
        name = str(focus.get("jpName") or symbol)
        quote = focus.get("quote", {})
        data_quality = focus.get("dataQuality", {})
        analysis_lines = [str(item) for item in focus.get("analysis", []) if item]
        evidence_records = research_snapshot.get("evidenceRecords", []) or []
        decision = research_snapshot.get("latestDecisionContext") or {}
        consensus = runtime_snapshot.get("tradingConsensus", {}) or {}
        runtime_queue = runtime_snapshot.get("runtimeQueue", []) or []
        virtual_summary = virtual_order_desk.get("summary", {}) or {}
        evidence_refs = list(decision.get("related_evidence_ids") or [])
        if not evidence_refs:
            evidence_refs = [str(item.get("id")) for item in evidence_records[:4] if item.get("id")]

        missing: list[str] = []
        if not data_quality.get("hasAnalysisHistory"):
            missing.append("全期間OHLCV")
        if not news_items:
            missing.append("最新ニュースEvidence")
        if not evidence_refs:
            missing.append("DecisionContext根拠")

        change_pct = float(quote.get("changePct") or 0.0)
        price_text = f"現在値 {quote.get('current'):.0f}円 / 変動 {change_pct:+.2f}%" if quote.get("current") else "価格データ取得待ち"
        first_analysis = analysis_lines[0] if analysis_lines else "全期間分析を準備中です"
        news_title = str(news_items[0].get("title")) if news_items else "ニュースEvidence取得待ち"
        next_task = str(runtime_queue[0].get("task")) if runtime_queue else "runtime_queue_waiting"
        phase_text = "市場中のため価格監視と仮想売買判断を優先します。" if market.get("is_open") else "閉場中のためニュース収集、Evidence整理、翌営業日シナリオを優先します。"

        if missing:
            summary = f"{name} は {price_text}。{first_analysis}。不足情報: {', '.join(missing)}。"
        else:
            summary = f"{name} は {price_text}。{first_analysis}。{len(evidence_refs)}件のEvidenceを参照しています。"

        return {
            "summary": summary,
            "market": phase_text,
            "focus": f"{symbol} の注目材料: {news_title}",
            "risk": self._risk_text(consensus, virtual_summary, missing),
            "tomorrow": f"次回タスク: {next_task}。寄り付き価格、出来高回復、ニュース反応を観察します。",
            "evidenceRefs": evidence_refs,
            "missingInformation": missing,
            "generatedBy": "StrategyOutputEngine",
            "source": "real_data_or_saved_evidence",
        }

    def _risk_text(self, consensus: dict[str, Any], virtual_summary: dict[str, Any], missing: list[str]) -> str:
        status = str(consensus.get("status") or "waiting")
        latest = str(virtual_summary.get("latestStatus") or "no_virtual_order")
        if missing:
            return f"根拠不足があるため新規仮想注文は抑制します。Consensus={status} / VirtualOrder={latest}。"
        if status == "waiting_for_market":
            return f"市場外のため仮想約定は停止中です。VirtualOrder={latest}。"
        if status == "approved_for_virtual_order":
            return f"Consensus Gateは仮想注文候補を許可しています。RiskGate通過後のみSimulationへ進めます。"
        return f"Consensus={status}。集中度、流動性、価格鮮度を継続監視します。"
