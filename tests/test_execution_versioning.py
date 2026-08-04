import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentscope_platform.api.app import create_app
from agentscope_platform.domain.agent import AgentExecution
from agentscope_platform.domain.tool import ToolMetadata
from agentscope_platform.domain.versioning import (
    ExecutionVersions,
    build_execution_versions,
)
from agentscope_platform.infrastructure.agentscope.trajectory import TrajectoryCollector
from internal_jwt_support import signed_internal_token
from test_api import TEST_SECRET, settings
from test_trajectory import tool_events


def versions(*, prompt: str = "prompt", model: str = "model-a") -> ExecutionVersions:
    return build_execution_versions(
        prompt=prompt,
        model=model,
        model_parameters={"temperature": 0},
        tools=(
            ToolMetadata.for_read_only(
                name="rag_search",
                required_scopes=("chat",),
            ),
        ),
        tool_implementation_revision="platform-tools.v1",
    )


def test_execution_versions_are_content_addressed_and_change_with_runtime_inputs() -> None:
    baseline = versions()

    assert baseline.schema_version == "agent-execution-versions.v1"
    assert baseline.prompt_version.startswith("sha256:")
    assert baseline.model_version.startswith("sha256:")
    assert baseline.toolset_version.startswith("sha256:")
    assert baseline.tool_versions["rag_search"].startswith("sha256:")
    assert versions() == baseline
    assert versions(prompt="changed") != baseline
    assert versions(model="model-b") != baseline

    changed_endpoint = build_execution_versions(
        prompt="prompt",
        model="model-a",
        model_parameters={"temperature": 0, "gatewayEndpoint": "http://other.local/v1"},
        tools=(ToolMetadata.for_read_only(name="rag_search", required_scopes=("chat",)),),
        tool_implementation_revision="platform-tools.v1",
    )
    assert changed_endpoint.model_version != baseline.model_version


def test_execution_versions_reject_malformed_per_tool_digests() -> None:
    value = versions().model_dump(by_alias=True)
    value["toolVersions"] = {"invalid tool name": "not-a-digest"}

    with pytest.raises(ValidationError):
        ExecutionVersions.model_validate(value)


def test_versioned_trajectory_keeps_stable_steps_and_runtime_versions() -> None:
    manifest = versions()
    collector = TrajectoryCollector(versions=manifest)
    for event in tool_events("c1", "rag_search", '{"query":"refund"}', "found"):
        collector.consume(event)  # type: ignore[arg-type]

    trajectory = collector.trajectory(
        trace_id="a" * 32,
        stop_reason="DONE",
    )

    assert trajectory.schema_version == "agent-trajectory.v1"
    assert trajectory.versions == manifest
    assert trajectory.steps[0].action == "rag_search"
    assert trajectory.versions.tool_versions[trajectory.steps[0].action]


class VersionedFakeRunner:
    execution_versions = versions()

    async def run(self, goal: str, context: object) -> AgentExecution:
        del context
        return AgentExecution(final_answer=f"completed: {goal}")


def test_agent_run_publishes_non_secret_runtime_version_headers() -> None:
    client = TestClient(create_app(settings(), VersionedFakeRunner()))
    token = signed_internal_token(
        TEST_SECRET,
        scopes=("chat", "agent"),
        department="acme_rd",
    )

    response = client.post(
        "/agent/run",
        json={"goal": "test"},
        headers={"X-Internal-Token": token},
    )

    assert response.status_code == 200
    assert response.headers["X-Agent-Prompt-Version"].startswith("sha256:")
    assert response.headers["X-Agent-Model-Version"].startswith("sha256:")
    assert response.headers["X-Agent-Toolset-Version"].startswith("sha256:")
    assert "toolVersions" not in response.text
