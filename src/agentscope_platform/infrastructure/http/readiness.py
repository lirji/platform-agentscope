import asyncio
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from agentscope_platform.application.confirmation import ToolConfirmationService
from agentscope_platform.application.ports import DependencyReadiness
from agentscope_platform.core.config import Settings


@dataclass(frozen=True, slots=True)
class _HttpTarget:
    name: str
    url: str
    required: bool


class HttpDependencyReadinessProbe:
    """Bounded, sanitized dependency probes for admission readiness."""

    def __init__(
        self,
        settings: Settings,
        confirmation_service: ToolConfirmationService,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._confirmation_service = confirmation_service
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.readiness_probe_timeout_seconds),
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=16,
                max_keepalive_connections=8,
                keepalive_expiry=settings.http_keepalive_expiry_seconds,
            ),
        )

    async def check(self) -> tuple[DependencyReadiness, ...]:
        static: list[DependencyReadiness] = []
        targets: list[_HttpTarget] = []
        if self._settings.agent_enabled:
            targets.append(
                _HttpTarget(
                    "modelGateway",
                    _origin_url(self._settings.gateway_base_url, "/health/liveliness"),
                    True,
                )
            )
        else:
            static.append(DependencyReadiness("modelGateway", True, "DISABLED"))

        if self._settings.async_task_enabled:
            targets.append(
                _HttpTarget(
                    "asyncTask",
                    _base_url(self._settings.async_task_base_url, "/actuator/health/readiness"),
                    True,
                )
            )
        else:
            static.append(DependencyReadiness("asyncTask", False, "DISABLED"))

        if self._settings.agent_mcp_enabled:
            targets.append(_HttpTarget("mcpProvider", self._settings.agent_mcp_url, True))
        else:
            static.append(DependencyReadiness("mcpProvider", False, "DISABLED"))
        if self._settings.agent_browser_enabled:
            targets.append(
                _HttpTarget(
                    "browserSandbox",
                    _base_url(self._settings.agent_browser_sandbox_url, "/health"),
                    True,
                )
            )
        else:
            static.append(DependencyReadiness("browserSandbox", False, "DISABLED"))
        if self._settings.agent_code_exec_enabled:
            targets.append(
                _HttpTarget(
                    "codeSandbox",
                    _base_url(self._settings.agent_code_sandbox_url, "/health"),
                    True,
                )
            )
        else:
            static.append(DependencyReadiness("codeSandbox", False, "DISABLED"))

        targets.extend(
            (
                _HttpTarget(
                    "knowledgeService",
                    _base_url(self._settings.knowledge_base_url, "/actuator/health/readiness"),
                    False,
                ),
                _HttpTarget(
                    "analyticsService",
                    _base_url(self._settings.analytics_base_url, "/actuator/health/readiness"),
                    False,
                ),
                _HttpTarget(
                    "workflowService",
                    _base_url(self._settings.workflow_base_url, "/actuator/health/readiness"),
                    False,
                ),
                _HttpTarget(
                    "orderService",
                    _base_url(self._settings.order_base_url, "/actuator/health/readiness"),
                    False,
                ),
            )
        )
        replay_required = (
            self._settings.agent_write_tools_enabled
            and self._settings.agent_confirmation_replay_store == "redis"
        )
        async with asyncio.TaskGroup() as group:
            probe_tasks = tuple(group.create_task(self._probe(target)) for target in targets)
            replay_task = (
                group.create_task(
                    self._confirmation_service.ready(self._settings.readiness_probe_timeout_seconds)
                )
                if replay_required
                else None
            )
        probed = tuple(task.result() for task in probe_tasks)

        if replay_required:
            assert replay_task is not None
            replay_ready = await replay_task
            static.append(
                DependencyReadiness(
                    "confirmationReplayStore",
                    True,
                    "UP" if replay_ready else "DOWN",
                )
            )
        else:
            static.append(DependencyReadiness("confirmationReplayStore", False, "DISABLED"))
        return tuple((*static, *probed))

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _probe(self, target: _HttpTarget) -> DependencyReadiness:
        try:
            response = await self._client.get(
                target.url,
                timeout=self._settings.readiness_probe_timeout_seconds,
            )
            healthy = (
                200 <= response.status_code < 300
                or response.status_code in {401, 403}
                or (target.name == "mcpProvider" and response.status_code == 405)
            )
        except (httpx.HTTPError, TimeoutError):
            healthy = False
        return DependencyReadiness(
            target.name,
            target.required,
            "UP" if healthy else "DOWN",
        )


def _base_url(value: str, path: str) -> str:
    return value.rstrip("/") + path


def _origin_url(value: str, path: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
