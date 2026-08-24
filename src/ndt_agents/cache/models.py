"""Strict shared cache contracts."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ndt_agents.context.assembly import canonical_json_bytes
from ndt_agents.contracts.v1 import TenantScope


class CacheModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class CacheClass(StrEnum):
    EXACT = "EXACT"
    RETRIEVAL = "RETRIEVAL"
    TOOL = "TOOL"
    PARSE = "PARSE"
    SEMANTIC = "SEMANTIC"


class CacheValidationState(StrEnum):
    VALID = "VALID"
    STALE = "STALE"
    REJECTED = "REJECTED"


class CacheSideEffect(StrEnum):
    PURE = "PURE"
    READ = "READ"
    WRITE = "WRITE"


class CachePolicy(CacheModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: str = Field(min_length=1, max_length=128)
    exact_ttl_seconds: int = Field(default=86400, ge=1, le=86400)
    retrieval_ttl_seconds: int = Field(default=21600, ge=1, le=21600)
    tool_ttl_seconds: int = Field(default=2592000, ge=1, le=2592000)
    parse_ttl_seconds: int = Field(default=7776000, ge=1, le=7776000)
    semantic_ttl_seconds: int = Field(default=3600, ge=1, le=3600)
    semantic_minimum_similarity: float = Field(default=0.95, ge=0.95, le=1.0)


class CachePutRequest(CacheModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    cache_entry_id: UUID
    scope: TenantScope
    cache_class: CacheClass
    cache_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    value: dict[str, JsonValue]
    value_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_manifest: dict[str, str] = Field(min_length=1, max_length=64)
    provenance: dict[str, str] = Field(min_length=1, max_length=64)
    contains_secret: bool = False
    contains_authorization_decision: bool = False
    stable: bool = True
    side_effect: CacheSideEffect = CacheSideEffect.PURE
    task_class: Literal["G0", "P1", "P2", "P3", "K1"]
    semantic_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    saved_tokens: int = Field(default=0, ge=0)
    refresh: bool = False
    created_at: datetime

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        if hashlib.sha256(canonical_json_bytes(self.value)).hexdigest() != self.value_sha256:
            raise ValueError("cache value hash does not match value")
        if self.created_at.utcoffset() is None:
            raise ValueError("cache creation time must include an explicit UTC offset")
        return self


class CacheGetRequest(CacheModel):
    scope: TenantScope
    cache_class: CacheClass
    cache_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_version_manifest: dict[str, str] = Field(min_length=1, max_length=64)
    current_information_required: bool = False
    now: datetime

    @model_validator(mode="after")
    def validate_now(self) -> Self:
        if self.now.utcoffset() is None:
            raise ValueError("cache lookup time must include an explicit UTC offset")
        return self


class CacheRecord(CacheModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    cache_entry_id: UUID
    scope: TenantScope
    cache_class: CacheClass
    cache_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    value: dict[str, JsonValue]
    value_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_manifest: dict[str, str]
    provenance: dict[str, str]
    validation_state: CacheValidationState
    saved_tokens: int = Field(ge=0)
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if hashlib.sha256(canonical_json_bytes(self.value)).hexdigest() != self.value_sha256:
            raise ValueError("stored cache value hash does not match value")
        if self.expires_at <= self.created_at:
            raise ValueError("cache expiry must be after creation")
        return self


class CacheMetrics(CacheModel):
    hits: int = Field(ge=0)
    misses: int = Field(ge=0)
    stale_rejections: int = Field(ge=0)
    bypasses: int = Field(ge=0)
    saved_tokens: int = Field(ge=0)


def cache_value_sha256(value: dict[str, JsonValue]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
