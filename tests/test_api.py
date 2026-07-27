from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentscope_platform.api.app import create_app
from agentscope_platform.application.ports import DagPlanningError
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import AgentExecution, RunContext
from agentscope_platform.domain.dag import DagPlan, DagPlanKind
from agentscope_platform.infrastructure.agentscope.runner import (
    AgentNotConfiguredError,
)

TEST_SECRET = "test-only-internal-secret-with-at-least-32-bytes"


class FakeRunner:
    def __init__(self) -> None:
        self.context: RunContext | None = None

    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        self.context = context
        return AgentExecution(final_answer=f"completed: {goal}")


class UnconfiguredRunner:
    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        del goal, context
        raise AgentNotConfiguredError("not configured")


class FakePlanner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, RunContext, DagPlanKind]] = []

    async def plan(
        self,
        goal: str,
        context: RunContext,
        kind: DagPlanKind,
    ) -> DagPlan:
        self.calls.append((goal, context, kind))
        description = (
            "用 schema_explore 确认表结构" if kind is DagPlanKind.ANALYST else "collect evidence"
        )
        return DagPlan.model_validate(
            {
                "tasks": [
                    {
                        "id": "t1",
                        "description": description,
                        "dependsOn": [],
                    }
                ]
            }
        )


class UnconfiguredPlanner(FakePlanner):
    async def plan(
        self,
        goal: str,
        context: RunContext,
        kind: DagPlanKind,
    ) -> DagPlan:
        del goal, context, kind
        raise AgentNotConfiguredError("not configured")


class FailedPlanner(FakePlanner):
    async def plan(
        self,
        goal: str,
        context: RunContext,
        kind: DagPlanKind,
    ) -> DagPlan:
        del goal, context, kind
        raise DagPlanningError("safe fallback")


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "internal_auth_required": True,
        "internal_jwt_algorithm": "HS256",
        "internal_jwt_secret": SecretStr(TEST_SECRET),
        "gateway_api_key": SecretStr("test-gateway-key"),
    }
    values.update(overrides)
    return Settings(**values)


def internal_token(**overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "acme",
        "uid": "alice",
        "scopes": ["chat", "agent"],
        "dept": "acme_rd",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, TEST_SECRET, algorithm="HS256")


def test_health_is_open_and_returns_trace_id() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP"}
    assert response.headers["X-Trace-Id"]


def test_agent_run_requires_internal_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    response = client.post("/agent/run", json={"goal": "test"})

    assert response.status_code == 401
    assert response.json()["detail"] == "valid internal authentication is required"


def test_agent_dag_run_requires_internal_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    response = client.post(
        "/agent/dag/run",
        json={
            "goal": "test",
            "tasks": [{"id": "t1", "description": "work"}],
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "valid internal authentication is required"


def test_planned_dag_and_analyst_routes_require_internal_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner(), FakePlanner()))

    planned = client.post("/agent/dag/plan-run", json={"goal": "test"})
    analyst = client.post("/agent/analyst/run", json={"goal": "test"})

    assert planned.status_code == 401
    assert analyst.status_code == 401


def test_planned_dag_and_analyst_routes_use_distinct_planners() -> None:
    runner = FakeRunner()
    planner = FakePlanner()
    client = TestClient(create_app(settings(), runner, planner))
    headers = {
        "X-Internal-Token": internal_token(),
        "X-Trace-Id": "planner-trace",
    }

    planned = client.post(
        "/agent/dag/plan-run",
        json={"goal": " general ", "ignoredLegacyField": "accepted"},
        headers=headers,
    )
    analyst = client.post(
        "/agent/analyst/run",
        json={"goal": " 分析退款 ", "webhookUrl": None},
        headers=headers,
    )

    assert planned.status_code == 200
    assert planned.json()["taskResults"][0]["description"] == "collect evidence"
    assert analyst.status_code == 200
    assert analyst.json()["taskResults"][0]["description"] == "用 schema_explore 确认表结构"
    assert [call[2] for call in planner.calls] == [
        DagPlanKind.GENERAL,
        DagPlanKind.ANALYST,
    ]
    assert all(call[1].trace_id == "planner-trace" for call in planner.calls)
    assert all(call[1].identity.tenant_id == "acme" for call in planner.calls)


