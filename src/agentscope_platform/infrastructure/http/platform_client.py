from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.infrastructure.http.models import (
    AnalyticsSqlReply,
    AnalyticsTableSchemaReply,
    AnalyticsTablesReply,
    KnowledgeQueryReply,
    OrderView,
    WorkflowInstanceReply,
    WorkflowTasksReply,
    WorkflowTaskView,
)


class PlatformServiceError(RuntimeError):
    def __init__(self, service: str, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.service = service
        self.status_code = status_code


class PlatformClient:
    """Tenant-aware client for tools backed by retained Java services."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
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
        min_score: float,
        category: str | None,
        context: RunContext,
    ) -> KnowledgeQueryReply:
        return await self._post(
            "knowledge-service",
            f"{self._settings.knowledge_base_url.rstrip('/')}/rag/query",
            {
                "query": query,
                "topK": top_k,
                "minScore": min_score,
                "category": category,
            },
            context,
            KnowledgeQueryReply,
        )

    async def get_order(self, order_no: str, context: RunContext) -> OrderView | None:
        encoded = quote(order_no, safe="")
        try:
            return await self._get(
                "order-service",
                f"{self._settings.order_base_url.rstrip('/')}/orders/{encoded}",
                context,
                OrderView,
            )
        except PlatformServiceError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def list_analytics_tables(self, context: RunContext) -> AnalyticsTablesReply:
        return await self._get(
            "analytics-service",
            f"{self._settings.analytics_base_url.rstrip('/')}/analytics/schema/tables",
            context,
            AnalyticsTablesReply,
        )

    async def describe_analytics_table(
        self,
        table: str,
        context: RunContext,
    ) -> AnalyticsTableSchemaReply | None:
        encoded = quote(table, safe="")
        try:
            return await self._get(
                "analytics-service",
                f"{self._settings.analytics_base_url.rstrip('/')}/analytics/schema/tables/{encoded}",
                context,
                AnalyticsTableSchemaReply,
            )
        except PlatformServiceError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def query_analytics(
        self,
        question: str,
        context: RunContext,
    ) -> AnalyticsSqlReply:
        return await self._post(
            "analytics-service",
            f"{self._settings.analytics_base_url.rstrip('/')}/analytics/sql",
            {"question": question},
            context,
            AnalyticsSqlReply,
        )

    async def get_workflow_instance(
        self,
        instance_id: str,
        context: RunContext,
    ) -> WorkflowInstanceReply | None:
        encoded = quote(instance_id, safe="")
        try:
            return await self._get(
                "workflow-service",
                f"{self._settings.workflow_base_url.rstrip('/')}/workflow/instances/{encoded}",
                context,
                WorkflowInstanceReply,
            )
        except PlatformServiceError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def list_workflow_tasks(
        self,
        context: RunContext,
    ) -> list[WorkflowTaskView]:
        reply = await self._get(
            "workflow-service",
            f"{self._settings.workflow_base_url.rstrip('/')}/workflow/tasks",
            context,
            WorkflowTasksReply,
        )
        return reply.root

    async def _post[ResponseT: BaseModel](
        self,
        service: str,
        url: str,
        payload: dict[str, Any],
        context: RunContext,
        response_type: type[ResponseT],
    ) -> ResponseT:
        return await self._request(
            service,
            "POST",
            url,
            context,
            response_type,
            payload,
        )

    async def _get[ResponseT: BaseModel](
        self,
        service: str,
        url: str,
        context: RunContext,
        response_type: type[ResponseT],
    ) -> ResponseT:
        return await self._request(
            service,
            "GET",
            url,
            context,
            response_type,
        )

    async def _request[ResponseT: BaseModel](
        self,
        service: str,
        method: str,
        url: str,
        context: RunContext,
        response_type: type[ResponseT],
        payload: dict[str, Any] | None = None,
    ) -> ResponseT:
        headers = {"X-Trace-Id": context.trace_id}
        if context.internal_token:
            headers[self._settings.internal_jwt_header] = context.internal_token

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    json=payload,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise PlatformServiceError(service, None, f"{service} unavailable") from exc

        if response.is_error:
            raise PlatformServiceError(
                service,
                response.status_code,
                f"{service} returned HTTP {response.status_code}",
            )
        try:
            return response_type.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise PlatformServiceError(
                service,
                response.status_code,
                f"invalid {service} response",
            ) from exc
