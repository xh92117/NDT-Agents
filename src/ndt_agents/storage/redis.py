"""Tenant-scoped Redis state service and deterministic in-memory test backend."""

from __future__ import annotations

import asyncio
import re
import ssl
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, Self
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.security.models import SecretSelector, SecurityContext
from ndt_agents.security.secrets import SecretManager
from ndt_agents.security.transport import TransportKind, TransportSecurityService
from ndt_agents.storage.errors import StorageError

_LOGICAL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NAMESPACE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class RedisSettings(BaseModel):
    """Loopback-only local/CI compatibility settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: SecretStr
    environment: Literal["local", "ci"] = "local"
    connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    operation_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    @model_validator(mode="after")
    def validate_scheme(self) -> Self:
        parsed = urlsplit(self.url.get_secret_value())
        if parsed.scheme not in {"redis", "rediss"} or parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("direct Redis settings are limited to local loopback")
        return self


class ManagedRedisSettings(BaseModel):
    """Reference-only Redis settings resolved immediately before construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: str = Field(min_length=1, max_length=2048)
    username: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    password_secret: SecretSelector
    connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    operation_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    @model_validator(mode="after")
    def validate_secret_purpose(self) -> Self:
        if self.password_secret.purpose != "redis.password":
            raise ValueError("managed Redis password purpose is invalid")
        return self


class KeyValueBackend(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def ping(self) -> None: ...


class RedisBackend:
    """Bounded Redis adapter that does not connect until an operation is called."""

    def __init__(self, client: Redis, operation_timeout_seconds: float) -> None:
        self._client = client
        self._operation_timeout_seconds = operation_timeout_seconds

    @classmethod
    def from_settings(cls, settings: RedisSettings) -> RedisBackend:
        return cls._from_url(
            settings.url.get_secret_value(),
            connect_timeout_seconds=settings.connect_timeout_seconds,
            operation_timeout_seconds=settings.operation_timeout_seconds,
            encrypted=settings.url.get_secret_value().startswith("rediss://"),
        )

    @classmethod
    def from_managed_settings(
        cls,
        settings: ManagedRedisSettings,
        *,
        context: SecurityContext,
        secrets: SecretManager,
        transport: TransportSecurityService,
    ) -> RedisBackend:
        transport_decision = transport.validate(context, TransportKind.REDIS, settings.endpoint)
        lease = secrets.resolve_current(context, settings.password_secret)
        password = secrets.read(context, lease).get_secret_value()
        parsed = urlsplit(settings.endpoint)
        password_value = quote(password, safe="")
        auth = (
            f"{quote(settings.username, safe='')}:{password_value}@"
            if settings.username is not None
            else f":{password_value}@"
        )
        url = urlunsplit((parsed.scheme, f"{auth}{parsed.netloc}", parsed.path, parsed.query, ""))
        return cls._from_url(
            url,
            connect_timeout_seconds=settings.connect_timeout_seconds,
            operation_timeout_seconds=settings.operation_timeout_seconds,
            encrypted=transport_decision.encrypted,
        )

    @classmethod
    def _from_url(
        cls,
        url: str,
        *,
        connect_timeout_seconds: float,
        operation_timeout_seconds: float,
        encrypted: bool,
    ) -> RedisBackend:
        if encrypted:
            client = Redis.from_url(
                url,
                socket_connect_timeout=connect_timeout_seconds,
                socket_timeout=operation_timeout_seconds,
                decode_responses=False,
                ssl_min_version=ssl.TLSVersion.TLSv1_2,
            )
        else:
            client = Redis.from_url(
                url,
                socket_connect_timeout=connect_timeout_seconds,
                socket_timeout=operation_timeout_seconds,
                decode_responses=False,
            )
        return cls(client, operation_timeout_seconds)

    async def _bounded[T](self, operation: Awaitable[T]) -> T:
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                return await operation
        except (TimeoutError, RedisError):
            raise StorageError(
                code="REDIS_UNAVAILABLE",
                message="Redis is unavailable.",
                retryable=True,
                next_action="Check Redis health and retry the operation.",
            ) from None

    async def get(self, key: str) -> bytes | None:
        value = await self._bounded(self._client.get(key))
        return value if isinstance(value, bytes) else None

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        await self._bounded(self._client.set(key, value, ex=ttl_seconds))

    async def delete(self, key: str) -> None:
        await self._bounded(self._client.delete(key))

    async def ping(self) -> None:
        await self._bounded(self._client.ping())

    async def close(self) -> None:
        await self._client.aclose()


class InMemoryKeyValueBackend:
    """Deterministic backend for local tests; never production storage."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._values: dict[str, tuple[bytes, float]] = {}
        self._lock = asyncio.Lock()

    @property
    def keys(self) -> set[str]:
        return set(self._values)

    async def get(self, key: str) -> bytes | None:
        async with self._lock:
            stored = self._values.get(key)
            if stored is None:
                return None
            value, expires_at = stored
            if expires_at <= self._clock():
                del self._values[key]
                return None
            return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        async with self._lock:
            self._values[key] = (value, self._clock() + ttl_seconds)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._values.pop(key, None)

    async def ping(self) -> None:
        return None


class RedisStateStore:
    """Build scope-bound Redis keys before every state operation."""

    def __init__(
        self, backend: KeyValueBackend, *, namespace: str, default_ttl_seconds: int
    ) -> None:
        if not _NAMESPACE.fullmatch(namespace):
            raise StorageError(
                code="STORAGE_INVALID_NAMESPACE",
                message="The storage namespace is invalid.",
                retryable=False,
                next_action="Use a registered lowercase storage namespace.",
            )
        if not 1 <= default_ttl_seconds <= 2_592_000:
            raise StorageError(
                code="STORAGE_INVALID_TTL",
                message="The storage TTL is outside the allowed range.",
                retryable=False,
                next_action="Use a TTL between 1 second and 30 days.",
            )
        self._backend = backend
        self._namespace = namespace
        self._default_ttl_seconds = default_ttl_seconds

    def _key(self, scope: TenantScope, logical_key: str) -> str:
        if not _LOGICAL_KEY.fullmatch(logical_key):
            raise StorageError(
                code="STORAGE_INVALID_KEY",
                message="The logical storage key is invalid.",
                retryable=False,
                next_action="Use a bounded registered logical key.",
            )
        return (
            f"ndt:v1:tenant:{scope.tenant_id}:project:{scope.project_id}:"
            f"{self._namespace}:{logical_key}"
        )

    async def get(self, scope: TenantScope, logical_key: str) -> bytes | None:
        return await self._backend.get(self._key(scope, logical_key))

    async def put(
        self,
        scope: TenantScope,
        logical_key: str,
        value: bytes,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = self._default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if not 1 <= ttl <= 2_592_000:
            raise StorageError(
                code="STORAGE_INVALID_TTL",
                message="The storage TTL is outside the allowed range.",
                retryable=False,
                next_action="Use a TTL between 1 second and 30 days.",
            )
        await self._backend.set(self._key(scope, logical_key), value, ttl)

    async def delete(self, scope: TenantScope, logical_key: str) -> None:
        await self._backend.delete(self._key(scope, logical_key))
