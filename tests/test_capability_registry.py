import json
from pathlib import Path

from fastapi.testclient import TestClient

from agentscope_platform.api.app import create_app
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import AgentExecution, RunContext
from agentscope_platform.domain.interop import capability_registry
from internal_jwt_support import signed_internal_token

ROOT = Path(__file__).resolve().parents[1]
TEST_SECRET = "test-only-internal-secret-with-at-least-32-bytes"


class FakeRunner:
    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        del context
        return AgentExecution(final_answer=f"completed: {goal}")


def settings() -> Settings:
    return Settings(
        _env_file=None,
        gateway_api_key="test-key",
        internal_jwt_secret=TEST_SECRET,
    )


def internal_token() -> str:
    return signed_internal_token(
        TEST_SECRET,
        scopes=("chat", "agent"),
        department="acme_rd",
    )


def test_registry_has_stable_revision_and_no_runtime_identity() -> None:
    first = capability_registry()
    second = capability_registry()
    payload = first.model_dump(by_alias=True, mode="json")

    assert first == second
    assert first.schema_version == "agent-capability-registry.v1"
    assert len(first.revision) == 64
    assert {item.name for item in first.capabilities}.issuperset(
        {
            "platform.agent.run",
            "platform.agent.run_async",
            "platform.agent.session.run",
            "platform.agent.session.get",
        }
    )
    serialized = json.dumps(payload)
    assert all(
        field not in serialized for field in ("tenantId", "userId", "internalToken", "endpointUrl")
    )


def test_versioned_registry_endpoint_and_legacy_projection_match() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))
    headers = {"X-Internal-Token": internal_token()}

    registry_response = client.get("/agent/capabilities/registry", headers=headers)
    legacy_response = client.get("/agent/capabilities", headers=headers)

    assert registry_response.status_code == 200
    assert registry_response.headers["etag"] == f'"{registry_response.json()["revision"]}"'
    assert legacy_response.status_code == 200
    assert legacy_response.json() == registry_response.json()["capabilities"][:4]


def test_committed_registry_manifest_matches_runtime_registry() -> None:
    committed = json.loads(
        (ROOT / "contracts" / "capabilities" / "agent-capabilities.v1.json").read_text()
    )

    assert committed == capability_registry().model_dump(by_alias=True, mode="json")
