"""FastAPI application factory for the S1-01 runtime scaffold."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHttpException
from starlette.staticfiles import StaticFiles

from ndt_agents.client.execution import (
    GeneralWorkbenchExecutor,
    ProfessionalWorkbenchExecutor,
    ReviewedWorkbenchExecutorRouter,
)
from ndt_agents.client.models import (
    ClientTaskClass,
    TaskCreateRequest,
    TaskEventBatch,
    WorkbenchCapabilities,
    WorkbenchExecutionMode,
    WorkbenchTask,
)
from ndt_agents.client.service import WorkbenchError, WorkbenchRuntime
from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.identity.middleware import IdentityRuntime, ScopeAuthorizationMiddleware
from ndt_agents.identity.models import ScopeResponse
from ndt_agents.knowledge.entry import KnowledgeEntryGraph
from ndt_agents.knowledge.models import KnowledgeEntryResponse, KnowledgeUiStartRequest
from ndt_agents.models.config import load_model_runtime_configuration
from ndt_agents.models.deepseek import build_deepseek_provider
from ndt_agents.models.inference import ModelInferenceProvider
from ndt_agents.observability import (
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.agent_config import (
    ConfiguredAgentRuntime,
    load_agent_runtime_configuration,
)
from ndt_agents.orchestration.configured_review_runtime import (
    ConfiguredReviewBindings,
    ConfiguredReviewedOrchestrationRuntime,
)
from ndt_agents.orchestration.configured_runtime import (
    ConfiguredExecutorFactory,
    ConfiguredOrchestrationRuntime,
)
from ndt_agents.orchestration.general_model_delegate import (
    GeneralModelDelegate,
    build_general_delegate_catalog,
)
from ndt_agents.orchestration.langgraph_runtime import ConfiguredChildDelegate
from ndt_agents.orchestration.professional_model_delegate import (
    REVIEWER_VERSION,
    ReviewModelDelegate,
    TechnicalQaModelDelegate,
    build_professional_delegate_catalog,
    build_professional_review_bindings,
)
from ndt_agents.orchestration.prompt_registry import load_prompt_registry
from ndt_agents.orchestration.review_recovery import ReviewRecoveryRepository
from ndt_agents.runtime.config import AppSettings
from ndt_agents.runtime.logging import configure_logging
from ndt_agents.runtime.middleware import RequestContextMiddleware, apply_response_headers
from ndt_agents.runtime.models import HealthCheck, HealthResponse, ProblemDetail
from ndt_agents.runtime.readiness import DependencyProbe
from ndt_agents.security.models import SecurityEnvironment

_LOGGER = logging.getLogger(__name__)


def _general_provider_timeout_seconds(agent_runtime: ConfiguredAgentRuntime) -> float:
    return agent_runtime.profile("general").timeout_ms / 1_000


def _professional_provider_timeout_seconds(agent_runtime: ConfiguredAgentRuntime) -> float:
    return (
        max(
            agent_runtime.profile("general").timeout_ms,
            agent_runtime.profile("technical_qa").timeout_ms,
        )
        / 1_000
    )


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unavailable"))


def _problem_response(status_code: int, problem: ProblemDetail) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content=problem.model_dump(mode="json"))
    apply_response_headers(response, problem.request_id)
    return response


def create_app(
    settings: AppSettings | None = None,
    *,
    configure_logs: bool = True,
    readiness_probes: tuple[DependencyProbe, ...] = (),
    identity: IdentityRuntime | None = None,
    knowledge_entry: KnowledgeEntryGraph | None = None,
    workbench: WorkbenchRuntime | None = None,
    model_environment: Mapping[str, str] | None = None,
    model_provider: ModelInferenceProvider | None = None,
    audit_service: AuditService | None = None,
    trace_service: TraceService | None = None,
    agent_tool_references: frozenset[str] = frozenset(),
    agent_delegates: Mapping[str, ConfiguredChildDelegate] | None = None,
    review_bindings: ConfiguredReviewBindings | None = None,
    review_recovery_repository: ReviewRecoveryRepository | None = None,
) -> FastAPI:
    """Build an application without contacting storage, model providers, or external services."""

    active_settings = settings or AppSettings.from_environment()
    if knowledge_entry is not None and identity is None:
        raise ValueError("Knowledge UI entry requires the authenticated identity runtime.")
    if workbench is not None and identity is None:
        raise ValueError("Workbench routes require the authenticated identity runtime.")
    model_runtime = None
    if active_settings.model_config_path is not None:
        model_runtime = load_model_runtime_configuration(
            active_settings.model_config_path,
            env_file_path=active_settings.model_env_file,
            environ=model_environment,
            expected_environment=SecurityEnvironment(active_settings.environment.value),
        )
    prompt_registry = None
    if active_settings.prompt_config_path is not None:
        prompt_registry = load_prompt_registry(active_settings.prompt_config_path)
    agent_runtime = None
    if active_settings.agent_config_path is not None:
        assert model_runtime is not None
        assert prompt_registry is not None
        agent_runtime = load_agent_runtime_configuration(
            active_settings.agent_config_path,
            model_runtime=model_runtime,
            prompt_registry=prompt_registry,
            known_tool_references=agent_tool_references,
        )
    if agent_delegates is not None and agent_runtime is None:
        raise ValueError("Configured agent delegates require an agent runtime configuration.")
    owned_trace_service: TraceService | None = None
    active_delegates = agent_delegates
    general_delegate = None
    professional_delegate = None
    review_model_delegate = None
    if active_settings.general_model_delegate_enabled:
        assert model_runtime is not None
        assert agent_runtime is not None
        if agent_delegates is not None:
            raise ValueError("The local General model delegate cannot replace injected delegates.")
        if audit_service is not None and trace_service is None:
            raise ValueError("An injected audit service requires its active trace service.")
        if audit_service is None:
            if trace_service is not None:
                audit_service = AuditService(InMemoryAuditRepository(), trace_service)
            else:
                owned_trace_service = TraceService(
                    service_name=active_settings.service_name,
                    service_version=active_settings.service_version,
                    exporter=InMemorySpanExporter(),
                )
                trace_service = owned_trace_service
                audit_service = AuditService(InMemoryAuditRepository(), trace_service)
        active_provider = model_provider or build_deepseek_provider(
            model_runtime,
            timeout_seconds=(
                _professional_provider_timeout_seconds(agent_runtime)
                if active_settings.professional_model_delegate_enabled
                else _general_provider_timeout_seconds(agent_runtime)
            ),
        )
        general_delegate = GeneralModelDelegate(
            model_runtime,
            active_provider,
            audit_service,
            trace_service=trace_service,
        )
        if active_settings.professional_model_delegate_enabled:
            if review_bindings is not None:
                raise ValueError(
                    "The local professional model delegate cannot replace injected review bindings."
                )
            professional_delegate = TechnicalQaModelDelegate(
                model_runtime,
                active_provider,
                audit_service,
                trace_service=trace_service,
            )
            technical_profile = agent_runtime.profile("technical_qa")
            review_model_delegate = ReviewModelDelegate(
                model_runtime,
                active_provider,
                audit_service,
                reviewer_version=REVIEWER_VERSION,
                model_version=technical_profile.model_id,
                trace_service=trace_service,
            )
            active_delegates = build_professional_delegate_catalog(
                agent_runtime,
                general_delegate,
                professional_delegate,
            )
            review_bindings = build_professional_review_bindings(
                agent_runtime,
                review_model_delegate,
            )
        else:
            active_delegates = build_general_delegate_catalog(agent_runtime, general_delegate)
    orchestration_runtime = (
        ConfiguredOrchestrationRuntime(ConfiguredExecutorFactory(agent_runtime, active_delegates))
        if agent_runtime is not None and active_delegates is not None
        else None
    )
    if review_bindings is not None and orchestration_runtime is None:
        raise ValueError("Configured review bindings require configured agent delegates.")
    if review_recovery_repository is not None and review_bindings is None:
        raise ValueError("Review recovery requires configured review bindings.")
    reviewed_orchestration_runtime = (
        ConfiguredReviewedOrchestrationRuntime(
            orchestration_runtime,
            review_bindings,
            review_recovery_repository=review_recovery_repository,
        )
        if orchestration_runtime is not None and review_bindings is not None
        else None
    )
    if configure_logs:
        configure_logging(
            service_name=active_settings.service_name,
            environment=active_settings.environment.value,
            level=active_settings.log_level,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _LOGGER.info("runtime started", extra={"event": "runtime_started"})
        try:
            if workbench is not None:
                await workbench.start()
            yield
        finally:
            if workbench is not None:
                await workbench.stop()
            if owned_trace_service is not None:
                owned_trace_service.shutdown()
            _LOGGER.info("runtime stopped", extra={"event": "runtime_stopped"})

    docs_url = "/docs" if active_settings.expose_api_docs else None
    openapi_url = "/openapi.json" if active_settings.expose_api_docs else None
    app = FastAPI(
        title=active_settings.service_name,
        version=active_settings.service_version,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.state.model_runtime = model_runtime
    app.state.prompt_registry = prompt_registry
    app.state.agent_runtime = agent_runtime
    app.state.orchestration_runtime = orchestration_runtime
    app.state.reviewed_orchestration_runtime = reviewed_orchestration_runtime
    app.state.general_model_delegate = general_delegate
    app.state.professional_model_delegate = professional_delegate
    app.state.review_model_delegate = review_model_delegate
    app.state.professional_workbench_executor = None
    app.state.workbench_capabilities = None
    app.state.audit_service = audit_service
    if identity is not None:
        app.add_middleware(ScopeAuthorizationMiddleware, identity=identity)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/health/live", response_model=HealthResponse, tags=["runtime"])
    async def liveness() -> HealthResponse:
        checks = (HealthCheck(name="process", status="PASS"),)
        return HealthResponse(
            service=active_settings.service_name,
            service_version=active_settings.service_version,
            status="PASS",
            checks=checks,
        )

    @app.get("/health/ready", response_model=HealthResponse, tags=["runtime"])
    async def readiness(response: Response) -> HealthResponse:
        dependency_checks = tuple([await probe.evaluate() for probe in readiness_probes])
        model_checks = (
            (HealthCheck(name="model_configuration", status="PASS"),)
            if model_runtime is not None
            else ()
        )
        prompt_checks = (
            (HealthCheck(name="prompt_configuration", status="PASS"),)
            if prompt_registry is not None
            else ()
        )
        agent_checks = (
            (HealthCheck(name="agent_configuration", status="PASS"),)
            if agent_runtime is not None
            else ()
        )
        review_checks = (
            (HealthCheck(name="review_execution_binding", status="PASS"),)
            if reviewed_orchestration_runtime is not None
            else ()
        )
        checks = (
            HealthCheck(name="application", status="PASS"),
            *model_checks,
            *prompt_checks,
            *agent_checks,
            *review_checks,
            *dependency_checks,
        )
        status: Literal["PASS", "FAIL"] = (
            "FAIL" if any(check.status == "FAIL" for check in checks) else "PASS"
        )
        if status == "FAIL":
            response.status_code = 503
        return HealthResponse(
            service=active_settings.service_name,
            service_version=active_settings.service_version,
            status=status,
            checks=checks,
        )

    if identity is not None:

        @app.get("/v1/runtime/scope", response_model=ScopeResponse, tags=["runtime"])
        async def active_scope(request: Request) -> ScopeResponse:
            scope = cast(TenantScope, request.state.scope)
            return ScopeResponse(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                user_id=scope.user_id,
                role_codes=scope.role_codes,
                permission_version=scope.permission_version,
                rbac_policy_version=identity.rbac.policy_version,
                route_policy_version=identity.routes.policy_version,
            )

    if knowledge_entry is not None:

        @app.post(
            "/v1/knowledge/imports",
            response_model=KnowledgeEntryResponse,
            status_code=202,
            tags=["knowledge"],
        )
        async def start_knowledge_import(
            payload: KnowledgeUiStartRequest,
            request: Request,
            response: Response,
        ) -> KnowledgeEntryResponse:
            scope = cast(TenantScope, request.state.scope)
            result = knowledge_entry.start_ui(scope=scope, request=payload)
            if result.status != "DISPATCH_READY":
                response.status_code = 409
            return knowledge_entry.response(result)

    if workbench is not None:
        enabled_task_classes: tuple[ClientTaskClass, ...] = ()
        execution_mode = WorkbenchExecutionMode.CONTRACT_ONLY
        if reviewed_orchestration_runtime is not None:
            assert orchestration_runtime is not None
            professional_executor = ProfessionalWorkbenchExecutor(reviewed_orchestration_runtime)
            workbench.bind_executor(
                ReviewedWorkbenchExecutorRouter(
                    GeneralWorkbenchExecutor(
                        orchestration_runtime,
                        failure_code=(
                            (lambda: general_delegate.last_error_code)
                            if general_delegate is not None
                            else None
                        ),
                    ),
                    professional_executor,
                )
            )
            app.state.professional_workbench_executor = professional_executor
            enabled_task_classes = (
                ClientTaskClass.GENERAL,
                ClientTaskClass.PROFESSIONAL_SYNC,
            )
            execution_mode = WorkbenchExecutionMode.REVIEWED_PROFESSIONAL
        elif active_settings.general_model_delegate_enabled:
            assert orchestration_runtime is not None
            assert general_delegate is not None
            workbench.bind_executor(
                GeneralWorkbenchExecutor(
                    orchestration_runtime,
                    failure_code=lambda: general_delegate.last_error_code,
                )
            )
            enabled_task_classes = (ClientTaskClass.GENERAL,)
            execution_mode = WorkbenchExecutionMode.GENERAL_LOCAL
        capabilities = WorkbenchCapabilities(
            execution_mode=execution_mode,
            task_classes=enabled_task_classes,
            limitations=(
                "SYNTHETIC input only.",
                "Customer, confidential, restricted, and production data are forbidden.",
                "Formal conclusions and publication are disabled.",
            ),
        )
        app.state.workbench_capabilities = capabilities
        asset_root = Path(__file__).resolve().parents[1] / "client" / "web"
        app.mount(
            "/workbench/assets",
            StaticFiles(directory=asset_root / "assets"),
            name="workbench-assets",
        )

        @app.get("/workbench", include_in_schema=False)
        async def workbench_shell() -> FileResponse:
            response = FileResponse(asset_root / "index.html", media_type="text/html")
            response.headers["cache-control"] = "no-store"
            response.headers["content-security-policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'"
            )
            return response

        @app.get("/workbench/sw.js", include_in_schema=False)
        async def workbench_service_worker() -> FileResponse:
            response = FileResponse(asset_root / "sw.js", media_type="text/javascript")
            response.headers["cache-control"] = "no-cache"
            response.headers["service-worker-allowed"] = "/workbench"
            return response

        @app.get(
            "/v1/workbench/capabilities",
            response_model=WorkbenchCapabilities,
            tags=["workbench"],
        )
        async def read_workbench_capabilities() -> WorkbenchCapabilities:
            return capabilities

        @app.post(
            "/v1/workbench/tasks",
            response_model=WorkbenchTask,
            status_code=202,
            tags=["workbench"],
        )
        async def create_workbench_task(
            payload: TaskCreateRequest, request: Request
        ) -> WorkbenchTask:
            scope = cast(TenantScope, request.state.scope)
            return await workbench.create_and_schedule(scope, payload)

        @app.get(
            "/v1/workbench/task",
            response_model=WorkbenchTask,
            tags=["workbench"],
        )
        async def read_workbench_task(task_id: UUID, request: Request) -> WorkbenchTask:
            scope = cast(TenantScope, request.state.scope)
            return workbench.get(scope, task_id)

        @app.get(
            "/v1/workbench/events",
            response_model=None,
            tags=["workbench"],
        )
        async def stream_workbench_events(
            task_id: UUID, request: Request, after_sequence: int = 0
        ) -> StreamingResponse:
            scope = cast(TenantScope, request.state.scope)
            workbench.events(scope, task_id, after_sequence)

            async def encode_events() -> AsyncIterator[bytes]:
                async for batch in workbench.stream_events(scope, task_id, after_sequence):
                    for event in batch.events:
                        data = event.model_dump_json()
                        yield f"id: {event.sequence}\nevent: task-event\ndata: {data}\n\n".encode()
                    control = TaskEventBatch(
                        task_id=batch.task_id,
                        after_sequence=batch.after_sequence,
                        last_sequence=batch.last_sequence,
                        terminal=batch.terminal,
                        events=(),
                    ).model_dump_json()
                    yield f"event: stream-state\ndata: {control}\n\n".encode()

            return StreamingResponse(
                encode_events(),
                media_type="text/event-stream",
                headers={
                    "cache-control": "no-store",
                    "x-accel-buffering": "no",
                },
            )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _error: RequestValidationError) -> JSONResponse:
        return _problem_response(
            422,
            ProblemDetail(
                error_code="REQUEST_VALIDATION_FAILED",
                message="The request payload or parameters are invalid.",
                request_id=_request_id(request),
                retryable=False,
                next_action="Correct the request using the versioned API schema.",
            ),
        )

    @app.exception_handler(StarletteHttpException)
    async def http_error(request: Request, error: StarletteHttpException) -> JSONResponse:
        message = (
            "The requested resource was not found."
            if error.status_code == 404
            else "Request failed."
        )
        return _problem_response(
            error.status_code,
            ProblemDetail(
                error_code=f"HTTP_{error.status_code}",
                message=message,
                request_id=_request_id(request),
                retryable=False,
                next_action="Verify the request path, method, and authorization scope.",
            ),
        )

    @app.exception_handler(WorkbenchError)
    async def workbench_error(request: Request, error: WorkbenchError) -> JSONResponse:
        return _problem_response(
            error.status_code,
            ProblemDetail(
                error_code=error.code,
                message=str(error),
                request_id=_request_id(request),
                retryable=False,
                next_action=error.next_action,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, error: Exception) -> JSONResponse:
        request_id = _request_id(request)
        _LOGGER.error(
            "unhandled request failure",
            exc_info=(type(error), error, error.__traceback__),
            extra={
                "event": "request_failed",
                "error_code": "INTERNAL_ERROR",
                "request_id": request_id,
            },
        )
        return _problem_response(
            500,
            ProblemDetail(
                error_code="INTERNAL_ERROR",
                message="The request could not be completed.",
                request_id=request_id,
                retryable=False,
                next_action="Contact the service operator with the request ID.",
            ),
        )

    return app
