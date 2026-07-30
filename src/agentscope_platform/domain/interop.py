from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class McpToolDescriptor(BaseModel):
    """Language-neutral capability descriptor consumed by platform interop."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")
