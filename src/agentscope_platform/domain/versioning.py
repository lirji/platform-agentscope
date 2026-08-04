import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from agentscope_platform.domain.agent import ExecutionVersions
from agentscope_platform.domain.tool import ToolMetadata

__all__ = ["ExecutionVersions", "build_execution_versions"]


def build_execution_versions(
    *,
    prompt: str,
    model: str,
    model_parameters: Mapping[str, Any],
    tools: Sequence[ToolMetadata],
    tool_implementation_revision: str,
) -> ExecutionVersions:
    """Build stable versions without persisting prompts, credentials, or model objects."""

    prompt_version = _fingerprint({"prompt": prompt})
    model_version = _fingerprint(
        {
            "model": model,
            "parameters": dict(model_parameters),
        }
    )
    tool_versions = {
        tool.name: _fingerprint(
            {
                "contract": tool.model_dump(by_alias=True, mode="json"),
                "implementationRevision": tool_implementation_revision,
            }
        )
        for tool in sorted(tools, key=lambda item: item.name)
    }
    return ExecutionVersions(
        promptVersion=prompt_version,
        modelVersion=model_version,
        toolsetVersion=_fingerprint(tool_versions),
        toolVersions=tool_versions,
    )


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"
