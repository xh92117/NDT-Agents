"""FastAPI application factory for the S1-01 runtime scaffold."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal, cast

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHttpException

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.identity.middleware import IdentityRuntime, ScopeAuthorizationMiddleware
from ndt_agents.identity.models import ScopeResponse
from ndt_agents.runtime.config import AppSettings
from ndt_agents.runtime.logging import configure_logging
from ndt_agents.runtime.middleware import RequestContextMiddleware, apply_response_headers
from ndt_agents.runtime.models import HealthCheck, HealthResponse, ProblemDetail
from ndt_agents.runtime.readiness import DependencyProbe

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
) -> FastAPI:
    """Build an application without contacting storage, models, or external services."""

    active_settings = settings or AppSettings.from_environment()
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
        checks = (HealthCheck(name="application", status="PASS"), *dependency_checks)
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
