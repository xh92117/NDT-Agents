"""Scope-bound, replay-safe human approval state machine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Any, Literal, Protocol, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import (
    ApprovalOutcome,
    ApprovalRecord,
    StrictModel,
    TenantScope,
)
from ndt_agents.observability.audit import AuditKind, AuditOutcome, AuditRecord, AuditService

APPROVAL_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
ZERO_SHA256 = "0" * 64
SYSTEM_ACTOR_ID = UUID(int=0)


class ApprovalKind(StrEnum):
    KNOWLEDGE = "KNOWLEDGE"
    PLAN = "PLAN"
    REPORT = "REPORT"
    CRITICAL_FINDING = "CRITICAL_FINDING"
    INSTRUMENT = "INSTRUMENT"
    DESTRUCTIVE = "DESTRUCTIVE"
    RELEASE = "RELEASE"


class ApprovalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ApprovalEventType(StrEnum):
    CANDIDATE = "CANDIDATE"
    DELEGATION = "DELEGATION"
    DECISION = "DECISION"
    RESUME = "RESUME"


class ApprovalRule(StrictModel):
    required_roles: frozenset[str] = Field(min_length=1)
    require_all_roles: bool = False
    delegation_allowed: bool = False
    validity_seconds: int = Field(ge=60, le=2_592_000)


class ApprovalPolicy(StrictModel):
    schema_version: Literal["1.0.0"] = APPROVAL_CONTRACT_VERSION
    policy_version: str = Field(min_length=1, max_length=128)
    rules: dict[ApprovalKind, ApprovalRule]

    @model_validator(mode="after")
    def complete(self) -> Self:
        if set(self.rules) != set(ApprovalKind):
            raise ValueError("approval policy must define every checkpoint kind")
        return self


def default_approval_policy() -> ApprovalPolicy:
    one = frozenset({"QUALIFIED_APPROVER"})
    return ApprovalPolicy(
        policy_version="approval-policy-1",
        rules={
            ApprovalKind.KNOWLEDGE: ApprovalRule(
                required_roles=frozenset({"QUALIFIED_APPROVER", "KNOWLEDGE_OWNER"}),
                delegation_allowed=True,
                validity_seconds=86_400,
            ),
            ApprovalKind.PLAN: ApprovalRule(
                required_roles=one, delegation_allowed=True, validity_seconds=86_400
            ),
            ApprovalKind.REPORT: ApprovalRule(required_roles=one, validity_seconds=86_400),
            ApprovalKind.CRITICAL_FINDING: ApprovalRule(
                required_roles=one, validity_seconds=21_600
            ),
            ApprovalKind.INSTRUMENT: ApprovalRule(
                required_roles=frozenset({"DEVICE_AUTHORIZED_APPROVER"}),
                validity_seconds=3_600,
            ),
            ApprovalKind.DESTRUCTIVE: ApprovalRule(
                required_roles=frozenset({"TENANT_ADMINISTRATOR"}),
                validity_seconds=3_600,
            ),
            ApprovalKind.RELEASE: ApprovalRule(
                required_roles=frozenset({"SECURITY_OWNER", "QUALITY_OWNER"}),
                require_all_roles=True,
                validity_seconds=86_400,
            ),
        },
    )


class ApprovalActor(StrictModel):
    schema_version: Literal["1.0.0"] = APPROVAL_CONTRACT_VERSION
    scope: TenantScope

    @property
    def actor_id(self) -> UUID:
        return self.scope.user_id

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(self.scope.role_codes)


class ApprovalCandidate(StrictModel):
    schema_version: Literal["1.0.0"] = APPROVAL_CONTRACT_VERSION
    approval_id: UUID
    scope: TenantScope
    task_id: UUID
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    kind: ApprovalKind
    action: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    target_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    target_id: UUID
    target_version: str = Field(min_length=1, max_length=128)
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preview: dict[str, Any]
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str = Field(min_length=1, max_length=128)
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def valid_candidate(self) -> Self:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != UTC.utcoffset(
            self.created_at
        ):
            raise ValueError("candidate creation time must use UTC")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() != UTC.utcoffset(
            self.expires_at
        ):
            raise ValueError("candidate expiry must use UTC")
        if self.expires_at <= self.created_at:
            raise ValueError("candidate expiry must follow creation")
        if self.preview_sha256 != canonical_sha256(self.preview):
            raise ValueError("candidate preview hash is invalid")
        return self


class ApprovalDelegation(StrictModel):
    schema_version: Literal["1.0.0"] = APPROVAL_CONTRACT_VERSION
    delegation_id: UUID
    approval_id: UUID
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    grantor_id: UUID
    delegate_id: UUID
    delegated_role: str = Field(min_length=1, max_length=128)
    created_at: datetime
    expires_at: datetime


class ApprovalDecision(StrictModel):
    schema_version: Literal["1.0.0"] = APPROVAL_CONTRACT_VERSION
    decision_id: UUID
    approval: ApprovalRecord
    actor_role: str = Field(min_length=1, max_length=128)


class ApprovalGrant(StrictModel):
    schema_version: Literal["1.0.0"] = APPROVAL_CONTRACT_VERSION
    resume_id: UUID
    approval_id: UUID
    scope: TenantScope
    task_id: UUID
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str = Field(min_length=1, max_length=128)
    decision_sha256s: tuple[str, ...] = Field(min_length=1)
    resumed_at: datetime


class ApprovalStatus(StrictModel):
    schema_version: Literal["1.0.0"] = APPROVAL_CONTRACT_VERSION
    candidate: ApprovalCandidate
    state: ApprovalState
    decisions: tuple[ApprovalDecision, ...]
    delegations: tuple[ApprovalDelegation, ...]
    grant: ApprovalGrant | None


class ApprovalEvent(StrictModel):
    schema_version: Literal["1.0.0"] = APPROVAL_CONTRACT_VERSION
    event_id: UUID
    approval_id: UUID
    scope: TenantScope
    sequence: int = Field(ge=1)
    event_type: ApprovalEventType
    payload: dict[str, Any]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class ApprovalError(RuntimeError):
    def __init__(self, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


def canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ApprovalError(
            "APPROVAL_PAYLOAD_INVALID",
            "The approval payload is not canonical JSON.",
            "Provide a JSON-compatible payload.",
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _project_key(scope: TenantScope) -> tuple[UUID, UUID]:
    return scope.tenant_id, scope.project_id


class ApprovalRepository(Protocol):
    def append(
        self,
        *,
        event_id: UUID,
        approval_id: UUID,
        scope: TenantScope,
        event_type: ApprovalEventType,
        payload: Mapping[str, Any],
        created_at: datetime,
    ) -> ApprovalEvent: ...

    def list(self, scope: TenantScope, approval_id: UUID) -> tuple[ApprovalEvent, ...]: ...

    def get(self, scope: TenantScope, event_id: UUID) -> ApprovalEvent | None: ...


class InMemoryApprovalRepository:
    """Append-only local journal with deterministic hash-chain verification."""

    def __init__(self) -> None:
        self._events: dict[tuple[UUID, UUID, UUID], list[ApprovalEvent]] = {}
        self._by_id: dict[UUID, ApprovalEvent] = {}
        self._lock = RLock()

    def append(
        self,
        *,
        event_id: UUID,
        approval_id: UUID,
        scope: TenantScope,
        event_type: ApprovalEventType,
        payload: Mapping[str, Any],
        created_at: datetime,
    ) -> ApprovalEvent:
        payload_dict = dict(payload)
        payload_sha256 = canonical_sha256(payload_dict)
        with self._lock:
            existing = self._by_id.get(event_id)
            if existing is not None:
                if (
                    existing.approval_id == approval_id
                    and _project_key(existing.scope) == _project_key(scope)
                    and existing.event_type is event_type
                    and existing.payload_sha256 == payload_sha256
                ):
                    return existing
                raise ApprovalError(
                    "APPROVAL_IDEMPOTENCY_CONFLICT",
                    "The event ID is already bound to different approval content.",
                    "Use the original exact content or a new event ID.",
                )
            key = (*_project_key(scope), approval_id)
            chain = self._events.setdefault(key, [])
            sequence = len(chain) + 1
            previous = chain[-1].event_sha256 if chain else ZERO_SHA256
            event_data = {
                "event_id": str(event_id),
                "approval_id": str(approval_id),
                "scope": scope.model_dump(mode="json"),
                "sequence": sequence,
                "event_type": event_type.value,
                "payload": payload_dict,
                "payload_sha256": payload_sha256,
                "previous_sha256": previous,
                "created_at": created_at.isoformat(),
            }
            event = ApprovalEvent(
                event_id=event_id,
                approval_id=approval_id,
                scope=scope,
                sequence=sequence,
                event_type=event_type,
                payload=payload_dict,
                payload_sha256=payload_sha256,
                previous_sha256=previous,
                event_sha256=canonical_sha256(event_data),
                created_at=created_at,
            )
            chain.append(event)
            self._by_id[event_id] = event
            return event

    def list(self, scope: TenantScope, approval_id: UUID) -> tuple[ApprovalEvent, ...]:
        chain = tuple(self._events.get((*_project_key(scope), approval_id), ()))
        self.verify(chain)
        return chain

    def get(self, scope: TenantScope, event_id: UUID) -> ApprovalEvent | None:
        event = self._by_id.get(event_id)
        if event is not None and _project_key(event.scope) != _project_key(scope):
            raise ApprovalError(
                "APPROVAL_SCOPE_MISMATCH",
                "The approval event is outside the authorized project.",
                "Use the exact authorized tenant and project.",
            )
        return event

    @staticmethod
    def verify(events: tuple[ApprovalEvent, ...]) -> None:
        previous = ZERO_SHA256
        for sequence, event in enumerate(events, start=1):
            event_data = {
                "event_id": str(event.event_id),
                "approval_id": str(event.approval_id),
                "scope": event.scope.model_dump(mode="json"),
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "payload": event.payload,
                "payload_sha256": event.payload_sha256,
                "previous_sha256": event.previous_sha256,
                "created_at": event.created_at.isoformat(),
            }
            if (
                event.sequence != sequence
                or event.previous_sha256 != previous
                or event.payload_sha256 != canonical_sha256(event.payload)
                or event.event_sha256 != canonical_sha256(event_data)
            ):
                raise ApprovalError(
                    "APPROVAL_CHAIN_INVALID",
                    "The approval event chain failed integrity verification.",
                    "Stop the workflow and reconcile immutable approval evidence.",
                )
            previous = event.event_sha256


class ApprovalService:
    """Create, decide, and resume approval checkpoints through one audited state machine."""

    def __init__(
        self,
        repository: ApprovalRepository,
        policy: ApprovalPolicy,
        audit: AuditService,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._audit_service = audit
        self._clock = clock

    def create(
        self,
        *,
        approval_id: UUID,
        scope: TenantScope,
        task_id: UUID,
        request_id: str,
        kind: ApprovalKind,
        action: str,
        target_type: str,
        target_id: UUID,
        target_version: str,
        candidate_sha256: str,
        preview: Mapping[str, Any],
    ) -> ApprovalStatus:
        now = self._clock()
        rule = self._policy.rules[kind]
        candidate = ApprovalCandidate(
            approval_id=approval_id,
            scope=scope,
            task_id=task_id,
            request_id=request_id,
            kind=kind,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_version=target_version,
            candidate_sha256=candidate_sha256,
            preview=dict(preview),
            preview_sha256=canonical_sha256(dict(preview)),
            policy_version=self._policy.policy_version,
            created_at=now,
            expires_at=now + timedelta(seconds=rule.validity_seconds),
        )
        existing = self._repository.list(scope, approval_id)
        if existing:
            stored = ApprovalCandidate.model_validate(existing[0].payload)
            if self._candidate_request(stored) == self._candidate_request(candidate):
                return self.status(scope, approval_id)
            self._deny(
                candidate,
                "APPROVAL_IDEMPOTENCY_CONFLICT",
                "The approval ID is bound to another candidate.",
            )
        self._audit(
            candidate,
            "approval.create",
            "PENDING",
            AuditOutcome.SUCCESS,
            candidate.candidate_sha256,
        )
        self._repository.append(
            event_id=approval_id,
            approval_id=approval_id,
            scope=scope,
            event_type=ApprovalEventType.CANDIDATE,
            payload=candidate.model_dump(mode="json"),
            created_at=now,
        )
        return self.status(scope, approval_id)

    def status(self, scope: TenantScope, approval_id: UUID) -> ApprovalStatus:
        events = self._repository.list(scope, approval_id)
        if not events or events[0].event_type is not ApprovalEventType.CANDIDATE:
            raise ApprovalError(
                "APPROVAL_NOT_FOUND",
                "The approval checkpoint does not exist in this project.",
                "Verify the approval ID and scope.",
            )
        candidate = ApprovalCandidate.model_validate(events[0].payload)
        if candidate.policy_version != self._policy.policy_version:
            raise ApprovalError(
                "APPROVAL_POLICY_INCOMPATIBLE",
                "The checkpoint policy version is not active in this runtime.",
                "Restore the recorded policy version or migrate the candidate through approval.",
            )
        decisions = tuple(
            ApprovalDecision.model_validate(event.payload)
            for event in events
            if event.event_type is ApprovalEventType.DECISION
        )
        delegations = tuple(
            ApprovalDelegation.model_validate(event.payload)
            for event in events
            if event.event_type is ApprovalEventType.DELEGATION
        )
        grants = tuple(
            ApprovalGrant.model_validate(event.payload)
            for event in events
            if event.event_type is ApprovalEventType.RESUME
        )
        state = self._state(candidate, decisions)
        return ApprovalStatus(
            candidate=candidate,
            state=state,
            decisions=decisions,
            delegations=delegations,
            grant=grants[-1] if grants else None,
        )

    def delegate(
        self,
        *,
        delegation_id: UUID,
        scope: TenantScope,
        approval_id: UUID,
        expected_candidate_sha256: str,
        grantor: ApprovalActor,
        delegate_id: UUID,
        delegated_role: str,
        expires_at: datetime,
    ) -> ApprovalDelegation:
        status = self.status(scope, approval_id)
        candidate = status.candidate
        existing = self._repository.get(scope, delegation_id)
        request = {
            "approval_id": str(approval_id),
            "candidate_sha256": expected_candidate_sha256,
            "grantor_id": str(grantor.actor_id),
            "delegate_id": str(delegate_id),
            "delegated_role": delegated_role,
            "expires_at": expires_at.isoformat(),
        }
        if existing is not None:
            stored = ApprovalDelegation.model_validate(existing.payload)
            if canonical_sha256(request) == canonical_sha256(self._delegation_request(stored)):
                return stored
            self._deny(
                candidate,
                "APPROVAL_IDEMPOTENCY_CONFLICT",
                "The delegation ID is bound to different content.",
            )
        self._require_pending_current(status, expected_candidate_sha256)
        self._require_actor_scope(candidate, grantor)
        rule = self._policy.rules[candidate.kind]
        if not rule.delegation_allowed or delegated_role not in rule.required_roles:
            self._deny(
                candidate,
                "APPROVAL_DELEGATION_DENIED",
                "Delegation is not allowed by this checkpoint policy.",
            )
        if delegated_role not in grantor.roles or grantor.actor_id == candidate.scope.user_id:
            self._deny(
                candidate,
                "APPROVAL_DELEGATION_DENIED",
                "The grantor lacks independent direct authority.",
            )
        now = self._clock()
        if expires_at.tzinfo is None or expires_at <= now or expires_at > candidate.expires_at:
            self._deny(
                candidate,
                "APPROVAL_DELEGATION_INVALID",
                "Delegation expiry is outside the candidate window.",
            )
        delegation = ApprovalDelegation(
            delegation_id=delegation_id,
            approval_id=approval_id,
            candidate_sha256=expected_candidate_sha256,
            grantor_id=grantor.actor_id,
            delegate_id=delegate_id,
            delegated_role=delegated_role,
            created_at=now,
            expires_at=expires_at,
        )
        self._audit(
            candidate,
            "approval.delegate",
            "DELEGATED",
            AuditOutcome.SUCCESS,
            canonical_sha256(request),
        )
        self._repository.append(
            event_id=delegation_id,
            approval_id=approval_id,
            scope=candidate.scope,
            event_type=ApprovalEventType.DELEGATION,
            payload=delegation.model_dump(mode="json"),
            created_at=now,
        )
        return delegation

    def decide(
        self,
        *,
        decision_id: UUID,
        scope: TenantScope,
        approval_id: UUID,
        expected_candidate_sha256: str,
        actor: ApprovalActor,
        outcome: Literal[
            ApprovalOutcome.APPROVED,
            ApprovalOutcome.REJECTED,
            ApprovalOutcome.CHANGES_REQUESTED,
        ],
        reason: str,
        actor_role: str | None = None,
    ) -> ApprovalDecision:
        status = self.status(scope, approval_id)
        candidate = status.candidate
        if outcome not in {
            ApprovalOutcome.APPROVED,
            ApprovalOutcome.REJECTED,
            ApprovalOutcome.CHANGES_REQUESTED,
        }:
            self._deny(
                candidate, "APPROVAL_OUTCOME_INVALID", "This outcome is not a human decision."
            )
        existing = self._repository.get(scope, decision_id)
        stored = ApprovalDecision.model_validate(existing.payload) if existing is not None else None
        chosen_role = actor_role or (
            stored.actor_role if stored is not None else self._choose_role(candidate, status, actor)
        )
        request = {
            "approval_id": str(approval_id),
            "candidate_sha256": expected_candidate_sha256,
            "actor_id": str(actor.actor_id),
            "actor_role": chosen_role,
            "outcome": outcome.value,
            "reason": reason,
        }
        if stored is not None:
            if canonical_sha256(request) == canonical_sha256(self._decision_request(stored)):
                return stored
            self._deny(
                candidate,
                "APPROVAL_IDEMPOTENCY_CONFLICT",
                "The decision ID is bound to different content.",
            )
        self._require_pending_current(status, expected_candidate_sha256)
        self._require_actor_scope(candidate, actor)
        if actor.actor_id == candidate.scope.user_id:
            self._deny(
                candidate,
                "APPROVAL_SELF_APPROVAL_DENIED",
                "A requester cannot approve their own candidate.",
            )
        if any(item.approval.actor_id == actor.actor_id for item in status.decisions):
            self._deny(
                candidate,
                "APPROVAL_DUPLICATE_ACTOR",
                "One actor cannot decide the same candidate twice.",
            )
        self._authorize_role(candidate, status, actor, chosen_role)
        now = self._clock()
        record = ApprovalRecord(
            approval_id=approval_id,
            scope=candidate.scope,
            action=candidate.action,
            target_type=candidate.target_type,
            target_id=candidate.target_id,
            target_version=candidate.target_version,
            target_sha256=candidate.candidate_sha256,
            policy_version=candidate.policy_version,
            actor_id=actor.actor_id,
            outcome=outcome,
            reason=reason,
            decided_at=now,
            expires_at=candidate.expires_at,
        )
        decision = ApprovalDecision(
            decision_id=decision_id, approval=record, actor_role=chosen_role
        )
        self._audit(
            candidate,
            "approval.decide",
            outcome.value,
            AuditOutcome.SUCCESS,
            canonical_sha256(request),
        )
        self._repository.append(
            event_id=decision_id,
            approval_id=approval_id,
            scope=candidate.scope,
            event_type=ApprovalEventType.DECISION,
            payload=decision.model_dump(mode="json"),
            created_at=now,
        )
        return decision

    def expire(
        self,
        *,
        decision_id: UUID,
        scope: TenantScope,
        approval_id: UUID,
        expected_candidate_sha256: str,
        reason: str = "The approval validity window elapsed.",
    ) -> ApprovalDecision:
        status = self.status(scope, approval_id)
        candidate = status.candidate
        if self._clock() < candidate.expires_at:
            self._deny(
                candidate, "APPROVAL_NOT_EXPIRED", "The approval validity window is still open."
            )
        return self._terminal_system_decision(
            decision_id, status, expected_candidate_sha256, ApprovalOutcome.EXPIRED, reason
        )

    def cancel(
        self,
        *,
        decision_id: UUID,
        scope: TenantScope,
        approval_id: UUID,
        expected_candidate_sha256: str,
        actor: ApprovalActor,
        reason: str,
    ) -> ApprovalDecision:
        status = self.status(scope, approval_id)
        candidate = status.candidate
        self._require_actor_scope(candidate, actor)
        if actor.actor_id != candidate.scope.user_id and "PROJECT_ADMINISTRATOR" not in actor.roles:
            self._deny(
                candidate,
                "APPROVAL_CANCEL_DENIED",
                "Only the requester or project administrator may cancel.",
            )
        return self._terminal_system_decision(
            decision_id,
            status,
            expected_candidate_sha256,
            ApprovalOutcome.CANCELLED,
            reason,
            actor_id=actor.actor_id,
            actor_role="REQUESTER"
            if actor.actor_id == candidate.scope.user_id
            else "PROJECT_ADMINISTRATOR",
        )

    def resume(
        self,
        *,
        resume_id: UUID,
        scope: TenantScope,
        approval_id: UUID,
        expected_candidate_sha256: str,
    ) -> ApprovalGrant:
        status = self.status(scope, approval_id)
        candidate = status.candidate
        existing = self._repository.get(scope, resume_id)
        request = {
            "approval_id": str(approval_id),
            "candidate_sha256": expected_candidate_sha256,
        }
        if existing is not None:
            stored = ApprovalGrant.model_validate(existing.payload)
            if canonical_sha256(request) == canonical_sha256(
                {
                    "approval_id": str(stored.approval_id),
                    "candidate_sha256": stored.candidate_sha256,
                }
            ):
                return stored
            self._deny(
                candidate,
                "APPROVAL_IDEMPOTENCY_CONFLICT",
                "The resume ID is bound to different content.",
            )
        if status.grant is not None:
            self._deny(
                candidate, "APPROVAL_REPLAYED", "The approved candidate already has a resume grant."
            )
        if status.state is not ApprovalState.APPROVED:
            self._deny(
                candidate, "APPROVAL_NOT_APPROVED", "The checkpoint has not reached full approval."
            )
        if expected_candidate_sha256 != candidate.candidate_sha256:
            self._deny(
                candidate, "APPROVAL_CANDIDATE_STALE", "The candidate hash changed before resume."
            )
        decision_hashes = tuple(
            canonical_sha256(decision.model_dump(mode="json")) for decision in status.decisions
        )
        grant = ApprovalGrant(
            resume_id=resume_id,
            approval_id=approval_id,
            scope=candidate.scope,
            task_id=candidate.task_id,
            candidate_sha256=candidate.candidate_sha256,
            policy_version=candidate.policy_version,
            decision_sha256s=decision_hashes,
            resumed_at=self._clock(),
        )
        self._audit(
            candidate, "approval.resume", "RESUMED", AuditOutcome.SUCCESS, canonical_sha256(request)
        )
        self._repository.append(
            event_id=resume_id,
            approval_id=approval_id,
            scope=candidate.scope,
            event_type=ApprovalEventType.RESUME,
            payload=grant.model_dump(mode="json"),
            created_at=grant.resumed_at,
        )
        return grant

    def _terminal_system_decision(
        self,
        decision_id: UUID,
        status: ApprovalStatus,
        expected_hash: str,
        outcome: Literal[ApprovalOutcome.EXPIRED, ApprovalOutcome.CANCELLED],
        reason: str,
        *,
        actor_id: UUID = SYSTEM_ACTOR_ID,
        actor_role: str = "SYSTEM",
    ) -> ApprovalDecision:
        candidate = status.candidate
        request = {
            "approval_id": str(candidate.approval_id),
            "candidate_sha256": expected_hash,
            "actor_id": str(actor_id),
            "actor_role": actor_role,
            "outcome": outcome.value,
            "reason": reason,
        }
        existing = self._repository.get(candidate.scope, decision_id)
        if existing is not None:
            stored = ApprovalDecision.model_validate(existing.payload)
            if canonical_sha256(request) == canonical_sha256(self._decision_request(stored)):
                return stored
            self._deny(
                candidate,
                "APPROVAL_IDEMPOTENCY_CONFLICT",
                "The decision ID is bound to different content.",
            )
        self._require_pending_current(status, expected_hash, check_expiry=False)
        now = self._clock()
        record = ApprovalRecord(
            approval_id=candidate.approval_id,
            scope=candidate.scope,
            action=candidate.action,
            target_type=candidate.target_type,
            target_id=candidate.target_id,
            target_version=candidate.target_version,
            target_sha256=candidate.candidate_sha256,
            policy_version=candidate.policy_version,
            actor_id=actor_id,
            outcome=outcome,
            reason=reason,
            decided_at=now,
            expires_at=candidate.expires_at,
        )
        decision = ApprovalDecision(decision_id=decision_id, approval=record, actor_role=actor_role)
        self._audit(
            candidate,
            "approval.decide",
            outcome.value,
            AuditOutcome.SUCCESS,
            canonical_sha256(request),
        )
        self._repository.append(
            event_id=decision_id,
            approval_id=candidate.approval_id,
            scope=candidate.scope,
            event_type=ApprovalEventType.DECISION,
            payload=decision.model_dump(mode="json"),
            created_at=now,
        )
        return decision

    def _state(
        self, candidate: ApprovalCandidate, decisions: tuple[ApprovalDecision, ...]
    ) -> ApprovalState:
        for decision in decisions:
            terminal = {
                ApprovalOutcome.REJECTED: ApprovalState.REJECTED,
                ApprovalOutcome.CHANGES_REQUESTED: ApprovalState.CHANGES_REQUESTED,
                ApprovalOutcome.EXPIRED: ApprovalState.EXPIRED,
                ApprovalOutcome.CANCELLED: ApprovalState.CANCELLED,
            }.get(decision.approval.outcome)
            if terminal is not None:
                return terminal
        approved_roles = {
            item.actor_role
            for item in decisions
            if item.approval.outcome is ApprovalOutcome.APPROVED
        }
        rule = self._policy.rules[candidate.kind]
        complete = (
            rule.required_roles <= approved_roles
            if rule.require_all_roles
            else bool(rule.required_roles & approved_roles)
        )
        return ApprovalState.APPROVED if complete else ApprovalState.PENDING

    def _choose_role(
        self, candidate: ApprovalCandidate, status: ApprovalStatus, actor: ApprovalActor
    ) -> str:
        rule = self._policy.rules[candidate.kind]
        used = {item.actor_role for item in status.decisions}
        direct = sorted((actor.roles & rule.required_roles) - used)
        if direct:
            return direct[0]
        delegated = sorted(
            item.delegated_role
            for item in status.delegations
            if item.delegate_id == actor.actor_id
            and item.candidate_sha256 == candidate.candidate_sha256
            and item.expires_at > self._clock()
            and item.delegated_role not in used
        )
        return delegated[0] if delegated else "UNAUTHORIZED"

    def _authorize_role(
        self,
        candidate: ApprovalCandidate,
        status: ApprovalStatus,
        actor: ApprovalActor,
        role: str,
    ) -> None:
        rule = self._policy.rules[candidate.kind]
        if role not in rule.required_roles:
            self._deny(
                candidate, "APPROVAL_ROLE_DENIED", "The actor lacks an eligible approval role."
            )
        if role in actor.roles:
            return
        valid = any(
            item.delegate_id == actor.actor_id
            and item.delegated_role == role
            and item.candidate_sha256 == candidate.candidate_sha256
            and item.expires_at > self._clock()
            for item in status.delegations
        )
        if not valid:
            self._deny(
                candidate, "APPROVAL_ROLE_DENIED", "No active scoped delegation grants this role."
            )

    def _require_pending_current(
        self, status: ApprovalStatus, expected_hash: str, *, check_expiry: bool = True
    ) -> None:
        candidate = status.candidate
        if expected_hash != candidate.candidate_sha256:
            self._deny(
                candidate,
                "APPROVAL_CANDIDATE_STALE",
                "The candidate hash does not match the checkpoint.",
            )
        if status.state is not ApprovalState.PENDING:
            self._deny(
                candidate, "APPROVAL_TERMINAL", "The approval checkpoint is already terminal."
            )
        if check_expiry and self._clock() >= candidate.expires_at:
            self._deny(candidate, "APPROVAL_EXPIRED", "The approval validity window elapsed.")

    def _require_actor_scope(self, candidate: ApprovalCandidate, actor: ApprovalActor) -> None:
        if (
            _project_key(actor.scope) != _project_key(candidate.scope)
            or actor.scope.permission_version != candidate.scope.permission_version
        ):
            self._deny(
                candidate,
                "APPROVAL_SCOPE_MISMATCH",
                "The actor scope or permission version differs.",
            )

    def _audit(
        self,
        candidate: ApprovalCandidate,
        action: str,
        decision: str,
        outcome: AuditOutcome,
        input_sha256: str,
    ) -> None:
        self._audit_service.record(
            AuditRecord(
                event_id=uuid4(),
                scope=candidate.scope,
                kind=AuditKind.APPROVAL,
                action=action,
                target_type="approval",
                target_id=str(candidate.approval_id),
                task_id=candidate.task_id,
                policy_version=candidate.policy_version,
                decision=decision,
                outcome=outcome,
                input_sha256=input_sha256,
                output_sha256=canonical_sha256({"decision": decision}),
                request_id=candidate.request_id,
                occurred_at=self._clock(),
            )
        )

    def _deny(self, candidate: ApprovalCandidate, code: str, message: str) -> None:
        self._audit(
            candidate, "approval.deny", code, AuditOutcome.DENIED, candidate.candidate_sha256
        )
        raise ApprovalError(
            code, message, "Correct the scope, authority, candidate, or checkpoint state."
        )

    @staticmethod
    def _candidate_request(candidate: ApprovalCandidate) -> dict[str, Any]:
        return candidate.model_dump(
            mode="json", exclude={"created_at", "expires_at", "preview_sha256"}
        )

    @staticmethod
    def _decision_request(decision: ApprovalDecision) -> dict[str, Any]:
        approval = decision.approval
        return {
            "approval_id": str(approval.approval_id),
            "candidate_sha256": approval.target_sha256,
            "actor_id": str(approval.actor_id),
            "actor_role": decision.actor_role,
            "outcome": approval.outcome.value,
            "reason": approval.reason,
        }

    @staticmethod
    def _delegation_request(delegation: ApprovalDelegation) -> dict[str, Any]:
        return {
            "approval_id": str(delegation.approval_id),
            "candidate_sha256": delegation.candidate_sha256,
            "grantor_id": str(delegation.grantor_id),
            "delegate_id": str(delegation.delegate_id),
            "delegated_role": delegation.delegated_role,
            "expires_at": delegation.expires_at.isoformat(),
        }
