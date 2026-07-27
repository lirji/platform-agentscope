import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from pydantic import ValidationError

from agentscope_platform.domain.agent import AgentRunReply
from agentscope_platform.evaluation.models import (
    GateResult,
    RunSample,
    ShadowCase,
    ShadowReport,
    ShadowThresholds,
    TargetSummary,
)

MAX_RESPONSE_BYTES = 2_000_000


class ShadowEvaluationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    base_url: str
    auth_header: str = "X-Internal-Token"
    auth_token: str = ""


def load_cases(path: Path) -> tuple[ShadowCase, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ShadowEvaluationError(f"unable to read suite: {path}") from exc

    cases: list[ShadowCase] = []
    ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            case = ShadowCase.model_validate_json(line)
        except ValidationError as exc:
            raise ShadowEvaluationError(f"invalid suite case at line {line_number}") from exc
        if not case.read_only:
            raise ShadowEvaluationError(f"suite case is not read-only: {case.id}")
        if case.id in ids:
            raise ShadowEvaluationError(f"duplicate suite case id: {case.id}")
        ids.add(case.id)
        cases.append(case)
    if not cases:
        raise ShadowEvaluationError("suite contains no cases")
    return tuple(cases)


def validate_target_url(value: str, allow_remote: bool = False) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ShadowEvaluationError("target URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ShadowEvaluationError("target URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ShadowEvaluationError("target URL must not contain query or fragment")

    hostname = parsed.hostname.lower()
    is_local = hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".localhost")
    if not is_local and not allow_remote:
        raise ShadowEvaluationError("remote targets require explicit --allow-remote-targets opt-in")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


async def evaluate_shadow(
    cases: tuple[ShadowCase, ...],
    legacy: Target,
    candidate: Target,
    *,
    runs: int = 1,
    timeout_seconds: float = 120,
    thresholds: ShadowThresholds | None = None,
    allow_remote_targets: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
    suite_name: str = "readonly-cases",
) -> ShadowReport:
    if runs < 1:
        raise ShadowEvaluationError("runs must be at least 1")
    if timeout_seconds <= 0:
        raise ShadowEvaluationError("timeout must be greater than 0")
    if legacy.name != "legacy" or candidate.name != "candidate":
        raise ShadowEvaluationError("target names must be legacy and candidate")

    normalized_targets = (
        Target(
            legacy.name,
            validate_target_url(legacy.base_url, allow_remote_targets),
            legacy.auth_header,
            legacy.auth_token,
        ),
        Target(
            candidate.name,
            validate_target_url(candidate.base_url, allow_remote_targets),
            candidate.auth_header,
            candidate.auth_token,
        ),
    )
    samples: list[RunSample] = []
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        for case in cases:
            for run_number in range(1, runs + 1):
                for target in normalized_targets:
                    samples.append(
                        await _execute(
                            client,
                            case,
                            target,
                            run_number,
                            uuid4().hex,
                        ),
                    )

    legacy_summary = summarize("legacy", samples)
    candidate_summary = summarize("candidate", samples)
    gate = evaluate_gate(
        legacy_summary,
        candidate_summary,
        thresholds or ShadowThresholds(),
    )
    return ShadowReport(
        suite=suite_name,
        generated_at=datetime.now(UTC),
        runs_per_case=runs,
        gate=gate,
        samples=tuple(samples),
    )


async def _execute(
    client: httpx.AsyncClient,
    case: ShadowCase,
    target: Target,
    run_number: int,
    trace_id: str,
) -> RunSample:
    headers = {
        "Content-Type": "application/json",
        "X-Trace-Id": trace_id,
        "traceparent": f"00-{trace_id}-{uuid4().hex[:16]}-01",
    }
    if target.auth_token:
        headers[target.auth_header] = target.auth_token
    started = monotonic()
    try:
        response = await client.post(
            f"{target.base_url}/agent/run",
            json={"goal": case.goal},
            headers=headers,
        )
    except httpx.HTTPError:
        return _failed_sample(
            case,
            target,
            run_number,
            started,
            "NETWORK_ERROR",
            trace_id=trace_id,
        )

    latency_ms = _elapsed_ms(started)
    if response.is_error:
        return _failed_sample(
            case,
            target,
            run_number,
            started,
            f"HTTP_{response.status_code}",
            status_code=response.status_code,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )
    if len(response.content) > MAX_RESPONSE_BYTES:
        return _failed_sample(
            case,
            target,
            run_number,
            started,
            "RESPONSE_TOO_LARGE",
            status_code=response.status_code,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )
    try:
        reply = AgentRunReply.model_validate_json(response.content)
    except (ValidationError, ValueError):
        return _failed_sample(
            case,
            target,
            run_number,
            started,
            "INVALID_CONTRACT",
            status_code=response.status_code,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )

    tools = tuple(step.action for step in reply.steps if step.action)
    tool_set = set(tools)
    missing = tuple(tool for tool in case.expected_tools if tool not in tool_set)
    forbidden = tuple(tool for tool in case.forbidden_tools if tool in tool_set)
    tool_score = sum(tool in tool_set for tool in case.expected_tools) / len(case.expected_tools)
    tool_order_valid = _is_subsequence(case.expected_tools, tools)
    completed = reply.stop_reason == "DONE" and bool(reply.final_answer.strip())
    answer_evaluated, answer_passed, answer_score = _evaluate_answer(
        reply.final_answer,
        case,
    )
    passed = completed and not missing and not forbidden and tool_order_valid and answer_passed
    error = None
    if forbidden:
        error = "FORBIDDEN_TOOL"
    elif missing:
        error = "EXPECTED_TOOL_MISSING"
    elif not tool_order_valid:
        error = "EXPECTED_TOOL_ORDER"
    elif not completed:
        error = "NOT_COMPLETED"
    elif not answer_passed:
        error = "ANSWER_ASSERTION"
    return RunSample(
        case_id=case.id,
        target=target.name,
        run=run_number,
        trace_id=trace_id,
        status_code=response.status_code,
        latency_ms=latency_ms,
        contract_valid=True,
        completed=completed,
        passed=passed,
        stop_reason=reply.stop_reason,
        tools=tools,
        missing_tools=missing,
        forbidden_tools=forbidden,
        tool_order_valid=tool_order_valid,
        tool_score=tool_score,
        answer_evaluated=answer_evaluated,
        answer_passed=answer_passed,
        answer_score=answer_score,
        error=error,
    )


def _failed_sample(
    case: ShadowCase,
    target: Target,
    run_number: int,
    started: float,
    error: str,
    *,
    status_code: int = 0,
    latency_ms: int | None = None,
    trace_id: str = "",
) -> RunSample:
    answer_evaluated = case.answer_assertions is not None
    return RunSample(
        case_id=case.id,
        target=target.name,
        run=run_number,
        trace_id=trace_id,
        status_code=status_code,
        latency_ms=_elapsed_ms(started) if latency_ms is None else latency_ms,
        contract_valid=False,
        completed=False,
        passed=False,
        missing_tools=case.expected_tools,
        answer_evaluated=answer_evaluated,
        answer_passed=not answer_evaluated,
        answer_score=0 if answer_evaluated else 1,
        error=error,
    )


def summarize(name: str, samples: list[RunSample]) -> TargetSummary:
    selected = [sample for sample in samples if sample.target == name]
    if not selected:
        raise ShadowEvaluationError(f"no samples for target: {name}")
    stop_reasons: dict[str, int] = {}
    for sample in selected:
        reason = sample.stop_reason or sample.error or "UNKNOWN"
        stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
    total = len(selected)
    answer_samples = [sample for sample in selected if sample.answer_evaluated]
    return TargetSummary(
        name=name,
        total_runs=total,
        passed_runs=sum(sample.passed for sample in selected),
        pass_rate=sum(sample.passed for sample in selected) / total,
        completion_rate=sum(sample.completed for sample in selected) / total,
        tool_accuracy=sum(sample.tool_score for sample in selected) / total,
        forbidden_violations=sum(bool(sample.forbidden_tools) for sample in selected),
        contract_errors=sum(not sample.contract_valid for sample in selected),
        p95_latency_ms=_percentile95([sample.latency_ms for sample in selected]),
        stop_reasons=stop_reasons,
        answer_evaluated_runs=len(answer_samples),
        answer_pass_rate=(
            sum(sample.answer_passed for sample in answer_samples) / len(answer_samples)
            if answer_samples
            else 1
        ),
    )


def evaluate_gate(
    legacy: TargetSummary,
    candidate: TargetSummary,
    thresholds: ShadowThresholds,
) -> GateResult:
    regressions: list[str] = []
    _absolute_rate_gate(
        regressions,
        "minimum_pass_rate",
        candidate.pass_rate,
        thresholds.min_pass_rate,
    )
    _absolute_rate_gate(
        regressions,
        "minimum_completion_rate",
        candidate.completion_rate,
        thresholds.min_completion_rate,
    )
    _absolute_rate_gate(
        regressions,
        "minimum_tool_accuracy",
        candidate.tool_accuracy,
        thresholds.min_tool_accuracy,
    )
    _relative_rate_gate(
        regressions,
        "pass_rate",
        legacy.pass_rate,
        candidate.pass_rate,
        thresholds.pass_rate_tolerance,
    )
    _relative_rate_gate(
        regressions,
        "completion_rate",
        legacy.completion_rate,
        candidate.completion_rate,
        thresholds.completion_rate_tolerance,
    )
    _relative_rate_gate(
        regressions,
        "tool_accuracy",
        legacy.tool_accuracy,
        candidate.tool_accuracy,
        thresholds.tool_accuracy_tolerance,
    )
    if legacy.answer_evaluated_runs or candidate.answer_evaluated_runs:
        _absolute_rate_gate(
            regressions,
            "minimum_answer_pass_rate",
            candidate.answer_pass_rate,
            thresholds.min_answer_pass_rate,
        )
        _relative_rate_gate(
            regressions,
            "answer_pass_rate",
            legacy.answer_pass_rate,
            candidate.answer_pass_rate,
            thresholds.answer_pass_rate_tolerance,
        )
    if candidate.forbidden_violations:
        regressions.append(
            f"forbidden_tool regression: candidate executed "
            f"{candidate.forbidden_violations} forbidden tool(s)"
        )
    if legacy.contract_errors:
        regressions.append(
            f"legacy_contract invalid: {legacy.contract_errors} response(s) failed validation"
        )
    if candidate.contract_errors:
        regressions.append(
            f"candidate_contract regression: {candidate.contract_errors} response(s) "
            "failed validation"
        )
    p95_limit = math.ceil(
        legacy.p95_latency_ms * thresholds.p95_latency_ratio + thresholds.p95_latency_slack_ms
    )
    if candidate.p95_latency_ms > p95_limit:
        regressions.append(
            f"p95_latency regression: candidate {candidate.p95_latency_ms}ms > limit {p95_limit}ms"
        )
    return GateResult(
        passed=not regressions,
        regressions=tuple(regressions),
        thresholds=thresholds,
        legacy=legacy,
        candidate=candidate,
    )


def _absolute_rate_gate(
    regressions: list[str],
    metric: str,
    candidate_value: float,
    minimum: float,
) -> None:
    if candidate_value + 1e-9 < minimum:
        regressions.append(
            f"{metric} regression: candidate {candidate_value:.4f} < minimum {minimum:.4f}"
        )


def _relative_rate_gate(
    regressions: list[str],
    metric: str,
    legacy_value: float,
    candidate_value: float,
    tolerance: float,
) -> None:
    limit = max(0.0, legacy_value - tolerance)
    if candidate_value + 1e-9 < limit:
        regressions.append(
            f"{metric} regression: candidate {candidate_value:.4f} "
            f"< legacy {legacy_value:.4f} - tolerance {tolerance:.4f}"
        )


def _percentile95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def _elapsed_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _is_subsequence(expected: tuple[str, ...], actual: tuple[str, ...]) -> bool:
    expected_index = 0
    for tool in actual:
        if tool == expected[expected_index]:
            expected_index += 1
            if expected_index == len(expected):
                return True
    return False


def _evaluate_answer(
    answer: str,
    case: ShadowCase,
) -> tuple[bool, bool, float]:
    assertions = case.answer_assertions
    if assertions is None:
        return False, True, 1

    normalized = answer.casefold()
    checks = [
        *(term.casefold() in normalized for term in assertions.all_of),
        *(any(term.casefold() in normalized for term in group) for group in assertions.any_of),
        *(term.casefold() not in normalized for term in assertions.none_of),
    ]
    passed_checks = sum(checks)
    return True, passed_checks == len(checks), passed_checks / len(checks)


def write_report(report: ShadowReport, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                report.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ShadowEvaluationError(f"unable to write report: {path}") from exc
