"""Strict operations policy, quota, backup, and restore evidence models."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel, TenantScope


class GovernanceState(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"


class EvidenceEnvironment(StrEnum):
    LOCAL_SYNTHETIC = "LOCAL_SYNTHETIC"
    STAGING = "STAGING"
    PRODUCTION_LIKE = "PRODUCTION_LIKE"


class QuotaDimension(StrEnum):
    TENANT_CONCURRENT_TASKS = "TENANT_CONCURRENT_TASKS"
    USER_CONCURRENT_TASKS = "USER_CONCURRENT_TASKS"
    PROJECT_ACCEPTED_TASKS = "PROJECT_ACCEPTED_TASKS"
    PROJECT_STORAGE_BYTES = "PROJECT_STORAGE_BYTES"
    PROJECT_REQUESTS = "PROJECT_REQUESTS"


class QuotaLimit(StrictModel):
    active: int = Field(ge=0)
    hard: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.active > self.hard:
            raise ValueError("active quota cannot exceed hard quota")
        return self


class QuotaPolicy(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: str = Field(min_length=1, max_length=128)
    tenant_concurrent_tasks: QuotaLimit
    user_concurrent_tasks: QuotaLimit
    project_accepted_tasks: QuotaLimit
    project_storage_bytes: QuotaLimit
    project_requests: QuotaLimit


class OperationsProfile(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    profile_version: str = Field(min_length=1, max_length=128)
    governance_state: GovernanceState
    security_baseline_version: str = Field(min_length=1, max_length=128)
    security_baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metric_registry_version: str = Field(min_length=1, max_length=128)
    reference_environment: str = Field(min_length=1, max_length=256)
    quota: QuotaPolicy
    task_state_rpo_minutes: int = Field(ge=0)
    task_service_rto_minutes: int = Field(ge=1)
    noncritical_analytics_rto_minutes: int = Field(ge=1)
    rolling_backup_retention_days: int = Field(ge=1)
    zero_loss_after_acknowledgement: tuple[Literal["APPROVAL", "PUBLICATION"], ...]
    approved_by_roles: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_governance(self) -> Self:
        required = {"OPERATIONS_OWNER", "QUALITY_OWNER", "SECURITY_OWNER"}
        if self.governance_state is GovernanceState.APPROVED and not required <= set(
            self.approved_by_roles
        ):
            raise ValueError("approved operations profile requires accountable owner roles")
        if len(set(self.zero_loss_after_acknowledgement)) != len(
            self.zero_loss_after_acknowledgement
        ):
            raise ValueError("zero-loss categories must be unique")
        return self


class QuotaClaim(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    claim_id: UUID
    scope: TenantScope
    policy_version: str
    dimension: QuotaDimension
    window_id: str | None = Field(default=None, max_length=64, pattern=r"^[0-9TZ:-]+$")
    amount: int = Field(ge=1)
    counter_after: int = Field(ge=0)
    reused: bool
    released: bool
    created_at: datetime


class BackupArtifact(StrictModel):
    artifact_id: UUID
    scope: TenantScope
    store: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    encryption_key_reference: str = Field(
        min_length=1, max_length=256, pattern=r"^(kms|vault|hsm)://[A-Za-z0-9._/-]+$"
    )


class BackupManifest(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    backup_id: UUID
    scope: TenantScope
    profile_version: str
    environment: EvidenceEnvironment
    started_at: datetime
    completed_at: datetime
    artifacts: tuple[BackupArtifact, ...] = Field(min_length=1)
    checkpoint_count: int = Field(ge=0)
    event_counts: dict[str, int]
    previous_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("backup completion cannot precede start")
        if len({item.artifact_id for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("backup artifacts must be unique")
        if any(item.scope != self.scope for item in self.artifacts):
            raise ValueError("backup artifacts require the exact manifest scope")
        if any(value < 0 for value in self.event_counts.values()):
            raise ValueError("event counts cannot be negative")
        if self.manifest_sha256 != backup_manifest_sha256(self):
            raise ValueError("backup manifest hash is invalid")
        return self


class RestoreEvidence(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    restore_id: UUID
    scope: TenantScope
    backup_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment: EvidenceEnvironment
    restored_artifact_hashes: dict[UUID, str]
    recovered_checkpoint_count: int = Field(ge=0)
    recovered_event_counts: dict[str, int]
    measured_rpo_minutes: float = Field(ge=0)
    measured_rto_minutes: float = Field(ge=0)
    rollback_ready: bool
    degraded_mode: str = Field(min_length=1, max_length=128)
    evidence_uri: str = Field(min_length=1, max_length=1024)
    completed_at: datetime


class RestoreStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class RestoreAssessment(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: RestoreStatus
    profile_version: str
    backup_manifest_sha256: str
    reason_code: str
    next_action: str


def backup_manifest_sha256(manifest: BackupManifest) -> str:
    payload = manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
