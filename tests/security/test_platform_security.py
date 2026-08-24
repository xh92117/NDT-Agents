"""S1-11 platform secret, transport, encryption, rotation, and audit tests."""

from __future__ import annotations

import asyncio
import json
import socket
import ssl
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import SecretBytes, SecretStr, ValidationError
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine

import ndt_agents.storage.postgres as postgres_module
from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.observability import (
    AuditKind,
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.runtime.logging import redact_credentials
from ndt_agents.security import (
    AuditSecurityHook,
    EncryptedEnvelope,
    EnvelopeEncryptionService,
    InMemoryKeyProvider,
    InMemorySecretProvider,
    KeySelector,
    KeyState,
    SecretManager,
    SecretSelector,
    SecurityContext,
    SecurityEnvironment,
    SecurityError,
    TransportKind,
    TransportSecurityService,
)
from ndt_agents.storage.postgres import ManagedPostgresSettings, PostgresSettings, PostgresStorage
from ndt_agents.storage.redis import ManagedRedisSettings, RedisBackend, RedisSettings

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("PLATFORM_OPERATOR",),
    permission_version="permissions-1",
)
OTHER_SCOPE = SCOPE.model_copy(update={"project_id": UUID("00000000-0000-4000-8000-000000000202")})
TASK_ID = UUID("00000000-0000-4000-8000-000000000301")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class SecurityRuntime:
    def __init__(self) -> None:
        self.clock = Clock()
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="ndt-security-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.repository = InMemoryAuditRepository()
        audit = AuditService(self.repository, self.traces)
        event_ids = iter(UUID(int=value) for value in range(1, 1000))
        self.hook = AuditSecurityHook(
            audit,
            clock=self.clock,
            event_id_factory=event_ids.__next__,
        )

    def close(self) -> None:
        self.traces.shutdown()


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def context(
    *,
    scope: TenantScope = SCOPE,
    environment: SecurityEnvironment = SecurityEnvironment.PRODUCTION,
) -> SecurityContext:
    return SecurityContext(
        scope=scope,
        environment=environment,
        request_id="security-request-1",
        task_id=TASK_ID,
        policy_version="platform-security-1",
        allowed_secret_purposes=frozenset({"postgres.password", "redis.password"}),
        allowed_key_purposes=frozenset({"artifact.content"}),
    )


def secret_selector(
    secret_id: str = "postgres-password",
    purpose: str = "postgres.password",
) -> SecretSelector:
    return SecretSelector(
        secret_id=secret_id,
        environment=SecurityEnvironment.PRODUCTION,
        tenant_id=SCOPE.tenant_id,
        project_id=SCOPE.project_id,
        purpose=purpose,
    )


def key_selector() -> KeySelector:
    return KeySelector(
        key_id="artifact-key",
        environment=SecurityEnvironment.PRODUCTION,
        tenant_id=SCOPE.tenant_id,
        project_id=SCOPE.project_id,
        purpose="artifact.content",
    )


def test_secret_lease_is_reference_only_bounded_and_audited() -> None:
    runtime = SecurityRuntime()
    provider = InMemorySecretProvider()
    selector = secret_selector()
    provider.register_test_secret(selector, version="v1", value=SecretStr("top-secret-value"))
    manager = SecretManager(provider, runtime.hook, clock=runtime.clock, lease_seconds=30)
    try:
        with runtime.traces.start_span("security.secret"):
            lease = manager.resolve_current(context(), selector)
            assert manager.read(context(), lease).get_secret_value() == "top-secret-value"
        assert "top-secret-value" not in repr(lease)
        assert "top-secret-value" not in json.dumps(lease.model_dump(mode="json"))
        events = runtime.repository.list(SCOPE)
        assert [event.action for event in events] == [
            "security.secret.resolve",
            "security.secret.use",
        ]
        assert all(event.kind is AuditKind.SECURITY for event in events)
        assert "top-secret-value" not in json.dumps(
            [event.model_dump(mode="json") for event in events]
        )
    finally:
        runtime.close()


