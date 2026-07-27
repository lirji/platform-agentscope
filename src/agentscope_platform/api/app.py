from dataclasses import dataclass
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentscope_platform.api.routes import candidate_router, router
from agentscope_platform.application.dag import (
    AgentDagApplicationService,
    DagValidationError,
)
from agentscope_platform.application.ports import AgentRunner
from agentscope_platform.application.service import AgentApplicationService
from agentscope_platform.core.config import Settings, get_settings
from agentscope_platform.infrastructure.agentscope.runner import (
    AgentNotConfiguredError,
    AgentScopeRunner,
)
from agentscope_platform.infrastructure.http.platform_client import PlatformClient
from agentscope_platform.infrastructure.observability.logging_observer import (
    LoggingRunObserver,
)
from agentscope_platform.infrastructure.observability.setup import (
    configure_logging,
    configure_tracing,
)
from agentscope_platform.infrastructure.security.internal_jwt import InternalJwtVerifier


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    jwt_verifier: InternalJwtVerifier
    agent_service: AgentApplicationService
    dag_service: AgentDagApplicationService


def create_app(
    settings: Settings | None = None,
    runner: AgentRunner | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings)
    platform_client = PlatformClient(app_settings)
    app_runner = runner or AgentScopeRunner(
        app_settings,
        platform_client,
        LoggingRunObserver(),
    )
    container = Container(
        settings=app_settings,
        jwt_verifier=InternalJwtVerifier(app_settings),
        agent_service=AgentApplicationService(app_runner),
        dag_service=AgentDagApplicationService(
            app_runner,
            max_tasks=app_settings.agent_dag_max_tasks,
            max_parallel_workers=app_settings.agent_dag_max_parallel_workers,
        ),
    )

    app = FastAPI(
        title="AgentScope Platform",
        description=(
            "Incremental AgentScope 2.0 replacement for langchain4j-platform agent-service."
        ),
        version="0.1.0",
    )
    app.state.container = container
    configure_tracing(app, app_settings)

    @app.middleware("http")
    async def trace_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        trace_id = request.headers.get("X-Trace-Id") or uuid4().hex
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    @app.exception_handler(AgentNotConfiguredError)
    async def agent_not_configured(
        request: Request,
        exc: AgentNotConfiguredError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": "agent model is not configured",
                "traceId": request.state.trace_id,
            },
        )

    @app.exception_handler(DagValidationError)
    async def invalid_dag(
        request: Request,
        exc: DagValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )

    app.include_router(router)
    if app_settings.agent_v2_enabled:
        app.include_router(candidate_router)
    return app
