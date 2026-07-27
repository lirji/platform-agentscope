from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentscope_platform.domain.agent import AgentRunReply


class AgentDagTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str | None = None
    description: str | None = None
    depends_on: list[str] | None = Field(default=None, alias="dependsOn")


class DagPlanKind(StrEnum):
    GENERAL = "general"
    ANALYST = "analyst"
    PROCESS = "process"


class DagPlanTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=20_000)
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")

    @field_validator("id", "description")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class DagPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    tasks: list[DagPlanTask] = Field(default_factory=list, max_length=6)


class AgentDagRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    goal: str | None = None
    tasks: list[AgentDagTask] | None = None
    webhook_url: str | None = Field(default=None, alias="webhookUrl")


class AgentPlanRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    goal: str | None = None
    webhook_url: str | None = Field(default=None, alias="webhookUrl")


class AgentDagTaskResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(alias="taskId")
    description: str
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    result: AgentRunReply


class AgentDagCritique(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    correctness: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    clarity: float = Field(ge=0, le=1)
    main_issue: str = Field(min_length=1, max_length=2_000, alias="mainIssue")


class AgentDagAttempt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    n: int
    levels: list[list[str]] = Field(default_factory=list)
    task_results: list[AgentDagTaskResult] = Field(
        default_factory=list,
        alias="taskResults",
    )
    synthesis: AgentRunReply
    critique: AgentDagCritique | None = None
    aggregate: float | None = None


class AgentDagRunReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goal: str
    levels: list[list[str]] = Field(default_factory=list)
    task_results: list[AgentDagTaskResult] = Field(
        default_factory=list,
        alias="taskResults",
    )
    synthesis: AgentRunReply
    tenant_id: str = Field(alias="tenantId")
    attempts: list[AgentDagAttempt] = Field(default_factory=list)
    accepted_by_threshold: bool = Field(
        default=True,
        alias="acceptedByThreshold",
    )
