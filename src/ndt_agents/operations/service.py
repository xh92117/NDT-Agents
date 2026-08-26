"""Atomic in-memory quota guard and deterministic restore validation."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import cast
from uuid import UUID

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.operations.models import (
    BackupManifest,
    EvidenceEnvironment,
    GovernanceState,
    OperationsProfile,
    QuotaClaim,
    QuotaDimension,
    QuotaLimit,
    RestoreAssessment,
    RestoreEvidence,
    RestoreStatus,
)


class OperationsError(RuntimeError):
    def __init__(self, code: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__("The operations request could not be completed.")


class QuotaGuard:
    def __init__(self, profile: OperationsProfile) -> None:
        self.profile = profile
        self._counts: dict[tuple[object, ...], int] = {}
        self._claims: dict[UUID, QuotaClaim] = {}
        self._lock = RLock()

    def claim(
        self,
        scope: TenantScope,
        claim_id: UUID,
        dimension: QuotaDimension,
        amount: int = 1,
        window_id: str | None = None,
    ) -> QuotaClaim:
        if amount < 1:
            raise OperationsError("QUOTA_AMOUNT_INVALID", "Request a positive quota amount.")
        windowed = dimension in {
            QuotaDimension.PROJECT_ACCEPTED_TASKS,
            QuotaDimension.PROJECT_REQUESTS,
        }
        if windowed and window_id is None:
            raise OperationsError(
                "QUOTA_WINDOW_REQUIRED", "Provide the server-derived quota window identity."
            )
        if not windowed and window_id is not None:
            raise OperationsError(
                "QUOTA_WINDOW_FORBIDDEN", "Remove the window from this quota dimension."
            )
        key = self._counter_key(scope, dimension, window_id)
        with self._lock:
            existing = self._claims.get(claim_id)
            if existing is not None:
                if (
                    existing.scope != scope
                    or existing.dimension is not dimension
                    or existing.amount != amount
                    or existing.window_id != window_id
                ):
                    raise OperationsError(
                        "QUOTA_CLAIM_CONFLICT", "Use a new claim identity for changed quota input."
                    )
                return existing.model_copy(update={"reused": True})
            current = self._counts.get(key, 0)
            limit = self._limit(dimension)
            projected = current + amount
            if projected > limit.hard:
                raise OperationsError(
                    "QUOTA_HARD_LIMIT_EXCEEDED", "Reduce load before retrying this operation."
                )
            if projected > limit.active:
                raise OperationsError(
                    "QUOTA_ACTIVE_LIMIT_EXCEEDED",
                    "Wait for capacity or obtain a recorded active-limit elevation.",
                )
            claim = QuotaClaim(
                claim_id=claim_id,
                scope=scope,
                policy_version=self.profile.quota.policy_version,
                dimension=dimension,
                window_id=window_id,
                amount=amount,
                counter_after=projected,
                reused=False,
                released=False,
                created_at=datetime.now(UTC),
            )
            self._counts[key] = projected
            self._claims[claim_id] = claim
            return claim

    def release(self, scope: TenantScope, claim_id: UUID) -> QuotaClaim:
        with self._lock:
            claim = self._claims.get(claim_id)
            if claim is None or claim.scope != scope:
                raise OperationsError(
                    "QUOTA_CLAIM_NOT_FOUND", "Select an active exact-scope claim."
                )
            if claim.dimension not in {
                QuotaDimension.TENANT_CONCURRENT_TASKS,
                QuotaDimension.USER_CONCURRENT_TASKS,
            }:
                raise OperationsError(
                    "QUOTA_CLAIM_NOT_RELEASEABLE", "Only concurrency claims may be released."
                )
            if claim.released:
                return claim.model_copy(update={"reused": True})
            key = self._counter_key(scope, claim.dimension, claim.window_id)
            current = self._counts.get(key, 0)
            if current < claim.amount:
                raise OperationsError(
                    "QUOTA_COUNTER_INVALID", "Reconcile quota state from audit evidence."
                )
            self._counts[key] = current - claim.amount
            released = claim.model_copy(
                update={"released": True, "counter_after": current - claim.amount}
            )
            self._claims[claim_id] = released
            return released

    def count(self, scope: TenantScope, dimension: QuotaDimension) -> int:
        with self._lock:
            return self._counts.get(self._counter_key(scope, dimension, None), 0)

    def window_count(self, scope: TenantScope, dimension: QuotaDimension, window_id: str) -> int:
        with self._lock:
            return self._counts.get(self._counter_key(scope, dimension, window_id), 0)

    def _limit(self, dimension: QuotaDimension) -> QuotaLimit:
        names = {
            QuotaDimension.TENANT_CONCURRENT_TASKS: "tenant_concurrent_tasks",
            QuotaDimension.USER_CONCURRENT_TASKS: "user_concurrent_tasks",
            QuotaDimension.PROJECT_ACCEPTED_TASKS: "project_accepted_tasks",
            QuotaDimension.PROJECT_STORAGE_BYTES: "project_storage_bytes",
            QuotaDimension.PROJECT_REQUESTS: "project_requests",
        }
        return cast(QuotaLimit, getattr(self.profile.quota, names[dimension]))

    def _counter_key(
        self, scope: TenantScope, dimension: QuotaDimension, window_id: str | None
    ) -> tuple[object, ...]:
        prefix: tuple[object, ...] = (self.profile.quota.policy_version, dimension, scope.tenant_id)
        if dimension is QuotaDimension.TENANT_CONCURRENT_TASKS:
            return prefix
        if dimension is QuotaDimension.USER_CONCURRENT_TASKS:
            return (*prefix, scope.project_id, scope.user_id, scope.permission_version)
        return (
            (*prefix, scope.project_id, window_id)
            if window_id is not None
            else (*prefix, scope.project_id)
        )


def assess_restore(
    profile: OperationsProfile,
    manifest: BackupManifest,
    evidence: RestoreEvidence,
    *,
    previous_manifest: BackupManifest | None = None,
) -> RestoreAssessment:
    def fail(code: str, action: str) -> RestoreAssessment:
        return RestoreAssessment(
            status=RestoreStatus.FAILED,
            profile_version=profile.profile_version,
            backup_manifest_sha256=manifest.manifest_sha256,
            reason_code=code,
            next_action=action,
        )

    if manifest.profile_version != profile.profile_version or (
        evidence.backup_manifest_sha256 != manifest.manifest_sha256
    ):
        return fail(
            "RESTORE_PROFILE_OR_MANIFEST_MISMATCH",
            "Use evidence for the exact profile and manifest.",
        )
    if evidence.scope != manifest.scope:
        return fail(
            "RESTORE_SCOPE_MISMATCH",
            "Use restore evidence from the exact manifest scope.",
        )
    if manifest.previous_manifest_sha256 is not None and (
        previous_manifest is None
        or previous_manifest.manifest_sha256 != manifest.previous_manifest_sha256
    ):
        return fail(
            "RESTORE_MANIFEST_CHAIN_INVALID", "Provide and verify the previous backup manifest."
        )
    expected = {item.artifact_id: item.content_sha256 for item in manifest.artifacts}
    if evidence.restored_artifact_hashes != expected:
        return fail(
            "RESTORE_ARTIFACT_INTEGRITY_FAILED", "Restore and verify every exact artifact hash."
        )
    if evidence.recovered_checkpoint_count != manifest.checkpoint_count:
        return fail("RESTORE_CHECKPOINT_LOSS", "Recover every committed checkpoint.")
    for category in profile.zero_loss_after_acknowledgement:
        expected_count = manifest.event_counts.get(category, 0)
        if evidence.recovered_event_counts.get(category, 0) != expected_count:
            return fail(
                "RESTORE_ZERO_LOSS_FAILED", f"Recover every acknowledged {category.lower()} event."
            )
    if evidence.measured_rpo_minutes > profile.task_state_rpo_minutes:
        return fail("RESTORE_RPO_EXCEEDED", "Improve backup frequency and rerun the restore drill.")
    if evidence.measured_rto_minutes > profile.task_service_rto_minutes:
        return fail("RESTORE_RTO_EXCEEDED", "Improve restore execution and rerun the drill.")
    if not evidence.rollback_ready:
        return fail("RESTORE_ROLLBACK_NOT_READY", "Prepare and verify the rollback path.")
    if profile.governance_state is not GovernanceState.APPROVED:
        return RestoreAssessment(
            status=RestoreStatus.BLOCKED,
            profile_version=profile.profile_version,
            backup_manifest_sha256=manifest.manifest_sha256,
            reason_code="RESTORE_POLICY_NOT_APPROVED",
            next_action="Obtain accountable approval for the exact operations profile.",
        )
    if evidence.environment is not EvidenceEnvironment.PRODUCTION_LIKE:
        return RestoreAssessment(
            status=RestoreStatus.BLOCKED,
            profile_version=profile.profile_version,
            backup_manifest_sha256=manifest.manifest_sha256,
            reason_code="RESTORE_ENVIRONMENT_NOT_QUALIFIED",
            next_action="Rerun on the approved production-like recovery environment.",
        )
    return RestoreAssessment(
        status=RestoreStatus.PASS,
        profile_version=profile.profile_version,
        backup_manifest_sha256=manifest.manifest_sha256,
        reason_code="RESTORE_ACCEPTED",
        next_action="Preserve the immutable recovery evidence for the release candidate.",
    )
