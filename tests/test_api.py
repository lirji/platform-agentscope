from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentscope_platform.api.app import create_app
from agentscope_platform.application.ports import (
    DagPlanningError,
    DagQualityError,
    TextGenerationError,
)
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import AgentExecution, RunContext
from agentscope_platform.domain.dag import (
    AgentDagCritique,
    DagPlan,
    DagPlanKind,
)
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
        description = {
            DagPlanKind.GENERAL: "collect evidence",
            DagPlanKind.ANALYST: "用 schema_explore 确认表结构",
            DagPlanKind.PROCESS: "用 workflow_status 查询流程",
        }[kind]
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


class AcceptingReviewer:
    async def critique(
        self,
        goal: str,
        answer: str,
        context: RunContext,
    ) -> AgentDagCritique:
        del goal, answer, context
        return AgentDagCritique(
            correctness=0.9,
            completeness=0.9,
            clarity=0.8,
            mainIssue="n/a",
        )

    async def revise(
        self,
        goal: str,
        previous_plan: DagPlan,
        previous_answer: str,
        critique: AgentDagCritique,
        context: RunContext,
    ) -> DagPlan:
        del goal, previous_plan, previous_answer, critique, context
        raise AssertionError("accepted critique must not replan")


class FailedReviewer(AcceptingReviewer):
    async def critique(
        self,
        goal: str,
        answer: str,
        context: RunContext,
    ) -> AgentDagCritique:
        del goal, answer, context
        raise DagQualityError("provider secret must not leak")


class FakeTextGenerator:
    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = list(outputs or [])
        self.contexts: list[RunContext] = []
        self.deterministic: list[bool] = []

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: RunContext,
        *,
        deterministic: bool = False,
    ) -> str:
        del system_prompt, user_prompt
        self.contexts.append(context)
        self.deterministic.append(deterministic)
        return self.outputs.pop(0)


class FailedTextGenerator(FakeTextGenerator):
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: RunContext,
        *,
        deterministic: bool = False,
    ) -> str:
        del system_prompt, user_prompt, context, deterministic
        raise TextGenerationError("provider secret must not leak")


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "internal_auth_required": True,
        "internal_jwt_algorithm": "HS256",
        "internal_jwt_secret": SecretStr(TEST_SECRET),
        "gateway_api_key": SecretStr("test-gateway-key"),
        "agent_dag_replan_enabled": False,
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


def test_workflow_ai_draft_endpoints_use_trusted_context_and_never_decide() -> None:
    generator = FakeTextGenerator(
        [
            '{"title":"退款未到账","priority":"HIGH","category":"refund",'
            '"summary":"退款长期未到账","tags":["未到账"]}',
            "您的退款请求已受理, 我们会尽快处理。",
        ]
    )
    client = TestClient(
        create_app(settings(), FakeRunner(), text_generator=generator)
    )
    headers = {"X-Internal-Token": internal_token()}

    ticket = client.post(
        "/internal/workflow/ticket-draft",
        json={"message": "退款一直没到账"},
        headers=headers,
    )
    reply = client.post(
        "/internal/workflow/reply-draft",
        json={"chatId": "c1", "message": "退款一直没到账"},
        headers=headers,
    )

    assert ticket.status_code == 200
    assert ticket.json()["priority"] == "HIGH"
    assert reply.status_code == 200
    assert reply.json() == {"reply": "您的退款请求已受理, 我们会尽快处理。"}
    assert [item.identity.tenant_id for item in generator.contexts] == ["acme", "acme"]
    assert generator.deterministic == [True, True]


def test_agent_run_requires_internal_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    response = client.post("/agent/run", json={"goal": "test"})

    assert response.status_code == 401
    assert response.json()["detail"] == "valid internal authentication is required"


def test_agent_capabilities_require_auth_and_match_legacy_discovery_contract() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    missing = client.get("/agent/capabilities")
    accepted = client.get(
        "/agent/capabilities",
        headers={"X-Internal-Token": internal_token()},
    )

    assert missing.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == [
        {
            "name": "platform.agent.run",
            "description": "Runs the platform agent through AgentScope.",
            "inputSchema": {
                "type": "object",
                "required": ["goal"],
                "properties": {
                    "goal": {"type": "string"},
                    "webhookUrl": {"type": "string"},
                },
            },
        },
        {
            "name": "platform.agent.run_async",
            "description": "Starts an async platform agent run through AgentScope.",
            "inputSchema": {
                "type": "object",
                "required": ["goal"],
                "properties": {
                    "goal": {"type": "string"},
                    "webhookUrl": {"type": "string"},
                },
            },
        },
        {
            "name": "platform.agent.dag.plan_run",
            "description": "Plans and runs a DAG agent workflow through AgentScope.",
            "inputSchema": {
                "type": "object",
                "required": ["goal"],
                "properties": {"goal": {"type": "string"}},
            },
        },
        {
            "name": "platform.agent.dag.plan_run_async",
            "description": "Starts an async planned DAG agent workflow through AgentScope.",
            "inputSchema": {
                "type": "object",
                "required": ["goal"],
                "properties": {
                    "goal": {"type": "string"},
                    "webhookUrl": {"type": "string"},
                },
            },
        },
    ]


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


def test_sibling_routes_require_internal_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    for path, payload in (
        ("/agent/chain", {"input": "hello"}),
        ("/agent/vote", {"question": "hello"}),
        ("/agent/reflexive", {"question": "hello"}),
    ):
        response = client.post(path, json=payload)
        assert response.status_code == 401
        assert response.json()["detail"] == "valid internal authentication is required"


