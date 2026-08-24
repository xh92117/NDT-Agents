"""Governed retention, export, deletion, legal hold, and cryptographic erasure."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol, Self
from uuid import UUID, uuid5

from pydantic import Field, JsonValue, model_validator

from ndt_agents.context.assembly import canonical_json_bytes
from ndt_agents.contracts.v1 import ApprovalOutcome, ApprovalRecord, DataClassification, TenantScope
from ndt_agents.memory.models import MemoryAccess, MemoryModel
from ndt_agents.security.models import KeyRef

_LIFECYCLE_NAMESPACE = UUID("e3c985c9-26f6-4ea9-81f8-b63024927518")
_CLASSIFICATION = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class LifecycleError(RuntimeError):
    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class LifecycleState(StrEnum):
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"
    CRYPTO_ERASED = "CRYPTO_ERASED"


class LegalHoldState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class LifecycleAction(StrEnum):
    REGISTER = "REGISTER"
    EXPORT = "EXPORT"
    DELETE = "DELETE"
    HOLD_APPLY = "HOLD_APPLY"
    HOLD_RELEASE = "HOLD_RELEASE"
    CRYPTO_ERASE = "CRYPTO_ERASE"


class LifecyclePolicy(MemoryModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: str = Field(min_length=1, max_length=128)
    default_retention_days: int = Field(default=365, ge=1, le=3650)
    audit_retention_days: int = Field(default=2555, ge=365, le=3650)


class GovernedObject(MemoryModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    object_id: UUID
    scope: TenantScope
    object_type: str = Field(min_length=1, max_length=128)
    object_version: str = Field(min_length=1, max_length=128)
    classification: DataClassification
    content: dict[str, JsonValue] | None
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retention_until: datetime
    encryption_key_ref: KeyRef | None = None
    state: LifecycleState = LifecycleState.ACTIVE
    deleted_at: datetime | None = None
    crypto_erased_at: datetime | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_object(self) -> Self:
        for value in (self.created_at, self.retention_until):
            if value.utcoffset() is None:
                raise ValueError("lifecycle times must include an explicit UTC offset")
        if self.retention_until <= self.created_at:
            raise ValueError("retention deadline must follow creation")
        if self.state is LifecycleState.ACTIVE:
            if self.content is None:
                raise ValueError("active governed object requires content")
            if (
                hashlib.sha256(canonical_json_bytes(self.content)).hexdigest()
                != self.content_sha256
            ):
                raise ValueError("governed content hash does not match content")
        elif self.content is not None:
            raise ValueError("deleted or erased governed object cannot retain content")
        if self.encryption_key_ref is not None and (
            self.encryption_key_ref.tenant_id != self.scope.tenant_id
            or self.encryption_key_ref.project_id != self.scope.project_id
        ):
            raise ValueError("governed encryption key must use the exact tenant and project")
        return self


class LegalHold(MemoryModel):
    hold_id: UUID
    scope: TenantScope
    object_id: UUID
    reason: str = Field(min_length=1, max_length=2000)
    state: LegalHoldState
    approval_id: UUID
    applied_at: datetime
    released_at: datetime | None = None


class DeletionPreview(MemoryModel):
    preview_id: UUID
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: TenantScope
    object_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    object_hashes: tuple[str, ...] = Field(min_length=1, max_length=100)
    force_before_retention: bool
    created_at: datetime


class ExportRecord(MemoryModel):
    object_id: UUID
    object_type: str
    object_version: str
    classification: DataClassification
    content: dict[str, JsonValue]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExportBundle(MemoryModel):
    scope: TenantScope
    records: tuple[ExportRecord, ...]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exported_at: datetime


class LifecycleEvent(MemoryModel):
    event_id: UUID
    scope: TenantScope
    action: LifecycleAction
    object_ids: tuple[UUID, ...]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_id: UUID | None = None
    occurred_at: datetime


class KeyRevoker(Protocol):
    def revoke(self, ref: KeyRef) -> None: ...


class InMemoryLifecycleRepository:
    def __init__(self) -> None:
        self.objects: dict[UUID, GovernedObject] = {}
        self.holds: dict[UUID, LegalHold] = {}
        self.events: list[LifecycleEvent] = []
        self.completed_previews: dict[str, tuple[UUID, ...]] = {}


class DataLifecycleService:
    def __init__(
        self,
        repository: InMemoryLifecycleRepository,
        policy: LifecyclePolicy,
        *,
        key_revoker: KeyRevoker,
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._keys = key_revoker

    def register(
        self,
        access: MemoryAccess,
        *,
        object_id: UUID,
        object_type: str,
        object_version: str,
        classification: DataClassification,
        content: dict[str, JsonValue],
        created_at: datetime,
        retention_days: int | None = None,
        encryption_key_ref: KeyRef | None = None,
    ) -> GovernedObject:
        _authorize(access, "register")
        if object_id in self._repository.objects:
            raise LifecycleError(
                code="LIFECYCLE_OBJECT_CONFLICT",
                message="The governed object ID already exists.",
                next_action="Use the existing object or create a new immutable version.",
            )
        days = (
            retention_days
            if retention_days is not None
            else (
                self._policy.audit_retention_days
                if object_type == "audit"
                else self._policy.default_retention_days
            )
        )
        if not 1 <= days <= 3650:
            raise LifecycleError(
                code="LIFECYCLE_RETENTION_INVALID",
                message="Retention must be between 1 and 3650 days.",
                next_action="Select a retention period permitted by the active policy.",
            )
        record = GovernedObject(
            object_id=object_id,
            scope=access.scope,
            object_type=object_type,
            object_version=object_version,
            classification=classification,
            content=content,
            content_sha256=hashlib.sha256(canonical_json_bytes(content)).hexdigest(),
            retention_until=created_at + timedelta(days=days),
            encryption_key_ref=encryption_key_ref,
            created_at=created_at,
        )
        self._repository.objects[object_id] = record
        self._event(access.scope, LifecycleAction.REGISTER, (record,), None, created_at)
        return record

    def export(
        self, access: MemoryAccess, object_ids: tuple[UUID, ...], *, now: datetime
    ) -> ExportBundle:
        _authorize(access, "export")
        objects = self._load_active(access, object_ids)
        records = tuple(
            ExportRecord(
                object_id=item.object_id,
                object_type=item.object_type,
                object_version=item.object_version,
                classification=item.classification,
                content=item.content or {},
                content_sha256=item.content_sha256,
            )
            for item in objects
        )
        payload = [record.model_dump(mode="json") for record in records]
        manifest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        self._event(access.scope, LifecycleAction.EXPORT, objects, None, now)
        return ExportBundle(
            scope=access.scope,
            records=records,
            manifest_sha256=manifest,
            exported_at=now,
        )

    def preview_delete(
        self,
        access: MemoryAccess,
        object_ids: tuple[UUID, ...],
        *,
        now: datetime,
        force_before_retention: bool = False,
    ) -> DeletionPreview:
        _authorize(access, "delete")
        objects = self._load_active(access, object_ids)
        self._deny_holds(objects)
        if not force_before_retention and any(now < item.retention_until for item in objects):
            raise LifecycleError(
                code="LIFECYCLE_RETENTION_ACTIVE",
                message="At least one object is still inside its retention period.",
                next_action="Wait for retention expiry or request an approved forced deletion.",
            )
        payload = {
            "scope": access.scope.model_dump(mode="json"),
            "object_ids": [str(item.object_id) for item in objects],
            "object_hashes": [item.content_sha256 for item in objects],
            "force_before_retention": force_before_retention,
            "created_at": now.isoformat(),
            "policy_version": self._policy.policy_version,
        }
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return DeletionPreview(
            preview_id=uuid5(_LIFECYCLE_NAMESPACE, f"delete:{digest}"),
            preview_sha256=digest,
            scope=access.scope,
            object_ids=tuple(item.object_id for item in objects),
            object_hashes=tuple(item.content_sha256 for item in objects),
            force_before_retention=force_before_retention,
            created_at=now,
        )

    def delete(
        self,
        access: MemoryAccess,
        preview: DeletionPreview,
        approval: ApprovalRecord,
        *,
        now: datetime,
    ) -> tuple[GovernedObject, ...]:
        _authorize(access, "delete")
        if not _same_scope(access.scope, preview.scope):
            raise _scope_denied()
        action = "data.delete.force" if preview.force_before_retention else "data.delete"
        _validate_approval(
            approval,
            scope=access.scope,
            action=action,
            target_type="lifecycle.preview",
            target_id=preview.preview_id,
            target_version=self._policy.policy_version,
            target_sha256=preview.preview_sha256,
            now=now,
        )
        completed = self._repository.completed_previews.get(preview.preview_sha256)
        if completed is not None:
            return tuple(self._repository.objects[object_id] for object_id in completed)
        objects = self._load_active(access, preview.object_ids)
        self._deny_holds(objects)
        if tuple(item.content_sha256 for item in objects) != preview.object_hashes:
            raise LifecycleError(
                code="LIFECYCLE_PREVIEW_STALE",
                message="The deletion preview no longer matches the governed objects.",
                next_action="Create and approve a new deletion preview.",
            )
        tombstones = tuple(
            item.model_copy(
                update={
                    "content": None,
                    "state": LifecycleState.DELETED,
                    "deleted_at": now,
                }
            )
            for item in objects
        )
        for item in tombstones:
            self._repository.objects[item.object_id] = item
        self._repository.completed_previews[preview.preview_sha256] = preview.object_ids
        self._event(access.scope, LifecycleAction.DELETE, tombstones, approval.approval_id, now)
        return tombstones

    def apply_hold(
        self,
        access: MemoryAccess,
        object_id: UUID,
        reason: str,
        approval: ApprovalRecord,
        *,
        now: datetime,
    ) -> LegalHold:
        _authorize(access, "hold")
        item = self._load_active(access, (object_id,))[0]
        _validate_approval(
            approval,
            scope=access.scope,
            action="data.hold.apply",
            target_type=item.object_type,
            target_id=item.object_id,
            target_version=item.object_version,
            target_sha256=item.content_sha256,
            now=now,
        )
        hold_id = uuid5(_LIFECYCLE_NAMESPACE, f"hold:{item.object_id}:{approval.approval_id}")
        existing = self._repository.holds.get(hold_id)
        if existing is not None:
            return existing
        hold = LegalHold(
            hold_id=hold_id,
            scope=access.scope,
            object_id=object_id,
            reason=reason,
            state=LegalHoldState.ACTIVE,
            approval_id=approval.approval_id,
            applied_at=now,
        )
        self._repository.holds[hold_id] = hold
        self._event(access.scope, LifecycleAction.HOLD_APPLY, (item,), approval.approval_id, now)
        return hold

    def release_hold(
        self,
        access: MemoryAccess,
        hold_id: UUID,
        approval: ApprovalRecord,
        *,
        now: datetime,
    ) -> LegalHold:
        _authorize(access, "hold")
        hold = self._repository.holds.get(hold_id)
        if hold is None or not _same_scope(access.scope, hold.scope):
            raise _scope_denied()
        if hold.state is LegalHoldState.RELEASED:
            return hold
        digest = hashlib.sha256(canonical_json_bytes(hold.model_dump(mode="json"))).hexdigest()
        _validate_approval(
            approval,
            scope=access.scope,
            action="data.hold.release",
            target_type="legal_hold",
            target_id=hold.hold_id,
            target_version=self._policy.policy_version,
            target_sha256=digest,
            now=now,
        )
        released = hold.model_copy(update={"state": LegalHoldState.RELEASED, "released_at": now})
        self._repository.holds[hold_id] = released
        item = self._repository.objects[hold.object_id]
        self._event(access.scope, LifecycleAction.HOLD_RELEASE, (item,), approval.approval_id, now)
        return released

    def cryptographic_erase(
        self,
        access: MemoryAccess,
        object_id: UUID,
        approval: ApprovalRecord,
        *,
        now: datetime,
    ) -> GovernedObject:
        _authorize(access, "erase")
        item = self._load_active(access, (object_id,))[0]
        self._deny_holds((item,))
        if now < item.retention_until:
            raise LifecycleError(
                code="LIFECYCLE_RETENTION_ACTIVE",
                message="The object is still inside its retention period.",
                next_action="Wait for retention expiry or use approved governed deletion.",
            )
        _validate_approval(
            approval,
            scope=access.scope,
            action="data.erase",
            target_type=item.object_type,
            target_id=item.object_id,
            target_version=item.object_version,
            target_sha256=item.content_sha256,
            now=now,
        )
        key = item.encryption_key_ref
        expected_purpose = f"object-{item.object_id.hex}"
        if key is None or key.purpose != expected_purpose:
            raise LifecycleError(
                code="LIFECYCLE_OBJECT_KEY_REQUIRED",
                message="Cryptographic erasure requires an object-unique encryption key.",
                next_action="Use governed deletion or provision an object-unique key before write.",
            )
        try:
            self._keys.revoke(key)
        except Exception as exc:
            raise LifecycleError(
                code="LIFECYCLE_KEY_REVOCATION_FAILED",
                message="The encryption key could not be revoked.",
                next_action="Restore the key provider and retry without deleting ciphertext.",
            ) from exc
        erased = item.model_copy(
            update={
                "content": None,
                "state": LifecycleState.CRYPTO_ERASED,
                "crypto_erased_at": now,
            }
        )
        self._repository.objects[item.object_id] = erased
        self._event(
            access.scope,
            LifecycleAction.CRYPTO_ERASE,
            (erased,),
            approval.approval_id,
            now,
        )
        return erased

    def _load_active(
        self, access: MemoryAccess, object_ids: tuple[UUID, ...]
    ) -> tuple[GovernedObject, ...]:
        if not object_ids or len(object_ids) != len(set(object_ids)):
            raise LifecycleError(
                code="LIFECYCLE_TARGET_INVALID",
                message="Lifecycle targets must be a non-empty unique object set.",
                next_action="Provide each exact governed object ID once.",
            )
        selected: list[GovernedObject] = []
        for object_id in object_ids:
            item = self._repository.objects.get(object_id)
            if item is None or not _same_scope(access.scope, item.scope):
                raise _scope_denied()
            if _CLASSIFICATION[item.classification] > _CLASSIFICATION[access.clearance]:
                raise LifecycleError(
                    code="LIFECYCLE_CLASSIFICATION_DENIED",
                    message="The object classification exceeds the active clearance.",
                    next_action="Use an authorized actor with sufficient clearance.",
                )
            if item.state is not LifecycleState.ACTIVE:
                raise LifecycleError(
                    code="LIFECYCLE_OBJECT_NOT_ACTIVE",
                    message="The governed object is already deleted or erased.",
                    next_action="Use its tombstone evidence instead of repeating the operation.",
                )
            selected.append(item)
        return tuple(selected)

    def _deny_holds(self, objects: tuple[GovernedObject, ...]) -> None:
        held = {
            hold.object_id
            for hold in self._repository.holds.values()
            if hold.state is LegalHoldState.ACTIVE
        }
        if any(item.object_id in held for item in objects):
            raise LifecycleError(
                code="LIFECYCLE_LEGAL_HOLD_ACTIVE",
                message="An active legal hold blocks deletion or cryptographic erasure.",
                next_action="Preserve the data until an authorized hold release is recorded.",
            )

    def _event(
        self,
        scope: TenantScope,
        action: LifecycleAction,
        objects: tuple[GovernedObject, ...],
        approval_id: UUID | None,
        now: datetime,
    ) -> None:
        input_payload = [(str(item.object_id), item.content_sha256) for item in objects]
        input_hash = hashlib.sha256(canonical_json_bytes(input_payload)).hexdigest()
        outcome_payload = [(str(item.object_id), item.state.value) for item in objects]
        outcome_hash = hashlib.sha256(canonical_json_bytes(outcome_payload)).hexdigest()
        self._repository.events.append(
            LifecycleEvent(
                event_id=uuid5(
                    _LIFECYCLE_NAMESPACE,
                    f"event:{action.value}:{input_hash}:{approval_id}:{now.isoformat()}",
                ),
                scope=scope,
                action=action,
                object_ids=tuple(item.object_id for item in objects),
                input_sha256=input_hash,
                outcome_sha256=outcome_hash,
                approval_id=approval_id,
                occurred_at=now,
            )
        )


def _validate_approval(
    approval: ApprovalRecord,
    *,
    scope: TenantScope,
    action: str,
    target_type: str,
    target_id: UUID,
    target_version: str,
    target_sha256: str,
    now: datetime,
) -> None:
    valid = (
        _same_scope(approval.scope, scope)
        and approval.action == action
        and approval.target_type == target_type
        and approval.target_id == target_id
        and approval.target_version == target_version
        and approval.target_sha256 == target_sha256
        and approval.outcome is ApprovalOutcome.APPROVED
        and approval.decided_at <= now
        and (approval.expires_at is None or now < approval.expires_at)
    )
    if not valid:
        raise LifecycleError(
            code="LIFECYCLE_APPROVAL_INVALID",
            message="The lifecycle approval is missing, stale, rejected, or target-mismatched.",
            next_action="Obtain a current approval for the exact scoped object or preview hash.",
        )


def _authorize(access: MemoryAccess, action: str) -> None:
    permission = f"lifecycle:{action}"
    if permission not in access.permissions:
        raise LifecycleError(
            code="LIFECYCLE_PERMISSION_DENIED",
            message="The governed lifecycle operation is not authorized.",
            next_action=f"Request the {permission} permission for the active scope.",
        )


def _same_scope(left: TenantScope, right: TenantScope) -> bool:
    return left.model_dump(mode="json") == right.model_dump(mode="json")


def _scope_denied() -> LifecycleError:
    return LifecycleError(
        code="LIFECYCLE_SCOPE_DENIED",
        message="The governed object is outside the active scope.",
        next_action="Use an object for the exact tenant, project, user, and permission version.",
    )
