"""只在一次 DAG 调用的重规划轮次之间复用, 不提供持久恢复或跨请求缓存。"""

import hashlib
import json
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from agentscope_platform.domain.dag import AgentDagTaskResult

# 时钟、订单/流程状态和分析查询要求新鲜读取, 不能只凭 readOnly 复用。
REUSABLE_EVIDENCE_TOOLS = frozenset({"rag_search", "schema_explore"})


@dataclass(frozen=True, slots=True)
class _Entry:
    fingerprint: str
    version: str
    expires_at: float
    result: AgentDagTaskResult


class DagResultReuse:
    """每节点仅保存最近成功结果, 大小受本次计划/重规划上限约束。"""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, _Entry] = {}
        self._ineligible: dict[str, str] = {}

    @staticmethod
    def fingerprint(
        goal: str,
        task_id: str,
        description: str,
        dependencies: list[tuple[str, str]],
    ) -> str:
        """依赖使用执行版本而非仅输出文本, 上游重跑后下游必须重新计算。"""
        value = json.dumps([goal, task_id, description, dependencies], ensure_ascii=False)
        return hashlib.sha256(value.encode()).hexdigest()

    def get(self, task_id: str, fingerprint: str) -> tuple[AgentDagTaskResult, str] | None:
        """返回深拷贝, 避免后续修改污染前轮 attempts 或缓存。"""
        entry = self._entries.get(task_id)
        if entry is None or entry.fingerprint != fingerprint or monotonic() >= entry.expires_at:
            return None
        return entry.result.model_copy(deep=True), entry.version

    def reason(self, task_id: str, fingerprint: str) -> str:
        """复用诊断不改变缓存决策, 不暴露输入摘要或业务内容。"""
        entry = self._entries.get(task_id)
        if self._ttl <= 0:
            return "reuse_disabled"
        if entry is None:
            return self._ineligible.get(task_id, "no_reusable_result")
        if entry.fingerprint != fingerprint:
            return "reuse_input_changed"
        if monotonic() >= entry.expires_at:
            return "reuse_expired"
        return "replan_reused"

    def record(self, task_id: str, fingerprint: str, result: AgentDagTaskResult) -> str:
        """失败、实时读取、未知工具或 TTL=0 均不复用; 执行版本仍用于失效下游。"""
        version = uuid4().hex
        if (
            self._ttl > 0
            and result.result.stop_reason == "DONE"
            and all(
                step.action in REUSABLE_EVIDENCE_TOOLS
                for step in result.result.steps
                if step.action
            )
        ):
            self._ineligible.pop(task_id, None)
            self._entries[task_id] = _Entry(
                fingerprint,
                version,
                monotonic() + self._ttl,
                result.model_copy(deep=True),
            )
        else:
            self._ineligible[task_id] = (
                "previous_failed"
                if result.result.stop_reason != "DONE"
                else "non_reusable_tools"
                if self._ttl > 0
                else "reuse_disabled"
            )
            self._entries.pop(task_id, None)
        return version
