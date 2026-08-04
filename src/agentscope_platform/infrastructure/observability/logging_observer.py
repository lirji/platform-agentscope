import structlog

from agentscope_platform.application.observer import RunObservation, RunObserver


class LoggingRunObserver(RunObserver):
    def __init__(self) -> None:
        self._logger = structlog.get_logger("agent_run")

    def started(self, model: str) -> None:
        del model

    def record(self, observation: RunObservation) -> None:
        self._logger.info(
            "agent_run_completed",
            trace_id=observation.trace_id,
            tenant_id=observation.tenant_id,
            user_id=observation.user_id,
            model=observation.model,
            stop_reason=observation.stop_reason,
            duration_ms=observation.duration_ms,
            input_tokens=observation.input_tokens,
            output_tokens=observation.output_tokens,
            tools=list(observation.tools),
        )
