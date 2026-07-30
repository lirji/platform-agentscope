import pytest

from agentscope_platform.evaluation.conversation_stream import (
    ConversationStreamContractError,
    validate_conversation_stream,
)


@pytest.mark.parametrize(
    "events",
    [
        [
            {"sequence": 0, "type": "token", "data": "你"},
            {"sequence": 1, "type": "token", "data": "好"},
            {"sequence": 2, "type": "done", "data": ""},
        ],
        [
            {"sequence": 0, "type": "token", "data": "partial"},
            {"sequence": 1, "type": "error", "data": "candidate timeout"},
        ],
    ],
)
def test_accepts_well_formed_candidate_streams(events: list[dict[str, object]]) -> None:
    validate_conversation_stream(events)


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"sequence": 1, "type": "done", "data": ""}],
        [{"sequence": 0, "type": "token", "data": ""}],
        [{"sequence": 0, "type": "token", "data": "unterminated"}],
        [
            {"sequence": 0, "type": "done", "data": ""},
            {"sequence": 1, "type": "token", "data": "late"},
        ],
        [{"sequence": 0, "type": "done", "data": "unexpected"}],
        [{"sequence": 0, "type": "error", "data": ""}],
    ],
)
def test_rejects_sequence_and_terminal_violations(
    events: list[dict[str, object]],
) -> None:
    with pytest.raises(ConversationStreamContractError):
        validate_conversation_stream(events)
