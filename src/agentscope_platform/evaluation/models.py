from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShadowCase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    expected_tools: tuple[str, ...] = Field(alias="expectedTools", min_length=1)
    forbidden_tools: tuple[str, ...] = Field(default=(), alias="forbiddenTools")
    read_only: bool = Field(alias="readOnly")


class RunSample(BaseModel):
    case_id: str
    target: str
    run: int
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


class ShadowThresholds(BaseModel):
    min_pass_rate: float = Field(default=0.8, ge=0, le=1)
    min_completion_rate: float = Field(default=0.8, ge=0, le=1)
    min_tool_accuracy: float = Field(default=0.8, ge=0, le=1)
    pass_rate_tolerance: float = Field(default=0.05, ge=0, le=1)
    completion_rate_tolerance: float = Field(default=0.05, ge=0, le=1)
    tool_accuracy_tolerance: float = Field(default=0.05, ge=0, le=1)
    p95_latency_ratio: float = Field(default=1.5, ge=0)
    p95_latency_slack_ms: int = Field(default=250, ge=0)


class GateResult(BaseModel):
    passed: bool
    regressions: tuple[str, ...]
    thresholds: ShadowThresholds
    legacy: TargetSummary
    candidate: TargetSummary


class ShadowReport(BaseModel):
    schema_version: str = "1"
    suite: str
    generated_at: datetime
    runs_per_case: int
    gate: GateResult
    samples: tuple[RunSample, ...]
