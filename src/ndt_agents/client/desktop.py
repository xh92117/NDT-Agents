"""Application-owned desktop session and Tool Registry bridge."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Literal, Protocol, Self
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, model_validator

from ndt_agents.contracts.v1 import StrictModel, ToolResult
from ndt_agents.observability.audit import AuditKind, AuditOutcome, AuditRecord, AuditService
from ndt_agents.observability.tracing import TraceService
from ndt_agents.orchestration.budget import BudgetGuard
from ndt_agents.tools.registry import (
    ToolInvocationContext,
    ToolRegistry,
    ToolRegistryError,
    canonical_sha256,
)

DESKTOP_BRIDGE_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_DESKTOP_ARGUMENT_BYTES = 1024
MAX_DESKTOP_CANCEL_REASON_BYTES = 512
MAX_DESKTOP_SESSION_HANDLE_BYTES = 128
_SESSION_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{31,127}$")


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class DesktopWireModel(StrictModel):
    """Strict camelCase JSON shared by the Python service and Rust shell."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        alias_generator=_to_camel,
        populate_by_name=True,
    )


class DesktopBridgeError(RuntimeError):
    """Stable desktop denial with an actionable recovery boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        next_action: str,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.next_action = next_action
        self.retryable = retryable
        super().__init__(message)

    def to_payload(self, *, request_sha256: str | None = None) -> DesktopBridgeErrorPayload:
        return DesktopBridgeErrorPayload(
            code=self.code,
            message=str(self),
            next_action=self.next_action,
            retryable=self.retryable,
            request_sha256=request_sha256,
        )


class DesktopBridgeRequest(DesktopWireModel):
    """Untrusted IPC input; authority fields intentionally do not exist here."""

    schema_version: Literal["1.0.0"] = DESKTOP_BRIDGE_SCHEMA_VERSION
    operation: Literal["INVOKE"] = "INVOKE"
    session_handle: str = Field(min_length=32, max_length=MAX_DESKTOP_SESSION_HANDLE_BYTES)
    task_id: UUID
    run_id: UUID
    registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    tool_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    arguments: dict[str, object]
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")

    @model_validator(mode="after")
    def validate_untrusted_payload(self) -> Self:
        if _SESSION_HANDLE_PATTERN.fullmatch(self.session_handle) is None:
            raise ValueError("desktop session handle is malformed")
        if self.task_id.int == 0 or self.run_id.int == 0:
            raise ValueError("desktop task and run identities must be non-nil")
        try:
            encoded = json.dumps(
                self.arguments,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError("desktop arguments must be canonical JSON") from error
        if len(encoded) > MAX_DESKTOP_ARGUMENT_BYTES:
            raise ValueError("desktop arguments exceed the input byte budget")
        return self

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", by_alias=True))


class DesktopCancelRequest(DesktopWireModel):
    """Hash-bound cancellation intent; it does not claim physical cancellation."""

    schema_version: Literal["1.0.0"] = DESKTOP_BRIDGE_SCHEMA_VERSION
    operation: Literal["CANCEL"] = "CANCEL"
    session_handle: str = Field(min_length=32, max_length=MAX_DESKTOP_SESSION_HANDLE_BYTES)
    task_id: UUID
    run_id: UUID
    registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=MAX_DESKTOP_CANCEL_REASON_BYTES)

    @model_validator(mode="after")
    def validate_untrusted_payload(self) -> Self:
        if _SESSION_HANDLE_PATTERN.fullmatch(self.session_handle) is None:
            raise ValueError("desktop session handle is malformed")
        if self.task_id.int == 0 or self.run_id.int == 0:
            raise ValueError("desktop task and run identities must be non-nil")
        if self.reason.strip() != self.reason:
            raise ValueError("desktop cancellation reason must not have outer whitespace")
        if len(self.reason.encode("utf-8")) > MAX_DESKTOP_CANCEL_REASON_BYTES:
            raise ValueError("desktop cancellation reason exceeds the UTF-8 byte budget")
        return self

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", by_alias=True))


class DesktopBridgeErrorPayload(DesktopWireModel):
    """Versioned error envelope exposed by the native ABI."""

    schema_version: Literal["1.0.0"] = DESKTOP_BRIDGE_SCHEMA_VERSION
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    message: str = Field(min_length=1, max_length=2000)
    next_action: str = Field(min_length=1, max_length=2000)
    retryable: bool
    request_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class DesktopBridgeResult(DesktopWireModel):
    schema_version: Literal["1.0.0"] = DESKTOP_BRIDGE_SCHEMA_VERSION
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_result: ToolResult


@dataclass(frozen=True, slots=True)
class DesktopSessionGrant:
    """Application-owned authority resolved from an opaque handle."""

    context: ToolInvocationContext
    budget: BudgetGuard
    observation_sha256: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() != UTC.utcoffset(
            self.expires_at
        ):
            raise ValueError("desktop session expiry must be UTC")
        if not _is_sha256(self.observation_sha256):
            raise ValueError("desktop observation identity must be SHA-256")


class DesktopSessionAuthority(Protocol):
    def resolve(self, session_handle: str) -> DesktopSessionGrant: ...


class InMemoryDesktopSessionAuthority:
    """Thread-safe reference authority; raw session handles are never persisted."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._clock = clock
        self._grants: dict[str, DesktopSessionGrant] = {}
        self._lock = RLock()

    def install(self, session_handle: str, grant: DesktopSessionGrant) -> None:
        digest = _session_sha256(session_handle)
        with self._lock:
            self._grants[digest] = grant

    def revoke(self, session_handle: str) -> None:
        digest = _session_sha256(session_handle)
        with self._lock:
            self._grants.pop(digest, None)

    def resolve(self, session_handle: str) -> DesktopSessionGrant:
        digest = _session_sha256(session_handle)
        with self._lock:
            grant = self._grants.get(digest)
            if grant is None:
                raise DesktopBridgeError(
                    "DESKTOP_SESSION_REQUIRED",
                    "No application-owned authenticated desktop session matches the handle.",
                    next_action="Authenticate again through the application session workflow.",
                )
            if self._clock() >= grant.expires_at:
                self._grants.pop(digest, None)
                raise DesktopBridgeError(
                    "DESKTOP_SESSION_EXPIRED",
                    "The application-owned desktop session has expired.",
                    next_action="Authenticate again before requesting a local tool invocation.",
                )
            return grant


