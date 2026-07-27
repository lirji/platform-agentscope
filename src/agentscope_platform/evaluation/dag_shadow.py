from dataclasses import dataclass
from pathlib import Path
from time import monotonic

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentscope_platform.domain.dag import AgentDagRunReply, AgentDagRunRequest
from agentscope_platform.evaluation.shadow import (
    MAX_RESPONSE_BYTES,
    ShadowEvaluationError,
    Target,
    validate_target_url,
)


class DagShadowCase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    request: AgentDagRunRequest
    expected_levels: list[list[str]] = Field(alias="expectedLevels")
    read_only: bool = Field(alias="readOnly")


class DagShadowSample(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    case_id: str = Field(alias="caseId")
    target: str
    passed: bool
    status_code: int | None = Field(default=None, alias="statusCode")
    latency_ms: int = Field(alias="latencyMs")
    error: str | None = None


class DagShadowReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    suite: str
    passed: bool
    samples: list[DagShadowSample]


@dataclass(frozen=True, slots=True)
class _ValidatedTarget:
    name: str
    base_url: str
    auth_header: str
    auth_token: str


def load_dag_cases(path: Path) -> tuple[DagShadowCase, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ShadowEvaluationError(f"unable to read suite: {path}") from exc

    cases: list[DagShadowCase] = []
    ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            case = DagShadowCase.model_validate_json(line)
        except ValidationError as exc:
            raise ShadowEvaluationError(f"invalid DAG suite case at line {line_number}") from exc
        if not case.read_only:
            raise ShadowEvaluationError(f"DAG suite case is not read-only: {case.id}")
        if case.id in ids:
            raise ShadowEvaluationError(f"duplicate DAG suite case id: {case.id}")
        task_ids = [task.id for task in case.request.tasks or ()]
        expected_ids = [task_id for level in case.expected_levels for task_id in level]
        if (
            not task_ids
            or len(task_ids) != len(set(task_ids))
            or len(expected_ids) != len(set(expected_ids))
            or set(task_ids) != set(expected_ids)
        ):
            raise ShadowEvaluationError(f"invalid expected DAG levels: {case.id}")
        ids.add(case.id)
        cases.append(case)
    if not cases:
        raise ShadowEvaluationError("DAG suite contains no cases")
    return tuple(cases)


async def evaluate_dag_shadow(
    cases: tuple[DagShadowCase, ...],
    legacy: Target,
    candidate: Target,
    *,
    timeout_seconds: float = 120,
    allow_remote_targets: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
    suite_name: str = "dag-cases",
) -> DagShadowReport:
    if timeout_seconds <= 0:
        raise ShadowEvaluationError("timeout must be greater than 0")
    if legacy.name != "legacy" or candidate.name != "candidate":
        raise ShadowEvaluationError("target names must be legacy and candidate")

    targets = tuple(
        _ValidatedTarget(
            name=target.name,
            base_url=validate_target_url(target.base_url, allow_remote_targets),
            auth_header=target.auth_header,
            auth_token=target.auth_token,
        )
        for target in (legacy, candidate)
    )
    samples: list[DagShadowSample] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        transport=transport,
    ) as client:
        for case in cases:
            for target in targets:
                samples.append(await _execute(client, case, target))
    return DagShadowReport(
        suite=suite_name,
        passed=all(sample.passed for sample in samples),
        samples=samples,
    )


async def _execute(
    client: httpx.AsyncClient,
    case: DagShadowCase,
    target: _ValidatedTarget,
) -> DagShadowSample:
    headers = {"Content-Type": "application/json"}
    if target.auth_token:
        headers[target.auth_header] = target.auth_token
    started = monotonic()
    try:
        response = await client.post(
            f"{target.base_url}/agent/dag/run",
            json=case.request.model_dump(by_alias=True, exclude_none=True),
            headers=headers,
        )
    except httpx.HTTPError:
        return _failed(case, target, started, "NETWORK_ERROR")

    if response.is_error:
        return _failed(
            case,
            target,
            started,
            f"HTTP_{response.status_code}",
            response.status_code,
        )
    if len(response.content) > MAX_RESPONSE_BYTES:
        return _failed(
            case,
            target,
            started,
            "RESPONSE_TOO_LARGE",
            response.status_code,
        )
    try:
        reply = AgentDagRunReply.model_validate_json(response.content)
    except (ValidationError, ValueError):
        return _failed(
            case,
            target,
            started,
            "INVALID_CONTRACT",
            response.status_code,
        )

    expected_task_ids = [task_id for level in case.expected_levels for task_id in level]
    actual_task_ids = [result.task_id for result in reply.task_results]
    tenant_ids = {
        reply.tenant_id,
        reply.synthesis.tenant_id,
        *(result.result.tenant_id for result in reply.task_results),
    }
    error: str | None = None
    if reply.goal != (case.request.goal or "").strip():
        error = "GOAL_MISMATCH"
    elif reply.levels != case.expected_levels:
        error = "LEVELS_MISMATCH"
    elif actual_task_ids != expected_task_ids:
        error = "TASK_ORDER_MISMATCH"
    elif any(
        result.description != (task.description or "").strip()
        or result.depends_on != (task.depends_on or [])
        for result, task in zip(
            reply.task_results,
            [
                next(task for task in case.request.tasks or () if task.id == task_id)
                for task_id in expected_task_ids
            ],
            strict=True,
        )
    ):
        error = "TASK_CONTRACT_MISMATCH"
    elif len(tenant_ids) != 1:
        error = "TENANT_MISMATCH"
    elif reply.synthesis.stop_reason != "DONE" or not reply.synthesis.final_answer.strip():
        error = "SYNTHESIS_INCOMPLETE"
    return DagShadowSample(
        caseId=case.id,
        target=target.name,
        passed=error is None,
        statusCode=response.status_code,
        latencyMs=_elapsed_ms(started),
        error=error,
    )


def _failed(
    case: DagShadowCase,
    target: _ValidatedTarget,
    started: float,
    error: str,
    status_code: int | None = None,
) -> DagShadowSample:
    return DagShadowSample(
        caseId=case.id,
        target=target.name,
        passed=False,
        statusCode=status_code,
        latencyMs=_elapsed_ms(started),
        error=error,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))
