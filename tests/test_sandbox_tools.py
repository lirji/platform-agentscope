from dataclasses import replace

import pytest
from agentscope.message import TextBlock, ToolResultState
from pydantic import SecretStr, ValidationError

from agentscope_platform.application.ports import RemoteSandboxGateway
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import bind_run_context, reset_run_context
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.sandbox import (
    BrowserActionReply,
    BrowserActionRequest,
    CodeExecutionReply,
    CodeExecutionRequest,
    SandboxGatewayError,
    sandbox_operation_id,
    sandbox_session_id,
)
from agentscope_platform.infrastructure.agentscope.governed_tools import GovernedToolset
from agentscope_platform.infrastructure.http.platform_client import PlatformClient
from tool_confirmation_support import CONFIRMATION_SECRET, DOWNSTREAM_SECRET


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        agent_browser_enabled=True,
        agent_browser_sandbox_url="https://browser-sandbox.test",
        agent_browser_allowed_hosts_json='["example.com"]',
        agent_code_exec_enabled=True,
        agent_code_sandbox_url="https://code-sandbox.test",
        agent_confirmation_secret=SecretStr(CONFIRMATION_SECRET),
        agent_downstream_jwt_secret=SecretStr(DOWNSTREAM_SECRET),
    )


def context(*, tenant: str = "acme") -> RunContext:
    return RunContext(
        identity=TenantIdentity(tenant, "alice", frozenset({"agent"})),
        internal_token=f"token-{tenant}",
        trace_id=f"trace-{tenant}",
        idempotency_key="request-42",
    )


def text(result: object) -> str:
    block = result.content[0]
    assert isinstance(block, TextBlock)
    return block.text


class FakeSandboxGateway(RemoteSandboxGateway):
    def __init__(self) -> None:
        self.browser_calls: list[tuple[BrowserActionRequest, RunContext, float]] = []
        self.code_calls: list[tuple[CodeExecutionRequest, RunContext, float]] = []
        self.closed: list[RunContext] = []

    async def browser_action(
        self,
        request: BrowserActionRequest,
        context: RunContext,
        timeout_seconds: float,
    ) -> BrowserActionReply:
        self.browser_calls.append((request, context, timeout_seconds))
        return BrowserActionReply(
            output=f"browser:{request.action}",
            currentUrl="https://example.com/docs",
            artifactId="shot-1" if request.action == "screenshot" else None,
        )

    async def execute_code(
        self,
        request: CodeExecutionRequest,
        context: RunContext,
        timeout_seconds: float,
    ) -> CodeExecutionReply:
        self.code_calls.append((request, context, timeout_seconds))
        return CodeExecutionReply(status="COMPLETED", output="14", truncated=False)

    async def close_browser(self, context: RunContext) -> None:
        self.closed.append(context)


def test_browser_and_code_sandbox_tools_are_default_off() -> None:
    settings = Settings(_env_file=None)
    names = {tool.name for tool in GovernedToolset(settings, PlatformClient(settings)).tools()}

    assert not names & {
        "browser_open",
        "browser_click",
        "browser_click_xy",
        "browser_type",
        "browser_screenshot",
        "browser_see",
        "code_exec",
    }


def test_enabled_remote_sandboxes_require_urls_and_browser_host_allowlist() -> None:
    with pytest.raises(ValidationError, match="AGENT_BROWSER_SANDBOX_URL"):
        Settings(_env_file=None, agent_browser_enabled=True)
    with pytest.raises(ValidationError, match="AGENT_BROWSER_ALLOWED_HOSTS_JSON"):
        Settings(
            _env_file=None,
            agent_browser_enabled=True,
            agent_browser_sandbox_url="https://browser-sandbox.test",
        )
    with pytest.raises(ValidationError, match="AGENT_CODE_SANDBOX_URL"):
        Settings(_env_file=None, agent_code_exec_enabled=True)


