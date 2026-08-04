from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentscope_platform.domain.agent import RunContext


class SandboxGatewayError(RuntimeError):
    """Sanitized remote sandbox failure."""


class BrowserActionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1"] = Field(default="1", alias="schemaVersion")
    session_id: str = Field(alias="sessionId", pattern=r"^run-[a-f0-9]{32}$")
    operation_id: str = Field(alias="operationId", pattern=r"^op-[a-f0-9]{32}$")
    action: Literal["open", "click", "click_xy", "type", "screenshot", "see"]
    arguments: dict[str, Any]
    allowed_hosts: tuple[str, ...] = Field(alias="allowedHosts", min_length=1, max_length=64)


class BrowserActionReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    output: str = Field(max_length=100_000)
    current_url: str | None = Field(default=None, alias="currentUrl", max_length=4096)
    artifact_id: str | None = Field(default=None, alias="artifactId", max_length=256)
    truncated: bool = False


class CodeExecutionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1"] = Field(default="1", alias="schemaVersion")
    operation_id: str = Field(alias="operationId", pattern=r"^op-[a-f0-9]{32}$")
    language: Literal["java"]
    source: str = Field(min_length=1, max_length=20_000)
    timeout_ms: int = Field(alias="timeoutMs", ge=100, le=300_000)
    max_output_chars: int = Field(alias="maxOutputChars", ge=100, le=100_000)
    network_enabled: Literal[False] = Field(alias="networkEnabled")
    workspace: Literal["ephemeral"]
    max_memory_mb: int = Field(alias="maxMemoryMb", ge=16, le=1024)
    max_processes: int = Field(alias="maxProcesses", ge=1, le=64)


class CodeExecutionReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    status: Literal["COMPLETED", "FAILED", "TIMED_OUT"]
    output: str | None = Field(default=None, max_length=100_000)
    error: str | None = Field(default=None, max_length=4000)
    truncated: bool = False

    @model_validator(mode="after")
    def validate_status_fields(self) -> "CodeExecutionReply":
        if self.status == "COMPLETED" and self.error:
            raise ValueError("completed code execution cannot contain an error")
        if self.status == "FAILED" and not self.error:
            raise ValueError("failed code execution must contain an error")
        return self


def sandbox_session_id(context: RunContext) -> str:
    request_key = context.idempotency_key or context.trace_id
    material = f"{context.identity.tenant_id}\0{context.identity.user_id}\0{request_key}"
    return "run-" + sha256(material.encode()).hexdigest()[:32]


def sandbox_operation_id(
    context: RunContext,
    tool_name: str,
    sequence: int,
) -> str:
    request_key = context.idempotency_key or context.trace_id
    material = (
        f"{context.identity.tenant_id}\0{context.identity.user_id}\0{request_key}\0"
        f"{tool_name}\0{sequence}"
    )
    return "op-" + sha256(material.encode()).hexdigest()[:32]
