from typing import Any, cast

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from agentscope_platform.api.dependencies import RunContextDependency
from agentscope_platform.application.dag import AgentDagApplicationService
from agentscope_platform.application.service import AgentApplicationService
from agentscope_platform.domain.agent import AgentRunReply, AgentRunRequest
from agentscope_platform.domain.dag import AgentDagRunReply, AgentDagRunRequest

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
        "phase": "2-dag-orchestration",
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
