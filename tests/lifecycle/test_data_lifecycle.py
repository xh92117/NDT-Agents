"""S2-09 INT-DATA-LIFECYCLE governed workflow tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import JsonValue

from ndt_agents.context.assembly import canonical_json_bytes
from ndt_agents.contracts.v1 import (
    ApprovalOutcome,
    ApprovalRecord,
    DataClassification,
    TenantScope,
)
from ndt_agents.lifecycle import (
    DataLifecycleService,
    GovernedObject,
    InMemoryLifecycleRepository,
    LegalHoldState,
    LifecycleAction,
    LifecycleError,
    LifecyclePolicy,
    LifecycleState,
)
from ndt_agents.memory import MemoryAccess
from ndt_agents.security.models import KeyRef, SecurityEnvironment

NOW = datetime(2026, 8, 24, 17, 0, tzinfo=UTC)
SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000001"),
    project_id=UUID("00000000-0000-4000-8000-000000000002"),
    user_id=UUID("00000000-0000-4000-8000-000000000003"),
    role_codes=("DATA_OWNER",),
    permission_version="perm-1",
)
ACCESS = MemoryAccess(
    scope=SCOPE,
    permissions=tuple(
        f"lifecycle:{action}" for action in ("register", "export", "delete", "hold", "erase")
    ),
    clearance=DataClassification.RESTRICTED,
)


class Revoker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.revoked: list[KeyRef] = []

    def revoke(self, ref: KeyRef) -> None:
        if self.fail:
            raise RuntimeError("key provider unavailable")
        self.revoked.append(ref)


def runtime(
    *, fail_revoke: bool = False
) -> tuple[DataLifecycleService, InMemoryLifecycleRepository, Revoker]:
    repository = InMemoryLifecycleRepository()
    revoker = Revoker(fail=fail_revoke)
    return (
        DataLifecycleService(
            repository,
            LifecyclePolicy(policy_version="lifecycle-1"),
            key_revoker=revoker,
        ),
        repository,
        revoker,
    )


def key_for(object_id: UUID, *, unique: bool = True) -> KeyRef:
    return KeyRef(
        key_id=f"object-{object_id.hex}",
        environment=SecurityEnvironment.LOCAL,
        tenant_id=SCOPE.tenant_id,
        project_id=SCOPE.project_id,
        purpose=f"object-{object_id.hex}" if unique else "shared-data",
        version="1",
    )


def register(
    service: DataLifecycleService,
    index: int = 1,
    *,
    object_type: str = "memory",
    retention_days: int = 1,
    encrypted: bool = False,
    unique_key: bool = True,
) -> GovernedObject:
    object_id = UUID(f"00000000-0000-4000-8000-{index:012d}")
    content: dict[str, JsonValue] = {"record": index, "text": f"value-{index}"}
    return service.register(
        ACCESS,
        object_id=object_id,
        object_type=object_type,
        object_version="1",
        classification=DataClassification.INTERNAL,
        content=content,
        created_at=NOW,
        retention_days=retention_days,
        encryption_key_ref=key_for(object_id, unique=unique_key) if encrypted else None,
    )


def approval(
    *,
    action: str,
    target_type: str,
    target_id: UUID,
    target_version: str,
    target_sha256: str,
    outcome: ApprovalOutcome = ApprovalOutcome.APPROVED,
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=UUID("90000000-0000-4000-8000-000000000001"),
        scope=SCOPE,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_version=target_version,
        target_sha256=target_sha256,
        policy_version="approval-1",
        actor_id=UUID("90000000-0000-4000-8000-000000000002"),
        outcome=outcome,
        reason="Exact governed action approved.",
        decided_at=NOW,
        expires_at=NOW + timedelta(days=10),
    )


def test_registration_applies_retention_and_immutable_hash() -> None:
    service, repository, _ = runtime()
    normal = register(service, 1)
    audit = register(service, 2, object_type="audit", retention_days=2555)

    assert normal.retention_until == NOW + timedelta(days=1)
    assert audit.retention_until == NOW + timedelta(days=2555)
    assert normal.content is not None
    assert normal.content_sha256 == hashlib.sha256(canonical_json_bytes(normal.content)).hexdigest()
    assert repository.events[0].action is LifecycleAction.REGISTER


@pytest.mark.parametrize("days", (0, 3651))
def test_registration_rejects_retention_outside_policy_bounds(days: int) -> None:
    service, repository, _ = runtime()
    with pytest.raises(LifecycleError, match="Retention") as denied:
        register(service, retention_days=days)
    assert denied.value.code == "LIFECYCLE_RETENTION_INVALID"
    assert repository.objects == {}


def test_export_is_scope_checked_and_hash_manifested() -> None:
    service, _, _ = runtime()
    item = register(service)
    bundle = service.export(ACCESS, (item.object_id,), now=NOW)
    expected = hashlib.sha256(
        canonical_json_bytes([record.model_dump(mode="json") for record in bundle.records])
    ).hexdigest()
    assert bundle.manifest_sha256 == expected

    other = SCOPE.model_copy(update={"project_id": UUID("00000000-0000-4000-8000-000000000099")})
    with pytest.raises(LifecycleError, match="outside") as denied:
        service.export(ACCESS.model_copy(update={"scope": other}), (item.object_id,), now=NOW)
    assert denied.value.code == "LIFECYCLE_SCOPE_DENIED"


def test_retention_blocks_normal_delete_but_approved_force_creates_tombstone() -> None:
    service, repository, _ = runtime()
    item = register(service)
    with pytest.raises(LifecycleError, match="retention") as blocked:
        service.preview_delete(ACCESS, (item.object_id,), now=NOW)
    assert blocked.value.code == "LIFECYCLE_RETENTION_ACTIVE"

    preview = service.preview_delete(
        ACCESS, (item.object_id,), now=NOW, force_before_retention=True
    )
    approved = approval(
        action="data.delete.force",
        target_type="lifecycle.preview",
        target_id=preview.preview_id,
        target_version="lifecycle-1",
        target_sha256=preview.preview_sha256,
    )
    deleted = service.delete(ACCESS, preview, approved, now=NOW + timedelta(seconds=1))
    repeated = service.delete(ACCESS, preview, approved, now=NOW + timedelta(seconds=2))
    assert deleted == repeated
    assert deleted[0].state is LifecycleState.DELETED
    assert deleted[0].content is None
    assert deleted[0].content_sha256 == item.content_sha256
    assert repository.events[-1].action is LifecycleAction.DELETE


def test_stale_rejected_or_target_mismatched_approval_is_denied() -> None:
    service, _, _ = runtime()
    item = register(service)
    preview = service.preview_delete(
        ACCESS, (item.object_id,), now=NOW, force_before_retention=True
    )
    rejected = approval(
        action="data.delete.force",
        target_type="lifecycle.preview",
        target_id=preview.preview_id,
        target_version="lifecycle-1",
        target_sha256=preview.preview_sha256,
        outcome=ApprovalOutcome.REJECTED,
    )
    with pytest.raises(LifecycleError, match="approval") as denied:
        service.delete(ACCESS, preview, rejected, now=NOW)
    assert denied.value.code == "LIFECYCLE_APPROVAL_INVALID"


def test_legal_hold_blocks_delete_until_exact_approved_release() -> None:
    service, _, _ = runtime()
    item = register(service)
    apply = approval(
        action="data.hold.apply",
        target_type=item.object_type,
        target_id=item.object_id,
        target_version=item.object_version,
        target_sha256=item.content_sha256,
    )
    hold = service.apply_hold(ACCESS, item.object_id, "Litigation", apply, now=NOW)
    assert hold.state is LegalHoldState.ACTIVE
    with pytest.raises(LifecycleError, match="legal hold"):
        service.preview_delete(ACCESS, (item.object_id,), now=NOW, force_before_retention=True)

    hold_hash = hashlib.sha256(canonical_json_bytes(hold.model_dump(mode="json"))).hexdigest()
    release = approval(
        action="data.hold.release",
        target_type="legal_hold",
        target_id=hold.hold_id,
        target_version="lifecycle-1",
        target_sha256=hold_hash,
    )
    released = service.release_hold(ACCESS, hold.hold_id, release, now=NOW)
    assert released.state is LegalHoldState.RELEASED
    assert service.release_hold(ACCESS, hold.hold_id, release, now=NOW) == released
    assert service.preview_delete(ACCESS, (item.object_id,), now=NOW, force_before_retention=True)


def test_cryptographic_erasure_revokes_unique_key_and_removes_content() -> None:
    service, repository, revoker = runtime()
    item = register(service, encrypted=True)
    approved = approval(
        action="data.erase",
        target_type=item.object_type,
        target_id=item.object_id,
        target_version=item.object_version,
        target_sha256=item.content_sha256,
    )
    erased = service.cryptographic_erase(
        ACCESS, item.object_id, approved, now=NOW + timedelta(days=2)
    )
    assert erased.state is LifecycleState.CRYPTO_ERASED
    assert erased.content is None
    assert revoker.revoked == [item.encryption_key_ref]
    assert repository.events[-1].action is LifecycleAction.CRYPTO_ERASE


def test_erasure_rejects_shared_key_active_retention_hold_and_provider_failure() -> None:
    shared_service, _, _ = runtime()
    shared = register(shared_service, encrypted=True, unique_key=False)
    approved = approval(
        action="data.erase",
        target_type=shared.object_type,
        target_id=shared.object_id,
        target_version=shared.object_version,
        target_sha256=shared.content_sha256,
    )
    with pytest.raises(LifecycleError, match="retention"):
        shared_service.cryptographic_erase(ACCESS, shared.object_id, approved, now=NOW)
    with pytest.raises(LifecycleError, match="object-unique") as key_error:
        shared_service.cryptographic_erase(
            ACCESS, shared.object_id, approved, now=NOW + timedelta(days=2)
        )
    assert key_error.value.code == "LIFECYCLE_OBJECT_KEY_REQUIRED"

    failing, _, _ = runtime(fail_revoke=True)
    item = register(failing, encrypted=True)
    item_approval = approval(
        action="data.erase",
        target_type=item.object_type,
        target_id=item.object_id,
        target_version=item.object_version,
        target_sha256=item.content_sha256,
    )
    with pytest.raises(LifecycleError, match="could not be revoked") as unavailable:
        failing.cryptographic_erase(
            ACCESS, item.object_id, item_approval, now=NOW + timedelta(days=2)
        )
    assert unavailable.value.code == "LIFECYCLE_KEY_REVOCATION_FAILED"


def test_permissions_fail_closed_before_state_change() -> None:
    service, repository, _ = runtime()
    denied = ACCESS.model_copy(update={"permissions": ()})
    with pytest.raises(LifecycleError, match="not authorized") as error:
        service.register(
            denied,
            object_id=UUID("00000000-0000-4000-8000-000000000001"),
            object_type="memory",
            object_version="1",
            classification=DataClassification.INTERNAL,
            content={"value": "no"},
            created_at=NOW,
        )
    assert error.value.code == "LIFECYCLE_PERMISSION_DENIED"
    assert repository.objects == {}
