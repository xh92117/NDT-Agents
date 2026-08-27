"""Application-owned loopback-only local Workbench composition."""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ndt_agents.client import WorkbenchRuntime
from ndt_agents.identity.middleware import IdentityRuntime
from ndt_agents.identity.models import OidcSettings
from ndt_agents.identity.oidc import OidcJwtVerifier
from ndt_agents.identity.rbac import Permission, RbacPolicy, RoutePermissionPolicy
from ndt_agents.models.inference import ModelInferenceProvider
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings

LOCAL_WORKBENCH_SESSION_PATH = "/local/workbench/session"
_COOKIE_NAME = "ndt_local_workbench_session"
_TENANT_ID = UUID("00000000-0000-4000-8000-000000000101")
_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000102")
_USER_ID = UUID("00000000-0000-4000-8000-000000000103")
_PERMISSION_VERSION = "permissions-1"
_ROLE = "PROJECT_OPERATOR"


class LocalWorkbenchSessionMiddleware:
    """Convert one ephemeral same-origin cookie into exact scoped API headers."""

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if path.startswith("/v1/") and self._has_session(scope):
            replacement = {
                b"authorization": f"Bearer {self._token}".encode("ascii"),
                b"x-tenant-id": str(_TENANT_ID).encode("ascii"),
                b"x-project-id": str(_PROJECT_ID).encode("ascii"),
            }
            scope = dict(scope)
            scope["headers"] = [
                (key, value)
                for key, value in scope.get("headers", [])
                if key.lower() not in replacement
            ] + list(replacement.items())
        await self._app(scope, receive, send)

    def _has_session(self, scope: Scope) -> bool:
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        cookie = SimpleCookie()
        cookie.load(headers.get(b"cookie", b"").decode("latin-1"))
        session = cookie.get(_COOKIE_NAME)
        return session is not None and hmac.compare_digest(session.value, self._token)


def _identity_and_token() -> tuple[IdentityRuntime, str]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "s6-local-workbench", "alg": "RS256", "use": "sig"})
    issuer = "https://local-workbench.invalid/"
    audience = "ndt-agents-api"
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": "s6-local-workbench-user",
            "user_id": str(_USER_ID),
            "tenant_id": str(_TENANT_ID),
            "project_ids": [str(_PROJECT_ID)],
            "roles": [_ROLE],
            "permission_version": _PERMISSION_VERSION,
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(hours=1),
            "jti": "s6-local-workbench-session",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "s6-local-workbench", "typ": "JWT"},
    )
    permissions = frozenset(
        {
            Permission.WORKBENCH_CAPABILITY_READ,
            Permission.WORKBENCH_TASK_CREATE,
            Permission.WORKBENCH_TASK_READ,
            Permission.WORKBENCH_EVENT_READ,
        }
    )
    identity = IdentityRuntime(
        verifier=OidcJwtVerifier(
            settings=OidcSettings(issuer=issuer, audience=audience),
            jwks={"keys": [public_jwk]},
        ),
        rbac=RbacPolicy(
            policy_version="rbac-s6-local-workbench",
            grants={_ROLE: permissions},
        ),
        routes=RoutePermissionPolicy(
            policy_version="routes-s6-local-workbench",
            permissions={
                ("GET", "/v1/workbench/capabilities"): Permission.WORKBENCH_CAPABILITY_READ,
                ("POST", "/v1/workbench/tasks"): Permission.WORKBENCH_TASK_CREATE,
                ("GET", "/v1/workbench/task"): Permission.WORKBENCH_TASK_READ,
                ("GET", "/v1/workbench/events"): Permission.WORKBENCH_EVENT_READ,
            },
        ),
    )
    return identity, token


def create_local_workbench_app(
    settings: AppSettings,
    *,
    configure_logs: bool = True,
    model_environment: Mapping[str, str] | None = None,
    model_provider: ModelInferenceProvider | None = None,
) -> FastAPI:
    """Build the explicit local frontend-integration application without a network call."""

    if not settings.local_workbench_enabled:
        raise ValueError("the local workbench setting is disabled")
    identity, token = _identity_and_token()
    app = create_app(
        settings,
        configure_logs=configure_logs,
        identity=identity,
        workbench=WorkbenchRuntime(),
        model_environment=model_environment,
        model_provider=model_provider,
    )

    @app.get(LOCAL_WORKBENCH_SESSION_PATH, include_in_schema=False)
    async def start_local_workbench_session() -> RedirectResponse:
        response = RedirectResponse("/workbench", status_code=303)
        response.set_cookie(
            _COOKIE_NAME,
            token,
            httponly=True,
            samesite="strict",
            max_age=3600,
            path="/",
        )
        response.headers["cache-control"] = "no-store"
        return response

    app.add_middleware(LocalWorkbenchSessionMiddleware, token=token)
    app.state.local_workbench_session_enabled = True
    return app
