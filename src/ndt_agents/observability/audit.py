"""Immutable, scope-bound audit event service with deterministic hash-chain validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.observability.tracing import TraceService

_ZERO_SHA256 = "0" * 64


class AuditKind(StrEnum):
    AUTHORIZATION = "AUTHORIZATION"
    TASK = "TASK"
    AGENT = "AGENT"
    CHECKPOINT = "CHECKPOINT"
    BUDGET = "BUDGET"
    REVIEW = "REVIEW"
    CORRECTION = "CORRECTION"
    MODEL = "MODEL"
    TOOL = "TOOL"
    CACHE = "CACHE"
    ARTIFACT = "ARTIFACT"
    KNOWLEDGE = "KNOWLEDGE"
    APPROVAL = "APPROVAL"
    SECURITY = "SECURITY"


class AuditOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"
    FAILED = "FAILED"


class AuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuditRecord(AuditModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: UUID
    scope: TenantScope
    kind: AuditKind
    action: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    target_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    target_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
    task_id: UUID | None = None
    policy_version: str = Field(min_length=1, max_length=128)
    decision: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    outcome: AuditOutcome
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.occurred_at.utcoffset() != UTC.utcoffset(self.occurred_at):
            raise ValueError("occurred_at must use UTC")
        return self


class AuditEvent(AuditRecord):
    sequence: int = Field(ge=1)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    previous_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CompletenessResult(AuditModel):
    required: frozenset[AuditKind]
    present: frozenset[AuditKind]
    missing: frozenset[AuditKind]
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    ratio: float = Field(ge=0.0, le=1.0)


class AuditError(RuntimeError):
    """Stable audit failure with a required recovery action."""

    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class AuditRepository(Protocol):
    """Minimal persistence port used by the audit service."""

    def append(self, record: AuditRecord, *, trace_id: str, span_id: str) -> AuditEvent: ...

    def list(self, scope: TenantScope) -> tuple[AuditEvent, ...]: ...


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scope_key(scope: TenantScope) -> tuple[UUID, UUID]:
    return scope.tenant_id, scope.project_id


class InMemoryAuditRepository:
    """Thread-safe reference repository that exposes append and scoped read only."""

    def __init__(self) -> None:
        self._events: dict[tuple[UUID, UUID], list[AuditEvent]] = {}
        self._by_id: dict[UUID, tuple[str, AuditEvent]] = {}
        self._lock = RLock()

    def append(self, record: AuditRecord, *, trace_id: str, span_id: str) -> AuditEvent:
        request_payload = {
            "record": record.model_dump(mode="json"),
            "trace_id": trace_id,
            "span_id": span_id,
        }
        request_sha256 = _canonical_sha256(request_payload)
        with self._lock:
            existing = self._by_id.get(record.event_id)
            if existing is not None:
                if existing[0] == request_sha256:
                    return existing[1]
                raise AuditError(
                    code="AUDIT_IDEMPOTENCY_CONFLICT",
                    message="The audit event ID is already bound to different content.",
                    next_action="Use the original content or allocate a new event ID.",
                )
            key = _scope_key(record.scope)
            chain = self._events.setdefault(key, [])
            sequence = len(chain) + 1
            previous = chain[-1].event_sha256 if chain else _ZERO_SHA256
            event_payload = {
                **record.model_dump(mode="json"),
                "sequence": sequence,
                "trace_id": trace_id,
                "span_id": span_id,
                "previous_sha256": previous,
            }
            event = AuditEvent(
                **event_payload,
                event_sha256=_canonical_sha256(event_payload),
            )
            chain.append(event)
            self._by_id[event.event_id] = (request_sha256, event)
            return event

    def list(self, scope: TenantScope) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events.get(_scope_key(scope), ()))

    def get(self, scope: TenantScope, event_id: UUID) -> AuditEvent:
        with self._lock:
            existing = self._by_id.get(event_id)
            if existing is None:
                raise AuditError(
                    code="AUDIT_EVENT_INVALID",
                    message="The audit event does not exist.",
                    next_action="Verify the event ID and authorized scope.",
                )
            event = existing[1]
            if _scope_key(event.scope) != _scope_key(scope):
                raise AuditError(
                    code="AUDIT_SCOPE_MISMATCH",
                    message="The audit event is outside the authorized scope.",
                    next_action="Use the exact authorized tenant and project scope.",
                )
            return event

    def verify(self, scope: TenantScope) -> None:
        self.verify_events(self.list(scope))

    @staticmethod
    def verify_events(events: Iterable[AuditEvent]) -> None:
        previous = _ZERO_SHA256
        for expected_sequence, event in enumerate(events, start=1):
            payload = event.model_dump(mode="json", exclude={"event_sha256"})
            if (
                event.sequence != expected_sequence
                or event.previous_sha256 != previous
                or event.event_sha256 != _canonical_sha256(payload)
            ):
                raise AuditError(
                    code="AUDIT_CHAIN_INVALID",
                    message="The audit event sequence or hash chain is invalid.",
                    next_action="Stop trust propagation and reconcile against immutable evidence.",
                )
            previous = event.event_sha256


class AuditService:
    """Correlate strict audit records to the current trace and evaluate completeness."""

    def __init__(self, repository: AuditRepository, traces: TraceService) -> None:
        self._repository = repository
        self._traces = traces

    def record(self, record: AuditRecord) -> AuditEvent:
        link = self._traces.current_link()
        return self._repository.append(record, trace_id=link.trace_id, span_id=link.span_id)

    def completeness(
        self,
        *,
        scope: TenantScope,
        request_id: str,
        task_id: UUID,
        required: frozenset[AuditKind],
    ) -> CompletenessResult:
        if not required:
            raise AuditError(
                code="AUDIT_EVENT_INVALID",
                message="The required audit event set cannot be empty.",
                next_action="Declare the workflow event kinds before evaluation.",
            )
        present = frozenset(
            event.kind
            for event in self._repository.list(scope)
            if event.request_id == request_id and event.task_id == task_id
        )
        matched = present & required
        missing = required - matched
        return CompletenessResult(
            required=required,
            present=matched,
            missing=missing,
            numerator=len(matched),
            denominator=len(required),
            ratio=len(matched) / len(required),
        )
