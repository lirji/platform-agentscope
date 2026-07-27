import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from agentscope_platform.evaluation.judge import JudgeError, JudgeRequest, JudgeResult
from agentscope_platform.evaluation.models import (
    RunSample,
    ShadowCase,
    ShadowThresholds,
)
from agentscope_platform.evaluation.shadow import (
    ShadowEvaluationError,
    Target,
    evaluate_gate,
    evaluate_shadow,
    load_cases,
    summarize,
    validate_target_url,
    write_report,
)


def case(**overrides: object) -> ShadowCase:
    values: dict[str, object] = {
        "id": "rag",
        "goal": "find refund policy",
        "expectedTools": ["rag_search"],
        "forbiddenTools": ["refund_start"],
        "readOnly": True,
    }
    values.update(overrides)
    return ShadowCase.model_validate(values)


def reply(goal: str, tools: list[str], stop_reason: str = "DONE") -> dict[str, object]:
    return {
        "goal": goal,
        "steps": [
            {
                "n": index,
                "thought": "",
                "action": tool,
                "actionInput": "input",
                "observation": "redacted from report",
            }
            for index, tool in enumerate(tools, start=1)
        ],
        "finalAnswer": "sensitive business answer",
        "stopReason": stop_reason,
        "depth": 0,
        "tenantId": "acme",
    }


async def test_evaluates_same_cases_and_sanitizes_report(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        tools = ["rag_search"]
        if request.url.host == "candidate.localhost":
            tools = ["rag_search", "refund_start"]
        return httpx.Response(200, json=reply(body["goal"], tools))

    report = await evaluate_shadow(
        (case(),),
        Target("legacy", "http://legacy.localhost", auth_token="legacy-secret"),
        Target("candidate", "http://candidate.localhost", auth_token="candidate-secret"),
        runs=2,
        transport=httpx.MockTransport(handler),
    )

    assert len(requests) == 4
    assert {request.url.host for request in requests} == {
        "legacy.localhost",
        "candidate.localhost",
    }
    trace_ids = [request.headers["X-Trace-Id"] for request in requests]
    assert len(set(trace_ids)) == 4
    assert {sample.trace_id for sample in report.samples} == set(trace_ids)
    assert all(
        request.headers["traceparent"].startswith(f"00-{request.headers['X-Trace-Id']}-")
        for request in requests
    )
    assert report.gate.legacy.pass_rate == 1
    assert report.gate.candidate.forbidden_violations == 2
    assert not report.gate.passed
    assert any("forbidden_tool regression" in item for item in report.gate.regressions)

    output = tmp_path / "report.json"
    write_report(report, output)
    serialized = output.read_text(encoding="utf-8")
    assert "legacy-secret" not in serialized
    assert "candidate-secret" not in serialized
    assert "sensitive business answer" not in serialized
    assert "redacted from report" not in serialized


async def test_http_and_contract_errors_are_safe_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "legacy.localhost":
            return httpx.Response(503, text="provider secret")
        return httpx.Response(200, text="not-json")

    report = await evaluate_shadow(
        (case(),),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(handler),
    )

    assert [sample.error for sample in report.samples] == [
        "HTTP_503",
        "INVALID_CONTRACT",
    ]
    assert all(not sample.contract_valid for sample in report.samples)
    assert "provider secret" not in report.model_dump_json()


async def test_network_and_oversized_responses_fail_without_body_leakage() -> None:
    def network_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "legacy.localhost":
            return httpx.Response(200, json=reply("goal", ["rag_search"]))
        raise httpx.ConnectError("secret network detail", request=request)

    network_report = await evaluate_shadow(
        (case(),),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(network_handler),
    )
    assert network_report.samples[1].error == "NETWORK_ERROR"
    assert "secret network detail" not in network_report.model_dump_json()

    oversized_report = await evaluate_shadow(
        (case(),),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * 2_000_001)
        ),
    )
    assert all(sample.error == "RESPONSE_TOO_LARGE" for sample in oversized_report.samples)


