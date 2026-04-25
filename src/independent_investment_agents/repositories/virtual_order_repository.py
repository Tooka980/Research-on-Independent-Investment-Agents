from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta, timezone

from independent_investment_agents.domain.virtual_orders import DecisionTrace, VirtualExecution, VirtualOrder


JST = timezone(timedelta(hours=9), "JST")


class VirtualOrderRepository:
    """Append-only local storage for virtual order simulation artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.orders_path = root / "orders.jsonl"
        self.executions_path = root / "executions.jsonl"
        self.decision_log_path = root / "decision_log.jsonl"
        self.trades_path = root / "trades.csv"
        self.markdown_path = root / "orders.md"

    def ensure_storage(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for path in [self.orders_path, self.executions_path, self.decision_log_path]:
            path.touch(exist_ok=True)
        if not self.trades_path.exists():
            with self.trades_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["execution_id", "order_id", "symbol", "side", "quantity", "execution_price", "commission", "slippage", "executed_at", "simulation_rule"])

    def append_order(self, order: VirtualOrder) -> None:
        self._append_jsonl(self.orders_path, order.to_dict())
        self.export_markdown()

    def append_execution(self, execution: VirtualExecution) -> None:
        self._append_jsonl(self.executions_path, execution.to_dict())
        with self.trades_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                execution.id,
                execution.order_id,
                execution.symbol,
                execution.side,
                execution.quantity,
                execution.execution_price,
                execution.commission,
                execution.slippage,
                execution.executed_at,
                execution.simulation_rule,
            ])
        self.export_markdown()

    def append_decision_trace(self, trace: DecisionTrace) -> None:
        self._append_jsonl(self.decision_log_path, trace.to_dict())
        self.export_markdown()

    def read_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._read_jsonl(self.orders_path, limit)

    def read_executions(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._read_jsonl(self.executions_path, limit)

    def read_decision_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._read_jsonl(self.decision_log_path, limit)

    def has_order_for_symbol(self, symbol: str) -> bool:
        return any(item.get("symbol") == symbol for item in self._read_jsonl(self.orders_path, limit=500))

    def read_markdown(self) -> str:
        self.ensure_storage()
        if not self.markdown_path.exists():
            return self.export_markdown()
        return self.markdown_path.read_text(encoding="utf-8")

    def export_markdown(self, limit: int = 40) -> str:
        self.ensure_storage()
        orders = self.read_orders(limit=limit)
        executions = self.read_executions(limit=limit)
        traces = self.read_decision_traces(limit=limit)
        execution_by_order = {item.get("order_id"): item for item in executions}
        lines = [
            "# Virtual Order History",
            "",
            "All records are simulated inside this application. No broker API or real order is used.",
            "",
            "## Orders",
        ]
        for order in orders:
            execution = execution_by_order.get(order.get("id"), {})
            executed_at = order.get("simulated_executed_at")
            if str(order.get("status") or "").startswith("simulated_"):
                executed_at = executed_at or execution.get("executed_at")
            lines.append(
                "- "
                f"`{order.get('id')}` {order.get('symbol')} {order.get('side')}/{order.get('order_type')} "
                f"status={order.get('status')} "
                f"created={_jst_display(order.get('created_at'))} "
                f"executed={_jst_display(executed_at)} "
                f"decision={order.get('related_decision_context_id')} "
                f"evidence={', '.join(order.get('related_evidence_ids') or [])}"
            )
        lines.extend(["", "## Decision Trace"])
        for trace in traces:
            lines.append(
                "- "
                f"`{trace.get('id')}` outcome={trace.get('outcome')} "
                f"decision={trace.get('decision_context_id')} "
                f"order={trace.get('virtual_order_id')} "
                f"execution={trace.get('virtual_execution_id')} "
                f"at={_jst_display(trace.get('created_at'))}"
            )
        text = "\n".join(lines) + "\n"
        self.markdown_path.write_text(text, encoding="utf-8")
        return text

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        self.ensure_storage()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _read_jsonl(self, path: Path, limit: int) -> list[dict[str, Any]]:
        self.ensure_storage()
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows[-limit:]


def _jst_display(value: Any) -> str:
    if not value:
        return "pending"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST).strftime("%Y/%m/%d %H:%M:%S")
