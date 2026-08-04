from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentscope_platform.api.routes import candidate_router, router
from agentscope_platform.application.async_task import (
    AsyncTaskManager,
    AsyncTaskRejectedError,
)
from agentscope_platform.application.confirmation import ToolConfirmationService
from agentscope_platform.application.dag import (
    AgentDagApplicationService,
    DagReviewPolicy,
    DagValidationError,
)
from agentscope_platform.application.observer import CompositeRunObserver
from agentscope_platform.application.planning import AgentDagPlanningService
from agentscope_platform.application.ports import (
    AgentRunner,
    AgentSessionStore,
    AsyncTaskGateway,
    DagPlanner,
    DagQualityError,
    DagQualityReviewer,
    ReadinessProbe,
    ResumableAgentRunner,
    TextGenerationError,
    TextGenerator,
)
from agentscope_platform.application.quality import CritiqueWeights
from agentscope_platform.application.service import AgentApplicationService
from agentscope_platform.application.session import (
    AgentSessionActiveError,
    AgentSessionConflictError,
    AgentSessionGoalMismatchError,
    AgentSessionNotFoundError,
    AgentSessionResumeConfirmationRequiredError,
    AgentSessionService,
)
from agentscope_platform.application.sibling import (
    PromptChainService,
    ReflexionPolicy,
    ReflexionService,
    SiblingValidationError,
    VotingService,
)
from agentscope_platform.application.workflow_ai import WorkflowAiDraftService
from agentscope_platform.core.config import Settings, get_settings
from agentscope_platform.domain.agent import ExecutionVersions
from agentscope_platform.domain.tool import ToolMetadata
from agentscope_platform.domain.versioning import build_execution_versions
from agentscope_platform.infrastructure.agentscope.governed_tools import GovernedToolset
from agentscope_platform.infrastructure.agentscope.planner import (
    AgentScopeDagPlanner,
)
from agentscope_platform.infrastructure.agentscope.reviewer import (
    AgentScopeDagQualityReviewer,
)
from agentscope_platform.infrastructure.agentscope.runner import (
    SYSTEM_PROMPT,
    TOOL_IMPLEMENTATION_REVISION,
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
from agentscope_platform.infrastructure.http.readiness import HttpDependencyReadinessProbe
from agentscope_platform.infrastructure.http.resilience import DependencyGuardRegistry
from agentscope_platform.infrastructure.mcp.client import StreamableHttpMcpGateway
from agentscope_platform.infrastructure.observability.async_task_metrics import (
    AsyncTaskMetrics,
)
from agentscope_platform.infrastructure.observability.logging_observer import (
    LoggingRunObserver,
)
from agentscope_platform.infrastructure.observability.prometheus import (
    configure_metrics,
)
from agentscope_platform.infrastructure.observability.runtime_metrics import (
    RunMetricsObserver,
)
from agentscope_platform.infrastructure.observability.setup import (
    configure_logging,
    configure_tracing,
)
from agentscope_platform.infrastructure.persistence.agent_session import (
    build_agent_session_store,
)
from agentscope_platform.infrastructure.sandbox.client import HttpRemoteSandboxGateway
from agentscope_platform.infrastructure.security.internal_jwt import InternalJwtVerifier
from agentscope_platform.infrastructure.security.tool_confirmation import (
    JwtToolConfirmationCodec,
    build_confirmation_replay_store,
)


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
    confirmation_service: ToolConfirmationService
    session_service: AgentSessionService
    session_store: AgentSessionStore
    readiness_probe: ReadinessProbe
    confirmable_tools: dict[str, ToolMetadata]
    execution_versions: ExecutionVersions


def create_app(
    settings: Settings | None = None,
    runner: AgentRunner | None = None,
    planner: DagPlanner | None = None,
    reviewer: DagQualityReviewer | None = None,
    text_generator: TextGenerator | None = None,
    async_task_gateway: AsyncTaskGateway | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings)
    configure_metrics(app_settings)
    dependency_guards = DependencyGuardRegistry(app_settings)
    platform_client = PlatformClient(app_settings, guards=dependency_guards)
    mcp_gateway = StreamableHttpMcpGateway(app_settings, guards=dependency_guards)
    sandbox_gateway = HttpRemoteSandboxGateway(app_settings, guards=dependency_guards)
    confirmation_service = ToolConfirmationService(
        JwtToolConfirmationCodec(app_settings),
        build_confirmation_replay_store(app_settings),
        app_settings,
    )
    app_readiness_probe = readiness_probe or HttpDependencyReadinessProbe(
        app_settings,
        confirmation_service,
    )
    app_runner = runner or AgentScopeRunner(
        app_settings,
        platform_client,
        CompositeRunObserver(
            RunMetricsObserver(app_settings),
            LoggingRunObserver(),
        ),
        mcp_gateway=mcp_gateway,
        sandbox_gateway=sandbox_gateway,
        confirmation_consumer=confirmation_service,
    )
    execution_versions = getattr(
        app_runner,
        "execution_versions",
        build_execution_versions(
            prompt=SYSTEM_PROMPT,
            model=app_settings.gateway_model,
            model_parameters={
                "gatewayEndpoint": app_settings.gateway_base_url,
                "temperature": app_settings.gateway_temperature,
                "maxOutputTokens": min(
                    app_settings.agent_model_max_output_tokens,
                    app_settings.agent_max_tokens,
                ),
                "parallelToolCalls": True,
            },
            tools=(),
            tool_implementation_revision=TOOL_IMPLEMENTATION_REVISION,
        ),
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
    task_gateway = async_task_gateway or HttpAsyncTaskClient(
        app_settings,
        guards=dependency_guards,
    )
    task_manager = AsyncTaskManager(task_gateway, app_settings, AsyncTaskMetrics())
    session_store = build_agent_session_store(
        kind=app_settings.agent_session_store,
        redis_url=app_settings.agent_session_redis_url.get_secret_value(),
        namespace=app_settings.agent_session_redis_namespace,
    )
    container = Container(
        settings=app_settings,
        jwt_verifier=InternalJwtVerifier(app_settings),
        agent_service=AgentApplicationService(app_runner),
        dag_service=dag_service,
        planning_service=AgentDagPlanningService(app_planner, dag_service),
        process_planning_service=AgentDagPlanningService(
            app_planner,
            process_dag_service,
            process_write_tools=(
                frozenset({"refund_start"})
                if app_settings.agent_refund_start_enabled
                else frozenset()
            ),
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
        confirmation_service=confirmation_service,
        session_service=AgentSessionService(
            cast(ResumableAgentRunner, app_runner),
            session_store,
            ttl_seconds=app_settings.agent_session_ttl_seconds,
            lease_seconds=app_settings.agent_session_lease_seconds,
            lease_owner_id=(app_settings.async_task_worker_id or f"api-{uuid4().hex}"),
        ),
        session_store=session_store,
        readiness_probe=app_readiness_probe,
        confirmable_tools=GovernedToolset(
            app_settings,
            platform_client,
            mcp_gateway=mcp_gateway,
            sandbox_gateway=sandbox_gateway,
            confirmation_consumer=confirmation_service,
        ).confirmable_metadata(),
        execution_versions=execution_versions,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        try:
            yield
        finally:
            await task_manager.shutdown()
            await platform_client.close()
            await mcp_gateway.close()
            await sandbox_gateway.close()
            await app_readiness_probe.close()
            await confirmation_service.close()
            await session_store.close()

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

    @app.exception_handler(AgentSessionNotFoundError)
    async def agent_session_not_found(
        request: Request,
        exc: AgentSessionNotFoundError,
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(status_code=404, content={"error": "agent session not found"})

    @app.exception_handler(AgentSessionActiveError)
    @app.exception_handler(AgentSessionConflictError)
    @app.exception_handler(AgentSessionGoalMismatchError)
    async def agent_session_conflict(request: Request, exc: RuntimeError) -> JSONResponse:
        del request, exc
        return JSONResponse(status_code=409, content={"error": "agent session conflict"})

    @app.exception_handler(AgentSessionResumeConfirmationRequiredError)
    async def agent_session_confirmation_required(
        request: Request,
        exc: AgentSessionResumeConfirmationRequiredError,
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=412,
            content={"error": "fresh side-effect confirmation required"},
        )

    app.include_router(router)
    if app_settings.agent_v2_enabled:
        app.include_router(candidate_router)
    return app
