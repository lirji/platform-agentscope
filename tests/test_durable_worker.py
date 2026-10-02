import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import jwt
import pytest
from pydantic import SecretStr, ValidationError

from agentscope_platform.api.app import Container, create_app
from agentscope_platform.application.async_task import AsyncTaskManager, AsyncTaskRejectedError
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import AgentExecution, RunContext, TenantIdentity
from agentscope_platform.domain.async_task import ReadOnlyTaskClaimReply
from agentscope_platform.infrastructure.async_worker import ReadOnlyTaskWorker
from agentscope_platform.infrastructure.http.async_task_client import HttpAsyncTaskClient
from test_async_task_manager import FakeAsyncTaskGateway, wait_terminal

INTERNAL = "test-durable-internal-secret-with-32-characters"
WORKER = "test-durable-worker-secret-with-32-characters"


def settings(role: str, **extra: Any) -> Settings:
    return Settings(
        _env_file=None,
        async_task_enabled=True,
        async_task_role=role,
        async_task_worker_id="agentscope-platform",
        async_task_worker_jwt_secret=SecretStr(WORKER),
        internal_jwt_secret=SecretStr(INTERNAL),
        async_task_drain_timeout_seconds=0.1,
        **extra,
    )


def identity_token(tenant: str = "acme") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "langchain4j-platform",
            "aud": "platform-internal",
            "sub": tenant,
            "uid": "alice",
            "dept": "dept-a",
            "scopes": ["agent"],
            "token_use": "internal_access",
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(seconds=300),
        },
        INTERNAL,
        algorithm="HS256",
        headers={"kid": "platform-internal-v1", "typ": "JWT"},
    )


class Runner:
    def __init__(self) -> None:
        self.calls: list[RunContext] = []

    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        self.calls.append(context)
        return AgentExecution(steps=(), final_answer=goal, stop_reason="FINISH", depth=1)


class DurableClient(HttpAsyncTaskClient):
    def __init__(self, configured: Settings, central: FakeAsyncTaskGateway) -> None:
        super().__init__(configured)
        self.central = central
        self.seen_workers: list[str] = []

    async def claim(self, worker_id: str) -> ReadOnlyTaskClaimReply | None:
        self.seen_workers.append(worker_id)
        for task in self.central.tasks.values():
            if task.status.terminal or (
                task.lease_expires_at and task.lease_expires_at > datetime.now(UTC)
            ):
                continue
            ctx = RunContext(TenantIdentity(task.tenant_id, task.user_id), None, "trace")
            leased = await self.central.lease(task.task_id, worker_id, 60, ctx)
            return ReadOnlyTaskClaimReply(
                task=leased, internalToken=identity_token(), traceId="persisted-trace"
            )
        return None

    async def update_status(self, *args: Any, **kwargs: Any) -> Any:
        return await self.central.update_status(*args, **kwargs)

    async def lease(self, *args: Any, **kwargs: Any) -> Any:
        return await self.central.lease(*args, **kwargs)


async def test_api_process_does_not_execute_and_new_worker_rehydrates_owner_input() -> None:
    central = FakeAsyncTaskGateway()
    runner = Runner()
    api = create_app(settings("api"), runner=runner, async_task_gateway=central)
    api_container = cast(Container, api.state.container)
    context = RunContext(
        TenantIdentity("acme", "alice", frozenset({"agent"})), "old-expired-token", "trace"
    )
    manager = api_container.async_task_manager

    async def closure(_: object) -> None:
        raise AssertionError("request closure must never run in api role")

    created = await manager.submit(
        kind="agent.run",
        input_data={"goal": "read order"},
        webhook_url=None,
        context=context,
        execute=closure,
    )
    assert central.tasks[created.task_id].lease_epoch == 0
    assert manager.free_slots == manager.settings.async_task_max_concurrent
    assert "old-expired-token" not in json.dumps(central.tasks[created.task_id].input)
    # API退出后构建全新的container/manager, 不复用任何闭包或句柄.
    await manager.shutdown()
    configured = settings("worker")
    client = DurableClient(configured, central)
    worker_app = create_app(configured, runner=runner, async_task_gateway=client)
    worker_container = cast(Container, worker_app.state.container)
    worker = ReadOnlyTaskWorker(worker_container, client)
    assert await worker.poll_once()
    result = await wait_terminal(central, created.task_id)
    assert result.result["finalAnswer"] == "read order"
    assert runner.calls[0].identity == TenantIdentity(
        "acme", "alice", frozenset({"agent"}), "dept-a"
    )
    assert runner.calls[0].confirmation_grants == ()
    assert runner.calls[0].trace_id == "persisted-trace"
    await worker_container.async_task_manager.shutdown()


