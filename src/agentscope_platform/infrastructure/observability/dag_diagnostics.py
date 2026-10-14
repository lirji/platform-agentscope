"""DAG 诊断日志与低基数指标; 不把任务/节点/租户标识放入指标标签。"""

import structlog
from opentelemetry import metrics

from agentscope_platform.domain.dag_diagnostics import (
    DagDiagnosticEvent,
    DagDiagnosticSummary,
    DagModelDiagnostic,
    DagOperationDiagnostic,
)


class DagDiagnosticsObserver:
    """独立 DAG 指标族, 不与既有 agent_run 计数相加以免重复计费。"""

    def __init__(self) -> None:
        meter = metrics.get_meter("agentscope_platform.dag")
        self._logger = structlog.get_logger("dag_diagnostics")
        self._calls = meter.create_counter("agent_dag_model_calls", unit="call")
        self._tokens = meter.create_counter("agent_dag_model_tokens", unit="token")
        self._unknown = meter.create_counter("agent_dag_usage_unknown", unit="call")
        self._unpriced = meter.create_counter("agent_dag_price_unknown", unit="call")
        self._cost = meter.create_counter("agent_dag_estimated_cost_usd", unit="USD")
        self._duration = meter.create_histogram("agent_dag_operation_duration_ms", unit="ms")
        self._queue = meter.create_histogram("agent_dag_worker_queue_ms", unit="ms")
        self._operations = meter.create_counter("agent_dag_operations", unit="operation")
        self._runs = meter.create_counter("agent_dag_segments", unit="segment")
        self._delivery_failures = meter.create_counter("agent_dag_diagnostic_delivery_failures")
        self._dropped = meter.create_counter("agent_dag_diagnostic_dropped_records")

    def record(self, event: DagDiagnosticEvent) -> None:
        """日志关联精确片段和操作; 指标只使用服务端封闭角色/状态/原因。"""
        # 日志输出与指标相互独立, 一种 exporter 故障不阻断另一种。
        try:
            self._logger.info(
                f"dag_diagnostic_{event.kind}", **event.model_dump(by_alias=True, mode="json")
            )
        finally:
            self._record_metrics(event)

    def _record_metrics(self, event: DagDiagnosticEvent) -> None:
        if isinstance(event, DagModelDiagnostic):
            labels = {"role": event.role.value, "status": event.status}
            self._calls.add(1, labels)
            if event.input_tokens is None or event.output_tokens is None:
                self._unknown.add(1, {"role": event.role.value})
            else:
                self._tokens.add(
                    event.input_tokens, {"role": event.role.value, "direction": "input"}
                )
                self._tokens.add(
                    event.output_tokens, {"role": event.role.value, "direction": "output"}
                )
            if event.estimated_cost_usd is not None:
                self._cost.add(float(event.estimated_cost_usd), {"role": event.role.value})
            if event.input_rate_per_million is None or event.output_rate_per_million is None:
                self._unpriced.add(1, {"role": event.role.value})
        elif isinstance(event, DagOperationDiagnostic):
            # stopReason 来自既有 runner, 允许集合外的值统一归 OTHER 防止标签膨胀。
            status = (
                event.status
                if event.status
                in {
                    "DONE",
                    "ERROR",
                    "CANCELLED",
                    "SKIPPED",
                    "PARTIAL",
                    "TIMEOUT",
                    "MAX_STEPS",
                    "MAX_TOKENS",
                    "LOOP_DETECTED",
                }
                else "OTHER"
            )
            labels = {"role": event.role.value, "status": status}
            self._duration.record(event.duration_ms, labels)
            self._operations.add(1, {**labels, "reason": event.reason.value})
            if event.role.value == "worker":
                self._queue.record(event.queue_ms, {"status": status})
        elif isinstance(event, DagDiagnosticSummary):
            status = (
                event.status
                if event.status in {"DONE", "PARTIAL", "ERROR", "CANCELLED"}
                else "OTHER"
            )
            self._runs.add(1, {"status": status, "resumed": str(event.resumed).lower()})
            self._delivery_failures.add(event.delivery_failures)
            self._dropped.add(event.dropped_records)
