from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RunObservation:
    trace_id: str
    tenant_id: str
    user_id: str
    model: str
    stop_reason: str
    duration_ms: int
    input_tokens: int
    output_tokens: int
    tools: tuple[str, ...]


class RunObserver(Protocol):
    def record(self, observation: RunObservation) -> None:
        """Record non-secret run governance data."""


class NoopRunObserver:
    def record(self, observation: RunObservation) -> None:
        del observation
