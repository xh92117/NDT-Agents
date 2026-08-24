"""Immutable tenant-scoped artifact service over an object-storage port."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ndt_agents.contracts.v1 import ArtifactRef, DataClassification, TenantScope
from ndt_agents.storage.errors import StorageError

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


@dataclass(frozen=True, slots=True)
class StoredObject:
    content: bytes
    metadata: Mapping[str, str]


class ObjectBackend(Protocol):
    async def put_if_absent(
        self, key: str, content: bytes, metadata: Mapping[str, str]
    ) -> bool: ...

    async def get(self, key: str) -> StoredObject | None: ...


class InMemoryObjectBackend:
    """Deterministic object backend for local integration tests."""

    def __init__(self) -> None:
        self._objects: dict[str, StoredObject] = {}
        self._lock = asyncio.Lock()

    async def put_if_absent(self, key: str, content: bytes, metadata: Mapping[str, str]) -> bool:
        async with self._lock:
            if key in self._objects:
                return False
            self._objects[key] = StoredObject(content=content, metadata=dict(metadata))
            return True

    async def get(self, key: str) -> StoredObject | None:
        async with self._lock:
            return self._objects.get(key)

    def corrupt(self, key: str, content: bytes) -> None:
        stored = self._objects[key]
        self._objects[key] = StoredObject(content=content, metadata=stored.metadata)


class ArtifactStorageService:
    """Validate identity, scope, and integrity around an object-storage backend."""

    def __init__(self, *, backend: ObjectBackend, bucket: str) -> None:
        if not _BUCKET.fullmatch(bucket):
            raise StorageError(
                code="ARTIFACT_BUCKET_INVALID",
                message="The artifact bucket name is invalid.",
                retryable=False,
                next_action="Configure an approved S3-compatible bucket name.",
            )
        self._backend = backend
        self._bucket = bucket

    def _object_key(self, scope: TenantScope, artifact_id: UUID, artifact_version: str) -> str:
        if not _SAFE_SEGMENT.fullmatch(artifact_version):
            raise StorageError(
                code="ARTIFACT_VERSION_INVALID",
                message="The artifact version is invalid.",
                retryable=False,
                next_action="Use a bounded immutable artifact version.",
            )
        return (
            f"tenants/{scope.tenant_id}/projects/{scope.project_id}/"
            f"artifacts/{artifact_id}/versions/{artifact_version}"
        )

    async def put(
        self,
        *,
        scope: TenantScope,
        artifact_id: UUID,
        artifact_version: str,
        content: bytes,
        media_type: str,
        classification: DataClassification,
    ) -> ArtifactRef:
        key = self._object_key(scope, artifact_id, artifact_version)
        digest = hashlib.sha256(content).hexdigest()
        metadata = {
            "sha256": digest,
            "tenant_id": str(scope.tenant_id),
            "project_id": str(scope.project_id),
            "artifact_id": str(artifact_id),
            "artifact_version": artifact_version,
            "classification": classification.value,
        }
        if not await self._backend.put_if_absent(key, content, metadata):
            raise StorageError(
                code="ARTIFACT_ALREADY_EXISTS",
                message="The immutable artifact version already exists.",
                retryable=False,
                next_action="Use the existing artifact or create a new version.",
            )
        return ArtifactRef(
            artifact_id=artifact_id,
            scope=scope,
            artifact_version=artifact_version,
            uri=f"artifact://{self._bucket}/{key}",
            media_type=media_type,
            size_bytes=len(content),
            sha256=digest,
            classification=classification,
            immutable=True,
        )

    async def get(self, scope: TenantScope, artifact: ArtifactRef) -> bytes:
        if (
            artifact.scope.tenant_id != scope.tenant_id
            or artifact.scope.project_id != scope.project_id
        ):
            raise StorageError(
                code="ARTIFACT_SCOPE_DENIED",
                message="The artifact is outside the active scope.",
                retryable=False,
                next_action="Use an artifact authorized for the active tenant and project.",
            )
        key = self._object_key(scope, artifact.artifact_id, artifact.artifact_version)
        expected_uri = f"artifact://{self._bucket}/{key}"
        if artifact.uri != expected_uri:
            raise StorageError(
                code="ARTIFACT_URI_INVALID",
                message="The artifact URI does not belong to this store.",
                retryable=False,
                next_action="Use a reference created by the active artifact service.",
            )
        stored = await self._backend.get(key)
        if stored is None:
            raise StorageError(
                code="ARTIFACT_NOT_FOUND",
                message="The artifact object is missing.",
                retryable=False,
                next_action="Restore the object from approved evidence or select another artifact.",
            )
        digest = hashlib.sha256(stored.content).hexdigest()
        expected_metadata = {
            "sha256": artifact.sha256,
            "tenant_id": str(scope.tenant_id),
            "project_id": str(scope.project_id),
            "artifact_id": str(artifact.artifact_id),
            "artifact_version": artifact.artifact_version,
            "classification": artifact.classification.value,
        }
        if (
            digest != artifact.sha256
            or len(stored.content) != artifact.size_bytes
            or any(stored.metadata.get(key) != value for key, value in expected_metadata.items())
        ):
            raise StorageError(
                code="ARTIFACT_INTEGRITY_FAILED",
                message="The artifact failed integrity validation.",
                retryable=False,
                next_action="Quarantine the object and restore verified evidence.",
            )
        return stored.content
