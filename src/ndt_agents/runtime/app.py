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

from ndt_agents.client.models import TaskCreateRequest, TaskEventBatch, WorkbenchTask
from ndt_agents.client.service import WorkbenchError, WorkbenchRuntime
from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.identity.middleware import IdentityRuntime, ScopeAuthorizationMiddleware
from ndt_agents.identity.models import ScopeResponse
from ndt_agents.knowledge.entry import KnowledgeEntryGraph
from ndt_agents.knowledge.models import KnowledgeEntryResponse, KnowledgeUiStartRequest
from ndt_agents.models.config import load_model_runtime_configuration
from ndt_agents.runtime.config import AppSettings
from ndt_agents.runtime.logging import configure_logging
from ndt_agents.runtime.middleware import RequestContextMiddleware, apply_response_headers
from ndt_agents.runtime.models import HealthCheck, HealthResponse, ProblemDetail
from ndt_agents.runtime.readiness import DependencyProbe
from ndt_agents.security.models import SecurityEnvironment

_LOGGER = logging.getLogger(__name__)


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
    if configure_logs:
        configure_logging(
            service_name=active_settings.service_name,
            environment=active_settings.environment.value,
            level=active_settings.log_level,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _LOGGER.info("runtime started", extra={"event": "runtime_started"})
        yield
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
        checks = (
            HealthCheck(name="application", status="PASS"),
            *model_checks,
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
            return workbench.create(scope, payload)

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
            batch = workbench.events(scope, task_id, after_sequence)

            async def encode_events() -> AsyncIterator[bytes]:
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
