"""Local fault proxy that loses exactly one successful create response."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI(title="Phase 3 create-response-loss proxy")
dropped = False


@app.get("/_fault/state")
async def state() -> dict[str, Any]:
    return {"droppedCreateResponse": dropped}


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PATCH", "DELETE", "PUT", "OPTIONS"],
)
async def proxy(path: str, request: Request) -> Response:
    global dropped
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length"}
    }
    async with httpx.AsyncClient() as client:
        upstream = await client.request(
            request.method,
            f"http://127.0.0.1:18086/{path}",
            params=request.query_params,
            headers=headers,
            content=body,
            timeout=None,
        )
    if request.method == "POST" and path == "async/tasks" and not dropped:
        dropped = True
        return Response(
            content='{"error":"synthetic response loss after upstream commit"}',
            status_code=503,
            media_type="application/json",
        )
    response_headers = {}
    if content_type := upstream.headers.get("content-type"):
        response_headers["content-type"] = content_type
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )
