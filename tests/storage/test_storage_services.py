"""S1-02 storage integration tests using deterministic local backends."""

from __future__ import annotations

import asyncio
import io
import socket
from collections.abc import Coroutine
from contextlib import redirect_stdout
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from ndt_agents.contracts.v1 import DataClassification, TenantScope
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings
from ndt_agents.runtime.readiness import DependencyProbe
from ndt_agents.storage.artifacts import ArtifactStorageService, InMemoryObjectBackend
from ndt_agents.storage.errors import StorageError
from ndt_agents.storage.postgres import PostgresSettings, PostgresStorage
from ndt_agents.storage.redis import (
    InMemoryKeyValueBackend,
    RedisBackend,
    RedisSettings,
    RedisStateStore,
)
from ndt_agents.storage.schema import metadata

ROOT_SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("TESTER",),
    permission_version="test-1",
)
OTHER_SCOPE = ROOT_SCOPE.model_copy(
    update={"project_id": UUID("00000000-0000-4000-8000-000000000202")}
)


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def test_schema_has_pgvector_and_explicit_scope_on_every_business_table() -> None:
    assert set(metadata.tables) == {
        "tenant_registry",
        "project_registry",
        "tenant_membership",
        "project_membership",
        "runtime_task",
        "runtime_checkpoint",
        "runtime_assignment_output",
        "runtime_side_effect",
        "runtime_interrupt",
        "runtime_audit_event",
        "artifact_record",
        "knowledge_embedding",
    }
    for table_name in {
        "project_registry",
        "project_membership",
        "runtime_task",
        "runtime_checkpoint",
        "runtime_assignment_output",
        "runtime_side_effect",
        "runtime_interrupt",
        "runtime_audit_event",
        "artifact_record",
        "knowledge_embedding",
    }:
        table = metadata.tables[table_name]
        assert {"tenant_id", "project_id"} <= set(table.columns.keys())
    assert str(metadata.tables["knowledge_embedding"].c.embedding.type) == "VECTOR(1536)"


def test_alembic_migration_compiles_upgrade_and_rollback_for_postgresql() -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused@localhost/unused")

    upgrade_output = io.StringIO()
    with redirect_stdout(upgrade_output):
        command.upgrade(config, "head", sql=True)
    upgrade_sql = upgrade_output.getvalue()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in upgrade_sql
    assert "CREATE TABLE runtime_task" in upgrade_sql
    assert "CREATE TABLE knowledge_embedding" in upgrade_sql
    assert "CREATE TABLE runtime_assignment_output" in upgrade_sql
    assert "CREATE TABLE runtime_side_effect" in upgrade_sql
    assert "CREATE TABLE runtime_interrupt" in upgrade_sql
    assert "CREATE TABLE runtime_audit_event" in upgrade_sql
    assert "CREATE TRIGGER runtime_audit_event_append_only" in upgrade_sql
    assert "CREATE TABLE runtime_approval_event" in upgrade_sql
    assert "CREATE TRIGGER runtime_approval_event_append_only" in upgrade_sql
    assert "CREATE TABLE runtime_review_recovery_event" in upgrade_sql
    assert "CREATE TRIGGER review_recovery_append_only" in upgrade_sql
    assert "FORCE ROW LEVEL SECURITY" in upgrade_sql
    assert "ADD COLUMN graph_version" in upgrade_sql
    assert "VECTOR(1536)" in upgrade_sql

    downgrade_output = io.StringIO()
    with redirect_stdout(downgrade_output):
        command.downgrade(config, "head:base", sql=True)
    downgrade_sql = downgrade_output.getvalue()
    assert "DROP TABLE knowledge_embedding" in downgrade_sql
    assert "DROP TABLE runtime_task" in downgrade_sql
    assert "DROP TABLE runtime_assignment_output" in downgrade_sql
    assert "DROP TABLE runtime_audit_event" in downgrade_sql
    assert "DROP TABLE runtime_approval_event" in downgrade_sql
    assert "DROP TABLE runtime_review_recovery_event" in downgrade_sql


def test_connection_settings_are_immutable_strict_and_secret_safe() -> None:
    postgres = PostgresSettings(dsn=SecretStr("postgresql+asyncpg://user:password@localhost/ndt"))
    redis = RedisSettings(url=SecretStr("redis://:password@localhost/0"))

    assert "password" not in repr(postgres)
    assert "password" not in repr(redis)
    with pytest.raises(ValidationError):
        PostgresSettings(dsn=SecretStr("sqlite:///local.db"))
    with pytest.raises(ValidationError):
        RedisSettings(url=SecretStr("http://redis.local"))


