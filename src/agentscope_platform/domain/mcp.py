from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentscope_platform.domain.tool import ToolMetadata


class McpGatewayError(RuntimeError):
    """Sanitized failure returned by the remote MCP boundary."""


class McpToolBinding(BaseModel):
    """Explicit local-tool to remote-MCP-tool allowlist entry."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    server_id: str = Field(alias="serverId", pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    remote_name: str = Field(
        alias="remoteName",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$",
    )
    description: str = Field(min_length=1, max_length=1000)
    metadata: ToolMetadata

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("MCP tool description must not be blank")
        return normalized

    @field_validator("remote_name")
    @classmethod
    def reject_recursive_agent_tools(cls, value: str) -> str:
        if value.casefold().startswith("platform.agent."):
            raise ValueError("recursive Agent tools are forbidden")
        return value

    @model_validator(mode="after")
    def keep_mcp_tool_names_namespaced(self) -> "McpToolBinding":
        expected_prefix = f"mcp_{self.server_id}_"
        if not self.metadata.name.startswith(expected_prefix):
            raise ValueError(f"local MCP tool name must start with {expected_prefix}")
        return self
