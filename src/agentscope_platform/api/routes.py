import asyncio
import codecs
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from agentscope_platform.api.dependencies import RunContextDependency
from agentscope_platform.application.async_task import (
    AsyncTaskManager,
    AsyncTaskNotFoundError,
)
from agentscope_platform.application.confirmation import (
    ToolConfirmationDeniedError,
    ToolConfirmationService,
    ToolConfirmationUnavailableError,
)
from agentscope_platform.application.dag import AgentDagApplicationService
from agentscope_platform.application.planning import AgentDagPlanningService
from agentscope_platform.application.ports import DependencyReadiness, ProgressSink
from agentscope_platform.application.privacy import redact_pii
from agentscope_platform.application.service import AgentApplicationService
from agentscope_platform.application.session import AgentSessionService
from agentscope_platform.application.sibling import (
    PromptChainService,
    ReflexionService,
    VotingService,
)
from agentscope_platform.application.workflow_ai import WorkflowAiDraftService
from agentscope_platform.domain.agent import AgentRunReply, AgentRunRequest
from agentscope_platform.domain.async_task import (
    AgentAsyncTask,
    AgentTaskCancelReply,
    AgentTaskKind,
    AsyncTaskStatus,
    CentralAsyncTask,
)
from agentscope_platform.domain.confirmation import (
    ToolConfirmationReply,
    ToolConfirmationRequest,
)
from agentscope_platform.domain.dag import (
    AgentDagRunReply,
    AgentDagRunRequest,
    AgentPlanRunRequest,
    DagPlanKind,
)
from agentscope_platform.domain.interop import (
    AgentCapabilityRegistry,
    McpToolDescriptor,
    capability_registry,
)
from agentscope_platform.domain.session import AgentSessionCheckpoint, AgentSessionRunRequest
from agentscope_platform.domain.sibling import (
    ChainRunReply,
    ChainRunRequest,
    ReflexionReply,
    ReflexionRequest,
    VoteReply,
    VoteRequest,
)
from agentscope_platform.domain.workflow_ai import (
    WorkflowReplyDraft,
    WorkflowReplyDraftRequest,
    WorkflowTicketDraft,
    WorkflowTicketDraftRequest,
)
from agentscope_platform.infrastructure.observability.prometheus import (
    PROMETHEUS_CONTENT_TYPE,
    render_prometheus_metrics,
)

router = APIRouter()
candidate_router = APIRouter(prefix="/agent/v2")
log = logging.getLogger(__name__)


@router.get("/health", tags=["platform"])
async def health() -> dict[str, str]:
    return {"status": "UP"}


@router.get(
    "/metrics",
    response_class=Response,
    tags=["platform"],
    summary="Scrape low-cardinality service metrics",
)
async def prometheus_metrics(context: RunContextDependency) -> Response:
    del context
    return Response(
        content=render_prometheus_metrics(),
        media_type=PROMETHEUS_CONTENT_TYPE,
    )


@router.get("/readiness", tags=["platform"])
async def readiness(request: Request) -> JSONResponse:
    configured = request.app.state.container.settings.agent_enabled
    try:
        dependencies = await request.app.state.container.readiness_probe.check()
        session_ready = await request.app.state.container.session_store.ready(
            request.app.state.container.settings.readiness_probe_timeout_seconds
        )
        dependencies = (
            *dependencies,
            DependencyReadiness(
                name="agentSessionStore",
                required=True,
                status="UP" if session_ready else "DOWN",
            ),
        )
    except Exception:
        dependencies = (
            DependencyReadiness(
                name="runtimeDependencies",
                required=True,
                status="DOWN",
            ),
        )
    dependencies_ready = all(not item.required or item.status == "UP" for item in dependencies)
    body: dict[str, Any] = {
        "status": "UP" if configured and dependencies_ready else "DEGRADED",
        "checks": {
            "agentScope": "UP",
            "modelConfiguration": "UP" if configured else "MISSING_GATEWAY_API_KEY",
            "candidateRoute": (
                "ENABLED" if request.app.state.container.settings.agent_v2_enabled else "DISABLED"
            ),
            **{item.name: item.status for item in dependencies},
        },
    }
    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if configured and dependencies_ready
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content=body,
    )


@router.get("/info", tags=["platform"])
async def info() -> dict[str, str]:
    return {
        "name": "agentscope-platform",
        "phase": "5-full-cutover",
        "framework": "AgentScope 2.0",
    }


