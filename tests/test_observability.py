from agentscope_platform.application.observer import RunObservation
from agentscope_platform.core.config import Settings
from agentscope_platform.infrastructure.observability.logging_observer import (
    LoggingRunObserver,
)
from agentscope_platform.infrastructure.observability.setup import _trace_endpoint


def test_trace_endpoint_accepts_base_or_full_path() -> None:
    base = Settings(otel_exporter_otlp_endpoint="http://collector:4318")
    full = Settings(otel_exporter_otlp_endpoint="http://collector:4318/v1/traces")

    assert _trace_endpoint(base) == "http://collector:4318/v1/traces"
    assert _trace_endpoint(full) == "http://collector:4318/v1/traces"


def test_logging_observer_emits_governance_fields_without_secrets() -> None:
    observation = RunObservation(
        trace_id="trace",
        tenant_id="acme",
        user_id="alice",
        model="chat-default",
        stop_reason="DONE",
        duration_ms=10,
        input_tokens=20,
        output_tokens=5,
        tools=("rag_search",),
    )

    LoggingRunObserver().record(observation)

    assert "internal_token" not in RunObservation.__dataclass_fields__
    assert "api_key" not in RunObservation.__dataclass_fields__