def test_sandbox_ids_are_retry_stable_and_tenant_bound() -> None:
    first = context()
    retried = replace(first, trace_id="trace-retry")
    other_tenant = context(tenant="globex")

    assert sandbox_session_id(first) == sandbox_session_id(retried)
    assert sandbox_operation_id(first, "browser_open", 1) == sandbox_operation_id(
        retried, "browser_open", 1
    )
    assert sandbox_session_id(first) != sandbox_session_id(other_tenant)
    assert sandbox_operation_id(first, "code_exec", 1) != sandbox_operation_id(
        other_tenant, "code_exec", 1
    )


def test_remote_sandbox_tools_have_explicit_policy_metadata() -> None:
    settings = configured_settings()
    gateway = FakeSandboxGateway()
    tools = GovernedToolset(
        settings,
        PlatformClient(settings),
        sandbox_gateway=gateway,
    ).tools()
    by_name = {tool.name: tool for tool in tools}

    assert set(by_name) == {
        "browser_open",
        "browser_click",
        "browser_click_xy",
        "browser_type",
        "browser_screenshot",
        "browser_see",
        "code_exec",
    }
    assert by_name["browser_screenshot"].metadata.read_only is True
    assert by_name["browser_see"].metadata.read_only is True
    assert all(not by_name[name].is_concurrency_safe for name in by_name)
    assert by_name["browser_click"].metadata.side_effect.value == "high"
    assert by_name["code_exec"].metadata.requires_confirmation.value == "always"
    assert all(tool.metadata.retry_policy.value == "none" for tool in tools)


async def test_browser_open_is_host_allowlisted_and_uses_opaque_trusted_ids() -> None:
    settings = configured_settings()
    gateway = FakeSandboxGateway()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings),
        sandbox_gateway=gateway,
    )
    run_context = context()
    token = bind_run_context(run_context)
    try:
        denied = await toolset.browser_open("https://evil.example/private")
        allowed = await toolset.browser_open("https://example.com/docs")
    finally:
        reset_run_context(token)

    assert denied.state == ToolResultState.ERROR
    assert "allowlist" in text(denied)
    assert text(allowed) == "browser:open\ncurrentUrl: https://example.com/docs"
    assert len(gateway.browser_calls) == 1
    request, seen_context, timeout = gateway.browser_calls[0]
    assert request.action == "open"
    assert request.arguments == {"url": "https://example.com/docs"}
    assert request.allowed_hosts == ("example.com",)
    assert request.session_id.startswith("run-")
    assert request.operation_id.startswith("op-")
    assert all(value not in request.session_id for value in ("acme", "alice", "trace-acme"))
    assert seen_context == run_context
    assert timeout == settings.agent_browser_timeout_seconds


async def test_browser_write_denies_without_confirmation_and_never_calls_provider() -> None:
    settings = configured_settings()
    gateway = FakeSandboxGateway()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings),
        sandbox_gateway=gateway,
    )
    token = bind_run_context(context())
    try:
        by_name = {tool.name: tool for tool in toolset.tools()}
        result = await by_name["browser_click"].call(link_text="Buy now")
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.ERROR
    assert "explicit confirmation" in text(result)
    assert gateway.browser_calls == []


async def test_browser_actions_keep_session_and_unique_operation_ids() -> None:
    settings = configured_settings()
    gateway = FakeSandboxGateway()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings),
        sandbox_gateway=gateway,
    )
    token = bind_run_context(context())
    try:
        await toolset.browser_click("Docs")
        await toolset.browser_type("input[name=q]", "agentscope")
        await toolset.browser_screenshot()
        await toolset.browser_see("Describe the chart")
    finally:
        reset_run_context(token)

    requests = [item[0] for item in gateway.browser_calls]
    assert [request.action for request in requests] == ["click", "type", "screenshot", "see"]
    assert len({request.session_id for request in requests}) == 1
    assert len({request.operation_id for request in requests}) == 4