async def test_runtime_version_mismatch_is_terminal_without_model_execution() -> None:
    central = FakeAsyncTaskGateway()
    ctx = RunContext(TenantIdentity("acme", "alice"), None, "trace")
    await central.create(
        task_id="old-version",
        kind="agent.readonly.run.v1",
        input_data={"goal": "test", "_executionVersions": {"wrong": "version"}},
        webhook_url=None,
        context=ctx,
    )
    configured = settings("worker")
    runner = Runner()
    client = DurableClient(configured, central)
    app = create_app(configured, runner=runner, async_task_gateway=client)
    worker = ReadOnlyTaskWorker(cast(Container, app.state.container), client)
    assert await worker.poll_once()
    assert runner.calls == []
    assert central.tasks["old-version"].error == "ASYNC_TASK_EXECUTION_VERSION_MISMATCH"
    await client.close()


@pytest.mark.parametrize(
    "flag",
    [
        "agent_refund_start_enabled",
        "agent_mcp_enabled",
        "agent_browser_enabled",
        "agent_code_exec_enabled",
    ],
)
def test_durable_role_rejects_write_or_external_tools(flag: str) -> None:
    with pytest.raises(ValidationError, match="external/write tools disabled"):
        settings("worker", **{flag: True})


async def test_adopt_does_not_exceed_local_running_capacity() -> None:
    central = FakeAsyncTaskGateway()
    configured = settings("worker", async_task_max_concurrent=1)
    manager = AsyncTaskManager(central, configured)
    ctx = RunContext(TenantIdentity("acme", "alice"), None, "trace")
    event = asyncio.Event()

    async def execute(_: object) -> None:
        await event.wait()

    for task_id in ["one", "two"]:
        await central.create(
            task_id=task_id,
            kind="agent.readonly.run.v1",
            input_data={},
            webhook_url=None,
            context=ctx,
        )
        task = await central.lease(task_id, manager.worker_id, 60, ctx)
        if task_id == "one":
            await manager.adopt(task, ctx, execute)
        else:
            with pytest.raises(AsyncTaskRejectedError, match="capacity"):
                await manager.adopt(task, ctx, execute)
    event.set()
    await wait_terminal(central, "one")
    await manager.shutdown()


async def test_claim_http_uses_separate_task_bound_dispatch_token() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    configured = settings("worker")
    async with httpx.AsyncClient(
        base_url="http://central.test", transport=httpx.MockTransport(handle)
    ) as raw:
        client = HttpAsyncTaskClient(configured, raw)
        assert await client.claim("agentscope-platform.one") is None
    assert seen[0].url.path == "/async/tasks/dispatch/claim"
    assert "X-Internal-Token" not in seen[0].headers
    claims = jwt.decode(
        seen[0].headers["X-Async-Worker-Token"],
        WORKER,
        algorithms=["HS256"],
        audience="async-task-worker",
    )
    assert claims["act"] == "dispatch" and claims["task_id"] == "readonly-dispatch"
    assert claims["tenant"] == claims["actor_uid"] == "_dispatch"


def test_runtime_config_digest_changes_with_planner_behavior_and_ignores_roles() -> None:
    from agentscope_platform.application.async_task import runtime_config_digest

    assert runtime_config_digest(settings("api")) == runtime_config_digest(settings("worker"))
    assert runtime_config_digest(settings("worker", agent_planner_max_tokens=1000)) != (
        runtime_config_digest(settings("worker", agent_planner_max_tokens=2000))
    )


def test_production_durable_role_requires_immutable_revision() -> None:
    with pytest.raises(ValidationError, match="ASYNC_TASK_RUNTIME_REVISION"):
        settings("worker", app_env="production", internal_auth_required=True)


def test_worker_health_requires_recent_successful_poll(tmp_path: Any, monkeypatch: Any) -> None:
    import time

    import agentscope_platform.worker as entry

    path = tmp_path / "health"
    monkeypatch.setattr(entry, "HEALTH_FILE", path)
    assert not entry.healthy()
    path.write_text(str(time.time()))
    assert entry.healthy()
    path.write_text(str(time.time() - 91))
    assert not entry.healthy()
