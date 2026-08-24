"""Public V1 contracts for agent, tool, artifact, and state boundaries."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
Sha256 = str


class StrictModel(BaseModel):
    """Reject unknown fields and treat boundary payloads as immutable values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AgentStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    NEEDS_USER = "NEEDS_USER"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ToolStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    DENIED = "DENIED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class ReviewDecision(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    CONFLICT = "CONFLICT"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    FAILED = "FAILED"


class ApprovalOutcome(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class DataClassification(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class MemoryScope(StrEnum):
    RUNTIME = "RUNTIME"
    SESSION = "SESSION"
    USER = "USER"
    PROJECT = "PROJECT"
    AUDIT = "AUDIT"


class TenantScope(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    tenant_id: UUID
    project_id: UUID
    user_id: UUID
    role_codes: tuple[str, ...] = Field(min_length=1)
    permission_version: str = Field(min_length=1, max_length=128)


class Limit(StrictModel):
    default: int = Field(ge=0)
    active: int = Field(ge=0)
    hard: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> Limit:
        if not self.default <= self.active <= self.hard:
            raise ValueError("limit order must satisfy default <= active <= hard")
        return self


class BudgetPolicy(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    policy_id: str = Field(min_length=1, max_length=128)
    task_class: Literal["G0", "P1", "P2", "P3", "K1"]
    graph_steps: Limit
    llm_calls: Limit
    tool_calls: Limit
    total_tokens: Limit
    wall_time_ms: Limit
    professional_concurrency: Limit
    review_rounds: Limit
    correction_rounds: Limit


class ArtifactRef(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    artifact_id: UUID
    scope: TenantScope
    artifact_version: str = Field(min_length=1, max_length=64)
    uri: str = Field(min_length=1, max_length=2048)
    media_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)
    sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    classification: DataClassification
    immutable: bool


class CitationRef(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    citation_id: UUID
    artifact_id: UUID
    source_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    locator_type: Literal["PAGE", "SECTION", "CLAUSE", "TABLE", "FIGURE", "CELL", "LINE"]
    locator: str = Field(min_length=1, max_length=512)
    claim_id: str = Field(min_length=1, max_length=128)


class Issue(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    severity: Literal["INFO", "WARNING", "ERROR", "CRITICAL"]
    message: str = Field(min_length=1, max_length=4000)
    affected_path: str | None = Field(default=None, max_length=1024)
    next_action: str | None = Field(default=None, max_length=2000)


class TaskContext(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    task_id: UUID
    scope: TenantScope
    task_class: Literal["G0", "P1", "P2", "P3", "K1"]
    goal: str = Field(min_length=1, max_length=8000)
    success_criteria: tuple[str, ...] = Field(min_length=1)
    risk_level: RiskLevel
    dependency_data: dict[str, Any]
    context_manifest_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: tuple[ArtifactRef, ...]
    skill_versions: dict[str, str]
    prompt_versions: dict[str, str]
    model_versions: dict[str, str]
    knowledge_versions: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    budget: BudgetPolicy
    output_schema_id: str = Field(min_length=1, max_length=512)
    review_checklist: tuple[str, ...]
    created_at: datetime


class AgentResult(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    task_id: UUID
    run_id: UUID
    status: AgentStatus
    summary: str = Field(min_length=1, max_length=12000)
    structured_data: dict[str, Any]
    artifacts: tuple[ArtifactRef, ...]
    evidence: tuple[CitationRef, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    issues: tuple[Issue, ...]
    retryable: bool
    failure_code: str | None = Field(default=None, max_length=128)
    completed_at: datetime

    @model_validator(mode="after")
    def validate_failure(self) -> AgentResult:
        if self.status in {AgentStatus.FAILED, AgentStatus.BLOCKED} and not self.failure_code:
            raise ValueError("failed or blocked result requires failure_code")
        if self.status == AgentStatus.SUCCESS and self.failure_code:
            raise ValueError("successful result cannot include failure_code")
        return self


class ToolResult(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    call_id: UUID
    task_id: UUID
    run_id: UUID
    scope: TenantScope
    tool_name: str = Field(min_length=1, max_length=128)
    tool_version: str = Field(min_length=1, max_length=64)
    status: ToolStatus
    output: dict[str, Any]
    exit_code: int | None = None
    stdout: str = Field(max_length=200000)
    stderr: str = Field(max_length=200000)
    encoding: str | None = Field(default=None, max_length=64)
    truncated: bool
    artifacts: tuple[ArtifactRef, ...]
    idempotency_key: str | None = Field(default=None, max_length=256)
    input_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = Field(default=None, max_length=128)
    retryable: bool
    duration_ms: int = Field(ge=0)
    completed_at: datetime

    @model_validator(mode="after")
    def validate_error(self) -> ToolResult:
        if self.status in {ToolStatus.FAILED, ToolStatus.BLOCKED, ToolStatus.DENIED}:
            if not self.error_code:
                raise ValueError("failed, blocked, or denied tool result requires error_code")
        return self


class Checkpoint(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    checkpoint_id: UUID
    task_id: UUID
    scope: TenantScope
    sequence: int = Field(ge=0)
    graph_version: str = Field(min_length=1, max_length=128)
    state_schema_version: str = Field(min_length=1, max_length=64)
    state_artifact: ArtifactRef
    state_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    committed_side_effect_ids: tuple[UUID, ...]
    created_at: datetime


class MemoryRecord(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    memory_id: UUID
    scope: TenantScope
    memory_scope: MemoryScope
    content: dict[str, Any]
    provenance_ids: tuple[UUID, ...] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    classification: DataClassification
    approval_state: Literal["CANDIDATE", "APPROVED", "REJECTED", "EXPIRED"]
    expires_at: datetime | None
    created_at: datetime


class CacheEntry(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    cache_entry_id: UUID
    scope: TenantScope
    cache_class: Literal["EXACT", "RETRIEVAL", "TOOL", "PARSE", "SEMANTIC"]
    cache_key_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    permission_version: str = Field(min_length=1, max_length=128)
    version_manifest: dict[str, str]
    value_artifact: ArtifactRef
    validation_state: Literal["VALID", "STALE", "REJECTED"]
    created_at: datetime
    expires_at: datetime


class ReviewResult(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    review_id: UUID
    task_id: UUID
    target_run_id: UUID
    target_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_version: str = Field(min_length=1, max_length=128)
    decision: ReviewDecision
    findings: tuple[Issue, ...]
    correction_count: int = Field(ge=0, le=2)
    completed_at: datetime


class ApprovalRecord(StrictModel):
    schema_version: Literal["1.0.0"] = CONTRACT_VERSION
    approval_id: UUID
    scope: TenantScope
    action: str = Field(min_length=1, max_length=128)
    target_type: str = Field(min_length=1, max_length=128)
    target_id: UUID
    target_version: str = Field(min_length=1, max_length=128)
    target_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str = Field(min_length=1, max_length=128)
    actor_id: UUID
    outcome: ApprovalOutcome
    reason: str = Field(min_length=1, max_length=4000)
    decided_at: datetime
    expires_at: datetime | None