async def test_code_exec_is_remote_bounded_and_has_no_local_fallback() -> None:
    settings = configured_settings()
    gateway = FakeSandboxGateway()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings),
        sandbox_gateway=gateway,
    )
    run_context = context()
    token = bind_run_context(run_context)
    try:
        result = await toolset.code_exec("2 + 3 * 4")
        oversized = await toolset.code_exec("x" * (settings.agent_code_max_source_chars + 1))
    finally:
        reset_run_context(token)

    assert text(result) == "14"
    assert oversized.state == ToolResultState.ERROR
    assert len(gateway.code_calls) == 1
    request, seen_context, timeout = gateway.code_calls[0]
    assert request.language == "java"
    assert request.source == "2 + 3 * 4"
    assert request.timeout_ms == int(settings.agent_code_timeout_seconds * 1000)
    assert request.max_output_chars == settings.agent_code_max_output_chars
    assert request.network_enabled is False
    assert request.workspace == "ephemeral"
    assert request.max_memory_mb == 64
    assert request.max_processes == 4
    assert seen_context == run_context
    assert timeout == settings.agent_code_timeout_seconds


async def test_code_timeout_and_error_are_stable() -> None:
    class TimeoutGateway(FakeSandboxGateway):
        async def execute_code(
            self,
            request: CodeExecutionRequest,
            context: RunContext,
            timeout_seconds: float,
        ) -> CodeExecutionReply:
            del request, context, timeout_seconds
            return CodeExecutionReply(status="TIMED_OUT", output="partial", truncated=True)

    settings = configured_settings()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings),
        sandbox_gateway=TimeoutGateway(),
    )
    token = bind_run_context(context())
    try:
        result = await toolset.code_exec("while (true) {}")
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.ERROR
    assert text(result) == "Code execution timed out.\npartial\n[truncated]"


async def test_sandbox_failures_are_sanitized_and_not_retried() -> None:
    class FailingGateway(FakeSandboxGateway):
        async def browser_action(
            self,
            request: BrowserActionRequest,
            context: RunContext,
            timeout_seconds: float,
        ) -> BrowserActionReply:
            self.browser_calls.append((request, context, timeout_seconds))
            raise SandboxGatewayError("browser sandbox returned HTTP 503")

        async def execute_code(
            self,
            request: CodeExecutionRequest,
            context: RunContext,
            timeout_seconds: float,
        ) -> CodeExecutionReply:
            self.code_calls.append((request, context, timeout_seconds))
            raise SandboxGatewayError("code sandbox returned HTTP 503")

    settings = configured_settings()
    gateway = FailingGateway()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings),
        sandbox_gateway=gateway,
    )
    token = bind_run_context(context())
    try:
        browser = await toolset.browser_open("https://example.com")
        code = await toolset.code_exec("2+2")
    finally:
        reset_run_context(token)

    assert text(browser) == "Browser sandbox call failed: browser sandbox returned HTTP 503"
    assert text(code) == "Code sandbox call failed: code sandbox returned HTTP 503"
    assert len(gateway.browser_calls) == 1
    assert len(gateway.code_calls) == 1


async def test_sandbox_sessions_and_jobs_are_cross_tenant_isolated() -> None:
    settings = configured_settings()
    gateway = FakeSandboxGateway()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings),
        sandbox_gateway=gateway,
    )

    for tenant in ("acme", "globex"):
        token = bind_run_context(context(tenant=tenant))
        try:
            await toolset.browser_open("https://example.com")
            await toolset.code_exec("2+2")
        finally:
            reset_run_context(token)

    browser_requests = [item[0] for item in gateway.browser_calls]
    assert len({request.session_id for request in browser_requests}) == 2
    assert [item[1].internal_token for item in gateway.browser_calls] == [
        "token-acme",
        "token-globex",
    ]
    assert [item[1].internal_token for item in gateway.code_calls] == [
        "token-acme",
        "token-globex",
    ]
    assert all("tenantId" not in request.model_dump(by_alias=True) for request in browser_requests)
    assert all("userId" not in item[0].model_dump(by_alias=True) for item in gateway.code_calls)
