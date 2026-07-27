from pydantic import BaseModel, ConfigDict, Field

from agentscope_platform.domain.agent import AgentRunReply


class AgentDagTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str | None = None
    description: str | None = None
    depends_on: list[str] | None = Field(default=None, alias="dependsOn")


class AgentDagRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    goal: str | None = None
    tasks: list[AgentDagTask] | None = None
    webhook_url: str | None = Field(default=None, alias="webhookUrl")


class AgentDagTaskResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(alias="taskId")
    description: str
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    result: AgentRunReply


class AgentDagCritique(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    correctness: float
    completeness: float
    clarity: float
    main_issue: str = Field(alias="mainIssue")


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
