"""语言中立的中央检查点协议; 不包含 AgentScope 或数据库类型。"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CheckpointStatus(StrEnum):
    """稳定持久化状态码, 只允许RUNNING提交后转为DONE。"""

    RUNNING = "RUNNING"
    DONE = "DONE"


class CheckpointOperation(BaseModel):
    """操作输入与结果版本显式关联, RUNNING 的未知结果不可冒充完成。"""

    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: str
    status: CheckpointStatus
    reusable: bool = False
    result: Any = None


class DagCheckpointState(BaseModel):
    """固定截止时间和单调预算跨进程保留; 凭据只存在执行上下文。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    binding: str = Field(pattern=r"^[0-9a-f]{64}$")
    deadline: int = Field(gt=0)
    model_calls: int = Field(default=0, alias="modelCalls", ge=0)
    reserved_tokens: int = Field(default=0, alias="reservedTokens", ge=0)
    operations: dict[str, CheckpointOperation] = Field(default_factory=dict, max_length=256)


class DagCheckpoint(BaseModel):
    """revision=0/state=null 表示尚未创建; 后续保存必须CAS。"""

    revision: int = Field(ge=0)
    state: DagCheckpointState | None = None


class DagCheckpointRequest(BaseModel):
    """读取时不带state/revision, 保存时必须提供CAS版本。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    lease_epoch: int = Field(alias="leaseEpoch", ge=1)
    expected_revision: int | None = Field(default=None, alias="expectedRevision", ge=0)
    state: DagCheckpointState | None = None
