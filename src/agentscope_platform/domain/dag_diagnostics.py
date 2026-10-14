"""独立版本化诊断事件; 不扩展旧业务响应, 不承载模型或工具内容。"""

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# 复用旧 Agent stopReason 协议的成功码, 诊断不重新解释或修改业务状态。
SUCCESS_STOP_REASON = "DONE"


class DagRole(StrEnum):
    """角色由编排器指定, 不接受模型输出覆盖。"""

    PLANNER = "planner"
    WORKER = "worker"
    SYNTHESIS = "synthesis"
    CRITIC = "critic"
    REPLANNER = "replanner"


class DagDiagnosticReason(StrEnum):
    """封闭原因码同时约束事件契约和指标标签基数。"""

    EXECUTED = "executed"
    REPLAN_REUSED = "replan_reused"
    CHECKPOINT_REUSED = "checkpoint_reused"
    REUSE_INPUT_CHANGED = "reuse_input_changed"
    REUSE_EXPIRED = "reuse_expired"
    PREVIOUS_FAILED = "previous_failed"
    NON_REUSABLE_TOOLS = "non_reusable_tools"
    REUSE_DISABLED = "reuse_disabled"
    NO_REUSABLE_RESULT = "no_reusable_result"
    CHECKPOINT_INCOMPLETE = "checkpoint_incomplete"
    CHECKPOINT_NOT_REUSABLE = "checkpoint_not_reusable"
    CHECKPOINT_INPUT_CHANGED = "checkpoint_input_changed"
    UPSTREAM_FAILED = "upstream_failed"


class DiagnosticBase(BaseModel):
    """executionId 标识本次进程执行片段, 不是跨接管计费账单。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    schema_version: Literal[1] = 1
    execution_id: str
    trace_id: str
    tenant_id: str


class OperationIdentity(DiagnosticBase):
    """并行模型调用通过不可混淆的操作标识关联到节点与轮次。"""

    operation_id: str
    role: DagRole
    attempt: int = Field(ge=1)
    node_id: str | None = None


class DagModelDiagnostic(OperationIdentity):
    """实际 usage 与部署费率估算; null 表示未知, 不代表免费。"""

    kind: Literal["model"] = "model"
    call_id: str
    model: str
    status: Literal["DONE", "ERROR", "CANCELLED"]
    duration_ms: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    input_rate_per_million: Decimal | None = Field(default=None, ge=0)
    output_rate_per_million: Decimal | None = Field(default=None, ge=0)
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0)


class DagOperationDiagnostic(OperationIdentity):
    """执行耗时与排队分开; duration 包括检查点及操作编排开销。"""

    kind: Literal["operation"] = "operation"
    status: str
    reason: DagDiagnosticReason
    duration_ms: float = Field(ge=0)
    queue_ms: float = Field(ge=0)
    execution_ms: float = Field(ge=0)
    observed_model_calls: int = Field(ge=0)


class DagCriticalPath(BaseModel):
    """本轮已观测节点执行耗时加权的最长依赖路径, 不含排队和模型其他角色。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    attempt: int
    node_ids: list[str]
    execution_ms: float
    complete: bool


class DagDiagnosticSummary(DiagnosticBase):
    """片段汇总; 历史缺口及观测缺口必须显式展示。"""

    kind: Literal["summary"] = "summary"
    scope: Literal["execution_segment"] = "execution_segment"
    status: str
    accepted_by_threshold: bool | None = None
    duration_ms: float = Field(ge=0)
    resumed: bool
    history_complete: bool
    observed_model_calls: int = Field(ge=0)
    known_input_tokens: int = Field(ge=0)
    known_output_tokens: int = Field(ge=0)
    unknown_usage_calls: int = Field(ge=0)
    unpriced_calls: int = Field(ge=0)
    known_estimated_cost_usd: Decimal = Field(ge=0)
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0)
    delivery_failures: int = Field(ge=0)
    dropped_records: int = Field(ge=0)
    critical_paths: list[DagCriticalPath]


DagDiagnosticEvent = DagModelDiagnostic | DagOperationDiagnostic | DagDiagnosticSummary
