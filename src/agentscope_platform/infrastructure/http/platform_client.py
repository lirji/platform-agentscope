from typing import Any

import httpx

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext


class PlatformClient:
    """Tenant-aware client for tools backed by retained Java services."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._timeout = httpx.Timeout(
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
            write=settings.http_read_timeout_seconds,
            pool=settings.http_connect_timeout_seconds,
        )

    async def query_knowledge(
        self,
        query: str,
        top_k: int,
        context: RunContext,
    ) -> dict[str, Any]:
        return await self._post(
            f"{self._settings.knowledge_base_url.rstrip('/')}/rag/query",
            {"query": query, "topK": top_k},
            context,
        )

    async def _post(
        self,
        url: str,
        payload: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        headers = {"X-Trace-Id": context.trace_id}
        if context.internal_token:
            headers[self._settings.internal_jwt_header] = context.internal_token

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            value: dict[str, Any] = response.json()
            return value
