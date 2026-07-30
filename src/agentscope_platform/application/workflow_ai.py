from agentscope_platform.application.ports import TextGenerator
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.workflow_ai import WorkflowReplyDraft, WorkflowTicketDraft

TICKET_PROMPT = """
从退款请求抽取工单。只返回 JSON: title, priority, category, summary, tags。
priority 只能是 LOW/MEDIUM/HIGH/CRITICAL; 有投诉、大额、长期未解决、未到账或无法判断时从严取 HIGH。
不得决定批准或驳回, 不得执行流程副作用。
""".strip()

REPLY_PROMPT = """
为已经由 Java 工作流确定为可受理的退款请求生成简洁礼貌的中文答复。
只输出答复正文。不得声称执行了审批、退款、通知或其他副作用。
""".strip()


class WorkflowAiDraftService:
    def __init__(self, generator: TextGenerator) -> None:
        self._generator = generator

    async def ticket(self, message: str, context: RunContext) -> WorkflowTicketDraft:
        raw = await self._generator.generate(
            TICKET_PROMPT,
            message,
            context,
            deterministic=True,
        )
        return WorkflowTicketDraft.model_validate_json(raw)

    async def reply(
        self,
        chat_id: str,
        message: str,
        context: RunContext,
    ) -> WorkflowReplyDraft:
        del chat_id
        raw = await self._generator.generate(
            REPLY_PROMPT,
            message,
            context,
            deterministic=True,
        )
        return WorkflowReplyDraft(reply=raw)
