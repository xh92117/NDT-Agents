"""S1-13 generic human approval checkpoint integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from ndt_agents.approval import (
    ApprovalActor,
    ApprovalDecision,
    ApprovalError,
    ApprovalKind,
    ApprovalService,
    ApprovalState,
    ApprovalStatus,
    InMemoryApprovalRepository,
    default_approval_policy,
)
from ndt_agents.contracts.v1 import ApprovalOutcome, TenantScope
from ndt_agents.observability import (
    AuditKind,
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000101")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000102")
REQUESTER_ID = UUID("00000000-0000-4000-8000-000000000103")
APPROVER_ID = UUID("00000000-0000-4000-8000-000000000104")
SECOND_APPROVER_ID = UUID("00000000-0000-4000-8000-000000000105")
TASK_ID = UUID("00000000-0000-4000-8000-000000000201")
TARGET_ID = UUID("00000000-0000-4000-8000-000000000202")
CANDIDATE_HASH = "a" * 64


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 24, 6, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def scope(user_id: UUID, *roles: str, project_id: UUID = PROJECT_ID) -> TenantScope:
    return TenantScope(
        tenant_id=TENANT_ID,
        project_id=project_id,
        user_id=user_id,
        role_codes=roles or ("NDT_ENGINEER",),
        permission_version="permissions-1",
    )


class Runtime:
    def __init__(self, repository: InMemoryApprovalRepository | None = None) -> None:
        self.clock = Clock()
        self.repository = repository or InMemoryApprovalRepository()
        self.audit_repository = InMemoryAuditRepository()
        self.traces = TraceService(
            service_name="approval-test",
            service_version="1.0.0",
            exporter=InMemorySpanExporter(),
        )
        self.service = ApprovalService(
            self.repository,
            default_approval_policy(),
            AuditService(self.audit_repository, self.traces),
            clock=self.clock,
        )

    def create(
        self, kind: ApprovalKind = ApprovalKind.REPORT, approval_id: UUID | None = None
    ) -> ApprovalStatus:
        with self.traces.start_span("approval.create"):
            return self.service.create(
                approval_id=approval_id or uuid4(),
                scope=scope(REQUESTER_ID),
                task_id=TASK_ID,
                request_id="approval-request-1",
                kind=kind,
                action="artifact.release",
                target_type="artifact",
                target_id=TARGET_ID,
                target_version="candidate-1",
                candidate_sha256=CANDIDATE_HASH,
                preview={"summary": "bounded preview", "hash": CANDIDATE_HASH},
            )

    def actor(
        self, user_id: UUID = APPROVER_ID, *roles: str, project_id: UUID = PROJECT_ID
    ) -> ApprovalActor:
        return ApprovalActor(scope=scope(user_id, *roles, project_id=project_id))

    def decide(self, approval_id: UUID, actor: ApprovalActor, **updates: Any) -> ApprovalDecision:
        values: dict[str, Any] = {
            "decision_id": uuid4(),
            "scope": scope(REQUESTER_ID),
            "approval_id": approval_id,
            "expected_candidate_sha256": CANDIDATE_HASH,
            "actor": actor,
            "outcome": ApprovalOutcome.APPROVED,
            "reason": "Evidence and scope verified.",
        }
        values.update(updates)
        with self.traces.start_span("approval.decide"):
            return self.service.decide(**values)

    def close(self) -> None:
        self.traces.shutdown()


@pytest.mark.parametrize("kind", list(ApprovalKind))
def test_every_checkpoint_kind_starts_paused(kind: ApprovalKind) -> None:
    runtime = Runtime()
    try:
        status = runtime.create(kind)
        assert status.state is ApprovalState.PENDING
        assert status.candidate.preview_sha256
        with runtime.traces.start_span("approval.resume"):
            with pytest.raises(ApprovalError) as captured:
                runtime.service.resume(
                    resume_id=uuid4(),
                    scope=status.candidate.scope,
                    approval_id=status.candidate.approval_id,
                    expected_candidate_sha256=CANDIDATE_HASH,
                )
        assert captured.value.code == "APPROVAL_NOT_APPROVED"
    finally:
        runtime.close()


def test_authorized_approval_and_resume_are_exactly_idempotent() -> None:
    runtime = Runtime()
    try:
        status = runtime.create()
        decision_id = uuid4()
        decision = runtime.decide(
            status.candidate.approval_id,
            runtime.actor(APPROVER_ID, "QUALIFIED_APPROVER"),
            decision_id=decision_id,
        )
        replay = runtime.decide(
            status.candidate.approval_id,
            runtime.actor(APPROVER_ID, "QUALIFIED_APPROVER"),
            decision_id=decision_id,
        )
        assert replay == decision
        assert (
            runtime.service.status(status.candidate.scope, status.candidate.approval_id).state
            is ApprovalState.APPROVED
        )
        resume_id = uuid4()
        with runtime.traces.start_span("approval.resume"):
            grant = runtime.service.resume(
                resume_id=resume_id,
                scope=status.candidate.scope,
                approval_id=status.candidate.approval_id,
                expected_candidate_sha256=CANDIDATE_HASH,
            )
            replayed_grant = runtime.service.resume(
                resume_id=resume_id,
                scope=status.candidate.scope,
                approval_id=status.candidate.approval_id,
                expected_candidate_sha256=CANDIDATE_HASH,
            )
        assert replayed_grant == grant
        assert len(grant.decision_sha256s) == 1
    finally:
        runtime.close()


def test_self_cross_scope_stale_and_unauthorized_decisions_are_denied() -> None:
    runtime = Runtime()
    status = runtime.create()
    approval_id = status.candidate.approval_id
    cases = [
        (runtime.actor(REQUESTER_ID, "QUALIFIED_APPROVER"), {}, "APPROVAL_SELF_APPROVAL_DENIED"),
        (
            runtime.actor(APPROVER_ID, "QUALIFIED_APPROVER", project_id=uuid4()),
            {},
            "APPROVAL_SCOPE_MISMATCH",
        ),
        (runtime.actor(APPROVER_ID, "READ_ONLY_USER"), {}, "APPROVAL_ROLE_DENIED"),
        (
            runtime.actor(APPROVER_ID, "QUALIFIED_APPROVER"),
            {"expected_candidate_sha256": "b" * 64},
            "APPROVAL_CANDIDATE_STALE",
        ),
    ]
    try:
        for actor, updates, code in cases:
            with pytest.raises(ApprovalError) as captured:
                runtime.decide(approval_id, actor, **updates)
            assert captured.value.code == code
        assert (
            runtime.service.status(status.candidate.scope, approval_id).state
            is ApprovalState.PENDING
        )
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("outcome", "state"),
    [
        (ApprovalOutcome.REJECTED, ApprovalState.REJECTED),
        (ApprovalOutcome.CHANGES_REQUESTED, ApprovalState.CHANGES_REQUESTED),
    ],
)
def test_reject_and_request_change_are_terminal(outcome: Any, state: ApprovalState) -> None:
    runtime = Runtime()
    try:
        status = runtime.create()
        runtime.decide(
            status.candidate.approval_id,
            runtime.actor(APPROVER_ID, "QUALIFIED_APPROVER"),
            outcome=outcome,
        )
        assert (
            runtime.service.status(status.candidate.scope, status.candidate.approval_id).state
            is state
        )
        with pytest.raises(ApprovalError) as captured:
            runtime.decide(
                status.candidate.approval_id,
                runtime.actor(SECOND_APPROVER_ID, "QUALIFIED_APPROVER"),
            )
        assert captured.value.code == "APPROVAL_TERMINAL"
    finally:
        runtime.close()


def test_expiry_and_requester_cancellation_append_terminal_decisions() -> None:
    expired = Runtime()
    cancelled = Runtime()
    try:
        expiring = expired.create(ApprovalKind.INSTRUMENT)
        expired.clock.advance(3_601)
        with expired.traces.start_span("approval.expire"):
            expired.service.expire(
                decision_id=uuid4(),
                scope=expiring.candidate.scope,
                approval_id=expiring.candidate.approval_id,
                expected_candidate_sha256=CANDIDATE_HASH,
            )
        assert (
            expired.service.status(expiring.candidate.scope, expiring.candidate.approval_id).state
            is ApprovalState.EXPIRED
        )

        pending = cancelled.create()
        with cancelled.traces.start_span("approval.cancel"):
            cancelled.service.cancel(
                decision_id=uuid4(),
                scope=pending.candidate.scope,
                approval_id=pending.candidate.approval_id,
                expected_candidate_sha256=CANDIDATE_HASH,
                actor=cancelled.actor(REQUESTER_ID, "NDT_ENGINEER"),
                reason="Requester withdrew the candidate.",
            )
        assert (
            cancelled.service.status(pending.candidate.scope, pending.candidate.approval_id).state
            is ApprovalState.CANCELLED
        )
    finally:
        expired.close()
        cancelled.close()


def test_bounded_delegation_allows_one_independent_delegate() -> None:
    runtime = Runtime()
    try:
        status = runtime.create(ApprovalKind.PLAN)
        delegate_id = SECOND_APPROVER_ID
        with runtime.traces.start_span("approval.delegate"):
            runtime.service.delegate(
                delegation_id=uuid4(),
                scope=status.candidate.scope,
                approval_id=status.candidate.approval_id,
                expected_candidate_sha256=CANDIDATE_HASH,
                grantor=runtime.actor(APPROVER_ID, "QUALIFIED_APPROVER"),
                delegate_id=delegate_id,
                delegated_role="QUALIFIED_APPROVER",
                expires_at=runtime.clock.now + timedelta(hours=1),
            )
        runtime.decide(status.candidate.approval_id, runtime.actor(delegate_id, "NDT_ENGINEER"))
        assert (
            runtime.service.status(status.candidate.scope, status.candidate.approval_id).state
            is ApprovalState.APPROVED
        )

        report = runtime.create(ApprovalKind.REPORT)
        with runtime.traces.start_span("approval.delegate.denied"):
            with pytest.raises(ApprovalError) as captured:
                runtime.service.delegate(
                    delegation_id=uuid4(),
                    scope=report.candidate.scope,
                    approval_id=report.candidate.approval_id,
                    expected_candidate_sha256=CANDIDATE_HASH,
                    grantor=runtime.actor(APPROVER_ID, "QUALIFIED_APPROVER"),
                    delegate_id=delegate_id,
                    delegated_role="QUALIFIED_APPROVER",
                    expires_at=runtime.clock.now + timedelta(hours=1),
                )
        assert captured.value.code == "APPROVAL_DELEGATION_DENIED"
    finally:
        runtime.close()


def test_release_requires_distinct_security_and_quality_owners() -> None:
    runtime = Runtime()
    try:
        status = runtime.create(ApprovalKind.RELEASE)
        runtime.decide(
            status.candidate.approval_id,
            runtime.actor(APPROVER_ID, "SECURITY_OWNER"),
            actor_role="SECURITY_OWNER",
        )
        assert (
            runtime.service.status(status.candidate.scope, status.candidate.approval_id).state
            is ApprovalState.PENDING
        )
        runtime.decide(
            status.candidate.approval_id,
            runtime.actor(SECOND_APPROVER_ID, "QUALITY_OWNER"),
            actor_role="QUALITY_OWNER",
        )
        assert (
            runtime.service.status(status.candidate.scope, status.candidate.approval_id).state
            is ApprovalState.APPROVED
        )
    finally:
        runtime.close()


def test_conflicting_decision_and_second_resume_are_rejected() -> None:
    runtime = Runtime()
    try:
        status = runtime.create()
        decision_id = uuid4()
        actor = runtime.actor(APPROVER_ID, "QUALIFIED_APPROVER")
        runtime.decide(status.candidate.approval_id, actor, decision_id=decision_id)
        with pytest.raises(ApprovalError) as conflict:
            runtime.decide(
                status.candidate.approval_id,
                actor,
                decision_id=decision_id,
                reason="Different content.",
            )
        assert conflict.value.code == "APPROVAL_IDEMPOTENCY_CONFLICT"
        with runtime.traces.start_span("approval.resume"):
            runtime.service.resume(
                resume_id=uuid4(),
                scope=status.candidate.scope,
                approval_id=status.candidate.approval_id,
                expected_candidate_sha256=CANDIDATE_HASH,
            )
            with pytest.raises(ApprovalError) as replay:
                runtime.service.resume(
                    resume_id=uuid4(),
                    scope=status.candidate.scope,
                    approval_id=status.candidate.approval_id,
                    expected_candidate_sha256=CANDIDATE_HASH,
                )
        assert replay.value.code == "APPROVAL_REPLAYED"
    finally:
        runtime.close()


def test_restart_recovery_verifies_chain_and_preserves_approval() -> None:
    first = Runtime()
    try:
        status = first.create()
        first.decide(
            status.candidate.approval_id,
            first.actor(APPROVER_ID, "QUALIFIED_APPROVER"),
        )
        recovered = Runtime(first.repository)
        recovered.clock.now = first.clock.now
        try:
            restored = recovered.service.status(
                status.candidate.scope, status.candidate.approval_id
            )
            assert restored.state is ApprovalState.APPROVED
            events = first.repository.list(status.candidate.scope, status.candidate.approval_id)
            assert [event.sequence for event in events] == [1, 2]
            assert events[1].previous_sha256 == events[0].event_sha256
        finally:
            recovered.close()
    finally:
        first.close()


def test_tampered_event_chain_is_rejected() -> None:
    runtime = Runtime()
    try:
        status = runtime.create()
        events = runtime.repository.list(status.candidate.scope, status.candidate.approval_id)
        tampered = events[0].model_copy(update={"payload_sha256": "0" * 64})
        with pytest.raises(ApprovalError) as captured:
            InMemoryApprovalRepository.verify((tampered,))
        assert captured.value.code == "APPROVAL_CHAIN_INVALID"
    finally:
        runtime.close()


def test_candidate_creation_is_idempotent_and_conflict_safe() -> None:
    runtime = Runtime()
    approval_id = uuid4()
    try:
        first = runtime.create(approval_id=approval_id)
        replay = runtime.create(approval_id=approval_id)
        assert replay == first
        with runtime.traces.start_span("approval.create.conflict"):
            with pytest.raises(ApprovalError) as captured:
                runtime.service.create(
                    approval_id=approval_id,
                    scope=scope(REQUESTER_ID),
                    task_id=TASK_ID,
                    request_id="approval-request-1",
                    kind=ApprovalKind.REPORT,
                    action="artifact.release",
                    target_type="artifact",
                    target_id=TARGET_ID,
                    target_version="candidate-2",
                    candidate_sha256="b" * 64,
                    preview={"summary": "changed"},
                )
        assert captured.value.code == "APPROVAL_IDEMPOTENCY_CONFLICT"
    finally:
        runtime.close()


def test_allows_and_denials_are_hash_only_correlated_approval_audits() -> None:
    runtime = Runtime()
    try:
        status = runtime.create()
        with pytest.raises(ApprovalError):
            runtime.decide(
                status.candidate.approval_id,
                runtime.actor(REQUESTER_ID, "QUALIFIED_APPROVER"),
            )
        runtime.decide(
            status.candidate.approval_id,
            runtime.actor(APPROVER_ID, "QUALIFIED_APPROVER"),
        )
        events = runtime.audit_repository.list(status.candidate.scope)
        assert {event.kind for event in events} == {AuditKind.APPROVAL}
        assert {event.outcome.value for event in events} == {"SUCCESS", "DENIED"}
        assert all(event.trace_id != "0" * 32 and event.span_id != "0" * 16 for event in events)
        assert all(
            "bounded preview" not in json_text for json_text in (str(event) for event in events)
        )
    finally:
        runtime.close()