def test_secret_rotation_expiry_scope_revocation_and_provider_recovery() -> None:
    runtime = SecurityRuntime()
    provider = InMemorySecretProvider()
    selector = secret_selector()
    old_ref = provider.register_test_secret(selector, version="v1", value=SecretStr("old-secret"))
    manager = SecretManager(provider, runtime.hook, clock=runtime.clock, lease_seconds=10)
    try:
        with runtime.traces.start_span("security.secret.lifecycle"):
            old_lease = manager.resolve_current(context(), selector)
            runtime.clock.advance(11)
            with pytest.raises(SecurityError, match="expired") as expired:
                manager.read(context(), old_lease)
            assert expired.value.code == "SECRET_LEASE_EXPIRED"

            fresh_old_lease = manager.resolve_current(context(), selector)
            changed_permissions = context(
                scope=SCOPE.model_copy(update={"permission_version": "permissions-2"})
            )
            with pytest.raises(SecurityError, match="outside") as permission_error:
                manager.read(changed_permissions, fresh_old_lease)
            assert permission_error.value.code == "SECURITY_SCOPE_MISMATCH"

            new_ref = manager.rotate(
                context(), selector, version="v2", value=SecretStr("new-secret")
            )
            assert new_ref.version == "v2"
            with pytest.raises(SecurityError, match="stale") as stale:
                manager.read(context(), fresh_old_lease)
            assert stale.value.code == "SECRET_VERSION_STALE"

            restarted = SecretManager(provider, runtime.hook, clock=runtime.clock, lease_seconds=10)
            new_lease = restarted.resolve_current(context(), selector)
            assert restarted.read(context(), new_lease).get_secret_value() == "new-secret"

            wrong = context(scope=OTHER_SCOPE)
            with pytest.raises(SecurityError, match="outside") as scope_error:
                restarted.resolve_current(wrong, selector)
            assert scope_error.value.code == "SECURITY_SCOPE_MISMATCH"

            provider.set_available(False)
            with pytest.raises(SecurityError, match="unavailable") as unavailable:
                restarted.resolve_current(context(), selector)
            assert unavailable.value.code == "SECRET_PROVIDER_UNAVAILABLE"
            provider.set_available(True)
            restarted.revoke(context(), new_ref)
            with pytest.raises(SecurityError, match="revoked") as revoked:
                restarted.resolve_current(context(), selector)
            assert revoked.value.code == "SECRET_REVOKED"
        assert old_ref.version == "v1"
        assert len(runtime.repository.list(SCOPE)) >= 10
    finally:
        runtime.close()


def test_transport_policy_enforces_tls_and_loopback_exception() -> None:
    runtime = SecurityRuntime()
    transport = TransportSecurityService(runtime.hook)
    production = context()
    local = context(environment=SecurityEnvironment.LOCAL)
    try:
        with runtime.traces.start_span("security.transport"):
            assert transport.validate(
                production, TransportKind.HTTPS, "https://api.example.test/v1"
            ).encrypted
            assert transport.validate(
                production,
                TransportKind.POSTGRES,
                "postgresql+asyncpg://db.example.test/ndt?sslmode=verify-full",
            ).certificate_validation
            assert transport.validate(
                production,
                TransportKind.REDIS,
                "rediss://redis.example.test/0?ssl_cert_reqs=required",
            ).certificate_validation
            loopback = transport.validate(local, TransportKind.HTTPS, "http://127.0.0.1:8000")
            assert loopback.loopback_exception and not loopback.encrypted

            denied_endpoints = (
                (TransportKind.HTTPS, "http://api.example.test"),
                (TransportKind.HTTPS, "https://user:password@api.example.test"),
                (TransportKind.POSTGRES, "postgresql+asyncpg://db.example.test/ndt"),
                (TransportKind.REDIS, "rediss://redis.example.test/0"),
            )
            for kind, endpoint in denied_endpoints:
                with pytest.raises(SecurityError, match="transport security") as denied:
                    transport.validate(production, kind, endpoint)
                assert denied.value.code == "TLS_POLICY_DENIED"
            with pytest.raises(SecurityError):
                transport.validate(local, TransportKind.HTTPS, "http://service.local")
        events = runtime.repository.list(SCOPE)
        assert len(events) == 9
        assert sum(event.decision == "DENY" for event in events) == 5
    finally:
        runtime.close()


