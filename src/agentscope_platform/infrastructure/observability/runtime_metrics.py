from decimal import Decimal

from opentelemetry import metrics

from agentscope_platform.application.observer import RunObservation, RunObserver
from agentscope_platform.core.config import Settings


class RunMetricsObserver(RunObserver):
    """Low-cardinality runtime, token, estimated cost, and termination metrics."""

    def __init__(self, settings: Settings) -> None:
        meter = metrics.get_meter("agentscope_platform.agent_runtime")
        self._inflight = meter.create_up_down_counter(
            "agent_run_inflight",
            description="Agent runs currently executing in this process.",
            unit="run",
        )
        self._duration = meter.create_histogram(
            "agent_run_duration_ms",
            description="Agent run wall-clock latency distribution.",
            unit="ms",
        )
        self._terminations = meter.create_counter(
            "agent_run_terminations",
            description="Agent run terminal reasons.",
            unit="run",
        )
        self._tokens = meter.create_counter(
            "agent_run_tokens",
            description="Agent model tokens attributed by input/output direction.",
            unit="token",
        )
        self._cost = meter.create_counter(
            "agent_run_cost_usd",
            description="Estimated Agent model cost from configured per-token rates.",
            unit="USD",
        )
        self._input_rate = Decimal(str(settings.agent_input_cost_usd_per_million_tokens))
        self._output_rate = Decimal(str(settings.agent_output_cost_usd_per_million_tokens))

    def started(self, model: str) -> None:
        self._inflight.add(1, {"model": model})

    def record(self, observation: RunObservation) -> None:
        attributes = {"model": observation.model}
        self._inflight.add(-1, attributes)
        self._duration.record(observation.duration_ms, attributes)
        self._terminations.add(
            1,
            {"model": observation.model, "reason": observation.stop_reason},
        )
        self._tokens.add(
            observation.input_tokens,
            {"model": observation.model, "direction": "input"},
        )
        self._tokens.add(
            observation.output_tokens,
            {"model": observation.model, "direction": "output"},
        )
        estimated = (
            Decimal(observation.input_tokens) * self._input_rate
            + Decimal(observation.output_tokens) * self._output_rate
        ) / Decimal(1_000_000)
        self._cost.add(float(estimated), attributes)
