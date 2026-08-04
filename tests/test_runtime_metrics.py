from pydantic import SecretStr

from agentscope_platform.application.observer import RunObservation
from agentscope_platform.core.config import Settings
from agentscope_platform.infrastructure.observability.prometheus import (
    configure_metrics,
    render_prometheus_metrics,
)
from agentscope_platform.infrastructure.observability.runtime_metrics import (
    RunMetricsObserver,
)


def test_run_metrics_export_latency_inflight_tokens_cost_and_stop_reason() -> None:
    settings = Settings(
        gateway_api_key=SecretStr("test-key"),
        agent_input_cost_usd_per_million_tokens=1.0,
        agent_output_cost_usd_per_million_tokens=2.0,
    )
    configure_metrics(settings)
    observer = RunMetricsObserver(settings)

    observer.started("chat-default")
    observer.record(
        RunObservation(
            trace_id="trace-1",
            tenant_id="acme",
            user_id="alice",
            model="chat-default",
            stop_reason="TIMEOUT",
            duration_ms=250,
            input_tokens=100,
            output_tokens=50,
            tools=("knowledge_search",),
        )
    )

    rendered = render_prometheus_metrics()
    assert 'agent_run_inflight{model="chat-default"} 0' in rendered
    assert 'agent_run_terminations_total{model="chat-default",reason="TIMEOUT"} 1' in rendered
    assert 'agent_run_tokens_total{direction="input",model="chat-default"} 100' in rendered
    assert 'agent_run_tokens_total{direction="output",model="chat-default"} 50' in rendered
    assert 'agent_run_cost_usd_total{model="chat-default"} 0.0002' in rendered
    assert 'agent_run_duration_ms_bucket{le="+Inf",model="chat-default"} 1' in rendered
    assert 'agent_run_duration_ms_count{model="chat-default"} 1' in rendered
    assert 'agent_run_duration_ms_sum{model="chat-default"} 250' in rendered
