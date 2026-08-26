"""S6-10 publication authorization, idempotency, and smoke tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from ndt_agents.operations.publication import (
    PostPublicationCheck,
    PostPublicationCheckResult,
    PostPublicationSmoke,
    PublicationError,
    PublicationRecord,
    PublicationRequest,
    PublicationService,
    PublicationState,
    PublisherResult,
    StaticPublicationAuthority,
    Tg06Evidence,
    artifact_set_sha256,
    build_release_decision,
    finalize_post_publication,
)
from ndt_agents.operations.release import SigningEnvironment
from tests.operations.test_release_candidate import sealed, trusted_registry


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class PublisherSpy:
    def __init__(self, *, mismatch: bool = False) -> None:
        self.calls = 0
        self.mismatch = mismatch

    def __call__(self, request: PublicationRequest) -> PublisherResult:
        self.calls += 1
        return PublisherResult(
            deployed_candidate_sha256=(
                "f" * 64 if self.mismatch else request.candidate.manifest.candidate_sha256
            ),
            deployment_id="deployment-v1",
            deployment_uri="deployment://commercial/v1",
            immutable=True,
            published_at=datetime(2026, 8, 25, 2, tzinfo=UTC),
        )


def request(**decision_updates: object) -> PublicationRequest:
    candidate = sealed()
    tg06 = Tg06Evidence(
        candidate_sha256=candidate.manifest.candidate_sha256,
        passed=True,
        evidence_sha256=sha("tg06"),
        evidence_uri="artifact://release/tg06",
    )
    values: dict[str, object] = {
        "candidate_sha256": candidate.manifest.candidate_sha256,
        "artifact_set_sha256": artifact_set_sha256(candidate),
        "tg06_evidence_sha256": tg06.evidence_sha256,
        "approver_id": "release-authority-1",
        "approver_role": "RELEASE_AUTHORITY",
        "permission_version": "release-permissions-v1",
        "target": "commercial-production",
        "approved": True,
        "residual_risk_accepted": True,
        "decided_at": datetime(2026, 8, 25, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 26, tzinfo=UTC),
    }
    values.update(decision_updates)
    return PublicationRequest(
        candidate=candidate,
        tg06=tg06,
        decision=build_release_decision(**values),
        target="commercial-production",
        idempotency_key="publication-request-0001",
    )


def authority_for(
    publication_request: PublicationRequest,
    *,
    revoked: bool = False,
) -> StaticPublicationAuthority:
    return StaticPublicationAuthority(
        tg06_records=(publication_request.tg06,),
        decisions=(publication_request.decision,),
        revoked_decision_sha256s=(
            frozenset({publication_request.decision.decision_sha256}) if revoked else frozenset()
        ),
    )


def post_smoke(record: PublicationRecord, **updates: object) -> PostPublicationSmoke:
    values: dict[str, object] = {
        "publication_sha256": record.publication_sha256,
        "candidate_sha256": record.candidate_sha256,
        "deployment_id": record.deployment_id,
        "live_execution": True,
        "completed_at": record.published_at + timedelta(minutes=5),
        "checks": tuple(
            PostPublicationCheckResult(
                check=check,
                passed=True,
                evidence_sha256=sha(check.value),
            )
            for check in PostPublicationCheck
        ),
        "p0_findings": 0,
        "p1_findings": 0,
        "tenant_leaks": 0,
        "duplicate_committed_side_effects": 0,
        "correctness_failures": 0,
        "isolation_failures": 0,
        "evidence_uri": "artifact://release/post-publication-smoke",
    }
    values.update(updates)
    return PostPublicationSmoke.model_validate(values)


def test_exact_authorized_publication_is_one_call_and_idempotent() -> None:
    publisher = PublisherSpy()
    publication_request = request()
    service = PublicationService(
        publisher,
        trusted_registry(publication_request.candidate),
        authority_for(publication_request),
    )
    record = service.publish(publication_request, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    replay = service.publish(publication_request, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    assert record == replay
    assert record.state is PublicationState.PUBLISHED_PENDING_SMOKE
    assert publisher.calls == 1
    completed = finalize_post_publication(record, post_smoke(record))
    assert completed.state is PublicationState.COMPLETE


def test_blocked_candidate_stale_or_rejected_decision_makes_zero_calls() -> None:
    publisher = PublisherSpy()
    blocked = request()
    blocked_candidate = sealed(
        signing_environment=SigningEnvironment.TEST,
        key_approved=False,
    )
    blocked = blocked.model_copy(update={"candidate": blocked_candidate})
    service = PublicationService(
        publisher,
        trusted_registry(blocked_candidate),
        authority_for(blocked),
    )
    with pytest.raises(PublicationError) as candidate_error:
        service.publish(blocked, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    assert candidate_error.value.code == "PUBLICATION_PREREQUISITE_MISSING"

    stale = request(expires_at=datetime(2026, 8, 25, 0, 30, tzinfo=UTC))
    with pytest.raises(PublicationError):
        service.publish(stale, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    rejected = request(approved=False)
    with pytest.raises(PublicationError):
        service.publish(rejected, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    assert publisher.calls == 0


def test_changed_idempotency_input_conflicts_without_second_call() -> None:
    publisher = PublisherSpy()
    first = request()
    service = PublicationService(
        publisher,
        trusted_registry(first.candidate),
        authority_for(first),
    )
    service.publish(first, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    changed = request(approver_id="release-authority-2")
    with pytest.raises(PublicationError) as conflict:
        service.publish(changed, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    assert conflict.value.code == "PUBLICATION_IDEMPOTENCY_CONFLICT"
    assert publisher.calls == 1


def test_publisher_mismatch_is_not_recorded() -> None:
    publisher = PublisherSpy(mismatch=True)
    publication_request = request()
    service = PublicationService(
        publisher,
        trusted_registry(publication_request.candidate),
        authority_for(publication_request),
    )
    with pytest.raises(PublicationError) as mismatch:
        service.publish(publication_request, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    assert mismatch.value.code == "PUBLICATION_DEPLOYMENT_MISMATCH"
    assert publisher.calls == 1


def test_unsafe_late_or_mismatched_smoke_requires_rollback() -> None:
    publication_request = request()
    service = PublicationService(
        PublisherSpy(),
        trusted_registry(publication_request.candidate),
        authority_for(publication_request),
    )
    record = service.publish(publication_request, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    unsafe = finalize_post_publication(record, post_smoke(record, tenant_leaks=1))
    late = finalize_post_publication(
        record,
        post_smoke(record, completed_at=record.published_at + timedelta(hours=1)),
    )
    mismatched = finalize_post_publication(
        record,
        post_smoke(record, candidate_sha256="f" * 64),
    )
    assert unsafe.state is PublicationState.ROLLBACK_REQUIRED
    assert late.state is PublicationState.ROLLBACK_REQUIRED
    assert mismatched.state is PublicationState.ROLLBACK_REQUIRED


def test_request_cannot_supply_its_own_release_authority_records() -> None:
    publication_request = request()
    publisher = PublisherSpy()
    service = PublicationService(
        publisher,
        trusted_registry(publication_request.candidate),
        StaticPublicationAuthority(tg06_records=(), decisions=()),
    )
    with pytest.raises(PublicationError) as missing:
        service.publish(publication_request, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    assert missing.value.code == "PUBLICATION_AUTHORITY_INVALID"
    assert publisher.calls == 0


def test_revoked_or_substituted_release_decision_is_denied() -> None:
    publication_request = request()
    publisher = PublisherSpy()
    revoked_service = PublicationService(
        publisher,
        trusted_registry(publication_request.candidate),
        authority_for(publication_request, revoked=True),
    )
    with pytest.raises(PublicationError) as revoked:
        revoked_service.publish(publication_request, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    assert revoked.value.code == "PUBLICATION_AUTHORITY_INVALID"

    substituted = request(approver_id="attacker")
    substituted_service = PublicationService(
        publisher,
        trusted_registry(substituted.candidate),
        authority_for(publication_request),
    )
    with pytest.raises(PublicationError) as mismatch:
        substituted_service.publish(substituted, now=datetime(2026, 8, 25, 1, tzinfo=UTC))
    assert mismatch.value.code == "PUBLICATION_AUTHORITY_INVALID"
    assert publisher.calls == 0
