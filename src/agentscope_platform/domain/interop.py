import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class McpToolDescriptor(BaseModel):
    """Language-neutral capability descriptor consumed by platform interop."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")


class AgentCapabilityRegistry(BaseModel):
    """Versioned, language-neutral Agent capability catalog."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["agent-capability-registry.v1"] = Field(
        default="agent-capability-registry.v1",
        alias="schemaVersion",
    )
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    capabilities: tuple[McpToolDescriptor, ...]


def capability_registry() -> AgentCapabilityRegistry:
    goal_schema = {
        "type": "object",
        "required": ["goal"],
        "properties": {
            "goal": {"type": "string"},
            "webhookUrl": {"type": "string"},
        },
    }
    session_run_schema = {
        "type": "object",
        "required": ["goal"],
        "properties": {
            "goal": {"type": "string", "minLength": 1, "maxLength": 20_000},
        },
        "additionalProperties": False,
    }
    session_get_schema = {
        "type": "object",
        "required": ["sessionId"],
        "properties": {
            "sessionId": {"type": "string", "pattern": r"^sess-[a-f0-9]{32}$"},
        },
        "additionalProperties": False,
    }
    capabilities = (
        McpToolDescriptor(
            name="platform.agent.run",
            description="Runs the platform agent through AgentScope.",
            inputSchema=goal_schema,
        ),
        McpToolDescriptor(
            name="platform.agent.run_async",
            description="Starts an async platform agent run through AgentScope.",
            inputSchema=goal_schema,
        ),
        McpToolDescriptor(
            name="platform.agent.dag.plan_run",
            description="Plans and runs a DAG agent workflow through AgentScope.",
            inputSchema={
                "type": "object",
                "required": ["goal"],
                "properties": {"goal": {"type": "string"}},
            },
        ),
        McpToolDescriptor(
            name="platform.agent.dag.plan_run_async",
            description="Starts an async planned DAG agent workflow through AgentScope.",
            inputSchema=goal_schema,
        ),
        McpToolDescriptor(
            name="platform.agent.session.run",
            description="Creates or resumes a durable Agent session.",
            inputSchema=session_run_schema,
        ),
        McpToolDescriptor(
            name="platform.agent.session.get",
            description="Reads an owner-scoped durable Agent session checkpoint.",
            inputSchema=session_get_schema,
        ),
    )
    canonical = json.dumps(
        [item.model_dump(by_alias=True, mode="json") for item in capabilities],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return AgentCapabilityRegistry(
        revision=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        capabilities=capabilities,
    )