def test_planned_routes_return_legacy_blank_goal_error() -> None:
    client = TestClient(create_app(settings(), FakeRunner(), FakePlanner()))
    headers = {"X-Internal-Token": internal_token()}

    blank = client.post(
        "/agent/dag/plan-run",
        json={"goal": " "},
        headers=headers,
    )
    missing_body = client.post("/agent/analyst/run", headers=headers)

    assert blank.status_code == 400
    assert blank.json() == {"error": "goal is required"}
    assert missing_body.status_code == 400
    assert missing_body.json() == {"error": "goal is required"}


def test_planned_route_preserves_unconfigured_model_error() -> None:
    client = TestClient(create_app(settings(), FakeRunner(), UnconfiguredPlanner()))

    response = client.post(
        "/agent/dag/plan-run",
        json={"goal": "test"},
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 503
    assert response.json()["error"] == "agent model is not configured"


def test_planned_route_falls_back_after_recoverable_planner_error() -> None:
    client = TestClient(create_app(settings(), FakeRunner(), FailedPlanner()))

    response = client.post(
        "/agent/dag/plan-run",
        json={"goal": "fallback goal"},
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 200
    assert response.json()["levels"] == [["t1"]]
    assert response.json()["taskResults"][0]["description"] == "fallback goal"


def test_agent_dag_run_preserves_legacy_contract_and_context() -> None:
    runner = FakeRunner()
    client = TestClient(create_app(settings(), runner))

    response = client.post(
        "/agent/dag/run",
        json={
            "goal": " investigate ",
            "tasks": [
                {"id": "first", "description": " collect "},
                {
                    "id": "second",
                    "description": "summarize",
                    "dependsOn": ["first"],
                },
            ],
            "webhookUrl": None,
        },
        headers={
            "X-Internal-Token": internal_token(),
            "X-Trace-Id": "dag-trace",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["goal"] == "investigate"
    assert body["levels"] == [["first"], ["second"]]
    assert [result["taskId"] for result in body["taskResults"]] == [
        "first",
        "second",
    ]
    assert body["taskResults"][1]["dependsOn"] == ["first"]
    assert body["tenantId"] == "acme"
    assert body["attempts"] == []
    assert body["acceptedByThreshold"] is True
    assert body["synthesis"]["stopReason"] == "DONE"
    assert response.headers["X-Trace-Id"] == "dag-trace"
    assert runner.context is not None
    assert runner.context.identity.tenant_id == "acme"
    assert runner.context.identity.user_id == "alice"
    assert runner.context.identity.department == "acme_rd"
    assert runner.context.trace_id == "dag-trace"


def test_agent_dag_run_returns_legacy_validation_error_shape() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    response = client.post(
        "/agent/dag/run",
        json={
            "goal": "cycle",
            "tasks": [
                {"id": "a", "description": "a", "dependsOn": ["b"]},
                {"id": "b", "description": "b", "dependsOn": ["a"]},
            ],
        },
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "task graph contains a cycle"}


def test_agent_dag_run_maps_unconfigured_runner_to_service_unavailable() -> None:
    client = TestClient(create_app(settings(), UnconfiguredRunner()))

    response = client.post(
        "/agent/dag/run",
        json={
            "goal": "test",
            "tasks": [
                {"id": "a", "description": "one"},
                {"id": "b", "description": "two"},
            ],
        },
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 503
    assert response.json()["error"] == "agent model is not configured"


def test_agent_dag_run_rejects_forged_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    response = client.post(
        "/agent/dag/run",
        json={
            "goal": "test",
            "tasks": [{"id": "t1", "description": "work"}],
        },
        headers={
            "X-Internal-Token": jwt.encode(
                {
                    "sub": "acme",
                    "uid": "mallory",
                    "scopes": ["agent"],
                    "exp": datetime.now(UTC) + timedelta(minutes=5),
                },
                "another-test-secret-with-at-least-32-bytes",
                algorithm="HS256",
            ),
        },
    )

    assert response.status_code == 401


def test_agent_run_preserves_legacy_contract_and_tenant() -> None:
    runner = FakeRunner()
    client = TestClient(create_app(settings(), runner))

    response = client.post(
        "/agent/run",
        json={"goal": " search docs ", "webhookUrl": None},
        headers={
            "X-Internal-Token": internal_token(),
            "X-Trace-Id": "trace-123",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == "trace-123"
    assert response.json() == {
        "goal": "search docs",
        "steps": [],
        "finalAnswer": "completed: search docs",
        "stopReason": "DONE",
        "depth": 0,
        "tenantId": "acme",
    }
    assert runner.context is not None
    assert runner.context.identity.user_id == "alice"
    assert runner.context.identity.department == "acme_rd"
    assert runner.context.identity.scopes == frozenset({"chat", "agent"})
    assert runner.context.trace_id == "trace-123"


def test_candidate_route_is_absent_by_default() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    response = client.post(
        "/agent/v2/run",
        json={"goal": "test"},
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 404


def test_candidate_route_preserves_contract_security_and_context() -> None:
    runner = FakeRunner()
    client = TestClient(
        create_app(
            settings(agent_v2_enabled=True),
            runner,
        ),
    )

    missing = client.post("/agent/v2/run", json={"goal": "test"})
    forged = client.post(
        "/agent/v2/run",
        json={"goal": "test"},
        headers={
            "X-Internal-Token": jwt.encode(
                {
                    "sub": "acme",
                    "uid": "mallory",
                    "scopes": ["agent"],
                    "exp": datetime.now(UTC) + timedelta(minutes=5),
                },
                "another-test-secret-with-at-least-32-bytes",
                algorithm="HS256",
            ),
        },
    )
    accepted = client.post(
        "/agent/v2/run",
        json={"goal": " candidate query "},
        headers={
            "X-Internal-Token": internal_token(),
            "X-Trace-Id": "candidate-trace",
        },
    )

    assert missing.status_code == 401
    assert forged.status_code == 401
    assert accepted.status_code == 200
    assert accepted.headers["X-Trace-Id"] == "candidate-trace"
    assert accepted.json() == {
        "goal": "candidate query",
        "steps": [],
        "finalAnswer": "completed: candidate query",
        "stopReason": "DONE",
        "depth": 0,
        "tenantId": "acme",
    }
    assert runner.context is not None
    assert runner.context.identity.user_id == "alice"
    assert runner.context.identity.department == "acme_rd"
    assert runner.context.identity.scopes == frozenset({"chat", "agent"})
    assert runner.context.trace_id == "candidate-trace"


def test_agent_run_rejects_forged_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))
    forged = jwt.encode(
        {
            "sub": "acme",
            "uid": "mallory",
            "scopes": ["agent"],
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "another-test-secret-with-at-least-32-bytes",
        algorithm="HS256",
    )

    response = client.post(
        "/agent/run",
        json={"goal": "test"},
        headers={"X-Internal-Token": forged},
    )

    assert response.status_code == 401


def test_readiness_reports_missing_model_configuration() -> None:
    app_settings = settings(gateway_api_key=SecretStr(""))
    client = TestClient(create_app(app_settings, FakeRunner()))

    response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json()["status"] == "DEGRADED"
    assert response.json()["checks"]["modelConfiguration"] == "MISSING_GATEWAY_API_KEY"
    assert response.json()["checks"]["candidateRoute"] == "DISABLED"


def test_readiness_reports_enabled_candidate_route() -> None:
    client = TestClient(
        create_app(
            settings(agent_v2_enabled=True),
            FakeRunner(),
        ),
    )

    response = client.get("/readiness")

    assert response.status_code == 200
    assert response.json()["checks"]["candidateRoute"] == "ENABLED"


def test_local_auth_can_be_explicitly_disabled() -> None:
    runner = FakeRunner()
    client = TestClient(
        create_app(
            settings(internal_auth_required=False),
            runner,
        ),
    )

    response = client.post("/agent/run", json={"goal": "local test"})

    assert response.status_code == 200
    assert response.json()["tenantId"] == "anonymous"
