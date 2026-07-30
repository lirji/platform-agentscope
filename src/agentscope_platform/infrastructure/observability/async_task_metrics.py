from opentelemetry import metrics


class AsyncTaskMetrics:
    """Low-cardinality async orchestration metrics exported by the app meter provider."""

    def __init__(self) -> None:
        meter = metrics.get_meter("agentscope_platform.async_task")
        self._submissions = meter.create_counter(
            "agent_async_task_submissions",
            description="Accepted Agent async task submissions.",
            unit="task",
        )
        self._completions = meter.create_counter(
            "agent_async_task_completions",
            description="Agent async task terminal completions.",
            unit="task",
        )
        self._heartbeat_failures = meter.create_counter(
            "agent_async_task_heartbeat_failures",
            description="Agent async task lease heartbeat failures.",
            unit="failure",
        )
        self._running = meter.create_up_down_counter(
            "agent_async_task_running",
            description="Agent async tasks executing in this process.",
            unit="task",
        )

    def submitted(self, kind: str) -> None:
        self._submissions.add(1, {"kind": kind})

    def completed(self, kind: str, status: str) -> None:
        self._completions.add(1, {"kind": kind, "status": status})

    def heartbeat_failed(self) -> None:
        self._heartbeat_failures.add(1)

    def running(self, delta: int, kind: str) -> None:
        self._running.add(delta, {"kind": kind})