def test_gate_enforces_relative_metrics_forbidden_tools_and_p95() -> None:
    legacy_samples = [
        RunSample(
            case_id=str(index),
            target="legacy",
            run=1,
            status_code=200,
            latency_ms=100,
            contract_valid=True,
            completed=True,
            passed=True,
            stop_reason="DONE",
            tool_score=1,
        )
        for index in range(4)
    ]
    candidate_samples = [
        RunSample(
            case_id=str(index),
            target="candidate",
            run=1,
            status_code=200,
            latency_ms=1000,
            contract_valid=True,
            completed=index < 3,
            passed=index < 2,
            stop_reason="DONE" if index < 3 else "ERROR",
            tool_score=0.5,
            forbidden_tools=("refund_start",) if index == 0 else (),
        )
        for index in range(4)
    ]

    gate = evaluate_gate(
        summarize("legacy", legacy_samples),
        summarize("candidate", candidate_samples),
        ShadowThresholds(
            pass_rate_tolerance=0.1,
            completion_rate_tolerance=0.1,
            tool_accuracy_tolerance=0.1,
            p95_latency_ratio=1,
            p95_latency_slack_ms=0,
        ),
    )

    assert not gate.passed
    assert {item.split()[0] for item in gate.regressions} == {
        "minimum_pass_rate",
        "minimum_completion_rate",
        "minimum_tool_accuracy",
        "pass_rate",
        "completion_rate",
        "tool_accuracy",
        "forbidden_tool",
        "p95_latency",
    }


async def test_expected_tools_must_preserve_declared_order() -> None:
    ordered_case = case(
        id="analytics",
        expectedTools=["schema_explore", "analytics_sql"],
        forbiddenTools=[],
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=reply(
                "analytics",
                ["analytics_sql", "schema_explore"],
            ),
        )
    )

    report = await evaluate_shadow(
        (ordered_case,),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=transport,
    )

    assert all(sample.error == "EXPECTED_TOOL_ORDER" for sample in report.samples)
    assert all(not sample.tool_order_valid for sample in report.samples)
    assert not report.gate.passed


@pytest.mark.parametrize(
    ("url", "allow_remote", "expected"),
    [
        ("http://localhost:8085/", False, "http://localhost:8085"),
        ("http://candidate.localhost:8085/base/", False, "http://candidate.localhost:8085/base"),
        ("https://test.example/agent", True, "https://test.example/agent"),
    ],
)
def test_target_url_validation(url: str, allow_remote: bool, expected: str) -> None:
    assert validate_target_url(url, allow_remote) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://test.example",
        "ftp://localhost/service",
        "http://user:secret@localhost",
        "http://localhost?token=secret",
    ],
)
def test_target_url_rejects_unsafe_values(url: str) -> None:
    with pytest.raises(ShadowEvaluationError):
        validate_target_url(url)


async def test_target_roles_are_not_ambiguous() -> None:
    with pytest.raises(ShadowEvaluationError, match="target names"):
        await evaluate_shadow(
            (case(),),
            Target("candidate", "http://legacy.localhost"),
            Target("legacy", "http://candidate.localhost"),
        )


