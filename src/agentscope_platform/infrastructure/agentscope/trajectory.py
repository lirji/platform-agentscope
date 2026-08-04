import json
from collections import deque
from dataclasses import dataclass
from typing import Any

from agentscope.event import (
    AgentEvent,
    ExceedMaxItersEvent,
    ModelCallEndEvent,
    ReplyEndEvent,
    TextBlockDeltaEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.types import ReplyFinishedReason

from agentscope_platform.domain.agent import AgentStep, AgentTrajectory, ExecutionVersions


@dataclass(slots=True)
class _PendingTool:
    order: int
    name: str
    input_json: str = ""
    result_text: str = ""
    finished: bool = False


class TrajectoryCollector:
    """Translate AgentScope events into the stable legacy AgentStep contract."""

    def __init__(
        self,
        loop_window: int = 6,
        initial_steps: tuple[AgentStep, ...] = (),
        versions: ExecutionVersions | None = None,
    ) -> None:
        self._pending: dict[str, _PendingTool] = {}
        self._completed: list[tuple[int, AgentStep]] = [
            (index, step) for index, step in enumerate(initial_steps)
        ]
        self._signatures: deque[str] = deque(maxlen=max(1, loop_window))
        self._text_blocks: dict[str, str] = {}
        self._next_order = len(initial_steps)
        self._versions = versions
        self.input_tokens = 0
        self.output_tokens = 0
        self.exceeded_max_iters = False
        self.reply_finished_reason: ReplyFinishedReason | None = None

    def consume(self, event: AgentEvent) -> None:
        if isinstance(event, ToolCallStartEvent):
            self._pending[event.tool_call_id] = _PendingTool(
                order=self._allocate_order(),
                name=event.tool_call_name,
            )
        elif isinstance(event, ToolCallDeltaEvent):
            pending = self._pending.get(event.tool_call_id)
            if pending is not None:
                pending.input_json += event.delta
        elif isinstance(event, ToolCallEndEvent):
            pending = self._pending.get(event.tool_call_id)
            if pending is not None:
                self._signatures.append(
                    f"{pending.name}|{_legacy_action_input(pending.input_json)}"
                )
        elif isinstance(event, ToolResultStartEvent):
            if event.tool_call_id not in self._pending:
                self._pending[event.tool_call_id] = _PendingTool(
                    order=self._allocate_order(),
                    name=event.tool_call_name,
                )
        elif isinstance(event, ToolResultTextDeltaEvent):
            pending = self._pending.get(event.tool_call_id)
            if pending is not None:
                pending.result_text += event.delta
        elif isinstance(event, ToolResultEndEvent):
            state = event.state.value if hasattr(event.state, "value") else str(event.state)
            self._finish_tool(event.tool_call_id, state)
        elif isinstance(event, ModelCallEndEvent):
            self.input_tokens += event.input_tokens
            self.output_tokens += event.output_tokens
        elif isinstance(event, ExceedMaxItersEvent):
            self.exceeded_max_iters = True
        elif isinstance(event, ReplyEndEvent):
            self.reply_finished_reason = event.finished_reason
        elif isinstance(event, TextBlockDeltaEvent):
            self._text_blocks[event.block_id] = (
                self._text_blocks.get(event.block_id, "") + event.delta
            )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def tool_names(self) -> tuple[str, ...]:
        ordered = sorted(
            [*self._pending.values()],
            key=lambda item: item.order,
        )
        return tuple(item.name for item in ordered)

    @property
    def best_effort_text(self) -> str:
        values = [value.strip() for value in self._text_blocks.values() if value.strip()]
        return values[-1] if values else ""

    def repeated_action(self, max_repeats: int) -> bool:
        if not self._signatures:
            return False
        latest = self._signatures[-1]
        return sum(signature == latest for signature in self._signatures) >= max_repeats

    def mark_loop(self) -> None:
        pending = max(self._pending.values(), key=lambda item: item.order, default=None)
        if pending is None or pending.finished:
            return
        repeats = sum(signature == self._signatures[-1] for signature in self._signatures)
        pending.result_text = (
            f"(stopped: action repeated {repeats}x within last "
            f"{len(self._signatures)} steps without progress)"
        )
        self._finish_pending(pending)

    def steps(self) -> tuple[AgentStep, ...]:
        return tuple(step for _, step in sorted(self._completed, key=lambda item: item[0]))

    def trajectory(self, *, trace_id: str, stop_reason: str) -> AgentTrajectory:
        if self._versions is None:
            raise ValueError("trajectory runtime versions are required")
        return AgentTrajectory(
            traceId=trace_id,
            versions=self._versions,
            steps=self.steps(),
            stopReason=stop_reason,
            inputTokens=self.input_tokens,
            outputTokens=self.output_tokens,
        )

    def stop_reason(self) -> str:
        if self.exceeded_max_iters:
            return "MAX_STEPS"
        if self.reply_finished_reason == ReplyFinishedReason.INTERRUPTED:
            return "CANCELLED"
        if self.reply_finished_reason == ReplyFinishedReason.EXCEED_MAX_ITERS:
            return "MAX_STEPS"
        if self.reply_finished_reason == ReplyFinishedReason.ERROR:
            return "ERROR"
        return "DONE"

    def _finish_tool(self, tool_call_id: str, state: str) -> None:
        pending = self._pending.get(tool_call_id)
        if pending is None or pending.finished:
            return
        if not pending.result_text and state != "success":
            pending.result_text = f"(tool {state})"
        self._finish_pending(pending)

    def _finish_pending(self, pending: _PendingTool) -> None:
        pending.finished = True
        self._completed.append(
            (
                pending.order,
                AgentStep(
                    n=pending.order + 1,
                    thought="",
                    action=pending.name,
                    actionInput=_legacy_action_input(pending.input_json),
                    observation=pending.result_text,
                ),
            )
        )

    def _allocate_order(self) -> int:
        order = self._next_order
        self._next_order += 1
        return order


def _legacy_action_input(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, dict) and len(parsed) == 1:
        only_value = next(iter(parsed.values()))
        if only_value is None:
            return ""
        if isinstance(only_value, str):
            return only_value
        return json.dumps(only_value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
