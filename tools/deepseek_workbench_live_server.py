"""Loopback-only authenticated Web runner for one synthetic DeepSeek task."""

from __future__ import annotations

import argparse
import hmac
import html
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ndt_agents.client import WorkbenchRuntime  # noqa: E402
from ndt_agents.identity.middleware import IdentityRuntime  # noqa: E402
from ndt_agents.identity.models import OidcSettings  # noqa: E402
from ndt_agents.identity.oidc import OidcJwtVerifier  # noqa: E402
from ndt_agents.identity.rbac import (  # noqa: E402
    Permission,
    RbacPolicy,
    RoutePermissionPolicy,
)
from ndt_agents.orchestration.general_model_delegate import (  # noqa: E402
    DEEPSEEK_POLICY_ACKNOWLEDGEMENT,
)
from ndt_agents.runtime.app import create_app  # noqa: E402
from ndt_agents.runtime.config import AppSettings, RuntimeEnvironment  # noqa: E402

HOST = "127.0.0.1"
PORT = 8765
COOKIE_NAME = "ndt_live_session"
TENANT_ID = UUID("00000000-0000-4000-8000-000000000101")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000102")
USER_ID = UUID("00000000-0000-4000-8000-000000000103")
PERMISSION_VERSION = "permissions-1"
ROLE = "PROJECT_OPERATOR"
FIXED_GOAL = (
    "Confirm the live Web workbench uses only synthetic input and summarize its "
    "non-production limitations."
)
FIXED_SUCCESS_CRITERIA = (
    "State that the input is synthetic.",
    "State that formal use is forbidden.",
    "State that no professional inspection conclusion is produced.",
)


class LiveWorkbenchGuardMiddleware:
    """Inject one ephemeral local session and restrict the live task payload."""

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        cookie = SimpleCookie()
        cookie.load(headers.get(b"cookie", b"").decode("latin-1"))
        session = cookie.get(COOKIE_NAME)
        authenticated = session is not None and hmac.compare_digest(
            session.value,
            self._token,
        )
        path = str(scope.get("path", ""))
        method = str(scope.get("method", ""))
        if authenticated and path.startswith("/v1/"):
            replacement = {
                b"authorization": f"Bearer {self._token}".encode("ascii"),
                b"x-tenant-id": str(TENANT_ID).encode("ascii"),
                b"x-project-id": str(PROJECT_ID).encode("ascii"),
            }
            scope = dict(scope)
            scope["headers"] = [
                (key, value)
                for key, value in scope.get("headers", [])
                if key.lower() not in replacement
            ] + list(replacement.items())
        if authenticated and method == "POST" and path == "/v1/workbench/tasks":
            body, receive = await self._bounded_body(receive)
            if body is None or not self._is_fixed_request(body):
                response = JSONResponse(
                    status_code=403,
                    content={
                        "error_code": "LIVE_SYNTHETIC_REQUEST_REQUIRED",
                        "message": "The local live runner accepts only its fixed synthetic task.",
                        "retryable": False,
                        "next_action": "Use the fixed synthetic Web E2E task.",
                    },
                )
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)

    @staticmethod
    async def _bounded_body(receive: Receive) -> tuple[bytes | None, Receive]:
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return None, receive
            body.extend(message.get("body", b""))
            if len(body) > 16_384:
                return None, receive
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        return bytes(body), replay

    @staticmethod
    def _is_fixed_request(body: bytes) -> bool:
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("schema_version") == "1.0.0"
            and payload.get("task_class") == "P1"
            and payload.get("goal") == FIXED_GOAL
            and payload.get("success_criteria") == list(FIXED_SUCCESS_CRITERIA)
        )


def _identity_and_token() -> tuple[IdentityRuntime, str]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "s6-web-live", "alg": "RS256", "use": "sig"})
    issuer = "https://local-live.invalid/"
    audience = "ndt-agents-api"
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": "s6-web-live-user",
            "user_id": str(USER_ID),
            "tenant_id": str(TENANT_ID),
            "project_ids": [str(PROJECT_ID)],
            "roles": [ROLE],
            "permission_version": PERMISSION_VERSION,
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=10),
            "jti": "s6-web-live-session",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "s6-web-live", "typ": "JWT"},
    )
    permissions = frozenset(
        {
            Permission.WORKBENCH_TASK_CREATE,
            Permission.WORKBENCH_TASK_READ,
            Permission.WORKBENCH_EVENT_READ,
            Permission.WORKBENCH_CAPABILITY_READ,
        }
    )
    identity = IdentityRuntime(
        verifier=OidcJwtVerifier(
            settings=OidcSettings(issuer=issuer, audience=audience),
            jwks={"keys": [public_jwk]},
        ),
        rbac=RbacPolicy(policy_version="rbac-s6-web-live", grants={ROLE: permissions}),
        routes=RoutePermissionPolicy(
            policy_version="routes-s6-web-live",
            permissions={
                ("POST", "/v1/workbench/tasks"): Permission.WORKBENCH_TASK_CREATE,
                ("GET", "/v1/workbench/task"): Permission.WORKBENCH_TASK_READ,
                ("GET", "/v1/workbench/events"): Permission.WORKBENCH_EVENT_READ,
                ("GET", "/v1/workbench/capabilities"): Permission.WORKBENCH_CAPABILITY_READ,
            },
        ),
    )
    return identity, token


