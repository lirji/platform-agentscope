from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentscope_platform.evaluation.shadow import ShadowEvaluationError


class SiblingCase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    endpoint: Literal[
        "/agent/chain",
        "/agent/vote",
        "/agent/reflexive",
    ]
    request: dict[str, object]
    expected_strategy: Literal["majority", "synthesis"] | None = Field(
        default=None,
        alias="expectedStrategy",
    )
    expected_step_names: list[str] = Field(
        default_factory=list,
        alias="expectedStepNames",
    )
    read_only: bool = Field(alias="readOnly")


def load_sibling_cases(path: Path) -> tuple[SiblingCase, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ShadowEvaluationError(f"unable to read suite: {path}") from exc

    cases: list[SiblingCase] = []
    ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            case = SiblingCase.model_validate_json(line)
        except ValidationError as exc:
            raise ShadowEvaluationError(
                f"invalid sibling suite case at line {line_number}"
            ) from exc
        if not case.read_only:
            raise ShadowEvaluationError(f"sibling suite case is not read-only: {case.id}")
        if case.id in ids:
            raise ShadowEvaluationError(f"duplicate sibling suite case id: {case.id}")
        if case.endpoint == "/agent/chain":
            if not str(case.request.get("input", "")).strip():
                raise ShadowEvaluationError(f"chain input is blank: {case.id}")
            if "steps" in case.request:
                raise ShadowEvaluationError(f"chain case contains caller-defined steps: {case.id}")
        else:
            if not str(case.request.get("question", "")).strip():
                raise ShadowEvaluationError(f"sibling question is blank: {case.id}")
        ids.add(case.id)
        cases.append(case)
    if not cases:
        raise ShadowEvaluationError("sibling suite contains no cases")
    return tuple(cases)
