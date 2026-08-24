"""Strict contracts for provider-neutral C0-C3 context compression."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from ndt_agents.context.models import ContextModel, _canonical_json_bytes
from ndt_agents.contracts.v1 import ArtifactRef, Checkpoint, TenantScope


class CompressionLevel(StrEnum):
    C0 = "C0"
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"


class ContextEventKind(StrEnum):
    SYSTEM_INSTRUCTION = "SYSTEM_INSTRUCTION"
    USER_TURN = "USER_TURN"
    ASSISTANT_TURN = "ASSISTANT_TURN"
    PROJECT_FACT = "PROJECT_FACT"
    RETRIEVAL = "RETRIEVAL"
    TOOL_LOG = "TOOL_LOG"
    DECISION = "DECISION"
    OPEN_ISSUE = "OPEN_ISSUE"


class CompressionItemKind(StrEnum):
    RAW_EVENT = "RAW_EVENT"
    ARTIFACT_REFERENCE = "ARTIFACT_REFERENCE"
    SEMANTIC_SUMMARY = "SEMANTIC_SUMMARY"


class CompressionValidationState(StrEnum):
    READY = "READY"
    REQUIRED = "REQUIRED"


class ContextCompressionPolicy(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: str = Field(min_length=1, max_length=128)
    c1_threshold: float = Field(default=0.4, gt=0.0, lt=1.0)
    c2_threshold: float = Field(default=0.6, gt=0.0, lt=1.0)
    c3_threshold: float = Field(default=0.8, gt=0.0, lt=1.0)
    recent_turn_count: int = Field(default=6, ge=1, le=20)
    c2_summary_token_limit: int = Field(default=800, ge=1, le=800)
    c3_digest_token_limit: int = Field(default=1200, ge=1, le=1200)
    max_semantic_compressions: int = Field(default=2, ge=1, le=2)

    @model_validator(mode="after")
    def validate_thresholds(self) -> Self:
        if not self.c1_threshold < self.c2_threshold < self.c3_threshold:
            raise ValueError("compression thresholds must be strictly increasing")
        return self


class RawContextEvent(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._:-]+$")
    task_id: UUID
    scope: TenantScope
    sequence: int = Field(ge=0)
    kind: ContextEventKind
    is_semantic_summary: Literal[False] = False
    content: dict[str, JsonValue]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    token_estimate: int = Field(ge=1, le=2_000_000)
    protected: bool = False
    recoverable_artifact: ArtifactRef | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        actual = hashlib.sha256(_canonical_json_bytes(self.content)).hexdigest()
        if actual != self.content_sha256:
            raise ValueError("raw context event content hash does not match content")
        if self.recoverable_artifact is not None and (
            self.recoverable_artifact.scope.model_dump(mode="json")
            != self.scope.model_dump(mode="json")
        ):
            raise ValueError("recoverable artifact must use the exact raw event scope")
        if self.created_at.utcoffset() is None:
            raise ValueError("created_at must include an explicit UTC offset")
        return self


class ContextCompressionRequest(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    scope: TenantScope
    raw_events: tuple[RawContextEvent, ...] = Field(min_length=1, max_length=1000)
    active_context_tokens: int = Field(ge=1, le=10_000_000)
    active_context_limit: int = Field(ge=1, le=10_000_000)
    semantic_compressions_used: int = Field(default=0, ge=0, le=2)
    checkpoint: Checkpoint | None = None
    policy: ContextCompressionPolicy

    @model_validator(mode="after")
    def validate_events(self) -> Self:
        event_ids = tuple(event.event_id for event in self.raw_events)
        sequences = tuple(event.sequence for event in self.raw_events)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("raw context event IDs must be unique")
        if len(sequences) != len(set(sequences)):
            raise ValueError("raw context event sequences must be unique")
        if sequences != tuple(sorted(sequences)):
            raise ValueError("raw context events must be ordered by sequence")
        return self


class SemanticCompressionRequest(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    scope: TenantScope
    level: Literal[CompressionLevel.C2, CompressionLevel.C3]
    source_events: tuple[RawContextEvent, ...] = Field(min_length=1)
    max_output_tokens: int = Field(ge=1, le=1200)
    policy_version: str = Field(min_length=1, max_length=128)


class SemanticCompressionResult(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    content: dict[str, JsonValue] = Field(min_length=1)
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    output_tokens: int = Field(ge=1, le=1200)
    provider_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)


class SemanticCompressor(Protocol):
    async def summarize(self, request: SemanticCompressionRequest) -> SemanticCompressionResult: ...


class CompressedContextItem(ContextModel):
    kind: CompressionItemKind
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    content: dict[str, JsonValue]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    token_estimate: int = Field(ge=1, le=2_000_000)
    protected: bool

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        actual = hashlib.sha256(_canonical_json_bytes(self.content)).hexdigest()
        if actual != self.content_sha256:
            raise ValueError("compressed context item hash does not match content")
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("compressed context source event IDs must be unique")
        return self


class ContextCompressionResult(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    scope: TenantScope
    level: CompressionLevel
    policy_version: str
    raw_events_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: tuple[CompressedContextItem, ...] = Field(min_length=1)
    input_tokens: int = Field(ge=1)
    output_tokens: int = Field(ge=1)
    token_reduction_ratio: float = Field(ge=0.0, le=1.0)
    semantic_compressions_used: int = Field(ge=0, le=2)
    checkpoint_id: UUID | None = None
    validation_state: CompressionValidationState
    validation_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    execution_ready: bool

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        expected_ready = self.validation_state is CompressionValidationState.READY
        if self.execution_ready != expected_ready:
            raise ValueError("execution readiness must match compression validation state")
        if (
            self.level in {CompressionLevel.C2, CompressionLevel.C3}
            and self.execution_ready
            and self.validation_report_sha256 is None
        ):
            raise ValueError("semantic compression requires an S2-03 validation proof")
        if not self.execution_ready and self.validation_report_sha256 is not None:
            raise ValueError("an unready compression result cannot carry a validation proof")
        if self.level is CompressionLevel.C3 and self.checkpoint_id is None:
            raise ValueError("C3 compression requires a durable checkpoint")
        return self