def live_settings(acknowledgement: str) -> AppSettings:
    """Build the exact local default-off override for this acknowledged runner."""

    return AppSettings(
        environment=RuntimeEnvironment.LOCAL,
        host=HOST,
        port=PORT,
        model_config_path=str(ROOT / "config/runtime/model-bindings.local.yaml"),
        model_env_file=str(ROOT / ".env"),
        prompt_config_path=str(ROOT / "prompts/professional/catalog.v1.yaml"),
        agent_config_path=str(ROOT / "config/runtime/agent-runtime.local.yaml"),
        general_model_delegate_enabled=True,
        professional_model_delegate_enabled=True,
        deepseek_policy_acknowledgement=acknowledgement,
    )


def create_live_app(
    settings: AppSettings,
    *,
    model_provider: Any | None = None,
    model_environment: Mapping[str, str] | None = None,
) -> Any:
    """Create the loopback-only app with one ephemeral local session."""

    if settings.host != HOST or settings.port != PORT:
        raise ValueError("the live Web runner is fixed to its loopback endpoint")
    identity, token = _identity_and_token()
    app = create_app(
        settings,
        identity=identity,
        workbench=WorkbenchRuntime(),
        model_environment=model_environment,
        model_provider=model_provider,
    )

    @app.get("/local-live/session", include_in_schema=False)
    async def local_live_session() -> RedirectResponse:
        response = RedirectResponse("/workbench", status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="strict",
            max_age=600,
            path="/",
        )
        return response

    @app.get("/local-live/evidence", include_in_schema=False)
    async def local_live_evidence(request: Request) -> JSONResponse:
        if not hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), token):
            return JSONResponse(status_code=404, content={"result": "NOT_FOUND"})
        return JSONResponse(content=_live_evidence_payload())

    @app.get("/local-live/evidence/view", include_in_schema=False)
    async def local_live_evidence_view(request: Request) -> HTMLResponse:
        if not hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), token):
            return HTMLResponse(status_code=404, content="Not found")
        payload = html.escape(json.dumps(_live_evidence_payload(), indent=2, sort_keys=True))
        return HTMLResponse(
            content=f"<!doctype html><title>Sanitized live evidence</title><pre>{payload}</pre>",
            headers={"Cache-Control": "no-store"},
        )

    def _live_evidence_payload() -> dict[str, object]:
        professional = app.state.professional_model_delegate
        reviewer = app.state.review_model_delegate
        professional_inference = professional.last_inference if professional is not None else None
        review_inference = reviewer.last_inference if reviewer is not None else None
        inferences = tuple(
            inference
            for inference in (professional_inference, review_inference)
            if inference is not None
        )
        evidences = tuple(
            inference.evidence for inference in inferences if inference.evidence is not None
        )
        successful = (
            len(inferences) == 2
            and all(inference.status == "SUCCESS" for inference in inferences)
            and app.state.professional_workbench_executor.last_review_manifest_sha256 is not None
        )
        first_evidence = evidences[0] if evidences else None
        professional_evidence = (
            professional_inference.evidence if professional_inference is not None else None
        )
        review_evidence = review_inference.evidence if review_inference is not None else None
        return {
            "result": "SUCCESS" if successful else "PENDING_OR_FAILED",
            "professional_failure_code": (
                professional.last_error_code if professional is not None else None
            ),
            "review_failure_code": reviewer.last_error_code if reviewer is not None else None,
            "professional_delegate_calls": professional.calls if professional is not None else 0,
            "review_delegate_calls": reviewer.calls if reviewer is not None else 0,
            "provider_id": first_evidence.provider_id if first_evidence is not None else None,
            "model_id": first_evidence.model_id if first_evidence is not None else None,
            "model_snapshot": (
                first_evidence.model_snapshot if first_evidence is not None else None
            ),
            "input_tokens": sum(evidence.input_tokens for evidence in evidences),
            "output_tokens": sum(evidence.output_tokens for evidence in evidences),
            "professional_input_tokens": (
                professional_evidence.input_tokens if professional_evidence is not None else 0
            ),
            "professional_output_tokens": (
                professional_evidence.output_tokens if professional_evidence is not None else 0
            ),
            "professional_finish_reason": (
                professional_evidence.finish_reason if professional_evidence is not None else None
            ),
            "review_input_tokens": (
                review_evidence.input_tokens if review_evidence is not None else 0
            ),
            "review_output_tokens": (
                review_evidence.output_tokens if review_evidence is not None else 0
            ),
            "review_finish_reason": (
                review_evidence.finish_reason if review_evidence is not None else None
            ),
            "finish_reasons": [evidence.finish_reason for evidence in evidences],
            "physical_llm_calls": sum(evidence.physical_llm_calls for evidence in evidences),
            "physical_tool_calls": sum(evidence.physical_tool_calls for evidence in evidences),
            "physical_network_calls": sum(
                evidence.physical_network_calls for evidence in evidences
            ),
            "review_required": True,
            "review_completed": successful,
            "formal_use_candidate": False,
            "secret_output": False,
        }

    app.add_middleware(LiveWorkbenchGuardMiddleware, token=token)
    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acknowledgement", required=True)
    args = parser.parse_args()
    if args.acknowledgement != DEEPSEEK_POLICY_ACKNOWLEDGEMENT:
        print(
            json.dumps(
                {"result": "FAILED", "failure_code": "DEEPSEEK_POLICY_ACKNOWLEDGEMENT_REQUIRED"}
            )
        )
        return 2
    app = create_live_app(live_settings(args.acknowledgement))
    print(json.dumps({"result": "READY", "url": f"http://{HOST}:{PORT}/local-live/session"}))
    uvicorn.run(app, host=HOST, port=PORT, log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
