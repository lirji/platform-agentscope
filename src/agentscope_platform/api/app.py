from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentscope_platform.api.routes import candidate_router, router
from agentscope_platform.application.async_task import (
    AsyncTaskManager,
    AsyncTaskRejectedError,
)
from agentscope_platform.application.dag import (
    AgentDagApplicationService,
    DagReviewPolicy,
    DagValidationError,
)
from agentscope_platform.application.planning import AgentDagPlanningService
from agentscope_platform.application.ports import (
    AgentRunner,
    AsyncTaskGateway,
    DagPlanner,
    DagQualityError,
    DagQualityReviewer,
    TextGenerationError,
    TextGenerator,
)
from agentscope_platform.application.quality import CritiqueWeights
from agentscope_platform.application.service import AgentApplicationService
from agentscope_platform.application.sibling import (
    PromptChainService,
    ReflexionPolicy,
    ReflexionService,
    SiblingValidationError,
    VotingService,
)
from agentscope_platform.application.workflow_ai import WorkflowAiDraftService
from agentscope_platform.core.config import Settings, get_settings
from agentscope_platform.infrastructure.agentscope.planner import (
    AgentScopeDagPlanner,
)
from agentscope_platform.infrastructure.agentscope.reviewer import (
    AgentScopeDagQualityReviewer,
)
from agentscope_platform.infrastructure.agentscope.runner import (
    AgentNotConfiguredError,
    AgentScopeRunner,
)
from agentscope_platform.infrastructure.agentscope.text_generator import (
    AgentScopeTextGenerator,
)
from agentscope_platform.infrastructure.http.async_task_client import (
    AsyncTaskGatewayError,
    HttpAsyncTaskClient,
)
from agentscope_platform.infrastructure.http.platform_client import PlatformClient
from agentscope_platform.infrastructure.observability.async_task_metrics import (
    AsyncTaskMetrics,
)
from agentscope_platform.infrastructure.observability.logging_observer import (
    LoggingRunObserver,
)
from agentscope_platform.infrastructure.observability.prometheus import (
    configure_metrics,
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
    planning_service: AgentDagPlanningService
    process_planning_service: AgentDagPlanningService
    chain_service: PromptChainService
    voting_service: VotingService
    reflexion_service: ReflexionService
    async_task_manager: AsyncTaskManager
    workflow_ai_draft_service: WorkflowAiDraftService


def create_app(
    settings: Settings | None = None,
    runner: AgentRunner | None = None,
    planner: DagPlanner | None = None,
    reviewer: DagQualityReviewer | None = None,
    text_generator: TextGenerator | None = None,
    async_task_gateway: AsyncTaskGateway | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings)
    configure_metrics(app_settings)
    platform_client = PlatformClient(app_settings)
    app_runner = runner or AgentScopeRunner(
        app_settings,
        platform_client,
        LoggingRunObserver(),
    )
    app_reviewer = reviewer or AgentScopeDagQualityReviewer(app_settings)
    dag_service = AgentDagApplicationService(
        app_runner,
        max_tasks=app_settings.agent_dag_max_tasks,
        max_parallel_workers=app_settings.agent_dag_max_parallel_workers,
        reviewer=app_reviewer,
        review_policy=DagReviewPolicy(
            enabled=app_settings.agent_dag_replan_enabled,
            max_replans=app_settings.agent_dag_replan_max_replans,
            threshold=app_settings.agent_dag_replan_threshold,
            weights=CritiqueWeights(
                correctness=(app_settings.agent_dag_replan_weight_correctness),
                completeness=(app_settings.agent_dag_replan_weight_completeness),
                clarity=app_settings.agent_dag_replan_weight_clarity,
            ),
        ),
    )
    process_dag_service = AgentDagApplicationService(
        app_runner,
        max_tasks=min(app_settings.agent_dag_max_tasks, 4),
        max_parallel_workers=app_settings.agent_dag_max_parallel_workers,
        review_policy=DagReviewPolicy(enabled=False),
    )
    app_planner = planner or AgentScopeDagPlanner(app_settings)
    app_text_generator = text_generator or AgentScopeTextGenerator(app_settings)
    task_gateway = async_task_gateway or HttpAsyncTaskClient(app_settings)
    task_manager = AsyncTaskManager(task_gateway, app_settings, AsyncTaskMetrics())
    container = Container(
        settings=app_settings,
        jwt_verifier=InternalJwtVerifier(app_settings),
        agent_service=AgentApplicationService(app_runner),
        dag_service=dag_service,
        planning_service=AgentDagPlanningService(app_planner, dag_service),
        process_planning_service=AgentDagPlanningService(
            app_planner,
            process_dag_service,
        ),
        chain_service=PromptChainService(
            app_text_generator,
            app_settings.agent_chaining_steps,
        ),
        voting_service=VotingService(
            app_text_generator,
            default_n=app_settings.agent_voting_n,
            max_candidates=app_settings.agent_voting_max_candidates,
            strategy=app_settings.agent_voting_strategy,
            min_agreement=app_settings.agent_voting_min_agreement,
            max_parallel_workers=app_settings.agent_sibling_max_parallel_workers,
        ),
        reflexion_service=ReflexionService(
            app_text_generator,
            app_reviewer,
            ReflexionPolicy(
                threshold=app_settings.agent_reflexion_threshold,
                max_improvements=app_settings.agent_reflexion_max_attempts,
                weights=CritiqueWeights(
                    correctness=app_settings.agent_reflexion_weight_correctness,
                    completeness=app_settings.agent_reflexion_weight_completeness,
                    clarity=app_settings.agent_reflexion_weight_clarity,
                ),
            ),
        ),
        async_task_manager=task_manager,
        workflow_ai_draft_service=WorkflowAiDraftService(app_text_generator),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        try:
            yield
        finally:
            await task_manager.shutdown()

    app = FastAPI(
        title="AgentScope Platform",
        description=(
            "Incremental AgentScope 2.0 replacement for langchain4j-platform agent-service."
        ),
        version="0.1.0",
        lifespan=lifespan,
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

    @app.exception_handler(DagQualityError)
    async def dag_quality_failed(
        request: Request,
        exc: DagQualityError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "error": "DAG quality review failed",
                "traceId": request.state.trace_id,
            },
        )

    @app.exception_handler(SiblingValidationError)
    async def invalid_sibling_request(
        request: Request,
        exc: SiblingValidationError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(TextGenerationError)
    async def sibling_generation_failed(
        request: Request,
        exc: TextGenerationError,
    ) -> JSONResponse:
        del exc
        return JSONResponse(
            status_code=502,
            content={
                "error": "agent generation failed",
                "traceId": request.state.trace_id,
            },
        )

    @app.exception_handler(AsyncTaskRejectedError)
    async def async_task_rejected(
        request: Request,
        exc: AsyncTaskRejectedError,
    ) -> JSONResponse:
        del exc
        return JSONResponse(
            status_code=503,
            content={
                "error": "async task submission is unavailable",
                "traceId": request.state.trace_id,
            },
        )

    @app.exception_handler(AsyncTaskGatewayError)
    async def async_task_gateway_failed(
        request: Request,
        exc: AsyncTaskGatewayError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "async task service request failed",
                "traceId": request.state.trace_id,
            },
        )

    app.include_router(router)
    if app_settings.agent_v2_enabled:
        app.include_router(candidate_router)
    return app
