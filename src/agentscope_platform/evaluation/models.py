from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AnswerAssertions(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    all_of: tuple[str, ...] = Field(default=(), alias="allOf")
    any_of: tuple[tuple[str, ...], ...] = Field(default=(), alias="anyOf")
    none_of: tuple[str, ...] = Field(default=(), alias="noneOf")

    @field_validator("all_of", "none_of")
    @classmethod
    def normalize_terms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(term.strip() for term in value)
        if any(not term for term in normalized):
            raise ValueError("answer assertion terms must not be blank")
        return normalized

    @field_validator("any_of")
    @classmethod
    def normalize_groups(
        cls,
        value: tuple[tuple[str, ...], ...],
    ) -> tuple[tuple[str, ...], ...]:
        normalized = tuple(tuple(term.strip() for term in group) for group in value)
        if any(not group or any(not term for term in group) for group in normalized):
            raise ValueError("answer assertion alternative groups must contain non-blank terms")
        return normalized

    @model_validator(mode="after")
    def require_at_least_one_check(self) -> "AnswerAssertions":
        if not self.all_of and not self.any_of and not self.none_of:
            raise ValueError("answer assertions must contain at least one check")
        return self


class ShadowCase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    expected_tools: tuple[str, ...] = Field(alias="expectedTools", min_length=1)
    forbidden_tools: tuple[str, ...] = Field(default=(), alias="forbiddenTools")
    read_only: bool = Field(alias="readOnly")
    answer_assertions: AnswerAssertions | None = Field(
        default=None,
        alias="answerAssertions",
    )


class RunSample(BaseModel):
    case_id: str
    target: str
    run: int
    trace_id: str = ""
    status_code: int
    latency_ms: int
    contract_valid: bool
    completed: bool
    passed: bool
    stop_reason: str | None = None
    tools: tuple[str, ...] = ()
    missing_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    tool_order_valid: bool = False
    tool_score: float = 0
    answer_evaluated: bool = False
    answer_passed: bool = True
    answer_score: float = 1
    error: str | None = None


class TargetSummary(BaseModel):
    name: str
    total_runs: int
    passed_runs: int
    pass_rate: float
    completion_rate: float
    tool_accuracy: float
    forbidden_violations: int
    contract_errors: int
    p95_latency_ms: int
    stop_reasons: dict[str, int]
    answer_evaluated_runs: int = 0
    answer_pass_rate: float = 1


class ShadowThresholds(BaseModel):
    min_pass_rate: float = Field(default=0.8, ge=0, le=1)
    min_completion_rate: float = Field(default=0.8, ge=0, le=1)
    min_tool_accuracy: float = Field(default=0.8, ge=0, le=1)
    pass_rate_tolerance: float = Field(default=0.05, ge=0, le=1)
    completion_rate_tolerance: float = Field(default=0.05, ge=0, le=1)
    tool_accuracy_tolerance: float = Field(default=0.05, ge=0, le=1)
    min_answer_pass_rate: float = Field(default=0.8, ge=0, le=1)
    answer_pass_rate_tolerance: float = Field(default=0.05, ge=0, le=1)
    p95_latency_ratio: float = Field(default=1.5, ge=0)
    p95_latency_slack_ms: int = Field(default=250, ge=0)


class GateResult(BaseModel):
    passed: bool
    regressions: tuple[str, ...]
    thresholds: ShadowThresholds
    legacy: TargetSummary
    candidate: TargetSummary


class ShadowReport(BaseModel):
    schema_version: str = "2"
    suite: str
    generated_at: datetime
    runs_per_case: int
    gate: GateResult
    samples: tuple[RunSample, ...]
