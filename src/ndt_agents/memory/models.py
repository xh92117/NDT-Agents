"""Strict scoped memory contracts."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ndt_agents.context.assembly import canonical_json_bytes
from ndt_agents.contracts.v1 import DataClassification, MemoryScope, TenantScope


class MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class MemoryApprovalState(StrEnum):
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ScopedMemoryRecord(MemoryModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    memory_id: UUID
    scope: TenantScope
    memory_scope: MemoryScope
    namespace_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    content: dict[str, JsonValue]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)
    classification: DataClassification
    approval_state: MemoryApprovalState
    protected: bool = False
    source_version: str = Field(min_length=1, max_length=128)
    expires_at: datetime | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if hashlib.sha256(canonical_json_bytes(self.content)).hexdigest() != self.content_sha256:
            raise ValueError("memory content hash does not match content")
        if len(self.provenance_ids) != len(set(self.provenance_ids)):
            raise ValueError("memory provenance IDs must be unique")
        if self.created_at.utcoffset() is None:
            raise ValueError("created_at must include an explicit UTC offset")
        if self.expires_at is not None:
            if self.expires_at.utcoffset() is None:
                raise ValueError("expires_at must include an explicit UTC offset")
            if self.expires_at <= self.created_at:
                raise ValueError("memory expiry must be after creation")
        if (
            self.memory_scope is MemoryScope.AUDIT
            and self.approval_state is not MemoryApprovalState.APPROVED
        ):
            raise ValueError("audit memory must be approved at creation")
        return self


class MemoryAccess(MemoryModel):
    scope: TenantScope
    permissions: tuple[str, ...] = Field(max_length=64)
    clearance: DataClassification

    @model_validator(mode="after")
    def validate_permissions(self) -> Self:
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("memory permissions must be unique")
        return self


class MemoryQuery(MemoryModel):
    access: MemoryAccess
    memory_scope: MemoryScope
    namespace_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    include_candidates: bool = False
    limit: int = Field(default=100, ge=1, le=500)
    now: datetime

    @model_validator(mode="after")
    def validate_now(self) -> Self:
        if self.now.utcoffset() is None:
            raise ValueError("memory query time must include an explicit UTC offset")
        return self


def memory_content_sha256(content: dict[str, JsonValue]) -> str:
    return hashlib.sha256(canonical_json_bytes(content)).hexdigest()