def test_aes_gcm_scope_tamper_and_unique_nonce_are_enforced() -> None:
    runtime = SecurityRuntime()
    provider = InMemoryKeyProvider()
    selector = key_selector()
    provider.register_test_key(selector, version="v1", material=SecretBytes(b"1" * 32))
    encryption = EnvelopeEncryptionService(provider, runtime.hook)
    try:
        with runtime.traces.start_span("security.encryption"):
            first = encryption.encrypt(
                context(), selector, b"inspection evidence", aad_context="artifact-v1"
            )
            second = encryption.encrypt(
                context(), selector, b"inspection evidence", aad_context="artifact-v1"
            )
            assert first.nonce_b64u != second.nonce_b64u
            assert first.ciphertext_b64u != second.ciphertext_b64u
            assert (
                encryption.decrypt(context(), first, aad_context="artifact-v1")
                == b"inspection evidence"
            )

            with pytest.raises(SecurityError, match="outside") as cross_scope:
                encryption.decrypt(context(scope=OTHER_SCOPE), first, aad_context="artifact-v1")
            assert cross_scope.value.code == "SECURITY_SCOPE_MISMATCH"

            replacement = "A" if first.ciphertext_b64u[0] != "A" else "B"
            tampered = first.model_copy(
                update={"ciphertext_b64u": replacement + first.ciphertext_b64u[1:]}
            )
            with pytest.raises(SecurityError, match="authenticated decryption") as invalid:
                encryption.decrypt(context(), tampered, aad_context="artifact-v1")
            assert invalid.value.code == "DECRYPTION_FAILED"
        serialized_events = json.dumps(
            [event.model_dump(mode="json") for event in runtime.repository.list(SCOPE)]
        )
        assert "inspection evidence" not in serialized_events
        assert first.ciphertext_b64u not in serialized_events
    finally:
        runtime.close()


def test_key_rotation_preserves_old_decrypt_until_revocation_and_survives_restart() -> None:
    runtime = SecurityRuntime()
    provider = InMemoryKeyProvider()
    selector = key_selector()
    old_ref = provider.register_test_key(selector, version="v1", material=SecretBytes(b"1" * 32))
    encryption = EnvelopeEncryptionService(provider, runtime.hook)
    try:
        with runtime.traces.start_span("security.key.lifecycle"):
            old_envelope = encryption.encrypt(
                context(), selector, b"old evidence", aad_context="artifact-v1"
            )
            new_ref = encryption.rotate(
                context(), selector, version="v2", material=SecretBytes(b"2" * 32)
            )
            assert provider.state(old_ref) is KeyState.DECRYPT_ONLY
            assert provider.state(new_ref) is KeyState.ACTIVE
            new_envelope = encryption.encrypt(
                context(), selector, b"new evidence", aad_context="artifact-v2"
            )
            assert new_envelope.key_ref == new_ref

            restarted = EnvelopeEncryptionService(provider, runtime.hook)
            assert (
                restarted.decrypt(context(), old_envelope, aad_context="artifact-v1")
                == b"old evidence"
            )
            restarted.revoke(context(), old_ref)
            with pytest.raises(SecurityError, match="revoked") as revoked:
                restarted.decrypt(context(), old_envelope, aad_context="artifact-v1")
            assert revoked.value.code == "KEY_REVOKED"
            assert (
                restarted.decrypt(context(), new_envelope, aad_context="artifact-v2")
                == b"new evidence"
            )

            provider.set_available(False)
            with pytest.raises(SecurityError, match="unavailable") as unavailable:
                restarted.encrypt(context(), selector, b"blocked", aad_context="artifact-v3")
            assert unavailable.value.code == "KEY_PROVIDER_UNAVAILABLE"
        with pytest.raises(SecurityError, match="invalid length"):
            InMemoryKeyProvider().register_test_key(
                selector, version="v1", material=SecretBytes(b"short")
            )
    finally:
        runtime.close()