class DesktopBridgeService:
    """Resolve desktop authority, then reuse the sole Tool Registry invocation path."""

    def __init__(
        self,
        *,
        authority: DesktopSessionAuthority,
        registry: ToolRegistry,
        audit: AuditService,
        traces: TraceService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        event_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._authority = authority
        self._registry = registry
        self._audit = audit
        self._traces = traces
        self._clock = clock
        self._event_id_factory = event_id_factory

    async def invoke(self, request: DesktopBridgeRequest) -> DesktopBridgeResult:
        grant = self._authority.resolve(request.session_handle)
        context = grant.context
        with self._traces.start_span("desktop.bridge.invoke"):
            if self._clock() >= grant.expires_at:
                self._deny(
                    grant,
                    request,
                    "DESKTOP_SESSION_EXPIRED",
                    "The application-owned desktop session has expired.",
                    "Authenticate again before requesting a local tool invocation.",
                )
            if request.task_id != context.task_id or request.run_id != context.run_id:
                self._deny(
                    grant,
                    request,
                    "DESKTOP_SCOPE_MISMATCH",
                    "The desktop request does not match the session task and run scope.",
                    "Rebuild the request from the active application task session.",
                )
            if (
                request.registry_version != context.expected_registry_version
                or request.registry_version != self._registry.version
            ):
                self._deny(
                    grant,
                    request,
                    "DESKTOP_REGISTRY_STALE",
                    "The desktop request is not bound to the active Tool Registry snapshot.",
                    "Refresh the desktop task session from the current registry.",
                )
            tool_key = f"{request.tool_name}@{request.tool_version}"
            if (
                tool_key not in context.allowed_tools
                and request.tool_name not in context.allowed_tools
            ):
                self._deny(
                    grant,
                    request,
                    "DESKTOP_TOOL_DENIED",
                    "The desktop request targets a tool outside the session allowlist.",
                    "Use only a tool exposed by the active application task session.",
                )
            try:
                tool_result = await self._registry.invoke(
                    name=request.tool_name,
                    version=request.tool_version,
                    arguments=request.arguments,
                    context=context,
                    budget=grant.budget,
                    observation_sha256=grant.observation_sha256,
                    idempotency_key=request.idempotency_key,
                )
            except ToolRegistryError as error:
                raise DesktopBridgeError(
                    error.code,
                    "The application Tool Registry denied the desktop invocation.",
                    next_action=error.next_action,
                    retryable=error.retryable,
                ) from error
            self._record(
                grant,
                request,
                action="desktop.bridge.invoke",
                decision="AUTHORIZED",
                outcome=AuditOutcome.SUCCESS,
                output_sha256=canonical_sha256(tool_result.model_dump(mode="json")),
            )
        return DesktopBridgeResult(
            request_sha256=request.request_sha256,
            tool_result=tool_result,
        )

    async def cancel(self, request: DesktopCancelRequest) -> None:
        """Validate cancellation authority and fail closed until an adapter is installed."""

        grant = self._authority.resolve(request.session_handle)
        context = grant.context
        with self._traces.start_span("desktop.bridge.cancel"):
            if request.task_id != context.task_id or request.run_id != context.run_id:
                self._deny_cancel(
                    grant,
                    request,
                    "DESKTOP_SCOPE_MISMATCH",
                    "The cancellation request does not match the session task and run scope.",
                    "Rebuild the cancellation request from the active application task session.",
                )
            if (
                request.registry_version != context.expected_registry_version
                or request.registry_version != self._registry.version
            ):
                self._deny_cancel(
                    grant,
                    request,
                    "DESKTOP_REGISTRY_STALE",
                    "The cancellation request is not bound to the active Tool Registry snapshot.",
                    "Refresh the desktop task session from the current registry.",
                )
            self._deny_cancel(
                grant,
                request,
                "DESKTOP_CANCEL_UNAVAILABLE",
                "No application-owned cancellation adapter is installed.",
                "Wait for the current operation to finish or install a qualified "
                "cancellation adapter.",
            )

    def _deny_cancel(
        self,
        grant: DesktopSessionGrant,
        request: DesktopCancelRequest,
        code: str,
        message: str,
        next_action: str,
    ) -> None:
        context = grant.context
        self._audit.record(
            AuditRecord(
                event_id=self._event_id_factory(),
                scope=context.scope,
                kind=AuditKind.AUTHORIZATION,
                action="desktop.bridge.cancel.deny",
                target_type="desktop.request",
                target_id=request.target_request_sha256,
                task_id=context.task_id,
                policy_version=context.policy_version,
                decision=code,
                outcome=AuditOutcome.DENIED,
                input_sha256=request.request_sha256,
                output_sha256=canonical_sha256({"error_code": code}),
                request_id=context.request_id,
                occurred_at=self._clock(),
            )
        )
        raise DesktopBridgeError(code, message, next_action=next_action)

    def _deny(
        self,
        grant: DesktopSessionGrant,
        request: DesktopBridgeRequest,
        code: str,
        message: str,
        next_action: str,
    ) -> None:
        self._record(
            grant,
            request,
            action="desktop.bridge.deny",
            decision=code,
            outcome=AuditOutcome.DENIED,
            output_sha256=canonical_sha256({"error_code": code}),
        )
        raise DesktopBridgeError(code, message, next_action=next_action)

    def _record(
        self,
        grant: DesktopSessionGrant,
        request: DesktopBridgeRequest,
        *,
        action: str,
        decision: str,
        outcome: AuditOutcome,
        output_sha256: str,
    ) -> None:
        context = grant.context
        self._audit.record(
            AuditRecord(
                event_id=self._event_id_factory(),
                scope=context.scope,
                kind=AuditKind.AUTHORIZATION,
                action=action,
                target_type="desktop.tool",
                target_id=f"{request.tool_name}:{request.tool_version}",
                task_id=context.task_id,
                policy_version=context.policy_version,
                decision=decision,
                outcome=outcome,
                input_sha256=request.request_sha256,
                output_sha256=output_sha256,
                request_id=context.request_id,
                occurred_at=self._clock(),
            )
        )


def _session_sha256(session_handle: str) -> str:
    if _SESSION_HANDLE_PATTERN.fullmatch(session_handle) is None:
        raise DesktopBridgeError(
            "DESKTOP_SESSION_REQUIRED",
            "The desktop session handle is missing or malformed.",
            next_action="Authenticate again through the application session workflow.",
        )
    return hashlib.sha256(session_handle.encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
