import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
from agentscope.message import TextBlock
from agentscope.model import ChatResponse, FinishedReason
from pydantic import SecretStr
from starlette.requests import ClientDisconnect

from agentscope_platform.api.conversation_app import _LeasedStream, create_conversation_app
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import current_run_context
from agentscope_platform.evaluation.conversation_stream import validate_conversation_stream
from agentscope_platform.infrastructure.agentscope.conversation_candidate import (
    ConversationCandidate,
)

SECRET = "test-conversation-only-internal-key-with-32-characters"
BODY = {
    "schema_version": "1",
    "message": "hello",
    "context": "trusted retrieval snapshot",
    "history": [],
    "style": {"language": "English", "tone": "concise", "citation_policy": "cite", "extra": ""},
}


def token(scopes: list[str] | None = None) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "langchain4j-platform",
            "aud": "platform-internal",
            "sub": "acme",
            "uid": "alice",
            "scopes": ["chat"] if scopes is None else scopes,
            "token_use": "internal_access",
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(seconds=300),
        },
        SECRET,
        algorithm="HS256",
        headers={"kid": "platform-internal-v1", "typ": "JWT"},
    )


class Model:
    def __init__(
        self,
        *,
        error: bool = False,
        pause: asyncio.Event | None = None,
        interrupted: bool = False,
        too_large: bool = False,
    ) -> None:
        self.calls = 0
        self.closed = 0
        self.error, self.pause, self.interrupted, self.too_large = (
            error,
            pause,
            interrupted,
            too_large,
        )

    async def __call__(self, messages: Any) -> AsyncGenerator[ChatResponse, None]:
        del messages
        self.calls += 1
        assert current_run_context().identity.tenant_id == "acme"

        async def chunks() -> AsyncGenerator[ChatResponse, None]:
            try:
                yield ChatResponse(content=[TextBlock(text="hello")], is_last=False)
                if self.pause:
                    await self.pause.wait()
                if self.error:
                    raise RuntimeError("private provider credential detail")
                if self.too_large:
                    yield ChatResponse(content=[TextBlock(text="x" * 65_536)], is_last=False)
                yield ChatResponse(
                    content=[TextBlock(text="hello")],
                    is_last=True,
                    finished_reason=(
                        FinishedReason.INTERRUPTED if self.interrupted else FinishedReason.COMPLETED
                    ),
                )
                raise AssertionError("provider must be closed at terminal response")
            finally:
                self.closed += 1

        return chunks()


def app(model: Model) -> Any:
    configured = Settings(_env_file=None, internal_jwt_secret=SecretStr(SECRET))
    return create_conversation_app(configured, ConversationCandidate(configured, model=model))


def parse(response: httpx.Response) -> list[dict[str, object]]:
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


async def test_candidate_stream_is_authenticated_stateless_ordered_and_closes_provider() -> None:
    model = Model()
    application = app(model)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://candidate"
    ) as client:
        assert (await client.post("/internal/conversation/stream", json=BODY)).status_code == 401
        assert (
            await client.post(
                "/internal/conversation/stream", json=BODY, headers={"X-Internal-Token": token([])}
            )
        ).status_code == 403
        response = await client.post(
            "/internal/conversation/stream", json=BODY, headers={"X-Internal-Token": token()}
        )
        assert (await client.post("/agent/run", json={"goal": "test"})).status_code == 404
    assert response.status_code == 200
    events = parse(response)
    validate_conversation_stream(events)
    assert [event["type"] for event in events] == ["token", "done"]
    assert model.closed == 1 and model.calls == 1
    assert not hasattr(application.state, "container")
    with pytest.raises(RuntimeError):
        current_run_context()


@pytest.mark.parametrize("mode", ["error", "interrupted", "too_large"])
async def test_candidate_failures_have_one_public_terminal_and_no_provider_details(
    mode: str,
) -> None:
    model = Model(**{mode: True})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(model)), base_url="http://candidate"
    ) as client:
        response = await client.post(
            "/internal/conversation/stream", json=BODY, headers={"X-Internal-Token": token()}
        )
    events = parse(response)
    validate_conversation_stream(events)
    assert events[-1] == {"sequence": 1, "type": "error", "data": "CONVERSATION_STREAM_FAILED"}
    assert model.closed == 1
    assert "private" not in response.text


async def test_body_identity_and_unbounded_payload_are_rejected_before_model_call() -> None:
    model = Model()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(model)), base_url="http://candidate"
    ) as client:
        for body in [{**BODY, "tenantId": "forged"}, {**BODY, "message": "x" * 65_537}]:
            response = await client.post(
                "/internal/conversation/stream", json=body, headers={"X-Internal-Token": token()}
            )
            assert response.status_code == 400
        response = await client.post(
            "/internal/conversation/stream",
            content=b"x" * 262_145,
            headers={"X-Internal-Token": token()},
        )
        assert response.status_code == 413
    assert model.calls == 0


async def test_capacity_is_bounded_and_released_after_complete_generations() -> None:
    pause = asyncio.Event()
    model = Model(pause=pause)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(model)), base_url="http://candidate"
    ) as client:

        async def generate() -> httpx.Response:
            return await client.post(
                "/internal/conversation/generate", json=BODY, headers={"X-Internal-Token": token()}
            )

        running = [asyncio.create_task(generate()) for _ in range(4)]
        for _ in range(100):
            if model.calls == 4:
                break
            await asyncio.sleep(0.01)
        assert (await generate()).status_code == 429
        assert model.calls == 4
        pause.set()
        assert all(response.status_code == 200 for response in await asyncio.gather(*running))
        assert (await generate()).json() == {"reply": "hello"}
    assert model.closed == 5


async def test_asgi_backpressure_does_not_prefetch_and_disconnect_closes_generator() -> None:
    consumed = 0
    closed = False

    async def events() -> AsyncGenerator[bytes, None]:
        nonlocal consumed, closed
        try:
            for _ in range(100):
                consumed += 1
                yield b"data: token\n\n"
        finally:
            closed = True

    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    response = _LeasedStream(events(), semaphore)
    reached = asyncio.Event()
    release = asyncio.Event()

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body":
            reached.set()
            await release.wait()
            raise OSError("client disconnected")

    async def receive() -> dict[str, str]:
        return {"type": "http.disconnect"}

    work = asyncio.create_task(
        response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    )
    await reached.wait()
    assert consumed == 1
    release.set()
    with pytest.raises(ClientDisconnect):
        await work
    assert closed and semaphore._value == 1


async def test_asgi_listener_disconnect_closes_cross_task_context_without_leaking_slot() -> None:
    configured = Settings(_env_file=None, internal_jwt_secret=SecretStr(SECRET))
    model = Model(pause=asyncio.Event())
    application = app(model)
    reached = asyncio.Event()

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            reached.set()
            await asyncio.Event().wait()

    received_body = False

    async def receive() -> dict[str, Any]:
        nonlocal received_body
        if not received_body:
            received_body = True
            return {"type": "http.request", "body": json.dumps(BODY).encode(), "more_body": False}
        await reached.wait()
        return {"type": "http.disconnect"}

    await asyncio.wait_for(
        application(
            {
                "type": "http",
                "asgi": {"spec_version": "2.3"},
                "method": "POST",
                "path": "/internal/conversation/stream",
                "query_string": b"",
                "headers": [(configured.internal_jwt_header.lower().encode(), token().encode())],
            },
            receive,
            send,
        ),
        timeout=2,
    )
    assert model.closed == 1
    with pytest.raises(RuntimeError):
        current_run_context()
