"""Deterministic localhost-only OpenAI-compatible model and webhook receiver."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response

app = FastAPI(title="Phase 3 QA local stub")
model_calls: list[dict[str, Any]] = []
webhook_calls: dict[str, list[dict[str, Any]]] = defaultdict(list)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(item.get("text", item.get("content", ""))) if isinstance(item, dict) else str(item)
            for item in value
        )
    return str(value)


def _response_content(payload: dict[str, Any]) -> str:
    messages = payload.get("messages") or []
    joined = "\n".join(
        _text(message.get("content", "")) for message in messages if isinstance(message, dict)
    )
    if "Score three independent dimensions" in joined:
        return '{"correctness":1.0,"completeness":1.0,"clarity":1.0,"mainIssue":"n/a"}'
    if (
        '"tasks" array' in joined
        or '"tasks" 数组' in joined
        or "Produce the revised DAG plan" in joined
    ):
        return (
            '{"tasks":[{"id":"t1","description":'
            '"Return a deterministic QA answer without side effects",'
            '"dependsOn":[]}]}'
        )
    return "QA_OK"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "UP"}


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages") or []
    joined = "\n".join(
        _text(message.get("content", "")) for message in messages if isinstance(message, dict)
    )
    if "QA_SLOW" in joined:
        await asyncio.sleep(20)
    content = _response_content(payload)
    model_calls.append(
        {
            "at": time.time(),
            "model": payload.get("model"),
            "structured": payload.get("response_format") is not None,
            "slow": "QA_SLOW" in joined,
        }
    )
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model", "chat-default"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_tokens": 15,
        },
    }


@app.post("/webhooks/{mode}")
async def webhook(mode: str, request: Request) -> Response:
    body = await request.json()
    webhook_calls[mode].append(
        {
            "headers": {
                "content-type": request.headers.get("content-type"),
                "x-async-task-id": request.headers.get("x-async-task-id"),
                "x-async-task-kind": request.headers.get("x-async-task-kind"),
                "x-tenant-id": request.headers.get("x-tenant-id"),
            },
            "body": body,
        }
    )
    attempt = len(webhook_calls[mode])
    if mode == "retry2" and attempt <= 2:
        return Response(status_code=503)
    if mode == "dead":
        return Response(status_code=503)
    return Response(status_code=204)


@app.get("/state")
async def state() -> dict[str, Any]:
    return {"modelCalls": model_calls, "webhookCalls": webhook_calls}


@app.post("/reset")
async def reset() -> dict[str, bool]:
    model_calls.clear()
    webhook_calls.clear()
    return {"reset": True}