def test_managed_storage_resolves_transient_secrets_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SecurityRuntime()
    provider = InMemorySecretProvider()
    postgres_secret = secret_selector()
    redis_secret = secret_selector("redis-password", "redis.password")
    provider.register_test_secret(postgres_secret, version="v1", value=SecretStr("postgres-secret"))
    provider.register_test_secret(redis_secret, version="v1", value=SecretStr("redis-secret"))
    secrets = SecretManager(provider, runtime.hook, clock=runtime.clock)
    transport = TransportSecurityService(runtime.hook)

    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("managed client construction attempted network access")

    postgres_options: dict[str, Any] = {}
    postgres_module_any = cast(Any, postgres_module)
    real_create_async_engine = postgres_module_any.create_async_engine

    def capture_engine(url: str | URL, **kwargs: Any) -> AsyncEngine:
        postgres_options.update(kwargs)
        return cast(AsyncEngine, real_create_async_engine(url, **kwargs))

    try:
        with runtime.traces.start_span("security.storage"):
            with monkeypatch.context() as isolated:
                isolated.setattr(socket.socket, "connect", deny_network)
                isolated.setattr(postgres_module, "create_async_engine", capture_engine)
                postgres = PostgresStorage.from_managed_settings(
                    ManagedPostgresSettings(
                        endpoint=("postgresql+asyncpg://db.example.test/ndt?sslmode=verify-full"),
                        username="ndt_app",
                        password_secret=postgres_secret,
                    ),
                    context=context(),
                    secrets=secrets,
                    transport=transport,
                )
                redis = RedisBackend.from_managed_settings(
                    ManagedRedisSettings(
                        endpoint=("rediss://redis.example.test/0?ssl_cert_reqs=required"),
                        username="ndt_app",
                        password_secret=redis_secret,
                    ),
                    context=context(),
                    secrets=secrets,
                    transport=transport,
                )
        run(postgres.close())
        run(redis.close())
        ssl_context = postgres_options["connect_args"]["ssl"]
        assert isinstance(ssl_context, ssl.SSLContext)
        assert ssl_context.minimum_version is ssl.TLSVersion.TLSv1_2
        assert ssl_context.check_hostname
        assert ssl_context.verify_mode is ssl.CERT_REQUIRED
        redis_connection = redis._client.connection_pool.connection_kwargs
        assert redis_connection["ssl_min_version"] is ssl.TLSVersion.TLSv1_2
        assert redis_connection["ssl_cert_reqs"] == "required"
        serialized = json.dumps(
            [event.model_dump(mode="json") for event in runtime.repository.list(SCOPE)]
        )
        assert "postgres-secret" not in serialized
        assert "redis-secret" not in serialized
        assert len(runtime.repository.list(SCOPE)) == 6
        with pytest.raises(ValidationError):
            PostgresSettings(dsn=SecretStr("postgresql+asyncpg://user:pass@db.example.test/ndt"))
        with pytest.raises(ValidationError):
            RedisSettings(url=SecretStr("redis://:pass@redis.example.test/0"))
    finally:
        runtime.close()


def test_audit_failure_prevents_secret_release() -> None:
    runtime = SecurityRuntime()
    provider = InMemorySecretProvider()
    selector = secret_selector()
    provider.register_test_secret(selector, version="v1", value=SecretStr("not-released"))
    manager = SecretManager(provider, runtime.hook, clock=runtime.clock)
    try:
        with pytest.raises(SecurityError, match="audit event") as failed:
            manager.resolve_current(context(), selector)
        assert failed.value.code == "SECURITY_AUDIT_FAILED"

        with pytest.raises(SecurityError, match="audit event"):
            manager.rotate(context(), selector, version="v2", value=SecretStr("not-committed"))
        assert provider.current_ref(selector).version == "v1"

        key_provider = InMemoryKeyProvider()
        key = key_selector()
        old_key = key_provider.register_test_key(key, version="v1", material=SecretBytes(b"1" * 32))
        encryption = EnvelopeEncryptionService(key_provider, runtime.hook)
        with pytest.raises(SecurityError, match="audit event"):
            encryption.rotate(context(), key, version="v2", material=SecretBytes(b"2" * 32))
        assert key_provider.state(old_key) is KeyState.ACTIVE
    finally:
        runtime.close()


def test_contracts_reject_raw_or_unknown_fields() -> None:
    selector = secret_selector()
    with pytest.raises(ValidationError):
        SecretSelector.model_validate({**selector.model_dump(), "value": "raw-secret"})
    envelope = {
        "key_ref": {
            **key_selector().model_dump(mode="json"),
            "version": "v1",
            "algorithm": "AES-256-GCM",
        },
        "nonce_b64u": "A" * 16,
        "ciphertext_b64u": "A" * 22,
        "aad_sha256": "a" * 64,
        "plaintext": "forbidden",
    }
    with pytest.raises(ValidationError):
        EncryptedEnvelope.model_validate(envelope)

    redacted = redact_credentials(
        "postgresql+asyncpg://user:db-password@db.test/ndt "
        "rediss://user:redis-password@redis.test/0"
    )
    assert "db-password" not in redacted
    assert "redis-password" not in redacted
    assert redacted.count("[REDACTED]") == 2

    with pytest.raises(SecurityError, match="empty") as empty_secret:
        InMemorySecretProvider().register_test_secret(selector, version="v1", value=SecretStr(""))
    assert empty_secret.value.code == "SECRET_VALUE_INVALID"
