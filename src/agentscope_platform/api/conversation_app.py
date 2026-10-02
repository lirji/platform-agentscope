"""独立无状态conversation候选HTTP入口, 不装配Agent容器或任务worker."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from agentscope_platform.core.config import Settings, get_settings
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.conversation import (
    ConversationGenerationReply,
    ConversationGenerationRequest,
)
from agentscope_platform.infrastructure.agentscope.conversation_candidate import (
    ConversationCandidate,
)
from agentscope_platform.infrastructure.security.internal_jwt import (
    InternalAuthenticationError,
    InternalJwtVerifier,
)


class _LeasedStream(StreamingResponse):
    """ASGI断连/发送失败也释放并发槽并关闭上游, 不依赖body已开始迭代."""

    def __init__(self, events: AsyncGenerator[bytes, None], semaphore: asyncio.Semaphore) -> None:
        super().__init__(
            events, media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )
        self.events = events
        self.semaphore = semaphore

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        try:
            await super().__call__(*args, **kwargs)
        finally:
            try:
                await self.events.aclose()
            finally:
                self.semaphore.release()


def create_conversation_app(
    settings: Settings | None = None,
    candidate: ConversationCandidate | None = None,
) -> FastAPI:
    configured = settings or get_settings()
    generator = candidate or ConversationCandidate(configured)
    verifier = InternalJwtVerifier(configured)
    slots = asyncio.Semaphore(4)
    app = FastAPI(title="Stateless conversation candidate", version="1")

    def authenticate(request: Request) -> RunContext:
        try:
            verified = verifier.verify_with_expiry(
                request.headers.get(configured.internal_jwt_header, "")
            )
        except InternalAuthenticationError as exc:
            raise HTTPException(401, "valid internal authentication is required") from exc
        if "chat" not in verified.identity.scopes:
            raise HTTPException(403, "chat permission required")
        trace = request.headers.get("X-Trace-Id", str(uuid4()))
        if len(trace) > 128:
            raise HTTPException(400, "trace exceeds safe size")
        return RunContext(
            verified.identity,
            request.headers[configured.internal_jwt_header],
            trace,
            token_expires_at=verified.expires_at,
        )

    async def payload(request: Request) -> ConversationGenerationRequest:
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 262_144:
                raise HTTPException(413, "conversation input exceeds safe size")
            data.extend(chunk)
        try:
            parsed = ConversationGenerationRequest.model_validate_json(data)
            generator.messages(parsed)
            return parsed
        except (ValidationError, ValueError, RuntimeError) as exc:
            raise HTTPException(400, "invalid conversation input") from exc

    async def acquire() -> None:
        try:
            await asyncio.wait_for(slots.acquire(), timeout=0.1)
        except TimeoutError as exc:
            raise HTTPException(
                429, "conversation capacity exhausted", headers={"Retry-After": "1"}
            ) from exc

    Context = Annotated[RunContext, Depends(authenticate)]

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "UP"}

    @app.post("/internal/conversation/generate", response_model=ConversationGenerationReply)
    async def generate(request: Request, context: Context) -> ConversationGenerationReply:
        parsed = await payload(request)
        await acquire()
        try:
            return ConversationGenerationReply(reply=await generator.generate(parsed, context))
        except Exception as exc:
            raise HTTPException(503, "conversation generation failed") from exc
        finally:
            slots.release()

    @app.post("/internal/conversation/stream")
    async def stream(request: Request, context: Context) -> StreamingResponse:
        parsed = await payload(request)
        await acquire()

        async def events() -> AsyncGenerator[bytes, None]:
            sequence = 0
            upstream = generator.stream(parsed, context)
            try:
                async for text in upstream:
                    event = {"sequence": sequence, "type": "token", "data": text}
                    yield ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
                    sequence += 1
                yield (
                    "data: "
                    + json.dumps({"sequence": sequence, "type": "done", "data": ""})
                    + "\n\n"
                ).encode()
            except asyncio.CancelledError:
                raise
            except Exception:
                event = {
                    "sequence": sequence,
                    "type": "error",
                    "data": "CONVERSATION_STREAM_FAILED",
                }
                yield ("data: " + json.dumps(event) + "\n\n").encode()
            finally:
                await upstream.aclose()

        return _LeasedStream(events(), slots)

    return app
