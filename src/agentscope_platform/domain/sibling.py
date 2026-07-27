from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VotingStrategy(StrEnum):
    MAJORITY = "majority"
    SYNTHESIS = "synthesis"


class ChainStepDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    instruction: str = Field(min_length=1, max_length=20_000)
    gate_min_length: int = Field(default=0, ge=0, alias="gateMinLength")
    gate_must_contain: str | None = Field(default=None, alias="gateMustContain")
    gate_must_match: str | None = Field(default=None, alias="gateMustMatch")


class ChainRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    input: str | None = None


class ChainStepResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    output: str
    gate_passed: bool = Field(alias="gatePassed")
    gate_reason: str = Field(alias="gateReason")


class ChainRunReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input: str
    steps: list[ChainStepResult]
    final_output: str = Field(alias="finalOutput")
    completed: bool
    tenant_id: str = Field(alias="tenantId")


class VoteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    question: str | None = None
    n: int | None = None


class VoteReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str
    votes: list[str]
    strategy: VotingStrategy
    decision: str
    agreement: float | None
    confident: bool
    tenant_id: str = Field(alias="tenantId")


class ReflexionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    question: str | None = None


class ReflexionAttempt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    n: int
    answer: str
    aggregate: float = Field(ge=0, le=1)
    correctness: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    clarity: float = Field(ge=0, le=1)
    main_issue: str = Field(alias="mainIssue")


class ReflexionReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str
    final_answer: str = Field(alias="finalAnswer")
    attempts: list[ReflexionAttempt]
    accepted_by_threshold: bool = Field(alias="acceptedByThreshold")
    tenant_id: str = Field(alias="tenantId")
