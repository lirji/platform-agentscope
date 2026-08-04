import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from agentscope_platform.application.ports import AsyncTaskGateway
from agentscope_platform.core.config import Settings
from agentscope_platform.core.deadline import outbound_deadline_epoch_ms
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.async_task import (
    AsyncTaskEventAppend,
    AsyncTaskStatus,
    CentralAsyncTask,
    CentralAsyncTaskEvent,
)
from agentscope_platform.infrastructure.http.resilience import (
    DependencyCallRejected,
    DependencyGuardRegistry,
    httpx_limits,
)
from agentscope_platform.infrastructure.security.async_task_worker_jwt import (
    AsyncTaskWorkerAction,
    AsyncTaskWorkerTokenIssuer,
)


class AsyncTaskGatewayError(RuntimeError):
    """A sanitized central async-task failure."""

    def __init__(self, message: str, *, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class HttpAsyncTaskClient(AsyncTaskGateway):
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        guards: DependencyGuardRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._worker_tokens = AsyncTaskWorkerTokenIssuer(settings)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.async_task_base_url.rstrip("/"),
            timeout=httpx.Timeout(
                settings.async_task_request_timeout_seconds,
                connect=settings.async_task_connect_timeout_seconds,
            ),
            limits=httpx_limits(settings),
        )
        self._guard = (guards or DependencyGuardRegistry(settings)).for_dependency(
            "async-task-service"
        )

    async def create(
        self,
        *,
        task_id: str,
        kind: str,
        input_data: dict[str, Any],
        webhook_url: str | None,
        context: RunContext,
    ) -> CentralAsyncTask:
        body = {
            "taskId": task_id,
            "kind": kind,
            "input": input_data,
            "webhookUrl": webhook_url,
        }
        try:
            response = await self._request("POST", "/async/tasks", context, json=body)
        except AsyncTaskGatewayError:
            existing = await self.get(task_id, context)
            if existing is not None:
                return existing
            raise
        return self._task(response)

    async def get(self, task_id: str, context: RunContext) -> CentralAsyncTask | None:
        response = await self._request(
            "GET",
            f"/async/tasks/{task_id}",
            context,
            allow_not_found=True,
        )
        return None if response is None else self._task(response)

    async def list(self, context: RunContext) -> list[CentralAsyncTask]:
        response = await self._request("GET", "/async/tasks", context)
        assert response is not None
        try:
            payload = response.json()
            return [CentralAsyncTask.model_validate(item) for item in payload]
        except (ValueError, TypeError) as exc:
            raise AsyncTaskGatewayError("async task service returned invalid JSON") from exc

    async def lease(
        self,
        task_id: str,
        worker_id: str,
        lease_seconds: float,
        context: RunContext,
        *,
        lease_epoch: int | None = None,
    ) -> CentralAsyncTask:
        body: dict[str, Any] = {
            "workerId": worker_id,
            "leaseSeconds": int(lease_seconds),
        }
        if lease_epoch is not None:
            body["leaseEpoch"] = lease_epoch
        try:
            response = await self._request(
                "POST",
                f"/async/tasks/{task_id}/lease",
                context,
                worker_authorization=(worker_id, "lease", task_id),
                json=body,
            )
        except AsyncTaskGatewayError:
            existing = await self.get(task_id, context)
            if (
                existing is not None
                and existing.lease_owner_id == worker_id
                and existing.lease_epoch > 0
                and (lease_epoch is None or existing.lease_epoch == lease_epoch)
            ):
                return existing
            raise
        return self._task(response)

    async def update_status(
        self,
        task_id: str,
        status: AsyncTaskStatus,
        *,
        result: Any | None,
        error: str | None,
        worker_id: str,
        lease_epoch: int,
        context: RunContext,
    ) -> CentralAsyncTask:
        response = await self._request(
            "PATCH",
            f"/async/tasks/{task_id}/status",
            context,
            worker_authorization=(worker_id, "status", task_id),
            json={
                "status": status.value,
                "result": result,
                "error": error,
                "workerId": worker_id,
                "leaseEpoch": lease_epoch,
            },
        )
        return self._task(response)

    async def cancel(self, task_id: str, context: RunContext) -> bool:
        try:
            response = await self._request(
                "DELETE",
                f"/async/tasks/{task_id}",
                context,
                allow_not_found=True,
            )
        except AsyncTaskGatewayError:
            existing = await self.get(task_id, context)
            return existing is not None and existing.status is AsyncTaskStatus.CANCELLED
        if response is None:
            return False
        try:
            return bool(response.json().get("cancelled"))
        except (ValueError, AttributeError) as exc:
            raise AsyncTaskGatewayError("async task service returned invalid JSON") from exc

    async def append_event(
        self,
        task_id: str,
        event: AsyncTaskEventAppend,
        context: RunContext,
    ) -> CentralAsyncTaskEvent:
        response = await self._request(
            "POST",
            f"/async/tasks/{task_id}/events",
            context,
            worker_authorization=(event.worker_id, "event", task_id),
            json=event.model_dump(by_alias=True, mode="json"),
        )
        assert response is not None
        try:
            return CentralAsyncTaskEvent.model_validate(response.json())
        except ValueError as exc:
            raise AsyncTaskGatewayError("async task service returned invalid event JSON") from exc

    async def stream(
        self,
        task_id: str,
        context: RunContext,
        *,
        last_event_id: str | None,
    ) -> AsyncIterator[bytes]:
        headers = self._headers(
            context,
            timeout_seconds=self._settings.async_task_max_runtime_seconds,
        )
        params = {"lastEventId": last_event_id} if last_event_id else None
        try:
            async with self._guard.lease(
                timeout_seconds=self._settings.async_task_max_runtime_seconds
            ) as lease:
                async with self._client.stream(
                    "GET",
                    f"/async/tasks/{task_id}/stream",
                    headers=headers,
                    params=params,
                    timeout=httpx.Timeout(
                        connect=self._settings.async_task_connect_timeout_seconds,
                        read=self._settings.async_task_stream_idle_timeout_seconds,
                        write=self._settings.async_task_request_timeout_seconds,
                        pool=self._settings.async_task_connect_timeout_seconds,
                    ),
                ) as response:
                    if response.status_code >= 400:
                        if response.status_code >= 500:
                            lease.mark_failed()
                        raise AsyncTaskGatewayError(
                            "async task stream is unavailable",
                            status_code=response.status_code,
                        )
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except DependencyCallRejected as exc:
            raise AsyncTaskGatewayError(f"async task stream is unavailable ({exc.reason})") from exc
        except (httpx.HTTPError, TimeoutError) as exc:
            raise AsyncTaskGatewayError("async task stream is unavailable") from exc

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        context: RunContext,
        *,
        allow_not_found: bool = False,
        worker_authorization: tuple[str, AsyncTaskWorkerAction, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response | None:
        headers = (
            self._worker_headers(context, *worker_authorization)
            if worker_authorization is not None
            else self._headers(context)
        )
        try:
            response = await self._guard.execute(
                lambda: self._client.request(
                    method,
                    path,
                    headers=headers,
                    **kwargs,
                ),
                timeout_seconds=self._settings.async_task_request_timeout_seconds,
                response_failed=lambda item: item.status_code >= 500,
            )
        except DependencyCallRejected as exc:
            raise AsyncTaskGatewayError(
                f"async task service is unavailable ({exc.reason})"
            ) from exc
        except httpx.HTTPError as exc:
            raise AsyncTaskGatewayError("async task service is unavailable") from exc
        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code >= 400:
            mapped = response.status_code if response.status_code in {400, 404, 409, 413} else 503
            raise AsyncTaskGatewayError("async task request failed", status_code=mapped)
        return response

    def _headers(
        self,
        context: RunContext,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, str]:
        timeout = timeout_seconds or self._settings.async_task_request_timeout_seconds
        headers = {
            "X-Trace-Id": context.trace_id,
            "X-Request-Deadline-Ms": str(outbound_deadline_epoch_ms(timeout)),
        }
        if context.internal_token:
            headers[self._settings.internal_jwt_header] = context.internal_token
        return headers

    def _worker_headers(
        self,
        context: RunContext,
        worker_id: str,
        action: AsyncTaskWorkerAction,
        task_id: str,
    ) -> dict[str, str]:
        token = self._worker_tokens.issue(
            context,
            worker_id=worker_id,
            action=action,
            task_id=task_id,
        )
        return {
            "X-Trace-Id": context.trace_id,
            "X-Request-Deadline-Ms": str(
                outbound_deadline_epoch_ms(self._settings.async_task_request_timeout_seconds)
            ),
            self._settings.async_task_worker_jwt_header: token,
        }

    @staticmethod
    def _task(response: httpx.Response | None) -> CentralAsyncTask:
        if response is None:
            raise AsyncTaskGatewayError("async task does not exist", status_code=404)
        try:
            return CentralAsyncTask.model_validate(response.json())
        except (json.JSONDecodeError, ValueError) as exc:
            raise AsyncTaskGatewayError("async task service returned invalid JSON") from exc