def test_suite_loader_rejects_duplicate_or_write_cases(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    value = case().model_dump_json(by_alias=True)
    path.write_text(f"{value}\n{value}\n", encoding="utf-8")
    with pytest.raises(ShadowEvaluationError, match="duplicate"):
        load_cases(path)

    path.write_text(
        case(id="write", readOnly=False).model_dump_json(by_alias=True),
        encoding="utf-8",
    )
    with pytest.raises(ShadowEvaluationError, match="not read-only"):
        load_cases(path)


def test_case_contract_rejects_missing_expected_tools() -> None:
    with pytest.raises(ValidationError):
        case(expectedTools=[])


async def test_answer_assertions_gate_semantic_evidence_without_leaking_answer(
    tmp_path: Path,
) -> None:
    asserted = case(
        id="order",
        expectedTools=["order_query"],
        forbiddenTools=[],
        answerAssertions={
            "allOf": ["101", "1200", "已支付"],
            "anyOf": [["张三", "customer-1"]],
            "noneOf": ["未找到订单", "查询失败"],
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "legacy.localhost":
            final_answer = "订单 101 金额 1200, 已支付, 客户张三"
        else:
            final_answer = "未找到订单 101, 查询失败"
        body = reply("order", ["order_query"])
        body["finalAnswer"] = final_answer
        return httpx.Response(200, json=body)

    report = await evaluate_shadow(
        (asserted,),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(handler),
    )

    assert report.samples[0].answer_evaluated
    assert report.samples[0].answer_passed
    assert report.samples[0].answer_score == 1
    assert report.samples[1].answer_evaluated
    assert not report.samples[1].answer_passed
    assert report.samples[1].error == "ANSWER_ASSERTION"
    assert report.gate.legacy.answer_pass_rate == 1
    assert report.gate.candidate.answer_pass_rate == 0
    assert any("answer_pass_rate" in item for item in report.gate.regressions)

    output = tmp_path / "semantic-report.json"
    write_report(report, output)
    serialized = output.read_text(encoding="utf-8")
    assert "订单 101 金额" not in serialized
    assert "未找到订单 101" not in serialized


def test_answer_assertions_reject_empty_terms_and_groups() -> None:
    with pytest.raises(ValidationError):
        case(answerAssertions={})
    with pytest.raises(ValidationError):
        case(answerAssertions={"allOf": [" "]})
    with pytest.raises(ValidationError):
        case(answerAssertions={"anyOf": [[]]})


class FakeJudge:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.requests: list[JudgeRequest] = []

    async def score(self, request: JudgeRequest) -> JudgeResult:
        self.requests.append(request)
        return JudgeResult(self.scores.pop(0))


class FailingJudge:
    async def score(self, request: JudgeRequest) -> JudgeResult:
        del request
        raise JudgeError("provider-secret")


async def test_optional_judge_is_default_off_and_only_scores_configured_cases() -> None:
    judged = case(judgeCriteria="Answer faithfully", judgeMinScore=0.7)
    unjudged = case(id="time", judgeCriteria=None)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=reply("goal", ["rag_search"]))
    )

    report = await evaluate_shadow(
        (judged,),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=transport,
    )
    assert all(not sample.judge_evaluated for sample in report.samples)
    assert report.gate.legacy.average_judge_score is None
    assert report.gate.candidate.average_judge_score is None

    judge = FakeJudge([0.9, 0.8])
    report = await evaluate_shadow(
        (judged, unjudged),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=transport,
        judge=judge,
    )
    assert len(judge.requests) == 2
    assert [sample.judge_evaluated for sample in report.samples] == [
        True,
        True,
        False,
        False,
    ]


async def test_judge_low_score_fails_gate_without_persisting_sensitive_content(
    tmp_path: Path,
) -> None:
    judged = case(
        judgeCriteria="Must explain the refund policy and cite a source",
        judgeMinScore=0.7,
    )
    judge = FakeJudge([0.9, 0.6])
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=reply(
                "goal-secret",
                ["rag_search"],
            ),
        )
    )

    report = await evaluate_shadow(
        (judged,),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=transport,
        judge=judge,
    )

    assert report.schema_version == "3"
    assert report.samples[0].judge_passed is True
    assert report.samples[0].judge_score == 0.9
    assert report.samples[1].judge_passed is False
    assert report.samples[1].error == "JUDGE_SCORE_BELOW_THRESHOLD"
    assert report.gate.legacy.average_judge_score == 0.9
    assert report.gate.candidate.average_judge_score == 0.6
    assert any("judge_pass_rate" in item for item in report.gate.regressions)
    assert any("judge_score" in item for item in report.gate.regressions)

    output = tmp_path / "judge-report.json"
    write_report(report, output)
    serialized = output.read_text(encoding="utf-8")
    assert "sensitive business answer" not in serialized
    assert "Must explain the refund policy" not in serialized
    assert "goal-secret" not in serialized


async def test_judge_failure_is_a_sanitized_fail_closed_result() -> None:
    report = await evaluate_shadow(
        (case(judgeCriteria="criteria"),),
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=reply("goal", ["rag_search"]))
        ),
        judge=FailingJudge(),
    )

    assert all(sample.judge_evaluated for sample in report.samples)
    assert all(sample.judge_passed is False for sample in report.samples)
    assert all(sample.judge_score == 0 for sample in report.samples)
    assert all(sample.error == "JUDGE_ERROR" for sample in report.samples)
    assert "provider-secret" not in report.model_dump_json()


def test_judge_case_validation_rejects_blank_or_orphan_threshold() -> None:
    with pytest.raises(ValidationError):
        case(judgeCriteria=" ")
    with pytest.raises(ValidationError):
        case(judgeMinScore=0.8)
    with pytest.raises(ValidationError):
        case(judgeCriteria="criteria", judgeMinScore=1.1)
