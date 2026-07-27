from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class TenantIdentity:
    tenant_id: str
    user_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    department: str | None = None


@dataclass(frozen=True, slots=True)
class RunContext:
    identity: TenantIdentity
    internal_token: str | None
    trace_id: str


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    goal: str = Field(min_length=1, max_length=20_000)
    webhook_url: str | None = Field(default=None, alias="webhookUrl")


class AgentStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    n: int
    thought: str = ""
    action: str = ""
    action_input: str = Field(default="", alias="actionInput")
    observation: str = ""


class AgentRunReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goal: str
    steps: list[AgentStep] = Field(default_factory=list)
    final_answer: str = Field(alias="finalAnswer")
    stop_reason: str = Field(alias="stopReason")
    depth: int = 0
    tenant_id: str = Field(alias="tenantId")


@dataclass(frozen=True, slots=True)
class AgentExecution:
    final_answer: str
    stop_reason: str = "DONE"
    steps: tuple[AgentStep, ...] = ()
    depth: int = 0