@router.post(
    "/internal/workflow/ticket-draft",
    response_model=WorkflowTicketDraft,
    tags=["workflow-ai-candidate"],
)
async def draft_workflow_ticket(
    payload: WorkflowTicketDraftRequest,
    context: RunContextDependency,
    request: Request,
) -> WorkflowTicketDraft:
    service = cast(
        WorkflowAiDraftService,
        request.app.state.container.workflow_ai_draft_service,
    )
    return await service.ticket(payload.message, context)


@router.post(
    "/internal/workflow/reply-draft",
    response_model=WorkflowReplyDraft,
    tags=["workflow-ai-candidate"],
)
async def draft_workflow_reply(
    payload: WorkflowReplyDraftRequest,
    context: RunContextDependency,
    request: Request,
) -> WorkflowReplyDraft:
    service = cast(
        WorkflowAiDraftService,
        request.app.state.container.workflow_ai_draft_service,
    )
    return await service.reply(payload.chat_id, payload.message, context)


@router.get(
    "/agent/capabilities",
    response_model=list[McpToolDescriptor],
    tags=["agent"],
    summary="Discover platform Agent capabilities",
)
async def agent_capabilities(context: RunContextDependency) -> list[McpToolDescriptor]:
    del context
    return list(capability_registry().capabilities[:4])


@router.get(
    "/agent/capabilities/registry",
    response_model=AgentCapabilityRegistry,
    tags=["agent"],
    summary="Discover the versioned platform Agent capability registry",
)
async def agent_capability_registry(
    context: RunContextDependency,
    response: Response,
) -> AgentCapabilityRegistry:
    del context
    registry = capability_registry()
    response.headers["ETag"] = f'"{registry.revision}"'
    return registry


@router.post(
    "/agent/sessions/{session_id}/run",
    response_model=AgentSessionCheckpoint,
    tags=["agent-session"],
    summary="Create or resume an owner-scoped durable Agent session",
)
async def run_agent_session(
    session_id: Annotated[str, Path(pattern=r"^sess-[a-f0-9]{32}$")],
    payload: AgentSessionRunRequest,
    context: RunContextDependency,
    request: Request,
) -> AgentSessionCheckpoint:
    service = cast(AgentSessionService, request.app.state.container.session_service)
    return await service.run(session_id, payload.goal, context)


@router.get(
    "/agent/sessions/{session_id}",
    response_model=AgentSessionCheckpoint,
    tags=["agent-session"],
    summary="Read an owner-scoped durable Agent session checkpoint",
)
async def get_agent_session(
    session_id: Annotated[str, Path(pattern=r"^sess-[a-f0-9]{32}$")],
    context: RunContextDependency,
    request: Request,
) -> AgentSessionCheckpoint:
    service = cast(AgentSessionService, request.app.state.container.session_service)
    return await service.get(session_id, context)


