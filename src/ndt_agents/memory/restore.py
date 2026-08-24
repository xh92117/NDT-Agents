"""Immutable snapshots with previewed direct and intent-based branch restore."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, Self
from uuid import UUID, uuid5

from pydantic import Field, JsonValue, model_validator

from ndt_agents.context.assembly import canonical_json_bytes
from ndt_agents.contracts.v1 import ArtifactRef, Checkpoint, TenantScope
from ndt_agents.memory.models import MemoryAccess, MemoryModel

_RESTORE_NAMESPACE = UUID("4107c3f4-a1cc-4338-a3f4-4ca9c184d4d2")


class RestoreError(RuntimeError):
    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class RestoreOutcome(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class IntentRestoreAction(StrEnum):
    AUTO_PREVIEW = "AUTO_PREVIEW"
    SHOW_CANDIDATES = "SHOW_CANDIDATES"


class MemorySnapshot(MemoryModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    snapshot_id: UUID
    task_id: UUID
    scope: TenantScope
    branch_id: UUID
    parent_snapshot_id: UUID | None = None
    checkpoint: Checkpoint
    graph_version: str = Field(min_length=1, max_length=128)
    state_schema_version: str = Field(min_length=1, max_length=64)
    state: dict[str, JsonValue] = Field(min_length=1)
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_ids: tuple[UUID, ...] = Field(max_length=100)
    project_facts: tuple[dict[str, JsonValue], ...] = Field(max_length=20)
    artifacts: tuple[ArtifactRef, ...] = Field(max_length=10)
    required_turns: tuple[dict[str, JsonValue], ...] = Field(max_length=6)
    injection_tokens: int = Field(ge=1, le=6000)
    created_at: datetime

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if hashlib.sha256(canonical_json_bytes(self.state)).hexdigest() != self.state_sha256:
            raise ValueError("snapshot state hash does not match state")
        if self.created_at.utcoffset() is None:
            raise ValueError("snapshot creation time must include an explicit UTC offset")
        if self.checkpoint.task_id != self.task_id or not _same_scope(
            self.checkpoint.scope, self.scope
        ):
            raise ValueError("snapshot checkpoint must use the exact task scope")
        if self.checkpoint.state_sha256 != self.state_sha256:
            raise ValueError("snapshot and checkpoint state hashes must match")
        if any(not _same_scope(artifact.scope, self.scope) for artifact in self.artifacts):
            raise ValueError("snapshot artifacts must use the exact scope")
        if len(self.memory_ids) != len(set(self.memory_ids)):
            raise ValueError("snapshot memory IDs must be unique")
        return self


class SnapshotMatch(MemoryModel):
    snapshot_id: UUID
    score: float = Field(ge=0.0, le=1.0)


class SnapshotMatcher(Protocol):
    async def search(
        self, intent: str, snapshots: tuple[MemorySnapshot, ...], limit: int
    ) -> tuple[SnapshotMatch, ...]: ...


class ArtifactAvailability(Protocol):
    async def exists(self, scope: TenantScope, artifact: ArtifactRef) -> bool: ...


class RestorePreview(MemoryModel):
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: UUID
    task_id: UUID
    source_branch_id: UUID
    target_branch_id: UUID
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_count: int = Field(ge=0)
    project_fact_count: int = Field(ge=0, le=20)
    artifact_count: int = Field(ge=0, le=10)
    required_turn_count: int = Field(ge=0, le=6)
    injection_tokens: int = Field(ge=1, le=6000)
    created_at: datetime


class IntentRestoreResult(MemoryModel):
    action: IntentRestoreAction
    matches: tuple[SnapshotMatch, ...] = Field(max_length=5)
    preview: RestorePreview | None = None

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if (self.action is IntentRestoreAction.AUTO_PREVIEW) != (self.preview is not None):
            raise ValueError("intent restore action and preview are inconsistent")
        return self


class RestoreDecision(MemoryModel):
    decision_id: UUID
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: UUID
    scope: TenantScope
    actor_user_id: UUID
    outcome: RestoreOutcome
    target_branch_id: UUID | None = None
    decided_at: datetime


class RestoredBranch(MemoryModel):
    branch_id: UUID
    source_snapshot_id: UUID
    parent_branch_id: UUID
    task_id: UUID
    scope: TenantScope
    state: dict[str, JsonValue]
    memory_ids: tuple[UUID, ...]
    project_facts: tuple[dict[str, JsonValue], ...]
    artifacts: tuple[ArtifactRef, ...]
    required_turns: tuple[dict[str, JsonValue], ...]
    restored_at: datetime


class InMemorySnapshotRepository:
    def __init__(self) -> None:
        self._snapshots: dict[UUID, MemorySnapshot] = {}
        self._decisions: dict[str, RestoreDecision] = {}

    def insert_snapshot(self, snapshot: MemorySnapshot) -> None:
        if snapshot.snapshot_id in self._snapshots:
            raise RestoreError(
                code="SNAPSHOT_IMMUTABLE_CONFLICT",
                message="The immutable snapshot ID already exists.",
                next_action="Use the existing snapshot or create a new snapshot version.",
            )
        self._snapshots[snapshot.snapshot_id] = snapshot

    def get_snapshot(self, snapshot_id: UUID) -> MemorySnapshot | None:
        return self._snapshots.get(snapshot_id)

    def snapshots(self) -> tuple[MemorySnapshot, ...]:
        return tuple(self._snapshots.values())

    def record_decision(self, decision: RestoreDecision) -> RestoreDecision:
        existing = self._decisions.get(decision.preview_sha256)
        if existing is not None:
            if existing.outcome is not decision.outcome:
                raise RestoreError(
                    code="RESTORE_DECISION_CONFLICT",
                    message="The restore preview already has a different terminal decision.",
                    next_action="Use the recorded decision or create a new preview.",
                )
            return existing
        self._decisions[decision.preview_sha256] = decision
        return decision


class MemoryRestoreService:
    def __init__(
        self,
        *,
        repository: InMemorySnapshotRepository,
        artifact_availability: ArtifactAvailability,
        supported_state_versions: frozenset[str],
    ) -> None:
        self._repository = repository
        self._artifacts = artifact_availability
        self._supported = supported_state_versions

    def create_snapshot(self, access: MemoryAccess, snapshot: MemorySnapshot) -> None:
        _authorize(access, "snapshot")
        if not _same_scope(access.scope, snapshot.scope):
            raise _scope_denied()
        self._repository.insert_snapshot(snapshot)

    async def preview_direct(
        self, access: MemoryAccess, snapshot_id: UUID, *, now: datetime
    ) -> RestorePreview:
        _authorize(access, "restore")
        snapshot = self._load_visible(access, snapshot_id)
        await self._validate_restore(snapshot)
        return _preview(snapshot, now)

    async def preview_intent(
        self,
        access: MemoryAccess,
        intent: str,
        *,
        matcher: SnapshotMatcher,
        now: datetime,
    ) -> IntentRestoreResult:
        _authorize(access, "restore")
        if not intent or len(intent) > 2000:
            raise RestoreError(
                code="RESTORE_INTENT_INVALID",
                message="The restore intent is empty or too large.",
                next_action="Provide one bounded description of the task to restore.",
            )
        visible = tuple(
            snapshot
            for snapshot in self._repository.snapshots()
            if _same_scope(access.scope, snapshot.scope)
        )
        matches = await matcher.search(intent, visible, 5)
        if len(matches) > 5 or tuple(sorted(matches, key=lambda item: -item.score)) != matches:
            raise RestoreError(
                code="RESTORE_MATCH_RESULT_INVALID",
                message="The snapshot matcher returned an invalid candidate list.",
                next_action="Reject the result and rerun the bounded matcher.",
            )
        if not matches:
            return IntentRestoreResult(
                action=IntentRestoreAction.SHOW_CANDIDATES,
                matches=(),
            )
        margin = matches[0].score - (matches[1].score if len(matches) > 1 else 0.0)
        if matches[0].score >= 0.90 and margin >= 0.12:
            snapshot = self._load_visible(access, matches[0].snapshot_id)
            await self._validate_restore(snapshot)
            return IntentRestoreResult(
                action=IntentRestoreAction.AUTO_PREVIEW,
                matches=matches,
                preview=_preview(snapshot, now),
            )
        return IntentRestoreResult(
            action=IntentRestoreAction.SHOW_CANDIDATES,
            matches=matches,
        )

    async def confirm(
        self, access: MemoryAccess, preview: RestorePreview, *, now: datetime
    ) -> RestoredBranch:
        _authorize(access, "restore")
        snapshot = self._load_visible(access, preview.snapshot_id)
        await self._validate_restore(snapshot)
        expected = _preview(snapshot, preview.created_at)
        if expected != preview:
            raise RestoreError(
                code="RESTORE_PREVIEW_TAMPERED",
                message="The restore preview does not match the immutable snapshot.",
                next_action="Discard it and create a new verified preview.",
            )
        decision = RestoreDecision(
            decision_id=uuid5(_RESTORE_NAMESPACE, f"confirm:{preview.preview_sha256}"),
            preview_sha256=preview.preview_sha256,
            snapshot_id=snapshot.snapshot_id,
            scope=snapshot.scope,
            actor_user_id=access.scope.user_id,
            outcome=RestoreOutcome.CONFIRMED,
            target_branch_id=preview.target_branch_id,
            decided_at=now,
        )
        decision = self._repository.record_decision(decision)
        return RestoredBranch(
            branch_id=preview.target_branch_id,
            source_snapshot_id=snapshot.snapshot_id,
            parent_branch_id=snapshot.branch_id,
            task_id=snapshot.task_id,
            scope=snapshot.scope,
            state=snapshot.state,
            memory_ids=snapshot.memory_ids,
            project_facts=snapshot.project_facts,
            artifacts=snapshot.artifacts,
            required_turns=snapshot.required_turns,
            restored_at=decision.decided_at,
        )

    def cancel(
        self, access: MemoryAccess, preview: RestorePreview, *, now: datetime
    ) -> RestoreDecision:
        _authorize(access, "restore")
        snapshot = self._load_visible(access, preview.snapshot_id)
        expected = _preview(snapshot, preview.created_at)
        if expected != preview:
            raise RestoreError(
                code="RESTORE_PREVIEW_TAMPERED",
                message="The restore preview does not match the immutable snapshot.",
                next_action="Discard it and create a new verified preview.",
            )
        return self._repository.record_decision(
            RestoreDecision(
                decision_id=uuid5(_RESTORE_NAMESPACE, f"cancel:{preview.preview_sha256}"),
                preview_sha256=preview.preview_sha256,
                snapshot_id=snapshot.snapshot_id,
                scope=snapshot.scope,
                actor_user_id=access.scope.user_id,
                outcome=RestoreOutcome.CANCELLED,
                decided_at=now,
            )
        )

    def _load_visible(self, access: MemoryAccess, snapshot_id: UUID) -> MemorySnapshot:
        snapshot = self._repository.get_snapshot(snapshot_id)
        if snapshot is None:
            raise RestoreError(
                code="SNAPSHOT_NOT_FOUND",
                message="The requested snapshot does not exist.",
                next_action="Select an available snapshot candidate.",
            )
        if not _same_scope(access.scope, snapshot.scope):
            raise _scope_denied()
        return snapshot

    async def _validate_restore(self, snapshot: MemorySnapshot) -> None:
        if snapshot.state_schema_version not in self._supported:
            raise RestoreError(
                code="RESTORE_VERSION_INCOMPATIBLE",
                message="The snapshot state version is not compatible with this runtime.",
                next_action="Use a compatible runtime or migrate the snapshot through review.",
            )
        for artifact in snapshot.artifacts:
            if not await self._artifacts.exists(snapshot.scope, artifact):
                raise RestoreError(
                    code="RESTORE_ARTIFACT_MISSING",
                    message="A snapshot artifact is unavailable or failed scope validation.",
                    next_action="Restore the verified artifact or select another snapshot.",
                )


def snapshot_state_sha256(state: dict[str, JsonValue]) -> str:
    return hashlib.sha256(canonical_json_bytes(state)).hexdigest()


def _preview(snapshot: MemorySnapshot, now: datetime) -> RestorePreview:
    if now.utcoffset() is None:
        raise ValueError("restore preview time must include an explicit UTC offset")
    target_branch = uuid5(
        _RESTORE_NAMESPACE, f"branch:{snapshot.snapshot_id}:{snapshot.state_sha256}"
    )
    payload = {
        "snapshot_id": str(snapshot.snapshot_id),
        "task_id": str(snapshot.task_id),
        "source_branch_id": str(snapshot.branch_id),
        "target_branch_id": str(target_branch),
        "state_sha256": snapshot.state_sha256,
        "memory_count": len(snapshot.memory_ids),
        "project_fact_count": len(snapshot.project_facts),
        "artifact_count": len(snapshot.artifacts),
        "required_turn_count": len(snapshot.required_turns),
        "injection_tokens": snapshot.injection_tokens,
        "created_at": now.isoformat(),
    }
    return RestorePreview(
        preview_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        snapshot_id=snapshot.snapshot_id,
        task_id=snapshot.task_id,
        source_branch_id=snapshot.branch_id,
        target_branch_id=target_branch,
        state_sha256=snapshot.state_sha256,
        memory_count=len(snapshot.memory_ids),
        project_fact_count=len(snapshot.project_facts),
        artifact_count=len(snapshot.artifacts),
        required_turn_count=len(snapshot.required_turns),
        injection_tokens=snapshot.injection_tokens,
        created_at=now,
    )


def _authorize(access: MemoryAccess, action: str) -> None:
    permission = f"memory:{action}"
    if permission not in access.permissions:
        raise RestoreError(
            code="RESTORE_PERMISSION_DENIED",
            message="The snapshot operation is not authorized.",
            next_action=f"Request the {permission} permission for the active scope.",
        )


def _same_scope(left: TenantScope, right: TenantScope) -> bool:
    return left.model_dump(mode="json") == right.model_dump(mode="json")


def _scope_denied() -> RestoreError:
    return RestoreError(
        code="RESTORE_SCOPE_DENIED",
        message="The snapshot is outside the active tenant scope.",
        next_action=(
            "Select a snapshot for the exact tenant, project, user, and permission version."
        ),
    )
