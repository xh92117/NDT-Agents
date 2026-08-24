"""Lazy PostgreSQL connection adapter with bounded operations and typed errors."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal, Protocol, Self
from urllib.parse import parse_qsl, urlsplit

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.security.models import SecretSelector, SecurityContext
from ndt_agents.security.secrets import SecretManager
from ndt_agents.security.transport import TransportKind, TransportSecurityService
from ndt_agents.storage.errors import StorageError


class RlsConnection(Protocol):
    async def execute(self, statement: object, parameters: dict[str, str]) -> object: ...


async def apply_rls_scope(connection: AsyncConnection | RlsConnection, scope: TenantScope) -> None:
    """Set transaction-local PostgreSQL scope variables before business queries."""

    values = (
        ("app.tenant_id", str(scope.tenant_id)),
        ("app.project_id", str(scope.project_id)),
        ("app.user_id", str(scope.user_id)),
        ("app.permission_version", scope.permission_version),
    )
    statement = sa.text("SELECT set_config(:setting, :value, true)")
    for setting, value in values:
        await connection.execute(statement, {"setting": setting, "value": value})


class PostgresSettings(BaseModel):
    """Loopback-only local/CI compatibility settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dsn: SecretStr
    environment: Literal["local", "ci"] = "local"
    pool_size: int = Field(default=5, ge=1, le=50)
    pool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    operation_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @model_validator(mode="after")
    def validate_driver(self) -> Self:
        parsed = urlsplit(self.dsn.get_secret_value())
        if parsed.scheme != "postgresql+asyncpg" or parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("direct PostgreSQL settings are limited to local loopback")
        return self


class ManagedPostgresSettings(BaseModel):
    """Reference-only settings resolved immediately before client construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: str = Field(min_length=1, max_length=2048)
    username: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    password_secret: SecretSelector
    pool_size: int = Field(default=5, ge=1, le=50)
    pool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    operation_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @model_validator(mode="after")
    def validate_secret_purpose(self) -> Self:
        if self.password_secret.purpose != "postgres.password":
            raise ValueError("managed PostgreSQL password purpose is invalid")
        return self


class PostgresStorage:
    """Own an async engine without connecting during construction."""

    def __init__(self, engine: AsyncEngine, operation_timeout_seconds: float) -> None:
        self._engine = engine
        self._operation_timeout_seconds = operation_timeout_seconds

    @classmethod
    def from_settings(cls, settings: PostgresSettings) -> PostgresStorage:
        return cls._from_dsn(
            settings.dsn.get_secret_value(),
            pool_size=settings.pool_size,
            pool_timeout_seconds=settings.pool_timeout_seconds,
            operation_timeout_seconds=settings.operation_timeout_seconds,
            ssl_context=None,
        )

    @classmethod
    def from_managed_settings(
        cls,
        settings: ManagedPostgresSettings,
        *,
        context: SecurityContext,
        secrets: SecretManager,
        transport: TransportSecurityService,
    ) -> PostgresStorage:
        transport_decision = transport.validate(context, TransportKind.POSTGRES, settings.endpoint)
        lease = secrets.resolve_current(context, settings.password_secret)
        password = secrets.read(context, lease).get_secret_value()
        parsed = urlsplit(settings.endpoint)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.pop("sslmode", None)
        dsn = URL.create(
            "postgresql+asyncpg",
            username=settings.username,
            password=password,
            host=parsed.hostname,
            port=parsed.port,
            database=parsed.path.lstrip("/"),
            query=query,
        ).render_as_string(hide_password=False)
        ssl_context: ssl.SSLContext | None = None
        if transport_decision.encrypted:
            ssl_context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        return cls._from_dsn(
            dsn,
            pool_size=settings.pool_size,
            pool_timeout_seconds=settings.pool_timeout_seconds,
            operation_timeout_seconds=settings.operation_timeout_seconds,
            ssl_context=ssl_context,
        )

    @classmethod
    def _from_dsn(
        cls,
        dsn: str,
        *,
        pool_size: int,
        pool_timeout_seconds: float,
        operation_timeout_seconds: float,
        ssl_context: ssl.SSLContext | None,
    ) -> PostgresStorage:
        connect_args: dict[str, object] = {"timeout": operation_timeout_seconds}
        if ssl_context is not None:
            connect_args["ssl"] = ssl_context
        engine = create_async_engine(
            dsn,
            pool_pre_ping=True,
            pool_size=pool_size,
            pool_timeout=pool_timeout_seconds,
            connect_args=connect_args,
        )
        return cls(engine, operation_timeout_seconds)

    async def ping(self) -> None:
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                async with self._engine.connect() as connection:
                    await connection.execute(sa.text("SELECT 1"))
        except (TimeoutError, SQLAlchemyError):
            raise StorageError(
                code="POSTGRES_UNAVAILABLE",
                message="PostgreSQL is unavailable.",
                retryable=True,
                next_action="Check PostgreSQL health and retry the operation.",
            ) from None

    @asynccontextmanager
    async def transaction(self, scope: TenantScope) -> AsyncIterator[AsyncConnection]:
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                async with self._engine.begin() as connection:
                    await apply_rls_scope(connection, scope)
                    yield connection
        except (TimeoutError, SQLAlchemyError):
            raise StorageError(
                code="POSTGRES_TRANSACTION_FAILED",
                message="The PostgreSQL transaction failed.",
                retryable=True,
                next_action="Inspect dependency health and retry from the last checkpoint.",
            ) from None

    async def close(self) -> None:
        await self._engine.dispose()
