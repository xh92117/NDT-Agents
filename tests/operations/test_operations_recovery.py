"""S6-04 quota, backup integrity, and recovery acceptance tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.operations.models import (
    BackupArtifact,
    BackupManifest,
    EvidenceEnvironment,
    GovernanceState,
    OperationsProfile,
    QuotaDimension,
    QuotaLimit,
    QuotaPolicy,
    RestoreEvidence,
    RestoreStatus,
    backup_manifest_sha256,
)
from ndt_agents.operations.service import OperationsError, QuotaGuard, assess_restore

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000701"),
    project_id=UUID("00000000-0000-4000-8000-000000000702"),
    user_id=UUID("00000000-0000-4000-8000-000000000703"),
    role_codes=("PROJECT_OPERATOR",),
    permission_version="permissions-ops-1",
)


def profile(*, approved: bool = False, concurrent_active: int = 2) -> OperationsProfile:
    return OperationsProfile(
        profile_version="operations-1",
        governance_state=GovernanceState.APPROVED if approved else GovernanceState.PROVISIONAL,
        security_baseline_version="1.0.0",
        security_baseline_sha256="a" * 64,
        metric_registry_version="metrics-1",
        reference_environment="local-synthetic" if not approved else "approved-reference",
        quota=QuotaPolicy(
            policy_version="quota-1",
            tenant_concurrent_tasks=QuotaLimit(active=concurrent_active, hard=3),
            user_concurrent_tasks=QuotaLimit(active=1, hard=2),
            project_accepted_tasks=QuotaLimit(active=10, hard=12),
            project_storage_bytes=QuotaLimit(active=1_000, hard=2_000),
            project_requests=QuotaLimit(active=100, hard=120),
        ),
        task_state_rpo_minutes=15,
        task_service_rto_minutes=240,
        noncritical_analytics_rto_minutes=1440,
        rolling_backup_retention_days=35,
        zero_loss_after_acknowledgement=("APPROVAL", "PUBLICATION"),
        approved_by_roles=(
            ("OPERATIONS_OWNER", "QUALITY_OWNER", "SECURITY_OWNER") if approved else ()
        ),
    )


def manifest(**updates: Any) -> BackupManifest:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "backup_id": UUID("00000000-0000-4000-8000-000000000710"),
        "scope": SCOPE,
        "profile_version": "operations-1",
        "environment": EvidenceEnvironment.LOCAL_SYNTHETIC,
        "started_at": now - timedelta(minutes=2),
        "completed_at": now,
        "artifacts": (
            BackupArtifact(
                artifact_id=UUID("00000000-0000-4000-8000-000000000711"),
                scope=SCOPE,
                store="checkpoint-store",
                content_sha256="b" * 64,
                size_bytes=128,
                encryption_key_reference="kms://recovery/test-key-v1",
            ),
        ),
        "checkpoint_count": 3,
        "event_counts": {"APPROVAL": 2, "PUBLICATION": 1, "AUDIT": 9},
        "previous_manifest_sha256": None,
        "manifest_sha256": "0" * 64,
    }
    values.update(updates)
    provisional = BackupManifest.model_construct(**values)
    values["manifest_sha256"] = backup_manifest_sha256(provisional)
    return BackupManifest.model_validate(values)


def evidence(item: BackupManifest, **updates: Any) -> RestoreEvidence:
    values: dict[str, Any] = {
        "restore_id": UUID("00000000-0000-4000-8000-000000000712"),
        "scope": item.scope,
        "backup_manifest_sha256": item.manifest_sha256,
        "environment": EvidenceEnvironment.LOCAL_SYNTHETIC,
        "restored_artifact_hashes": {
            artifact.artifact_id: artifact.content_sha256 for artifact in item.artifacts
        },
        "recovered_checkpoint_count": item.checkpoint_count,
        "recovered_event_counts": dict(item.event_counts),
        "measured_rpo_minutes": 4.0,
        "measured_rto_minutes": 18.0,
        "rollback_ready": True,
        "degraded_mode": "READ_ONLY_VALIDATION",
        "evidence_uri": "evidence://s6-04/local-drill",
        "completed_at": datetime.now(UTC),
    }
    values.update(updates)
    return RestoreEvidence(**values)


def test_quota_claims_are_exact_scope_atomic_and_idempotent() -> None:
    guard = QuotaGuard(profile())
    claim_id = UUID("00000000-0000-4000-8000-000000000720")
    first = guard.claim(SCOPE, claim_id, QuotaDimension.USER_CONCURRENT_TASKS)
    replay = guard.claim(SCOPE, claim_id, QuotaDimension.USER_CONCURRENT_TASKS)
    assert first.counter_after == 1
    assert replay.reused is True
    assert guard.count(SCOPE, QuotaDimension.USER_CONCURRENT_TASKS) == 1

    with pytest.raises(OperationsError) as denied:
        guard.claim(
            SCOPE,
            UUID("00000000-0000-4000-8000-000000000721"),
            QuotaDimension.USER_CONCURRENT_TASKS,
        )
    assert denied.value.code == "QUOTA_ACTIVE_LIMIT_EXCEEDED"
    assert guard.count(SCOPE, QuotaDimension.USER_CONCURRENT_TASKS) == 1

    released = guard.release(SCOPE, claim_id)
    replay_release = guard.release(SCOPE, claim_id)
    assert released.counter_after == 0
    assert replay_release.reused is True
    assert guard.count(SCOPE, QuotaDimension.USER_CONCURRENT_TASKS) == 0


def test_tenant_quota_aggregates_users_but_claim_identity_cannot_cross_scope() -> None:
    guard = QuotaGuard(profile())
    other = SCOPE.model_copy(update={"user_id": UUID("00000000-0000-4000-8000-000000000704")})
    first_id = UUID("00000000-0000-4000-8000-000000000722")
    guard.claim(SCOPE, first_id, QuotaDimension.TENANT_CONCURRENT_TASKS)
    guard.claim(
        other,
        UUID("00000000-0000-4000-8000-000000000723"),
        QuotaDimension.TENANT_CONCURRENT_TASKS,
    )
    assert guard.count(SCOPE, QuotaDimension.TENANT_CONCURRENT_TASKS) == 2
    with pytest.raises(OperationsError) as collision:
        guard.claim(other, first_id, QuotaDimension.TENANT_CONCURRENT_TASKS)
    assert collision.value.code == "QUOTA_CLAIM_CONFLICT"


def test_active_and_hard_quota_denials_are_distinct_and_counter_safe() -> None:
    active_guard = QuotaGuard(profile(concurrent_active=2))
    with pytest.raises(OperationsError) as active:
        active_guard.claim(
            SCOPE,
            UUID("00000000-0000-4000-8000-000000000724"),
            QuotaDimension.TENANT_CONCURRENT_TASKS,
            3,
        )
    assert active.value.code == "QUOTA_ACTIVE_LIMIT_EXCEEDED"
    hard_guard = QuotaGuard(profile(concurrent_active=3))
    with pytest.raises(OperationsError) as hard:
        hard_guard.claim(
            SCOPE,
            UUID("00000000-0000-4000-8000-000000000725"),
            QuotaDimension.TENANT_CONCURRENT_TASKS,
            4,
        )
    assert hard.value.code == "QUOTA_HARD_LIMIT_EXCEEDED"


def test_rate_and_daily_quotas_require_server_windows_and_reset_by_window() -> None:
    guard = QuotaGuard(profile())
    with pytest.raises(OperationsError) as missing:
        guard.claim(
            SCOPE,
            UUID("00000000-0000-4000-8000-000000000726"),
            QuotaDimension.PROJECT_REQUESTS,
        )
    assert missing.value.code == "QUOTA_WINDOW_REQUIRED"
    guard.claim(
        SCOPE,
        UUID("00000000-0000-4000-8000-000000000727"),
        QuotaDimension.PROJECT_REQUESTS,
        window_id="2026-08-25T15:00Z",
    )
    guard.claim(
        SCOPE,
        UUID("00000000-0000-4000-8000-000000000728"),
        QuotaDimension.PROJECT_REQUESTS,
        window_id="2026-08-25T15:01Z",
    )
    assert guard.window_count(SCOPE, QuotaDimension.PROJECT_REQUESTS, "2026-08-25T15:00Z") == 1


def test_backup_manifest_is_canonical_scope_bound_and_secret_free() -> None:
    item = manifest()
    assert item.manifest_sha256 == backup_manifest_sha256(item)
    assert "test-key-v1" in item.artifacts[0].encryption_key_reference
    assert "key_material" not in item.model_dump_json()
    with pytest.raises(ValidationError):
        BackupManifest.model_validate({**item.model_dump(mode="json"), "checkpoint_count": 4})
    foreign = item.artifacts[0].model_copy(
        update={"scope": SCOPE.model_copy(update={"permission_version": "changed"})}
    )
    with pytest.raises(ValidationError):
        manifest(artifacts=(foreign,))


def test_valid_synthetic_restore_is_blocked_until_policy_approval() -> None:
    item = manifest()
    result = assess_restore(profile(), item, evidence(item))
    assert result.status is RestoreStatus.BLOCKED
    assert result.reason_code == "RESTORE_POLICY_NOT_APPROVED"


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"restored_artifact_hashes": {}}, "RESTORE_ARTIFACT_INTEGRITY_FAILED"),
        ({"recovered_checkpoint_count": 2}, "RESTORE_CHECKPOINT_LOSS"),
        ({"recovered_event_counts": {"APPROVAL": 1, "PUBLICATION": 1}}, "RESTORE_ZERO_LOSS_FAILED"),
        ({"measured_rpo_minutes": 16.0}, "RESTORE_RPO_EXCEEDED"),
        ({"measured_rto_minutes": 241.0}, "RESTORE_RTO_EXCEEDED"),
        ({"rollback_ready": False}, "RESTORE_ROLLBACK_NOT_READY"),
        (
            {"scope": SCOPE.model_copy(update={"permission_version": "stale"})},
            "RESTORE_SCOPE_MISMATCH",
        ),
    ],
)
def test_restore_failures_are_typed(updates: dict[str, Any], expected: str) -> None:
    item = manifest()
    result = assess_restore(profile(), item, evidence(item, **updates))
    assert result.status is RestoreStatus.FAILED
    assert result.reason_code == expected


def test_only_approved_production_like_evidence_can_pass() -> None:
    item = manifest(environment=EvidenceEnvironment.PRODUCTION_LIKE)
    staging = assess_restore(
        profile(approved=True),
        item,
        evidence(item, environment=EvidenceEnvironment.STAGING),
    )
    passed = assess_restore(
        profile(approved=True),
        item,
        evidence(item, environment=EvidenceEnvironment.PRODUCTION_LIKE),
    )
    assert staging.status is RestoreStatus.BLOCKED
    assert staging.reason_code == "RESTORE_ENVIRONMENT_NOT_QUALIFIED"
    assert passed.status is RestoreStatus.PASS


def test_approved_profile_requires_all_accountable_roles() -> None:
    values = profile(approved=True).model_dump(mode="json")
    values["approved_by_roles"] = ["OPERATIONS_OWNER"]
    with pytest.raises(ValidationError):
        OperationsProfile.model_validate(values)