def test_planned_dag_and_analyst_routes_require_internal_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner(), FakePlanner()))

    planned = client.post("/agent/dag/plan-run", json={"goal": "test"})
    analyst = client.post("/agent/analyst/run", json={"goal": "test"})
    process = client.post("/agent/process/run", json={"goal": "test"})

    assert planned.status_code == 401
    assert analyst.status_code == 401
    assert process.status_code == 401


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
    process = client.post(
        "/agent/process/run",
        json={"goal": " 查询流程 "},
        headers=headers,
    )

    assert planned.status_code == 200
    assert planned.json()["taskResults"][0]["description"] == "collect evidence"
    assert analyst.status_code == 200
    assert analyst.json()["taskResults"][0]["description"] == "用 schema_explore 确认表结构"
    assert process.status_code == 200
    assert process.json()["taskResults"][0]["description"] == "用 workflow_status 查询流程"
    assert [call[2] for call in planner.calls] == [
        DagPlanKind.GENERAL,
        DagPlanKind.ANALYST,
        DagPlanKind.PROCESS,
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


def test_agent_dag_run_populates_critique_attempt_when_enabled() -> None:
    client = TestClient(
        create_app(
            settings(agent_dag_replan_enabled=True),
            FakeRunner(),
            FakePlanner(),
            AcceptingReviewer(),
        )
    )

    response = client.post(
        "/agent/dag/run",
        json={
            "goal": "quality",
            "tasks": [{"id": "t1", "description": "work"}],
        },
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["acceptedByThreshold"] is True
    assert len(body["attempts"]) == 1
    assert body["attempts"][0]["critique"] == {
        "correctness": 0.9,
        "completeness": 0.9,
        "clarity": 0.8,
        "mainIssue": "n/a",
    }
    assert body["attempts"][0]["aggregate"] == 0.885


def test_agent_dag_run_maps_quality_failure_without_leaking_detail() -> None:
    client = TestClient(
        create_app(
            settings(agent_dag_replan_enabled=True),
            FakeRunner(),
            FakePlanner(),
            FailedReviewer(),
        )
    )

    response = client.post(
        "/agent/dag/run",
        json={
            "goal": "quality",
            "tasks": [{"id": "t1", "description": "work"}],
        },
        headers={
            "X-Internal-Token": internal_token(),
            "X-Trace-Id": "quality-trace",
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": "DAG quality review failed",
        "traceId": "quality-trace",
    }
    assert "provider secret" not in response.text


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


def test_prompt_chain_preserves_legacy_contract_and_tenant_context() -> None:
    generator = FakeTextGenerator(["translated output", "这是一段最终总结内容"])
    client = TestClient(
        create_app(
            settings(),
            FakeRunner(),
            FakePlanner(),
            AcceptingReviewer(),
            generator,
        )
    )

    response = client.post(
        "/agent/chain",
        json={"input": "原始内容", "steps": [{"instruction": "caller override"}]},
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["input"] == "原始内容"
    assert body["finalOutput"] == "这是一段最终总结内容"
    assert body["completed"] is True
    assert [step["name"] for step in body["steps"]] == ["translate", "summarize"]
    assert body["tenantId"] == "acme"
    assert all(context.identity.tenant_id == "acme" for context in generator.contexts)


def test_voting_preserves_legacy_contract_and_candidate_override() -> None:
    generator = FakeTextGenerator(["Yes", " yes ", "No"])
    client = TestClient(
        create_app(
            settings(),
            FakeRunner(),
            FakePlanner(),
            AcceptingReviewer(),
            generator,
        )
    )

    response = client.post(
        "/agent/vote",
        json={"question": "Proceed?", "n": 3},
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 200
    assert response.json() == {
        "question": "Proceed?",
        "votes": ["Yes", " yes ", "No"],
        "strategy": "majority",
        "decision": "Yes",
        "agreement": 2 / 3,
        "confident": True,
        "tenantId": "acme",
    }


def test_reflexion_preserves_legacy_contract() -> None:
    generator = FakeTextGenerator(["answer"])
    client = TestClient(
        create_app(
            settings(),
            FakeRunner(),
            FakePlanner(),
            AcceptingReviewer(),
            generator,
        )
    )

    response = client.post(
        "/agent/reflexive",
        json={"question": "Explain"},
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "Explain"
    assert body["finalAnswer"] == "answer"
    assert body["acceptedByThreshold"] is True
    assert body["tenantId"] == "acme"
    assert len(body["attempts"]) == 1


def test_sibling_validation_uses_legacy_error_shape_before_generation() -> None:
    generator = FakeTextGenerator(["unused"])
    client = TestClient(
        create_app(
            settings(),
            FakeRunner(),
            FakePlanner(),
            AcceptingReviewer(),
            generator,
        )
    )

    response = client.post(
        "/agent/vote",
        json={"question": "q", "n": 0},
        headers={"X-Internal-Token": internal_token()},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "n must be between 1 and 10"}
    assert generator.contexts == []


def test_sibling_generation_failure_is_sanitized() -> None:
    client = TestClient(
        create_app(
            settings(),
            FakeRunner(),
            FakePlanner(),
            AcceptingReviewer(),
            FailedTextGenerator(),
        )
    )

    response = client.post(
        "/agent/chain",
        json={"input": "hello"},
        headers={
            "X-Internal-Token": internal_token(),
            "X-Trace-Id": "sibling-trace",
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": "agent generation failed",
        "traceId": "sibling-trace",
    }
    assert "provider secret" not in response.text
