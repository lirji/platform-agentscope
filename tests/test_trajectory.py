from agentscope.event import (
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
from agentscope.message import ToolResultState
from agentscope.types import ReplyFinishedReason

from agentscope_platform.infrastructure.agentscope.trajectory import TrajectoryCollector


def tool_events(call_id: str, name: str, arguments: str, result: str) -> list[object]:
    return [
        ToolCallStartEvent(reply_id="r", tool_call_id=call_id, tool_call_name=name),
        ToolCallDeltaEvent(reply_id="r", tool_call_id=call_id, delta=arguments),
        ToolCallEndEvent(reply_id="r", tool_call_id=call_id),
        ToolResultStartEvent(reply_id="r", tool_call_id=call_id, tool_call_name=name),
        ToolResultTextDeltaEvent(reply_id="r", tool_call_id=call_id, delta=result),
        ToolResultEndEvent(
            reply_id="r",
            tool_call_id=call_id,
            state=ToolResultState.SUCCESS,
        ),
    ]


def test_maps_tool_events_to_legacy_steps_without_reasoning() -> None:
    collector = TrajectoryCollector()
    for event in tool_events("c1", "rag_search", '{"query":"退款"}', "found"):
        collector.consume(event)  # type: ignore[arg-type]
    collector.consume(ModelCallEndEvent(reply_id="r", input_tokens=10, output_tokens=4))
    collector.consume(
        ReplyEndEvent(
            session_id="s",
            reply_id="r",
            finished_reason=ReplyFinishedReason.COMPLETED,
        )
    )

    assert [step.model_dump(by_alias=True) for step in collector.steps()] == [
        {
            "n": 1,
            "thought": "",
            "action": "rag_search",
            "actionInput": "退款",
            "observation": "found",
        }
    ]
    assert collector.total_tokens == 14
    assert collector.tool_names == ("rag_search",)
    assert collector.stop_reason() == "DONE"


def test_parallel_tool_results_remain_in_call_order() -> None:
    collector = TrajectoryCollector()
    starts = [
        ToolCallStartEvent(reply_id="r", tool_call_id="a", tool_call_name="order_query"),
        ToolCallDeltaEvent(reply_id="r", tool_call_id="a", delta='{"order_no":"101"}'),
        ToolCallEndEvent(reply_id="r", tool_call_id="a"),
        ToolCallStartEvent(reply_id="r", tool_call_id="b", tool_call_name="current_time"),
        ToolCallDeltaEvent(reply_id="r", tool_call_id="b", delta='{"timezone":"UTC"}'),
        ToolCallEndEvent(reply_id="r", tool_call_id="b"),
    ]
    for event in starts:
        collector.consume(event)
    for event in [
        *tool_events("b", "current_time", "", "now")[3:],
        *tool_events("a", "order_query", "", "order")[3:],
    ]:
        collector.consume(event)  # type: ignore[arg-type]

    assert [step.action for step in collector.steps()] == ["order_query", "current_time"]
    assert [step.n for step in collector.steps()] == [1, 2]


def test_max_iterations_interruption_and_best_effort_text() -> None:
    collector = TrajectoryCollector()
    collector.consume(ExceedMaxItersEvent(reply_id="r", name="agent"))
    collector.consume(TextBlockDeltaEvent(reply_id="r", block_id="answer", delta="partial answer"))

    assert collector.stop_reason() == "MAX_STEPS"
    assert collector.best_effort_text == "partial answer"


def test_repeated_action_is_detected_and_recorded() -> None:
    collector = TrajectoryCollector(loop_window=6)
    for index in range(3):
        for event in tool_events(
            f"c{index}",
            "rag_search",
            '{"query":"same"}',
            "same result",
        )[:3]:
            collector.consume(event)  # type: ignore[arg-type]

    assert collector.repeated_action(3)
    collector.mark_loop()
    assert collector.steps()[-1].action == "rag_search"
    assert "stopped: action repeated 3x" in collector.steps()[-1].observation
