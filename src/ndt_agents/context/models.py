"""Strict internal models for deterministic V1 context assembly."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ndt_agents.contracts.v1 import (
    ArtifactRef,
    BudgetPolicy,
    DataClassification,
    RiskLevel,
    TaskContext,
    TenantScope,
)


class ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ContextSourceType(StrEnum):
    SYSTEM_INSTRUCTION = "SYSTEM_INSTRUCTION"
    USER_INSTRUCTION = "USER_INSTRUCTION"
    PROJECT_FACT = "PROJECT_FACT"
    RETRIEVAL = "RETRIEVAL"
    MEMORY = "MEMORY"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    AGENT_OUTPUT = "AGENT_OUTPUT"


class ContextTrustLevel(StrEnum):
    TRUSTED_POLICY = "TRUSTED_POLICY"
    VERIFIED_INTERNAL = "VERIFIED_INTERNAL"
    USER_PROVIDED = "USER_PROVIDED"
    UNTRUSTED_EXTERNAL = "UNTRUSTED_EXTERNAL"


class ContextVisibility(StrEnum):
    USER = "USER"
    PROJECT = "PROJECT"


class ContextSelectionReason(StrEnum):
    SELECTED = "SELECTED"
    DEDUPLICATED = "DEDUPLICATED"
    TENANT_DENIED = "TENANT_DENIED"
    PROJECT_DENIED = "PROJECT_DENIED"
    USER_DENIED = "USER_DENIED"
    PERMISSION_VERSION_STALE = "PERMISSION_VERSION_STALE"
    ROLE_DENIED = "ROLE_DENIED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CLASSIFICATION_DENIED = "CLASSIFICATION_DENIED"
    IRRELEVANT = "IRRELEVANT"
    BUDGET_EXCLUDED = "BUDGET_EXCLUDED"
    LIMIT_EXCLUDED = "LIMIT_EXCLUDED"
    NOT_REQUESTED = "NOT_REQUESTED"
    UNREGISTERED = "UNREGISTERED"


class ContextAssemblyPolicy(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: str = Field(min_length=1, max_length=128)
    minimum_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    max_selected_items: int = Field(default=100, ge=1, le=500)
    max_selected_content_bytes: int = Field(default=65536, ge=1, le=2_000_000)
    max_candidate_content_bytes: int = Field(default=8_000_000, ge=1, le=16_000_000)
    max_artifacts: int = Field(default=20, ge=0, le=100)


class ContextItemCandidate(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    item_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._:-]+$")
    scope: TenantScope
    visibility: ContextVisibility
    source_type: ContextSourceType
    source_ref: str = Field(min_length=1, max_length=2048)
    source_version: str = Field(min_length=1, max_length=128)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trust_level: ContextTrustLevel
    classification: DataClassification
    content: dict[str, JsonValue]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_roles: tuple[str, ...] = Field(default=(), max_length=32)
    required_permissions: tuple[str, ...] = Field(default=(), max_length=64)
    relevance_score: float = Field(ge=0.0, le=1.0)
    protected: bool = False
    observed_at: datetime

    @model_validator(mode="after")
    def validate_access_lists(self) -> Self:
        _validate_unique_strings(self.required_roles, "required roles")
        _validate_unique_strings(self.required_permissions, "required permissions")
        _validate_aware_datetime(self.observed_at, "observed_at")
        return self


class ArtifactCandidate(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    artifact: ArtifactRef
    visibility: ContextVisibility
    required_roles: tuple[str, ...] = Field(default=(), max_length=32)
    required_permissions: tuple[str, ...] = Field(default=(), max_length=64)
    relevance_score: float = Field(ge=0.0, le=1.0)
    protected: bool = False

    @model_validator(mode="after")
    def validate_access_lists(self) -> Self:
        _validate_unique_strings(self.required_roles, "required roles")
        _validate_unique_strings(self.required_permissions, "required permissions")
        return self


class ToolAuthorization(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    tool_name: str = Field(min_length=1, max_length=128)
    scope: TenantScope
    visibility: ContextVisibility = ContextVisibility.PROJECT
    required_roles: tuple[str, ...] = Field(default=(), max_length=32)
    required_permissions: tuple[str, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def validate_access_lists(self) -> Self:
        _validate_unique_strings(self.required_roles, "required roles")
        _validate_unique_strings(self.required_permissions, "required permissions")
        return self


class TaskContextAssemblyRequest(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    scope: TenantScope
    task_class: Literal["G0", "P1", "P2", "P3", "K1"]
    goal: str = Field(min_length=1, max_length=8000)
    success_criteria: tuple[str, ...] = Field(min_length=1, max_length=20)
    risk_level: RiskLevel
    candidates: tuple[ContextItemCandidate, ...] = Field(default=(), max_length=500)
    artifact_candidates: tuple[ArtifactCandidate, ...] = Field(default=(), max_length=100)
    requested_tools: tuple[str, ...] = Field(default=(), max_length=12)
    tool_authorizations: tuple[ToolAuthorization, ...] = Field(default=(), max_length=24)
    granted_permissions: tuple[str, ...] = Field(default=(), max_length=256)
    clearance: DataClassification
    policy: ContextAssemblyPolicy
    skill_versions: dict[str, str]
    prompt_versions: dict[str, str]
    model_versions: dict[str, str]
    knowledge_versions: tuple[str, ...]
    budget: BudgetPolicy
    output_schema_id: str = Field(min_length=1, max_length=512)
    review_checklist: tuple[str, ...]
    created_at: datetime

    @model_validator(mode="after")
    def validate_unique_identifiers(self) -> Self:
        _validate_unique_strings(self.requested_tools, "requested tools")
        _validate_unique_strings(self.granted_permissions, "granted permissions")
        _validate_unique_strings(
            tuple(candidate.item_id for candidate in self.candidates), "context item IDs"
        )
        _validate_unique_strings(
            tuple(str(candidate.artifact.artifact_id) for candidate in self.artifact_candidates),
            "artifact candidate IDs",
        )
        _validate_unique_strings(
            tuple(item.tool_name for item in self.tool_authorizations), "tool authorizations"
        )
        _validate_aware_datetime(self.created_at, "created_at")
        return self


class ContextSourceLabel(ContextModel):
    item_id: str = Field(min_length=1, max_length=128)
    source_type: ContextSourceType
    source_ref: str = Field(min_length=1, max_length=2048)
    source_version: str = Field(min_length=1, max_length=128)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trust_level: ContextTrustLevel
    observed_at: datetime

    @model_validator(mode="after")
    def validate_observed_at(self) -> Self:
        _validate_aware_datetime(self.observed_at, "observed_at")
        return self


class SelectedContextEntry(ContextModel):
    content: dict[str, JsonValue]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: DataClassification
    relevance_score: float
    protected: bool
    content_size_bytes: int = Field(ge=0)
    sources: tuple[ContextSourceLabel, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_content_integrity(self) -> Self:
        encoded = _canonical_json_bytes(self.content)
        if hashlib.sha256(encoded).hexdigest() != self.content_sha256:
            raise ValueError("selected context content hash does not match content")
        if len(encoded) != self.content_size_bytes:
            raise ValueError("selected context content size does not match content")
        _validate_unique_strings(
            tuple(source.item_id for source in self.sources), "selected source item IDs"
        )
        return self


class ContextBundle(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: str = Field(min_length=1, max_length=128)
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_content_bytes: int = Field(ge=0)
    entries: tuple[SelectedContextEntry, ...]

    @model_validator(mode="after")
    def validate_entries(self) -> Self:
        if self.selected_content_bytes != sum(entry.content_size_bytes for entry in self.entries):
            raise ValueError("selected context byte total does not match entries")
        _validate_unique_strings(
            tuple(entry.content_sha256 for entry in self.entries), "selected content hashes"
        )
        return self


class ContextDecision(ContextModel):
    candidate_kind: Literal["ITEM", "ARTIFACT", "TOOL"]
    candidate_id: str
    reason: ContextSelectionReason


class TaskContextAssemblyResult(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: TaskContext
    policy_version: str
    selected_content_bytes: int = Field(ge=0)
    decisions: tuple[ContextDecision, ...]


def _validate_unique_strings(values: tuple[str, ...], label: str) -> None:
    if any(not value or len(value) > 256 for value in values):
        raise ValueError(f"{label} contain an invalid value")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


def _validate_aware_datetime(value: datetime, label: str) -> None:
    if value.utcoffset() is None:
        raise ValueError(f"{label} must include an explicit UTC offset")


def _canonical_json_bytes(value: JsonValue) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
