"""S1-03 SEC-TENANT and SEC-CACHE identity-isolation checks."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi.testclient import TestClient

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.identity.middleware import IdentityRuntime
from ndt_agents.identity.models import IdentityError, OidcSettings
from ndt_agents.identity.oidc import OidcJwtVerifier
from ndt_agents.identity.rbac import Permission, RbacPolicy, RoutePermissionPolicy
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings
from ndt_agents.storage.postgres import apply_rls_scope

TENANT_ID = UUID("00000000-0000-4000-8000-000000000401")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000402")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000403")
USER_ID = UUID("00000000-0000-4000-8000-000000000404")


@pytest.fixture(scope="module")
def signing_material() -> tuple[RSAPrivateKey, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "test-key-1", "alg": "RS256", "use": "sig"})
    return private_key, {"keys": [public_jwk]}


def issue_token(
    private_key: RSAPrivateKey,
    *,
    roles: tuple[str, ...] = ("PROJECT_VIEWER",),
    tenant_id: UUID = TENANT_ID,
    project_ids: tuple[UUID, ...] = (PROJECT_ID,),
    permission_version: str = "permissions-1",
    expires_delta: timedelta = timedelta(minutes=5),
    kid: str = "test-key-1",
) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "https://identity.example.test/",
        "aud": "ndt-agents-api",
        "sub": "oidc-subject-1",
        "user_id": str(USER_ID),
        "tenant_id": str(tenant_id),
        "project_ids": [str(project_id) for project_id in project_ids],
        "roles": list(roles),
        "permission_version": permission_version,
        "iat": now,
        "nbf": now - timedelta(seconds=1),
        "exp": now + expires_delta,
        "jti": "token-1",
    }
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid, "typ": "JWT"},
    )


def identity_runtime(jwks: dict[str, Any]) -> IdentityRuntime:
    verifier = OidcJwtVerifier(
        settings=OidcSettings(
            issuer="https://identity.example.test/",
            audience="ndt-agents-api",
        ),
        jwks=jwks,
    )
    rbac = RbacPolicy(
        policy_version="rbac-1",
        grants={
            "PROJECT_VIEWER": frozenset({Permission.RUNTIME_SCOPE_READ}),
            "NO_ACCESS": frozenset(),
        },
    )
    routes = RoutePermissionPolicy(
        policy_version="routes-1",
        permissions={
            ("GET", "/v1/runtime/scope"): Permission.RUNTIME_SCOPE_READ,
        },
    )
    return IdentityRuntime(verifier=verifier, rbac=rbac, routes=routes)


def authorization_headers(token: str, *, project_id: UUID = PROJECT_ID) -> dict[str, str]:
    return {
        "authorization": f"Bearer {token}",
        "x-tenant-id": str(TENANT_ID),
        "x-project-id": str(project_id),
        "x-request-id": "identity-test-1",
    }


def test_health_is_public_but_protected_route_requires_bearer(
    signing_material: tuple[RSAPrivateKey, dict[str, Any]],
) -> None:
    _, jwks = signing_material
    app = create_app(AppSettings(), configure_logs=False, identity=identity_runtime(jwks))

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        denied = client.get("/v1/runtime/scope", headers={"x-request-id": "missing-token"})

    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"
    assert denied.json()["error_code"] == "AUTH_TOKEN_MISSING"
    assert denied.json()["request_id"] == "missing-token"


def test_valid_oidc_claims_bind_immutable_request_scope(
    signing_material: tuple[RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwks = signing_material
    token = issue_token(private_key)
    app = create_app(AppSettings(), configure_logs=False, identity=identity_runtime(jwks))

    with TestClient(app) as client:
        response = client.get("/v1/runtime/scope", headers=authorization_headers(token))

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0.0",
        "tenant_id": str(TENANT_ID),
        "project_id": str(PROJECT_ID),
        "user_id": str(USER_ID),
        "role_codes": ["PROJECT_VIEWER"],
        "permission_version": "permissions-1",
        "rbac_policy_version": "rbac-1",
        "route_policy_version": "routes-1",
    }


@pytest.mark.parametrize(
    ("case", "expected_status", "expected_code"),
    [
        ("expired", 401, "AUTH_TOKEN_EXPIRED"),
        ("unknown-key", 401, "AUTH_KEY_UNKNOWN"),
        ("wrong-project", 403, "AUTH_PROJECT_DENIED"),
        ("no-access", 403, "AUTH_PERMISSION_DENIED"),
    ],
)
def test_expired_forged_scope_and_insufficient_role_are_denied(
    signing_material: tuple[RSAPrivateKey, dict[str, Any]],
    case: str,
    expected_status: int,
    expected_code: str,
) -> None:
    private_key, jwks = signing_material
    kwargs: dict[str, Any] = {}
    project_header = PROJECT_ID
    if case == "expired":
        kwargs["expires_delta"] = timedelta(minutes=-1)
    elif case == "unknown-key":
        kwargs["kid"] = "forged-key"
    elif case == "wrong-project":
        project_header = OTHER_PROJECT_ID
    elif case == "no-access":
        kwargs["roles"] = ("NO_ACCESS",)
    token = issue_token(private_key, **kwargs)
    app = create_app(AppSettings(), configure_logs=False, identity=identity_runtime(jwks))

    with TestClient(app) as client:
        response = client.get(
            "/v1/runtime/scope",
            headers=authorization_headers(token, project_id=project_header),
        )

    assert response.status_code == expected_status
    assert response.json()["error_code"] == expected_code
    assert token not in response.text


def test_unregistered_protected_route_is_denied_by_default(
    signing_material: tuple[RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwks = signing_material
    token = issue_token(private_key)
    app = create_app(AppSettings(), configure_logs=False, identity=identity_runtime(jwks))

    with TestClient(app) as client:
        response = client.get("/v1/unregistered", headers=authorization_headers(token))

    assert response.status_code == 403
    assert response.json()["error_code"] == "AUTH_ROUTE_UNREGISTERED"


def test_cache_authorization_scope_changes_for_every_security_version(
    signing_material: tuple[RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwks = signing_material
    runtime = identity_runtime(jwks)
    principal_one = runtime.verifier.verify(
        issue_token(private_key, project_ids=(PROJECT_ID, OTHER_PROJECT_ID))
    )
    principal_two = runtime.verifier.verify(
        issue_token(private_key, permission_version="permissions-2")
    )

    first = runtime.cache_authorization_scope(principal_one, PROJECT_ID)
    second = runtime.cache_authorization_scope(principal_two, PROJECT_ID)
    other_project = runtime.cache_authorization_scope(principal_one, OTHER_PROJECT_ID)

    assert first != second
    assert first != other_project
    assert str(TENANT_ID) in first
    assert "permissions-1" in first
    assert "rbac-1" in first
    assert "routes-1" in first

    unauthorized = runtime.verifier.verify(issue_token(private_key))
    with pytest.raises(IdentityError) as denied:
        runtime.cache_authorization_scope(unauthorized, OTHER_PROJECT_ID)
    assert denied.value.code == "AUTH_PROJECT_DENIED"


def test_rls_migration_forces_policies_and_has_offline_rollback() -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused@localhost/unused")
    upgrade_output = io.StringIO()
    with redirect_stdout(upgrade_output):
        command.upgrade(config, "head", sql=True)
    upgrade_sql = upgrade_output.getvalue()

    for table in (
        "runtime_task",
        "runtime_checkpoint",
        "runtime_assignment_output",
        "runtime_side_effect",
        "runtime_interrupt",
        "runtime_audit_event",
        "artifact_record",
        "knowledge_embedding",
        "tenant_registry",
        "project_registry",
        "tenant_membership",
        "project_membership",
    ):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in upgrade_sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in upgrade_sql
        assert f"CREATE POLICY scope_isolation ON {table}" in upgrade_sql

    downgrade_output = io.StringIO()
    with redirect_stdout(downgrade_output):
        command.downgrade(config, "head:base", sql=True)
    downgrade_sql = downgrade_output.getvalue()
    assert "DROP POLICY IF EXISTS scope_isolation ON runtime_task" in downgrade_sql
    assert "DROP TABLE project_membership" in downgrade_sql


def test_database_scope_is_set_locally_before_transaction_queries() -> None:
    class RecordingConnection:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str]]] = []

        async def execute(self, statement: object, parameters: dict[str, str]) -> object:
            self.calls.append((str(statement), parameters))
            return object()

    connection = RecordingConnection()
    scope = TenantScope(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        user_id=USER_ID,
        role_codes=("PROJECT_VIEWER",),
        permission_version="permissions-1",
    )

    import asyncio

    asyncio.run(apply_rls_scope(connection, scope))

    assert [call[1]["value"] for call in connection.calls] == [
        str(TENANT_ID),
        str(PROJECT_ID),
        str(USER_ID),
        "permissions-1",
    ]
    assert all("set_config" in call[0] for call in connection.calls)