@router.post(
    "/agent/tool-confirmations",
    response_model=ToolConfirmationReply,
    status_code=status.HTTP_201_CREATED,
    tags=["agent"],
    summary="Issue a short-lived argument-bound tool confirmation grant",
)
async def issue_tool_confirmation(
    payload: ToolConfirmationRequest,
    context: RunContextDependency,
    request: Request,
) -> ToolConfirmationReply:
    metadata = request.app.state.container.confirmable_tools.get(payload.tool_name)
    if metadata is None:
        raise HTTPException(status_code=404, detail="confirmable tool not found")
    service = cast(
        ToolConfirmationService,
        request.app.state.container.confirmation_service,
    )
    try:
        return service.issue(metadata, payload.arguments, context)
    except ToolConfirmationDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, ToolConfirmationUnavailableError) as exc:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if isinstance(exc, ToolConfirmationUnavailableError)
            else status.HTTP_400_BAD_REQUEST
        )
        detail = (
            "tool confirmation service is unavailable"
            if status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            else "invalid tool confirmation request"
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post(
    "/agent/run",
    response_model=AgentRunReply,
    tags=["agent"],
)
async def run_agent(
    payload: AgentRunRequest,
    context: RunContextDependency,
    request: Request,
    response: Response,
) -> AgentRunReply:
    return await _run_agent(payload, context, request, response)


@router.post(
    "/agent/run/async",
    response_model=AgentAsyncTask,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["agent"],
)
async def run_agent_async(
    payload: AgentRunRequest,
    context: RunContextDependency,
    request: Request,
) -> AgentAsyncTask:
    service = cast(AgentApplicationService, request.app.state.container.agent_service)
    return await _submit(
        request,
        context,
        AgentTaskKind.RUN,
        payload,
        lambda _progress: service.run_for_async(payload, context),
    )


@candidate_router.post(
    "/run",
    response_model=AgentRunReply,
    tags=["agent-candidate"],
)
async def run_candidate_agent(
    payload: AgentRunRequest,
    context: RunContextDependency,
    request: Request,
    response: Response,
) -> AgentRunReply:
    return await _run_agent(payload, context, request, response)


@router.post(
    "/agent/dag/run",
    response_model=AgentDagRunReply,
    tags=["agent-dag"],
)
async def run_agent_dag(
    payload: AgentDagRunRequest,
    context: RunContextDependency,
    request: Request,
) -> AgentDagRunReply:
    service = cast(
        AgentDagApplicationService,
        request.app.state.container.dag_service,
    )
    return await service.run(payload, context)


@router.post(
    "/agent/dag/run/async",
    response_model=AgentAsyncTask,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["agent-dag"],
)
async def run_agent_dag_async(
    payload: AgentDagRunRequest,
    context: RunContextDependency,
    request: Request,
) -> AgentAsyncTask:
    service = cast(AgentDagApplicationService, request.app.state.container.dag_service)
    return await _submit(
        request,
        context,
        AgentTaskKind.DAG,
        payload,
        lambda progress: service.run(payload, context, progress),
    )


@router.post(
    "/agent/dag/plan-run",
    response_model=AgentDagRunReply,
    tags=["agent-dag"],
)
async def plan_and_run_agent_dag(
    context: RunContextDependency,
    request: Request,
    payload: AgentPlanRunRequest | None = None,
) -> AgentDagRunReply:
    return await _plan_and_run(
        payload,
        context,
        request,
        DagPlanKind.GENERAL,
    )


@router.post(
    "/agent/dag/plan-run/async",
    response_model=AgentAsyncTask,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["agent-dag"],
)
async def plan_and_run_agent_dag_async(
    context: RunContextDependency,
    request: Request,
    payload: AgentPlanRunRequest | None = None,
) -> AgentAsyncTask:
    actual = payload or AgentPlanRunRequest()
    service = cast(AgentDagPlanningService, request.app.state.container.planning_service)
    return await _submit(
        request,
        context,
        AgentTaskKind.DAG_PLAN,
        actual,
        lambda progress: service.plan_and_run(
            actual,
            context,
            DagPlanKind.GENERAL,
            progress,
        ),
    )


@router.post(
    "/agent/analyst/run",
    response_model=AgentDagRunReply,
    tags=["agent-analyst"],
)
async def run_analyst_agent(
    context: RunContextDependency,
    request: Request,
    payload: AgentPlanRunRequest | None = None,
) -> AgentDagRunReply:
    return await _plan_and_run(
        payload,
        context,
        request,
        DagPlanKind.ANALYST,
    )


@router.post(
    "/agent/analyst/run/async",
    response_model=AgentAsyncTask,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["agent-analyst"],
)
async def run_analyst_agent_async(
    context: RunContextDependency,
    request: Request,
    payload: AgentPlanRunRequest | None = None,
) -> AgentAsyncTask:
    actual = payload or AgentPlanRunRequest()
    service = cast(AgentDagPlanningService, request.app.state.container.planning_service)
    return await _submit(
        request,
        context,
        AgentTaskKind.ANALYST,
        actual,
        lambda progress: service.plan_and_run(
            actual,
            context,
            DagPlanKind.ANALYST,
            progress,
        ),
    )


@router.post(
    "/agent/chain",
    response_model=ChainRunReply,
    tags=["agent-chain"],
)
async def run_prompt_chain(
    context: RunContextDependency,
    request: Request,
    payload: ChainRunRequest | None = None,
) -> ChainRunReply:
    service = cast(PromptChainService, request.app.state.container.chain_service)
    return await service.run(payload or ChainRunRequest(), context)


@router.post(
    "/agent/vote",
    response_model=VoteReply,
    tags=["agent-voting"],
)
async def run_voting(
    context: RunContextDependency,
    request: Request,
    payload: VoteRequest | None = None,
) -> VoteReply:
    service = cast(VotingService, request.app.state.container.voting_service)
    return await service.run(payload or VoteRequest(), context)


@router.post(
    "/agent/reflexive",
    response_model=ReflexionReply,
    tags=["agent-reflexion"],
)
async def run_reflexion(
    context: RunContextDependency,
    request: Request,
    payload: ReflexionRequest | None = None,
) -> ReflexionReply:
    service = cast(ReflexionService, request.app.state.container.reflexion_service)
    return await service.run(payload or ReflexionRequest(), context)


@router.post(
    "/agent/reflexive/stream",
    response_class=StreamingResponse,
    tags=["agent-reflexion"],
)
async def stream_reflexion(
    context: RunContextDependency,
    request: Request,
    payload: ReflexionRequest | None = None,
) -> StreamingResponse:
    service = cast(ReflexionService, request.app.state.container.reflexion_service)
    actual = payload or ReflexionRequest()
    return StreamingResponse(
        _reflexion_events(service, actual, context),
        media_type="text/event-stream",
    )


@router.post(
    "/agent/process/run",
    response_model=AgentDagRunReply,
    tags=["agent-process"],
    summary="Run the governed Process agent",
    description=(
        "Queries workflow state by default. When refund_start is enabled, explicitly confirmed, "
        "and protected by an idempotency key, it may start a refund workflow. It never approves, "
        "claims, or deletes workflow state."
    ),
)
async def run_process(
    context: RunContextDependency,
    request: Request,
    payload: AgentPlanRunRequest | None = None,
) -> AgentDagRunReply:
    service = cast(
        AgentDagPlanningService,
        request.app.state.container.process_planning_service,
    )
    return await service.plan_and_run(
        payload or AgentPlanRunRequest(),
        context,
        DagPlanKind.PROCESS,
    )


@router.post(
    "/agent/process/run/async",
    response_model=AgentAsyncTask,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["agent-process"],
)
async def run_process_async(
    context: RunContextDependency,
    request: Request,
    payload: AgentPlanRunRequest | None = None,
) -> AgentAsyncTask:
    actual = payload or AgentPlanRunRequest()
    service = cast(
        AgentDagPlanningService,
        request.app.state.container.process_planning_service,
    )
    return await _submit(
        request,
        context,
        AgentTaskKind.PROCESS,
        actual,
        lambda progress: service.plan_and_run(
            actual,
            context,
            DagPlanKind.PROCESS,
            progress,
        ),
    )


@router.get("/agent/tasks", response_model=list[AgentAsyncTask], tags=["agent-tasks"])
async def list_agent_tasks(
    context: RunContextDependency,
    request: Request,
) -> list[AgentAsyncTask]:
    return await _manager(request).list(context)


@router.get(
    "/agent/tasks/{task_id}",
    response_model=AgentAsyncTask,
    tags=["agent-tasks"],
)
async def get_agent_task(
    task_id: str,
    context: RunContextDependency,
    request: Request,
) -> AgentAsyncTask:
    try:
        return await _manager(request).get(task_id, context)
    except AsyncTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc


@router.delete(
    "/agent/tasks/{task_id}",
    response_model=AgentTaskCancelReply,
    tags=["agent-tasks"],
)
async def cancel_agent_task(
    task_id: str,
    context: RunContextDependency,
    request: Request,
) -> AgentTaskCancelReply:
    try:
        cancelled = await _manager(request).cancel(task_id, context)
    except AsyncTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc
    if not cancelled:
        raise HTTPException(status_code=409, detail="agent task was not cancelled")
    return AgentTaskCancelReply(taskId=task_id, cancelled=True)


@router.get(
    "/agent/tasks/{task_id}/stream",
    response_class=StreamingResponse,
    tags=["agent-tasks"],
)
async def stream_agent_task(
    task_id: str,
    context: RunContextDependency,
    request: Request,
    last_event_id: str | None = Query(default=None, alias="lastEventId"),
) -> Response:
    manager = _manager(request)
    try:
        await manager.get(task_id, context)
    except AsyncTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc
    resume_from = last_event_id or request.headers.get("Last-Event-ID")
    return StreamingResponse(
        _project_task_events(
            manager.gateway.stream(
                task_id,
                context,
                last_event_id=resume_from,
            )
        ),
        media_type="text/event-stream",
    )


async def _run_agent(
    payload: AgentRunRequest,
    context: RunContextDependency,
    request: Request,
    response: Response,
) -> AgentRunReply:
    service = cast(
        AgentApplicationService,
        request.app.state.container.agent_service,
    )
    reply = await service.run(payload, context)
    versions = request.app.state.container.execution_versions
    response.headers["X-Agent-Prompt-Version"] = versions.prompt_version
    response.headers["X-Agent-Model-Version"] = versions.model_version
    response.headers["X-Agent-Toolset-Version"] = versions.toolset_version
    return reply


async def _plan_and_run(
    payload: AgentPlanRunRequest | None,
    context: RunContextDependency,
    request: Request,
    kind: DagPlanKind,
) -> AgentDagRunReply:
    service = cast(
        AgentDagPlanningService,
        request.app.state.container.planning_service,
    )
    return await service.plan_and_run(
        payload or AgentPlanRunRequest(),
        context,
        kind,
    )


def _manager(request: Request) -> AsyncTaskManager:
    return cast(AsyncTaskManager, request.app.state.container.async_task_manager)


async def _submit(
    request: Request,
    context: RunContextDependency,
    kind: AgentTaskKind,
    payload: BaseModel,
    execute: Callable[[ProgressSink], Awaitable[Any]],
) -> AgentAsyncTask:
    input_data = payload.model_dump(
        by_alias=True,
        mode="json",
        exclude={"webhook_url"},
        exclude_none=True,
    )
    webhook_url = getattr(payload, "webhook_url", None)
    return await _manager(request).submit(
        kind=kind.value,
        input_data=input_data,
        webhook_url=webhook_url,
        context=context,
        execute=execute,
    )


async def _project_task_events(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    buffer = ""
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        async for chunk in chunks:
            buffer += decoder.decode(chunk)
            while True:
                boundary = _frame_boundary(buffer)
                if boundary is None:
                    break
                index, width = boundary
                frame, buffer = buffer[:index], buffer[index + width :]
                projected = _project_task_frame(frame)
                if projected is not None:
                    yield projected
        buffer += decoder.decode(b"", final=True)
        if buffer.strip():
            projected = _project_task_frame(buffer)
            if projected is not None:
                yield projected
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning(
            "agent task stream terminated error_type=%s",
            type(exc).__name__,
        )
        yield _stream_error_event("AGENT_TASK_STREAM_FAILED")
    finally:
        close = getattr(chunks, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception as exc:
                log.warning(
                    "agent task upstream close failed error_type=%s",
                    type(exc).__name__,
                )


def _stream_error_event(code: str) -> bytes:
    return (
        f'event: error\ndata: {{"error":"agent task stream failed","code":"{code}"}}\n\n'
    ).encode()


def _frame_boundary(value: str) -> tuple[int, int] | None:
    matches = [
        (index, len(marker))
        for marker in ("\r\n\r\n", "\n\n", "\r\r")
        if (index := value.find(marker)) >= 0
    ]
    return min(matches, default=None)


def _project_task_frame(frame: str) -> bytes | None:
    event_id: str | None = None
    event_name = "message"
    data_lines: list[str] = []
    for line in frame.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith("id:"):
            event_id = line[3:].strip()
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    data: Any = json.loads("\n".join(data_lines))
    if event_name in {status.value for status in AsyncTaskStatus}:
        data = AgentAsyncTask.from_central(CentralAsyncTask.model_validate(data)).model_dump(
            by_alias=True,
            mode="json",
        )
    data = redact_pii(data)
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.extend(
        [
            f"event: {event_name}",
            f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}",
            "",
            "",
        ]
    )
    return "\n".join(lines).encode()


class _QueueProgressSink(ProgressSink):
    def __init__(self, queue: asyncio.Queue[tuple[str, Any] | None]) -> None:
        self._queue = queue

    async def emit(self, event: str, data: Any) -> None:
        await self._queue.put((event, data))


async def _reflexion_events(
    service: ReflexionService,
    payload: ReflexionRequest,
    context: RunContextDependency,
) -> AsyncIterator[bytes]:
    queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue(maxsize=32)
    sink = _QueueProgressSink(queue)

    async def produce() -> None:
        cancelled = False
        try:
            await service.run(payload, context, sink)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as exc:
            log.warning(
                "agent reflexion stream terminated error_type=%s",
                type(exc).__name__,
            )
            await queue.put(
                (
                    "error",
                    {
                        "error": "agent reflexion failed",
                        "code": "AGENT_REFLEXION_STREAM_FAILED",
                    },
                )
            )
        finally:
            # Cancellation means the consumer has gone away. Awaiting a sentinel write here can
            # deadlock forever when the bounded queue is full and nobody will drain it.
            if not cancelled:
                await queue.put(None)

    producer = asyncio.create_task(produce())
    try:
        while (item := await queue.get()) is not None:
            event, data = item
            serialized = json.dumps(
                redact_pii(data),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield (f"event: {event}\ndata: {serialized}\n\n").encode()
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
