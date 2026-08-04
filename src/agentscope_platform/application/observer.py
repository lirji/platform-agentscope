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
    def started(self, model: str) -> None:
        """Record one newly active run without request-specific labels."""

    def record(self, observation: RunObservation) -> None:
        """Record non-secret run governance data."""


class NoopRunObserver:
    def started(self, model: str) -> None:
        del model

    def record(self, observation: RunObservation) -> None:
        del observation


class CompositeRunObserver:
    def __init__(self, *observers: RunObserver) -> None:
        self._observers = observers

    def started(self, model: str) -> None:
        for observer in self._observers:
            observer.started(model)

    def record(self, observation: RunObservation) -> None:
        for observer in self._observers:
            observer.record(observation)
