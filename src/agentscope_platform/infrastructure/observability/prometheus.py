import json
import re
from threading import Lock
from typing import Any

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import Gauge, InMemoryMetricReader, Sum
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from agentscope_platform.core.config import Settings

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
_reader: InMemoryMetricReader | None = None
_configure_lock = Lock()
_metric_name_pattern = re.compile(r"[^a-zA-Z0-9_:]")
_label_name_pattern = re.compile(r"[^a-zA-Z0-9_]")


def configure_metrics(settings: Settings) -> None:
    """Install one process-wide OTel reader before application instruments are created."""
    global _reader

    if _reader is not None:
        return
    with _configure_lock:
        if _reader is not None:
            return
        reader = InMemoryMetricReader()
        provider = MeterProvider(
            resource=Resource.create({SERVICE_NAME: settings.otel_service_name}),
            metric_readers=[reader],
        )
        metrics.set_meter_provider(provider)
        _reader = reader


def render_prometheus_metrics() -> str:
    reader = _reader
    if reader is None:
        return ""
    metrics_data = reader.get_metrics_data()
    if metrics_data is None:
        return ""

    lines: list[str] = []
    declared: set[str] = set()
    for resource_metrics in metrics_data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                metric_type: str
                metric_name = _prometheus_metric_name(metric.name)
                if isinstance(metric.data, Sum):
                    metric_type = "counter" if metric.data.is_monotonic else "gauge"
                    if metric.data.is_monotonic and not metric_name.endswith("_total"):
                        metric_name = f"{metric_name}_total"
                elif isinstance(metric.data, Gauge):
                    metric_type = "gauge"
                else:
                    continue

                if metric_name not in declared:
                    description = _escape_help(metric.description or metric.name)
                    lines.extend(
                        (
                            f"# HELP {metric_name} {description}",
                            f"# TYPE {metric_name} {metric_type}",
                        )
                    )
                    declared.add(metric_name)
                for point in metric.data.data_points:
                    labels = _prometheus_labels(dict(point.attributes or {}))
                    lines.append(f"{metric_name}{labels} {_prometheus_number(point.value)}")
    return "\n".join(lines) + ("\n" if lines else "")


def _prometheus_metric_name(value: str) -> str:
    normalized = _metric_name_pattern.sub("_", value)
    if normalized and normalized[0].isdigit():
        return f"_{normalized}"
    return normalized


def _prometheus_labels(attributes: dict[str, Any]) -> str:
    if not attributes:
        return ""
    rendered = []
    for key, value in sorted(attributes.items()):
        label = _label_name_pattern.sub("_", key)
        rendered.append(f'{label}="{_escape_label(_attribute_text(value))}"')
    return "{" + ",".join(rendered) + "}"


def _attribute_text(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _escape_help(value: str) -> str:
    return value.replace("\\", r"\\").replace("\n", r"\n")


def _escape_label(value: str) -> str:
    return _escape_help(value).replace('"', r"\"")


def _prometheus_number(value: int | float) -> str:
    if isinstance(value, float):
        if value == float("inf"):
            return "+Inf"
        if value == float("-inf"):
            return "-Inf"
        if value != value:
            return "NaN"
    return str(value)
