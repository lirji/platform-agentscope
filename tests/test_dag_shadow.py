import json
from pathlib import Path

import httpx

from agentscope_platform.evaluation import dag_cli
from agentscope_platform.evaluation.dag_shadow import (
    DagShadowReport,
    DagShadowSample,
    evaluate_dag_shadow,
    load_dag_cases,
)
from agentscope_platform.evaluation.shadow import Target

ROOT = Path(__file__).resolve().parents[1]


def dag_reply(request: dict[str, object], levels: list[list[str]]) -> dict[str, object]:
    tasks = request["tasks"]
    assert isinstance(tasks, list)
    task_by_id = {task["id"]: task for task in tasks}

    def run_reply(goal: str) -> dict[str, object]:
        return {
            "goal": goal,
            "steps": [],
            "finalAnswer": "offline result",
            "stopReason": "DONE",
            "depth": 0,
            "tenantId": "smoke",
        }

    return {
        "goal": request["goal"],
        "levels": levels,
        "taskResults": [
            {
                "taskId": task_id,
                "description": task_by_id[task_id]["description"],
                "dependsOn": task_by_id[task_id].get("dependsOn", []),
                "result": run_reply(str(task_by_id[task_id]["description"])),
            }
            for level in levels
            for task_id in level
        ],
        "synthesis": run_reply("synthesis"),
        "tenantId": "smoke",
        "attempts": [],
        "acceptedByThreshold": True,
    }


def planned_reply(
    goal: str,
    tasks: list[dict[str, object]],
    levels: list[list[str]],
) -> dict[str, object]:
    return dag_reply(
        {"goal": goal, "tasks": tasks},
        levels,
    )


def reviewed_reply(
    request: dict[str, object],
    levels: list[list[str]],
) -> dict[str, object]:
    body = dag_reply(request, levels)
    body["attempts"] = [
        {
            "n": 1,
            "levels": body["levels"],
            "taskResults": body["taskResults"],
            "synthesis": body["synthesis"],
            "critique": {
                "correctness": 0.9,
                "completeness": 0.9,
                "clarity": 0.8,
                "mainIssue": "n/a",
            },
            "aggregate": 0.885,
        }
    ]
    return body


async def test_dag_shadow_accepts_matching_legacy_and_candidate() -> None:
    cases = load_dag_cases(ROOT / "eval" / "baseline" / "dag-cases.jsonl")
    levels_by_goal = {case.request.goal: case.expected_levels for case in cases}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json=dag_reply(payload, levels_by_goal[payload["goal"]]),
        )

    report = await evaluate_dag_shadow(
        cases,
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(handler),
    )

    assert report.passed is True
    assert len(report.samples) == len(cases) * 2
    assert all(sample.error is None for sample in report.samples)


async def test_dag_shadow_fails_closed_on_candidate_level_regression() -> None:
    cases = load_dag_cases(ROOT / "eval" / "baseline" / "dag-cases.jsonl")
    case = cases[1]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        levels = (
            [list(reversed(level)) for level in case.expected_levels]
            if request.url.host == "candidate.localhost"
            else case.expected_levels
        )
        return httpx.Response(200, json=dag_reply(payload, levels))

    report = await evaluate_dag_shadow(
        (case,),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(handler),
    )

    assert report.passed is False
    assert report.samples[-1].target == "candidate"
    assert report.samples[-1].error == "LEVELS_MISMATCH"


async def test_dag_shadow_accepts_dynamic_general_and_analyst_plans() -> None:
    cases = load_dag_cases(ROOT / "eval" / "baseline" / "planner-cases.jsonl")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if request.url.path == "/agent/analyst/run":
            tasks = [
                {
                    "id": "t1",
                    "description": "用 schema_explore 确认退款表结构",
                    "dependsOn": [],
                },
                {
                    "id": "t2",
                    "description": "基于 t1 用 analytics_sql 查询趋势",
                    "dependsOn": ["t1"],
                },
            ]
            levels = [["t1"], ["t2"]]
        else:
            tasks = [
                {
                    "id": "t1",
                    "description": "调查并发变化",
                    "dependsOn": [],
                },
                {
                    "id": "t2",
                    "description": "调查模式匹配变化",
                    "dependsOn": [],
                },
            ]
            levels = [["t1", "t2"]]
        return httpx.Response(
            200,
            json=planned_reply(payload["goal"], tasks, levels),
        )

    report = await evaluate_dag_shadow(
        cases,
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(handler),
        suite_name="planner-cases",
    )

    assert report.passed is True
    assert len(report.samples) == 4


async def test_dag_shadow_fails_closed_when_analyst_plan_misses_tool_rule() -> None:
    case = load_dag_cases(ROOT / "eval" / "baseline" / "planner-cases.jsonl")[1]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json=planned_reply(
                payload["goal"],
                [
                    {
                        "id": "t1",
                        "description": "仅做普通分析",
                        "dependsOn": [],
                    }
                ],
                [["t1"]],
            ),
        )

    report = await evaluate_dag_shadow(
        (case,),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(handler),
    )

    assert report.passed is False
    assert all(sample.error == "PLANNER_REQUIREMENT_MISSING" for sample in report.samples)


async def test_dag_shadow_requires_critic_attempt_evidence() -> None:
    case = load_dag_cases(ROOT / "eval" / "baseline" / "critic-cases.jsonl")[0]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        body = reviewed_reply(payload, case.expected_levels or [])
        if request.url.host == "candidate.localhost":
            body["attempts"] = []
        return httpx.Response(200, json=body)

    report = await evaluate_dag_shadow(
        (case,),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(handler),
    )

    assert report.passed is False
    assert report.samples[0].passed is True
    assert report.samples[1].error == "CRITIQUE_MISSING"


async def test_dag_cli_writes_only_sanitized_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_evaluate(*args: object, **kwargs: object) -> DagShadowReport:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return DagShadowReport(
            suite="dag",
            passed=True,
            samples=[
                DagShadowSample(
                    caseId="case",
                    target="candidate",
                    passed=True,
                    statusCode=200,
                    latencyMs=1,
                )
            ],
        )

    monkeypatch.setattr(dag_cli, "evaluate_dag_shadow", fake_evaluate)
    monkeypatch.setenv("SHADOW_INTERNAL_TOKEN", "environment-only-secret")
    output = tmp_path / "dag-report.json"

    exit_code = await dag_cli.async_main(
        [
            "--legacy-url",
            "http://legacy.localhost",
            "--candidate-url",
            "http://candidate.localhost",
            "--suite",
            str(ROOT / "eval" / "baseline" / "dag-cases.jsonl"),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert captured["args"]
    assert "environment-only-secret" not in output.read_text(encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True


async def test_dag_cli_returns_configuration_error_for_remote_target(
    tmp_path: Path,
) -> None:
    exit_code = await dag_cli.async_main(
        [
            "--legacy-url",
            "http://legacy.example",
            "--candidate-url",
            "http://candidate.localhost",
            "--suite",
            str(ROOT / "eval" / "baseline" / "dag-cases.jsonl"),
            "--output",
            str(tmp_path / "report.json"),
        ]
    )

    assert exit_code == 2
