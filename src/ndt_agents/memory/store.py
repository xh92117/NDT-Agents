"""Default-deny scoped memory service with an in-memory repository adapter."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ndt_agents.contracts.v1 import DataClassification, MemoryScope, TenantScope
from ndt_agents.memory.models import (
    MemoryAccess,
    MemoryApprovalState,
    MemoryQuery,
    ScopedMemoryRecord,
)

_CLASSIFICATION = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class MemoryError(RuntimeError):
    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class MemoryRepository(Protocol):
    async def insert(self, record: ScopedMemoryRecord) -> None: ...

    async def get(self, memory_id: UUID) -> ScopedMemoryRecord | None: ...

    async def scan(self) -> tuple[ScopedMemoryRecord, ...]: ...


class InMemoryMemoryRepository:
    def __init__(self) -> None:
        self._records: dict[UUID, ScopedMemoryRecord] = {}
        self._lock = asyncio.Lock()

    async def insert(self, record: ScopedMemoryRecord) -> None:
        async with self._lock:
            if record.memory_id in self._records:
                raise MemoryError(
                    code="MEMORY_IMMUTABLE_CONFLICT",
                    message="The immutable memory ID already exists.",
                    next_action="Use the existing record or create a new memory version.",
                )
            self._records[record.memory_id] = record

    async def get(self, memory_id: UUID) -> ScopedMemoryRecord | None:
        async with self._lock:
            return self._records.get(memory_id)

    async def scan(self) -> tuple[ScopedMemoryRecord, ...]:
        async with self._lock:
            return tuple(self._records.values())


class MemoryStore:
    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    async def put(self, access: MemoryAccess, record: ScopedMemoryRecord) -> None:
        _authorize(access, record.memory_scope, "write")
        if not _record_visible(access.scope, record.scope, record.memory_scope):
            raise _scope_denied()
        if _CLASSIFICATION[record.classification] > _CLASSIFICATION[access.clearance]:
            raise MemoryError(
                code="MEMORY_CLASSIFICATION_DENIED",
                message="The memory classification exceeds the active clearance.",
                next_action="Use an authorized actor with sufficient clearance.",
            )
        await self._repository.insert(record)

    async def get(
        self, access: MemoryAccess, memory_id: UUID, *, now: datetime
    ) -> ScopedMemoryRecord | None:
        record = await self._repository.get(memory_id)
        if record is None:
            return None
        _authorize(access, record.memory_scope, "read")
        if not _record_visible(access.scope, record.scope, record.memory_scope):
            raise _scope_denied()
        query = MemoryQuery(
            access=access,
            memory_scope=record.memory_scope,
            namespace_id=record.namespace_id,
            include_candidates=True,
            now=now,
            limit=1,
        )
        return record if _included(record, query) else None

    async def query(self, query: MemoryQuery) -> tuple[ScopedMemoryRecord, ...]:
        _authorize(query.access, query.memory_scope, "read")
        if query.include_candidates and "memory:candidate:read" not in query.access.permissions:
            raise MemoryError(
                code="MEMORY_CANDIDATE_DENIED",
                message="Candidate memory access is not authorized.",
                next_action="Request the memory:candidate:read permission.",
            )
        selected = (
            record
            for record in await self._repository.scan()
            if record.memory_scope is query.memory_scope
            and record.namespace_id == query.namespace_id
            and _record_visible(query.access.scope, record.scope, record.memory_scope)
            and _CLASSIFICATION[record.classification] <= _CLASSIFICATION[query.access.clearance]
            and _included(record, query)
        )
        return tuple(
            sorted(selected, key=lambda item: (item.created_at, str(item.memory_id)))[: query.limit]
        )


def _authorize(access: MemoryAccess, memory_scope: MemoryScope, action: str) -> None:
    permission = f"memory:{memory_scope.value.lower()}:{action}"
    if permission not in access.permissions:
        raise MemoryError(
            code="MEMORY_PERMISSION_DENIED",
            message="The requested memory operation is not authorized.",
            next_action=f"Request the {permission} permission for the active scope.",
        )


def _record_visible(active: TenantScope, stored: TenantScope, memory_scope: MemoryScope) -> bool:
    same_project = (
        active.tenant_id == stored.tenant_id
        and active.project_id == stored.project_id
        and active.permission_version == stored.permission_version
    )
    if not same_project:
        return False
    if memory_scope in {MemoryScope.PROJECT, MemoryScope.AUDIT}:
        return True
    return active.user_id == stored.user_id


def _included(record: ScopedMemoryRecord, query: MemoryQuery) -> bool:
    if record.expires_at is not None and record.expires_at <= query.now:
        return False
    if record.approval_state in {MemoryApprovalState.REJECTED, MemoryApprovalState.EXPIRED}:
        return False
    if record.approval_state is MemoryApprovalState.CANDIDATE and not query.include_candidates:
        return False
    return True


def _scope_denied() -> MemoryError:
    return MemoryError(
        code="MEMORY_SCOPE_DENIED",
        message="The memory record is outside the active scope.",
        next_action=(
            "Use memory authorized for the exact tenant, project, user, and permission version."
        ),
    )
