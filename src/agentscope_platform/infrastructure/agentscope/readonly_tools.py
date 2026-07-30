import json
import logging
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolBase, ToolChunk

from agentscope_platform.application.ports import AnalyticsSqlPlanner
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import current_run_context
from agentscope_platform.infrastructure.agentscope.tools import ReadOnlyFunctionTool
from agentscope_platform.infrastructure.http.models import KnowledgeHit
from agentscope_platform.infrastructure.http.platform_client import (
    PlatformClient,
    PlatformServiceError,
)

MAX_RAG_SNIPPET_CHARS = 600
MAX_ANALYTICS_ROWS = 10
MAX_WORKFLOW_TASKS = 20
MAX_WORKFLOW_TEXT_CHARS = 1_000
log = logging.getLogger(__name__)


class ReadonlyToolset:
    def __init__(
        self,
        settings: Settings,
        client: PlatformClient,
        analytics_planner: AnalyticsSqlPlanner | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._analytics_planner = analytics_planner

    def tools(self) -> list[ToolBase]:
        return [
            ReadOnlyFunctionTool(
                self.rag_search,
                name="rag_search",
                description=(
                    "在当前租户企业知识库检索资料。query 填关键词或问题，返回带 [doc=ID] 的片段。"
                ),
                is_read_only=True,
            ),
            ReadOnlyFunctionTool(
                self.order_query,
                name="order_query",
                description=("按订单号查当前租户订单详情，只读。统计问题应使用 analytics_sql。"),
                is_read_only=True,
            ),
            ReadOnlyFunctionTool(
                self.schema_explore,
                name="schema_explore",
                description="留空列出可查表；填写表名查看字段、类型和枚举。应先探后查。",
                is_read_only=True,
            ),
            ReadOnlyFunctionTool(
                self.analytics_sql,
                name="analytics_sql",
                description="用自然语言查询当前租户业务数据库，只读并受 analytics 安全护栏保护。",
                is_read_only=True,
            ),
            ReadOnlyFunctionTool(
                self.workflow_status,
                name="workflow_status",
                description="按 instance_id 查询当前租户工作流实例状态与最终答复，只读。",
                is_read_only=True,
            ),
            ReadOnlyFunctionTool(
                self.workflow_tasks,
                name="workflow_tasks",
                description="列出当前租户待审批退款任务，只读且要求 approve scope。",
                is_read_only=True,
            ),
        ]

    async def rag_search(self, query: str) -> ToolChunk:
        """Search retained knowledge visible to the current tenant."""
        normalized = query.strip()
        if not normalized:
            return self._success("检索词为空：query 请填要查的关键词或问题。")
        context = current_run_context()
        try:
            reply = await self._client.query_knowledge(
                query=normalized,
                top_k=self._settings.agent_rag_top_k,
                min_score=self._settings.agent_rag_min_score,
                category=self._settings.agent_rag_category,
                context=context,
            )
        except PlatformServiceError as exc:
            return self._error(f"查询失败：{exc}")

        if reply.tenant_id and reply.tenant_id != context.identity.tenant_id:
            return self._error("查询失败：知识服务返回了不一致的租户。")

        hits = [
            hit
            for hit in reply.hits[: self._settings.agent_rag_top_k]
            if hit.text and hit.text.strip()
        ]
        if not hits:
            return self._success(f"知识库里没有检索到与「{normalized}」相关的资料。")

        lines = [f"检索到 {len(hits)} 条片段："]
        for hit in hits:
            lines.append(self._format_knowledge_hit(hit))
        return self._success("\n".join(lines))

    async def order_query(self, order_no: str) -> ToolChunk:
        """Query one order in the current tenant without modifying it."""
        normalized = order_no.strip()
        if not normalized:
            return self._success("订单号为空：order_no 请填要查的订单号。")
        try:
            order = await self._client.get_order(normalized, current_run_context())
        except PlatformServiceError as exc:
            return self._error(f"查询失败：{exc}")
        if order is None:
            return self._success(f"未找到订单 {normalized}")

        lines = [f"订单号: {order.order_no}", f"状态: {order.status}"]
        if order.amount is not None:
            lines.append(f"金额: ¥{order.amount}")
        if order.customer and order.customer.strip():
            lines.append(f"客户: {order.customer}")
        if order.created_at is not None:
            lines.append(f"下单日期: {order.created_at}")
        return self._success("\n".join(lines))

    async def schema_explore(self, table: str = "") -> ToolChunk:
        """List allowed tables or describe one allowed table."""
        normalized = table.strip()
        try:
            if not normalized:
                tables_result = await self._client.list_analytics_tables(current_run_context())
                if not tables_result.tables:
                    return self._success("没有可查询的表。")
                return self._success(f"可查询的表：{', '.join(tables_result.tables)}")

            schema_result = await self._client.describe_analytics_table(
                normalized,
                current_run_context(),
            )
        except PlatformServiceError as exc:
            prefix = "列出表失败" if not normalized else "查看表结构失败"
            return self._error(f"{prefix}：{exc}")

        if schema_result is None:
            return self._success(f"查看表结构失败：table not found or not allowed: {normalized}")
        return self._success(schema_result.schema_text or "（该表无结构信息）")

    async def analytics_sql(self, question: str) -> ToolChunk:
        """Run a guarded read-only natural language analytics query."""
        normalized = question.strip()
        if not normalized:
            return self._success("查询为空：question 请填要查的业务问题。")
        try:
            result = await self._client.query_analytics(
                normalized,
                current_run_context(),
            )
        except PlatformServiceError as exc:
            return self._error(f"查询失败：{exc}")

        await self._run_analytics_shadow(normalized)

        if result.guard_blocked:
            return self._success("查询被安全护栏拦截，未执行。请换一个只读、限定本租户数据的问法。")

        lines = [
            f"SQL: {result.sql or '(未生成)'}",
            f"行数: {result.row_count}",
        ]
        if result.rows:
            displayed = "; ".join(_java_map(row) for row in result.rows[:MAX_ANALYTICS_ROWS])
            if len(result.rows) > MAX_ANALYTICS_ROWS:
                displayed += f" ...(共 {len(result.rows)} 行)"
            lines.append(f"数据: {displayed}")
        if result.answer and result.answer.strip():
            lines.append(f"解读: {result.answer}")
        return self._success("\n".join(lines))

    async def _run_analytics_shadow(self, question: str) -> None:
        if (
            not self._settings.analytics_external_planner_shadow_enabled
            or self._analytics_planner is None
        ):
            return
        context = current_run_context()
        try:
            tables = await self._client.list_analytics_tables(context)
            schema_parts: list[str] = []
            for table in tables.tables[
                : self._settings.analytics_external_planner_max_tables
            ]:
                described = await self._client.describe_analytics_table(table, context)
                if described and described.schema_text:
                    schema_parts.append(f"[{table}]\n{described.schema_text}")
            plan = await self._analytics_planner.plan(
                question,
                "\n\n".join(schema_parts),
                context,
            )
            await self._client.execute_analytics_plan(question, plan.sql, context)
        except Exception as exc:
            log.warning(
                "analytics external planner shadow failed: %s",
                type(exc).__name__,
                extra={
                    "trace_id": context.trace_id,
                    "tenant_id": context.identity.tenant_id,
                },
            )

    async def workflow_status(self, instance_id: str) -> ToolChunk:
        """Query one workflow instance visible to the current tenant."""
        normalized = instance_id.strip()
        if not normalized:
            return self._success("instanceId 为空：请填写要查询的流程实例 ID。")
        try:
            result = await self._client.get_workflow_instance(
                normalized,
                current_run_context(),
            )
        except PlatformServiceError as exc:
            return self._error(f"查询失败：{exc}")
        if result is None:
            return self._success(f"未找到流程实例 {normalized}")

        lines = [f"instanceId: {result.instance_id}", f"status: {result.status}"]
        if result.reply and result.reply.strip():
            lines.append(f"reply: {_truncate(result.reply, MAX_WORKFLOW_TEXT_CHARS)}")
        elif result.status == "WAITING_APPROVAL":
            lines.append("仍在等待人工审批，尚无最终答复。")
        return self._success("\n".join(lines))

    async def workflow_tasks(self) -> ToolChunk:
        """List pending workflow tasks without claiming or completing them."""
        try:
            tasks = await self._client.list_workflow_tasks(current_run_context())
        except PlatformServiceError as exc:
            if exc.status_code == 403:
                return self._error("无审批权限：需要 approve scope 才能查看待审批任务。")
            return self._error(f"查询失败：{exc}")
        if not tasks:
            return self._success("当前没有待审批的退款任务。")

        lines = ["待审批任务："]
        for task in tasks[:MAX_WORKFLOW_TASKS]:
            item = (
                f"- taskId={task.task_id} priority={task.priority or ''} "
                f"summary={_truncate(task.summary or '', MAX_WORKFLOW_TEXT_CHARS)}"
            )
            if task.assignee and task.assignee.strip():
                item += f" assignee={task.assignee}"
            lines.append(item)
        if len(tasks) > MAX_WORKFLOW_TASKS:
            lines.append(f"...(共 {len(tasks)} 个待审批任务)")
        return self._success("\n".join(lines))

    @staticmethod
    def _format_knowledge_hit(hit: KnowledgeHit) -> str:
        display_name = hit.display_name.strip() if hit.display_name else "doc"
        index = hit.index.strip() if hit.index else "0"
        text = (hit.text or "").strip()
        if len(text) > MAX_RAG_SNIPPET_CHARS:
            text = text[:MAX_RAG_SNIPPET_CHARS] + "..."
        source = f"({hit.source}) " if hit.source and hit.source.strip() else ""
        return f"[doc={display_name}#{index}] {source}{text}"

    @staticmethod
    def _success(text: str) -> ToolChunk:
        return ToolChunk(content=[TextBlock(text=text)])

    @staticmethod
    def _error(text: str) -> ToolChunk:
        return ToolChunk(
            content=[TextBlock(text=text)],
            state=ToolResultState.ERROR,
        )


def _java_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, dict):
        return _java_map(value)
    if isinstance(value, list):
        return "[" + ", ".join(_java_value(item) for item in value) + "]"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _java_map(value: dict[str, Any]) -> str:
    return "{" + ", ".join(f"{key}={_java_value(item)}" for key, item in value.items()) + "}"


def _truncate(value: str, limit: int) -> str:
    normalized = value.strip()
    return normalized if len(normalized) <= limit else normalized[:limit] + "..."
