"""Bearer authentication and tenant/project/RBAC request enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.identity.models import IdentityError, Principal
from ndt_agents.identity.oidc import OidcJwtVerifier
from ndt_agents.identity.rbac import RbacPolicy, RoutePermissionPolicy
from ndt_agents.runtime.middleware import apply_response_headers
from ndt_agents.runtime.models import ProblemDetail


@dataclass(frozen=True, slots=True)
class IdentityRuntime:
    verifier: OidcJwtVerifier
    rbac: RbacPolicy
    routes: RoutePermissionPolicy

    def cache_authorization_scope(self, principal: Principal, project_id: UUID) -> str:
        if project_id not in principal.project_ids:
            raise IdentityError(
                code="AUTH_PROJECT_DENIED",
                status_code=403,
                message="The requested project is not authorized.",
                next_action="Select an authorized project.",
            )
        return (
            f"tenant={principal.tenant_id}|project={project_id}|user={principal.user_id}|"
            f"permission={principal.permission_version}|rbac={self.rbac.policy_version}|"
            f"routes={self.routes.policy_version}"
        )


class ScopeAuthorizationMiddleware(BaseHTTPMiddleware):
    """Protect every V1 route and deny any route absent from the versioned policy."""

    def __init__(self, app: ASGIApp, *, identity: IdentityRuntime) -> None:
        super().__init__(app)
        self._identity = identity

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)
        try:
            scope, principal = self._authorize(request)
        except IdentityError as error:
            return self._denied_response(request, error)
        request.state.scope = scope
        request.state.principal = principal
        request.state.rbac_policy_version = self._identity.rbac.policy_version
        request.state.route_policy_version = self._identity.routes.policy_version
        return await call_next(request)

    def _authorize(self, request: Request) -> tuple[TenantScope, Principal]:
        authorization = request.headers.get("authorization")
        if authorization is None or not authorization.startswith("Bearer "):
            raise IdentityError(
                code="AUTH_TOKEN_MISSING",
                status_code=401,
                message="Authentication is required.",
                next_action="Authenticate through the approved identity provider.",
            )
        token = authorization.removeprefix("Bearer ")
        if not token or " " in token:
            raise IdentityError(
                code="AUTH_TOKEN_INVALID",
                status_code=401,
                message="The authentication credential is invalid.",
                next_action="Authenticate again through the approved identity provider.",
            )
        principal = self._identity.verifier.verify(token)
        tenant_id = self._header_uuid(request, "x-tenant-id")
        project_id = self._header_uuid(request, "x-project-id")
        if tenant_id != principal.tenant_id:
            raise IdentityError(
                code="AUTH_TENANT_DENIED",
                status_code=403,
                message="The requested tenant is not authorized.",
                next_action="Select an authorized tenant.",
            )
        if project_id not in principal.project_ids:
            raise IdentityError(
                code="AUTH_PROJECT_DENIED",
                status_code=403,
                message="The requested project is not authorized.",
                next_action="Select an authorized project.",
            )
        permission = self._identity.routes.required_permission(request.method, request.url.path)
        if permission is None:
            raise IdentityError(
                code="AUTH_ROUTE_UNREGISTERED",
                status_code=403,
                message="The protected route is not registered for access.",
                next_action="Register an explicit route permission before enabling the route.",
            )
        if not self._identity.rbac.allows(principal, permission):
            raise IdentityError(
                code="AUTH_PERMISSION_DENIED",
                status_code=403,
                message="The active role does not grant the required permission.",
                next_action="Request the required role through an authorized administrator.",
            )
        return (
            TenantScope(
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=principal.user_id,
                role_codes=principal.roles,
                permission_version=principal.permission_version,
            ),
            principal,
        )

    @staticmethod
    def _header_uuid(request: Request, name: str) -> UUID:
        value = request.headers.get(name)
        if value is None:
            raise IdentityError(
                code="AUTH_SCOPE_INVALID",
                status_code=403,
                message="The tenant or project scope is invalid.",
                next_action="Select a valid authorized tenant and project.",
            )
        try:
            return UUID(value)
        except ValueError:
            raise IdentityError(
                code="AUTH_SCOPE_INVALID",
                status_code=403,
                message="The tenant or project scope is invalid.",
                next_action="Select a valid authorized tenant and project.",
            ) from None

    @staticmethod
    def _denied_response(request: Request, error: IdentityError) -> JSONResponse:
        request_id = str(getattr(request.state, "request_id", "unavailable"))
        response = JSONResponse(
            status_code=error.status_code,
            content=ProblemDetail(
                error_code=error.code,
                message=str(error),
                request_id=request_id,
                retryable=False,
                next_action=error.next_action,
            ).model_dump(mode="json"),
        )
        apply_response_headers(response, request_id)
        if error.status_code == 401:
            response.headers["www-authenticate"] = "Bearer"
        return response
