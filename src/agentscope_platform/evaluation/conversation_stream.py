from collections.abc import Mapping, Sequence


class ConversationStreamContractError(ValueError):
    """Raised when candidate SSE events violate the language-neutral contract."""


def validate_conversation_stream(events: Sequence[Mapping[str, object]]) -> None:
    if not events:
        raise ConversationStreamContractError("conversation stream must not be empty")

    terminal_seen = False
    for expected_sequence, event in enumerate(events):
        sequence = event.get("sequence")
        event_type = event.get("type")
        data = event.get("data")

        if isinstance(sequence, bool) or sequence != expected_sequence:
            raise ConversationStreamContractError(
                f"conversation stream sequence must be contiguous at {expected_sequence}"
            )
        if event_type not in {"token", "done", "error"}:
            raise ConversationStreamContractError(
                f"unsupported conversation stream event type: {event_type}"
            )
        if not isinstance(data, str):
            raise ConversationStreamContractError("conversation stream data must be text")
        if terminal_seen:
            raise ConversationStreamContractError(
                "conversation stream event appears after terminal event"
            )

        if event_type == "token":
            if not data:
                raise ConversationStreamContractError("conversation token data must not be empty")
            continue

        terminal_seen = True
        if expected_sequence != len(events) - 1:
            raise ConversationStreamContractError(
                "conversation terminal event must be the final event"
            )
        if event_type == "done" and data:
            raise ConversationStreamContractError("conversation done data must be empty")
        if event_type == "error" and not data:
            raise ConversationStreamContractError("conversation error data must not be empty")

    if not terminal_seen:
        raise ConversationStreamContractError("conversation stream must end with done or error")
