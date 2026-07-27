from typing import Any, cast

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from agentscope_platform.api.dependencies import RunContextDependency
from agentscope_platform.application.dag import AgentDagApplicationService
from agentscope_platform.application.planning import AgentDagPlanningService
from agentscope_platform.application.service import AgentApplicationService
from agentscope_platform.application.sibling import (
    PromptChainService,
    ReflexionService,
    VotingService,
)
from agentscope_platform.domain.agent import AgentRunReply, AgentRunRequest
from agentscope_platform.domain.dag import (
    AgentDagRunReply,
    AgentDagRunRequest,
    AgentPlanRunRequest,
    DagPlanKind,
)
from agentscope_platform.domain.sibling import (
    ChainRunReply,
    ChainRunRequest,
    ReflexionReply,
    ReflexionRequest,
    VoteReply,
    VoteRequest,
)

router = APIRouter()
candidate_router = APIRouter(prefix="/agent/v2")


@router.get("/health", tags=["platform"])
async def health() -> dict[str, str]:
    return {"status": "UP"}


@router.get("/readiness", tags=["platform"])
async def readiness(request: Request) -> JSONResponse:
    configured = request.app.state.container.settings.agent_enabled
    body: dict[str, Any] = {
        "status": "UP" if configured else "DEGRADED",
        "checks": {
            "agentScope": "UP",
            "modelConfiguration": "UP" if configured else "MISSING_GATEWAY_API_KEY",
            "candidateRoute": (
                "ENABLED" if request.app.state.container.settings.agent_v2_enabled else "DISABLED"
            ),
        },
    }
    return JSONResponse(
        status_code=status.HTTP_200_OK if configured else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body,
    )


@router.get("/info", tags=["platform"])
async def info() -> dict[str, str]:
    return {
        "name": "agentscope-platform",
        "phase": "2-multi-agent-orchestration",
        "framework": "AgentScope 2.0",
    }


@router.post(
    "/agent/run",
    response_model=AgentRunReply,
    tags=["agent"],
)
async def run_agent(
    payload: AgentRunRequest,
    context: RunContextDependency,
    request: Request,
) -> AgentRunReply:
    return await _run_agent(payload, context, request)


@candidate_router.post(
    "/run",
    response_model=AgentRunReply,
    tags=["agent-candidate"],
)
async def run_candidate_agent(
    payload: AgentRunRequest,
    context: RunContextDependency,
    request: Request,
) -> AgentRunReply:
    return await _run_agent(payload, context, request)


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
    "/agent/process/run",
    response_model=AgentDagRunReply,
    tags=["agent-process"],
    summary="Run the read-only Process candidate",
    description=(
        "Queries workflow status, pending tasks, or policy only. This candidate never "
        "starts, approves, claims, or modifies a workflow."
    ),
)
async def run_readonly_process(
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


async def _run_agent(
    payload: AgentRunRequest,
    context: RunContextDependency,
    request: Request,
) -> AgentRunReply:
    service = cast(
        AgentApplicationService,
        request.app.state.container.agent_service,
    )
    return await service.run(payload, context)


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
