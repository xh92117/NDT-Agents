"""S2-04 INT-MEMORY scoped store tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import JsonValue, ValidationError

from ndt_agents.contracts.v1 import DataClassification, MemoryScope, TenantScope
from ndt_agents.memory import (
    InMemoryMemoryRepository,
    MemoryAccess,
    MemoryApprovalState,
    MemoryError,
    MemoryQuery,
    MemoryStore,
    ScopedMemoryRecord,
    memory_content_sha256,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("ENGINEER",),
    permission_version="perm-1",
)
OTHER_USER = SCOPE.model_copy(update={"user_id": UUID("00000000-0000-4000-8000-000000000104")})
OTHER_PROJECT = SCOPE.model_copy(
    update={"project_id": UUID("00000000-0000-4000-8000-000000000202")}
)


def permissions(*scopes: MemoryScope) -> tuple[str, ...]:
    values = [
        f"memory:{scope.value.lower()}:{action}" for scope in scopes for action in ("read", "write")
    ]
    return (*values, "memory:candidate:read")


def access(scope: TenantScope = SCOPE, *memory_scopes: MemoryScope) -> MemoryAccess:
    selected = memory_scopes or tuple(MemoryScope)
    return MemoryAccess(
        scope=scope,
        permissions=permissions(*selected),
        clearance=DataClassification.RESTRICTED,
    )


def record(
    index: int,
    memory_scope: MemoryScope,
    *,
    scope: TenantScope = SCOPE,
    state: MemoryApprovalState = MemoryApprovalState.APPROVED,
    expires_at: datetime | None = None,
    classification: DataClassification = DataClassification.INTERNAL,
) -> ScopedMemoryRecord:
    content: dict[str, JsonValue] = {"fact": f"memory-{index}"}
    return ScopedMemoryRecord(
        memory_id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
        scope=scope,
        memory_scope=memory_scope,
        namespace_id="task-1" if memory_scope is MemoryScope.RUNTIME else "session-1",
        content=content,
        content_sha256=memory_content_sha256(content),
        provenance_ids=(UUID(f"10000000-0000-4000-8000-{index:012d}"),),
        confidence=0.9,
        classification=classification,
        approval_state=state,
        protected=memory_scope is MemoryScope.AUDIT,
        source_version="source-1",
        expires_at=expires_at,
        created_at=NOW,
    )


def query(
    memory_scope: MemoryScope,
    *,
    query_access: MemoryAccess | None = None,
    include_candidates: bool = False,
) -> MemoryQuery:
    return MemoryQuery(
        access=query_access or access(),
        memory_scope=memory_scope,
        namespace_id="task-1" if memory_scope is MemoryScope.RUNTIME else "session-1",
        include_candidates=include_candidates,
        now=NOW + timedelta(minutes=1),
    )


def test_all_five_memory_scopes_remain_distinct() -> None:
    async def scenario() -> None:
        store = MemoryStore(InMemoryMemoryRepository())
        for index, memory_scope in enumerate(MemoryScope, start=1):
            await store.put(access(), record(index, memory_scope))
        for memory_scope in MemoryScope:
            selected = await store.query(query(memory_scope))
            assert len(selected) == 1
            assert selected[0].memory_scope is memory_scope

    asyncio.run(scenario())


def test_user_scopes_deny_other_user_but_project_scope_can_be_shared() -> None:
    async def scenario() -> None:
        store = MemoryStore(InMemoryMemoryRepository())
        await store.put(access(), record(1, MemoryScope.USER))
        await store.put(access(), record(2, MemoryScope.PROJECT))

        assert await store.query(query(MemoryScope.USER, query_access=access(OTHER_USER))) == ()
        shared = await store.query(query(MemoryScope.PROJECT, query_access=access(OTHER_USER)))
        assert tuple(item.memory_id for item in shared) == (
            record(2, MemoryScope.PROJECT).memory_id,
        )

    asyncio.run(scenario())


def test_cross_project_and_stale_permission_version_are_denied() -> None:
    async def scenario() -> None:
        store = MemoryStore(InMemoryMemoryRepository())
        item = record(1, MemoryScope.PROJECT)
        await store.put(access(), item)
        with pytest.raises(MemoryError, match="outside") as denied:
            await store.get(access(OTHER_PROJECT), item.memory_id, now=NOW)
        assert denied.value.code == "MEMORY_SCOPE_DENIED"
        stale = SCOPE.model_copy(update={"permission_version": "stale"})
        assert await store.query(query(MemoryScope.PROJECT, query_access=access(stale))) == ()

    asyncio.run(scenario())


def test_permissions_and_classification_fail_closed() -> None:
    async def scenario() -> None:
        store = MemoryStore(InMemoryMemoryRepository())
        denied = MemoryAccess(
            scope=SCOPE,
            permissions=(),
            clearance=DataClassification.PUBLIC,
        )
        with pytest.raises(MemoryError, match="not authorized"):
            await store.put(denied, record(1, MemoryScope.USER))
        low_clearance = MemoryAccess(
            scope=SCOPE,
            permissions=permissions(MemoryScope.USER),
            clearance=DataClassification.PUBLIC,
        )
        with pytest.raises(MemoryError, match="clearance"):
            await store.put(
                low_clearance,
                record(2, MemoryScope.USER, classification=DataClassification.CONFIDENTIAL),
            )

    asyncio.run(scenario())


def test_candidates_require_explicit_query_and_expired_records_are_hidden() -> None:
    async def scenario() -> None:
        store = MemoryStore(InMemoryMemoryRepository())
        candidate = record(1, MemoryScope.PROJECT, state=MemoryApprovalState.CANDIDATE)
        expired = record(2, MemoryScope.PROJECT, expires_at=NOW + timedelta(seconds=1))
        await store.put(access(), candidate)
        await store.put(access(), expired)

        assert await store.query(query(MemoryScope.PROJECT)) == ()
        selected = await store.query(query(MemoryScope.PROJECT, include_candidates=True))
        assert tuple(item.memory_id for item in selected) == (candidate.memory_id,)

    asyncio.run(scenario())


def test_memory_ids_are_immutable_and_content_hash_is_verified() -> None:
    async def scenario() -> None:
        repository = InMemoryMemoryRepository()
        store = MemoryStore(repository)
        item = record(1, MemoryScope.USER)
        await store.put(access(), item)
        with pytest.raises(MemoryError, match="already exists") as conflict:
            await store.put(access(), item)
        assert conflict.value.code == "MEMORY_IMMUTABLE_CONFLICT"

    asyncio.run(scenario())
    payload = record(2, MemoryScope.USER).model_dump()
    payload["content"] = {"tampered": True}
    with pytest.raises(ValidationError, match="hash does not match"):
        ScopedMemoryRecord.model_validate(payload)


def test_audit_memory_must_be_approved_and_is_protected() -> None:
    item = record(1, MemoryScope.AUDIT)
    assert item.protected is True
    payload = item.model_dump()
    payload["approval_state"] = MemoryApprovalState.CANDIDATE
    with pytest.raises(ValidationError, match="audit memory must be approved"):
        ScopedMemoryRecord.model_validate(payload)