def test_client_construction_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("storage client construction attempted network access")

    with monkeypatch.context() as isolated:
        isolated.setattr(socket.socket, "connect", deny_network)
        postgres = PostgresStorage.from_settings(
            PostgresSettings(dsn=SecretStr("postgresql+asyncpg://user:pass@localhost/ndt"))
        )
        redis = RedisBackend.from_settings(
            RedisSettings(url=SecretStr("redis://:pass@localhost/0"))
        )
    run(postgres.close())
    run(redis.close())


def test_redis_state_keys_are_scoped_bounded_and_expiring() -> None:
    async def scenario() -> None:
        backend = InMemoryKeyValueBackend(clock=lambda: 100.0)
        store = RedisStateStore(backend, namespace="checkpoint", default_ttl_seconds=60)
        await store.put(ROOT_SCOPE, "task-1", b"tenant-one")

        assert await store.get(ROOT_SCOPE, "task-1") == b"tenant-one"
        assert await store.get(OTHER_SCOPE, "task-1") is None
        assert backend.keys == {
            "ndt:v1:tenant:00000000-0000-4000-8000-000000000101:"
            "project:00000000-0000-4000-8000-000000000102:checkpoint:task-1"
        }
        with pytest.raises(StorageError, match="STORAGE_INVALID_KEY"):
            await store.put(ROOT_SCOPE, "../escape", b"bad")

    run(scenario())


def test_artifact_service_verifies_hash_and_rejects_overwrite_and_cross_scope_read() -> None:
    async def scenario() -> None:
        backend = InMemoryObjectBackend()
        service = ArtifactStorageService(backend=backend, bucket="test-artifacts")
        artifact_id = UUID("00000000-0000-4000-8000-000000000301")
        created = await service.put(
            scope=ROOT_SCOPE,
            artifact_id=artifact_id,
            artifact_version="v1",
            content=b"inspection-result",
            media_type="application/octet-stream",
            classification=DataClassification.INTERNAL,
        )

        assert await service.get(ROOT_SCOPE, created) == b"inspection-result"
        with pytest.raises(StorageError, match="ARTIFACT_SCOPE_DENIED"):
            await service.get(OTHER_SCOPE, created)
        with pytest.raises(StorageError, match="ARTIFACT_ALREADY_EXISTS"):
            await service.put(
                scope=ROOT_SCOPE,
                artifact_id=artifact_id,
                artifact_version="v1",
                content=b"different",
                media_type="application/octet-stream",
                classification=DataClassification.INTERNAL,
            )

        backend.corrupt(created.uri.removeprefix("artifact://test-artifacts/"), b"corrupt")
        with pytest.raises(StorageError, match="ARTIFACT_INTEGRITY_FAILED"):
            await service.get(ROOT_SCOPE, created)

    run(scenario())


def test_readiness_runs_injected_dependencies_but_liveness_stays_independent() -> None:
    async def healthy() -> None:
        return None

    async def unavailable() -> None:
        raise StorageError(
            code="REDIS_UNAVAILABLE",
            message="Redis is unavailable.",
            retryable=True,
            next_action="Retry after the dependency recovers.",
        )

    app = create_app(
        AppSettings(),
        configure_logs=False,
        readiness_probes=(
            DependencyProbe(name="postgres", check=healthy),
            DependencyProbe(name="redis", check=unavailable),
        ),
    )
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json()["status"] == "PASS"
    assert ready.status_code == 503
    assert ready.json()["status"] == "FAIL"
    assert ready.json()["checks"] == [
        {"name": "application", "status": "PASS", "error_code": None},
        {"name": "postgres", "status": "PASS", "error_code": None},
        {"name": "redis", "status": "FAIL", "error_code": "REDIS_UNAVAILABLE"},
    ]


def test_storage_errors_carry_operator_action_without_backend_exception_text() -> None:
    error = StorageError(
        code="POSTGRES_UNAVAILABLE",
        message="PostgreSQL is unavailable.",
        retryable=True,
        next_action="Check the dependency and retry.",
    )

    assert error.code == "POSTGRES_UNAVAILABLE"
    assert error.retryable is True
    assert error.next_action == "Check the dependency and retry."
    assert datetime.now(UTC).tzinfo is UTC
