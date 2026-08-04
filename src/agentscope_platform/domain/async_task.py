from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AsyncTaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {
            AsyncTaskStatus.SUCCEEDED,
            AsyncTaskStatus.FAILED,
            AsyncTaskStatus.CANCELLED,
        }


class AgentTaskKind(StrEnum):
    RUN = "agent.run"
    DAG = "agent.dag"
    DAG_PLAN = "agent.dag-plan"
    ANALYST = "agent.analyst"
    PROCESS = "agent.process"


AGENT_TASK_KINDS = frozenset(kind.value for kind in AgentTaskKind)


class CentralAsyncTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    task_id: str = Field(alias="taskId")
    tenant_id: str = Field(alias="tenantId")
    user_id: str = Field(alias="userId")
    kind: str
    status: AsyncTaskStatus
    input: dict[str, Any] = Field(default_factory=dict)
    result: Any | None = None
    error: str | None = None
    webhook_url: str | None = Field(default=None, alias="webhookUrl")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    lease_owner_id: str | None = Field(default=None, alias="leaseOwnerId")
    lease_expires_at: datetime | None = Field(default=None, alias="leaseExpiresAt")
    lease_epoch: int = Field(default=0, alias="leaseEpoch", ge=0)

    @property
    def agent_kind(self) -> bool:
        return self.kind in AGENT_TASK_KINDS


class AgentAsyncTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    task_id: str = Field(alias="taskId")
    tenant_id: str = Field(alias="tenantId")
    user_id: str = Field(alias="userId")
    status: AsyncTaskStatus
    input: dict[str, Any] = Field(default_factory=dict)
    result: Any | None = None
    error: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")

    @classmethod
    def from_central(cls, task: CentralAsyncTask) -> "AgentAsyncTask":
        compatible_input = dict(task.input)
        if task.webhook_url:
            compatible_input["webhookUrl"] = task.webhook_url
        return cls(
            taskId=task.task_id,
            tenantId=task.tenant_id,
            userId=task.user_id,
            status=task.status,
            input=compatible_input,
            result=task.result,
            error=task.error,
            createdAt=task.created_at,
            updatedAt=task.updated_at,
            finishedAt=task.finished_at,
        )


class AgentTaskCancelReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    task_id: str = Field(alias="taskId")
    cancelled: bool


class AgentTaskProgress(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    task_id: str = Field(alias="taskId")
    event: str
    data: Any
    ts: datetime


class AsyncTaskEventAppend(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    event_key: str = Field(alias="eventKey", min_length=1, max_length=128)
    event: str = Field(min_length=1, max_length=128)
    data: Any
    worker_id: str = Field(alias="workerId", min_length=1, max_length=128)
    lease_epoch: int = Field(alias="leaseEpoch", ge=1)


class CentralAsyncTaskEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    task_id: str = Field(alias="taskId")
    sequence: int = Field(ge=1)
    event_key: str = Field(alias="eventKey")
    event: str
    data: Any
    created_at: datetime = Field(alias="createdAt")
    worker_id: str | None = Field(default=None, alias="workerId")
