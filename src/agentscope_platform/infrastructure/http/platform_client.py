from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from agentscope_platform.core.config import Settings
from agentscope_platform.core.deadline import outbound_deadline_epoch_ms
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.infrastructure.http.models import (
    AnalyticsSqlPlanReply,
    AnalyticsSqlReply,
    AnalyticsTableSchemaReply,
    AnalyticsTablesReply,
    KnowledgeQueryReply,
    OrderView,
    WorkflowInstanceReply,
    WorkflowStartReply,
    WorkflowTasksReply,
    WorkflowTaskView,
)
from agentscope_platform.infrastructure.http.resilience import (
    DependencyCallRejected,
    DependencyGuardRegistry,
    httpx_limits,
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
        *,
        client: httpx.AsyncClient | None = None,
        guards: DependencyGuardRegistry | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("client and transport are mutually exclusive")
        self._settings = settings
        self._timeout = httpx.Timeout(
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
            write=settings.http_read_timeout_seconds,
            pool=settings.http_connect_timeout_seconds,
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=self._timeout,
            transport=transport,
            limits=httpx_limits(settings),
        )
        self._guards = guards or DependencyGuardRegistry(settings)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

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

    async def execute_analytics_plan(
        self,
        question: str,
        sql: str,
        context: RunContext,
    ) -> AnalyticsSqlPlanReply:
        return await self._post(
            "analytics-service",
            f"{self._settings.analytics_base_url.rstrip('/')}/analytics/sql/plans/execute",
            {"question": question, "sql": sql},
            context,
            AnalyticsSqlPlanReply,
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

    async def start_refund(
        self,
        *,
        message: str,
        chat_id: str,
        dedupe_id: str,
        context: RunContext,
    ) -> WorkflowStartReply:
        return await self._post(
            "workflow-service",
            f"{self._settings.workflow_base_url.rstrip('/')}/workflow/refund/start",
            {
                "message": message,
                "chatId": chat_id,
                "dedupeId": dedupe_id,
            },
            context,
            WorkflowStartReply,
        )

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
        headers = {
            "X-Trace-Id": context.trace_id,
            "X-Request-Deadline-Ms": str(
                outbound_deadline_epoch_ms(self._settings.http_read_timeout_seconds)
            ),
        }
        if context.internal_token:
            headers[self._settings.internal_jwt_header] = context.internal_token

        try:
            response = await self._guards.for_dependency(service).execute(
                lambda: self._client.request(
                    method,
                    url,
                    json=payload,
                    headers=headers,
                ),
                timeout_seconds=self._settings.http_read_timeout_seconds,
                response_failed=lambda item: item.status_code >= 500,
            )
        except DependencyCallRejected as exc:
            raise PlatformServiceError(
                service,
                None,
                f"{service} unavailable ({exc.reason})",
            ) from exc
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
