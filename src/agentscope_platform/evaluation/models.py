import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentscope_platform.domain.agent import ExecutionVersions


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
    judge_criteria: str | None = Field(
        default=None,
        alias="judgeCriteria",
        max_length=4000,
    )
    judge_min_score: float | None = Field(
        default=None,
        alias="judgeMinScore",
        ge=0,
        le=1,
    )

    @field_validator("judge_criteria")
    @classmethod
    def normalize_judge_criteria(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("judge criteria must not be blank")
        return normalized

    @model_validator(mode="after")
    def reject_judge_threshold_without_criteria(self) -> "ShadowCase":
        if self.judge_criteria is None and self.judge_min_score is not None:
            raise ValueError("judge minimum score requires judge criteria")
        return self


class EvaluationDatasetReference(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["agent-evaluation-dataset-ref.v1"] = Field(
        default="agent-evaluation-dataset-ref.v1",
        alias="schemaVersion",
    )
    dataset_id: str = Field(
        alias="datasetId",
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    version: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    kind: Literal["baseline", "adversarial", "feedback"]


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["agent-evaluation-dataset.v1"] = Field(
        default="agent-evaluation-dataset.v1",
        alias="schemaVersion",
    )
    dataset_id: str = Field(
        alias="datasetId",
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    version: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    kind: Literal["baseline", "adversarial", "feedback"]
    created_at: datetime = Field(alias="createdAt")
    cases: tuple[ShadowCase, ...] = Field(min_length=1)
    source_sha256: str | None = Field(
        default=None,
        alias="sourceSha256",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_dataset(self) -> "EvaluationDataset":
        if any(not case.read_only for case in self.cases):
            raise ValueError("evaluation datasets must contain read-only cases")
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("evaluation dataset case ids must be unique")
        if self.kind == "adversarial" and any(not case.forbidden_tools for case in self.cases):
            raise ValueError("adversarial cases must declare forbidden tools")
        if self.version != computed_dataset_version(
            self.dataset_id,
            self.kind,
            self.cases,
        ):
            raise ValueError("evaluation dataset version does not match its content")
        return self

    def reference(self) -> EvaluationDatasetReference:
        return EvaluationDatasetReference(
            datasetId=self.dataset_id,
            version=self.version,
            kind=self.kind,
        )


class OnlineFeedbackRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["agent-online-feedback.v1"] = Field(alias="schemaVersion")
    feedback_id: str = Field(alias="feedbackId", min_length=1, max_length=256)
    goal: str = Field(min_length=1, max_length=20_000)
    rating: Literal["positive", "negative"]
    consent_for_evaluation: bool = Field(alias="consentForEvaluation")
    read_only: bool = Field(alias="readOnly")
    expected_tools: tuple[str, ...] = Field(alias="expectedTools", min_length=1)
    forbidden_tools: tuple[str, ...] = Field(default=(), alias="forbiddenTools")


class ReplayReference(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["agent-evaluation-replay.v1"] = Field(
        default="agent-evaluation-replay.v1",
        alias="schemaVersion",
    )
    report_sha256: str = Field(
        alias="reportSha256",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    original_generated_at: datetime = Field(alias="originalGeneratedAt")


def computed_dataset_version(
    dataset_id: str,
    kind: Literal["baseline", "adversarial", "feedback"],
    cases: tuple[ShadowCase, ...],
) -> str:
    canonical = json.dumps(
        {
            "datasetId": dataset_id,
            "kind": kind,
            "cases": [case.model_dump(by_alias=True, mode="json") for case in cases],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def unspecified_dataset_reference() -> EvaluationDatasetReference:
    return EvaluationDatasetReference(
        datasetId="legacy-unspecified",
        version="sha256:" + "0" * 64,
        kind="baseline",
    )


class GovernedToolCase(BaseModel):
    """Offline-only parity and safety case for a side-effect tool.

    These cases are deliberately separate from ``ShadowCase`` so the normal
    read-only shadow runner can never execute a business side effect.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    legacy_action: str = Field(alias="legacyAction", min_length=1, max_length=64)
    candidate_tool: str = Field(alias="candidateTool", min_length=1, max_length=64)
    execution_mode: Literal["stub_only"] = Field(alias="executionMode")
    read_only: bool = Field(alias="readOnly")
    confirmed: bool
    idempotency_key_present: bool = Field(alias="idempotencyKeyPresent")
    expected_policy: Literal[
        "allowed",
        "confirmation_required",
        "idempotency_required",
        "allowlist_denied",
        "arguments_rejected",
        "host_denied",
        "input_rejected",
        "provider_error",
    ] = Field(alias="expectedPolicy")
    expected_provider_calls: int = Field(alias="expectedProviderCalls", ge=0, le=2)
    expected_result: Literal[
        "DENIED",
        "WAITING_APPROVAL",
        "COMPLETED",
        "DEDUPLICATED",
        "PROVIDER_ERROR",
        "TIMED_OUT",
        "TRUNCATED",
    ] = Field(alias="expectedResult")

    @model_validator(mode="after")
    def validate_safety_expectations(self) -> "GovernedToolCase":
        denied = self.expected_policy in {
            "confirmation_required",
            "idempotency_required",
            "allowlist_denied",
            "arguments_rejected",
            "host_denied",
            "input_rejected",
        }
        if denied and self.expected_provider_calls != 0:
            raise ValueError("policy-denied cases cannot call the provider")
        if denied and self.expected_result != "DENIED":
            raise ValueError("policy-denied cases must expect DENIED")
        if self.expected_policy == "allowed" and not self.read_only:
            if not self.confirmed or not self.idempotency_key_present:
                raise ValueError("allowed side-effect cases require confirmation and idempotency")
        if self.expected_policy == "allowed":
            if self.expected_provider_calls == 0:
                raise ValueError("allowed cases must call the provider")
        if self.expected_result == "DEDUPLICATED" and self.expected_provider_calls != 2:
            raise ValueError("deduplication cases must perform two stub calls")
        return self


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
    judge_evaluated: bool = False
    judge_passed: bool | None = None
    judge_score: float | None = None
    versions: ExecutionVersions | None = None
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
    judge_evaluated_runs: int = 0
    judge_pass_rate: float = 1
    average_judge_score: float | None = None


class ShadowThresholds(BaseModel):
    min_pass_rate: float = Field(default=0.8, ge=0, le=1)
    min_completion_rate: float = Field(default=0.8, ge=0, le=1)
    min_tool_accuracy: float = Field(default=0.8, ge=0, le=1)
    pass_rate_tolerance: float = Field(default=0.05, ge=0, le=1)
    completion_rate_tolerance: float = Field(default=0.05, ge=0, le=1)
    tool_accuracy_tolerance: float = Field(default=0.05, ge=0, le=1)
    min_answer_pass_rate: float = Field(default=0.8, ge=0, le=1)
    answer_pass_rate_tolerance: float = Field(default=0.05, ge=0, le=1)
    min_judge_pass_rate: float = Field(default=0.8, ge=0, le=1)
    judge_pass_rate_tolerance: float = Field(default=0.05, ge=0, le=1)
    judge_score_tolerance: float = Field(default=0.05, ge=0, le=1)
    p95_latency_ratio: float = Field(default=1.5, ge=0)
    p95_latency_slack_ms: int = Field(default=250, ge=0)


class GateResult(BaseModel):
    passed: bool
    regressions: tuple[str, ...]
    thresholds: ShadowThresholds
    legacy: TargetSummary
    candidate: TargetSummary


class ShadowReport(BaseModel):
    schema_version: str = "4"
    suite: str
    generated_at: datetime
    runs_per_case: int
    dataset: EvaluationDatasetReference = Field(default_factory=unspecified_dataset_reference)
    replay: ReplayReference | None = None
    gate: GateResult
    samples: tuple[RunSample, ...]
