"""Strict child-agent definition, context, transition, and outcome contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ndt_agents.context.models import SelectedContextEntry
from ndt_agents.contracts.v1 import (
    AgentResult,
    ArtifactRef,
    BudgetPolicy,
    RiskLevel,
    TenantScope,
)


class ChildModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChildAgentKind(StrEnum):
    GENERAL = "GENERAL"
    PROFESSIONAL = "PROFESSIONAL"


class ChildSideEffectClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    MUTATING = "MUTATING"


class ChildPhase(StrEnum):
    PREPARED = "PREPARED"
    OBSERVE = "OBSERVE"
    PLAN = "PLAN"
    ACT = "ACT"
    VERIFY = "VERIFY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentDefinition(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    agent_type: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")
    kind: ChildAgentKind
    allowed_tools: frozenset[str] = Field(max_length=12)
    skill_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)


class ChildInput(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    assignment_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=1, max_length=8000)
    success_criteria: tuple[str, ...] = Field(min_length=1, max_length=20)
    context_entry_sha256s: tuple[str, ...] = Field(default=(), max_length=100)
    artifact_ids: tuple[UUID, ...] = Field(default=(), max_length=20)
    requested_tools: tuple[str, ...] = Field(default=(), max_length=12)
    side_effect_class: ChildSideEffectClass = ChildSideEffectClass.READ_ONLY


class ChildTaskContext(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parent_task_id: UUID
    run_id: UUID
    assignment_id: str = Field(min_length=1, max_length=128)
    kind: ChildAgentKind
    agent_type: str = Field(min_length=1, max_length=128)
    scope: TenantScope
    task_class: Literal["G0", "P1", "P2", "P3", "K1"]
    goal: str = Field(min_length=1, max_length=8000)
    success_criteria: tuple[str, ...] = Field(min_length=1, max_length=20)
    risk_level: RiskLevel
    context_entries: tuple[SelectedContextEntry, ...] = Field(default=(), max_length=100)
    artifacts: tuple[ArtifactRef, ...] = Field(max_length=20)
    dependency_assignment_ids: tuple[str, ...] = Field(max_length=4)
    side_effect_class: ChildSideEffectClass
    allowed_tools: tuple[str, ...] = Field(max_length=12)
    skill_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    knowledge_versions: tuple[str, ...]
    budget: BudgetPolicy
    output_schema_id: str = Field(min_length=1, max_length=512)
    review_checklist: tuple[str, ...]
    scratch_namespace: str = Field(min_length=1, max_length=1024)
    context_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_delivery_allowed: Literal[False] = False


class ChildTransition(ChildModel):
    sequence: int = Field(ge=1)
    source: ChildPhase
    target: ChildPhase
    event: str = Field(min_length=1, max_length=128)


class ChildRunOutcome(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parent_task_id: UUID
    run_id: UUID
    assignment_id: str
    status: Literal["COMPLETED", "FAILED"]
    phase: ChildPhase
    result: AgentResult | None
    transitions: tuple[ChildTransition, ...] = Field(min_length=1)
    execution_calls: Literal[0, 1] = 1
    review_required: bool
    aggregation_ready: bool
    user_delivery_allowed: Literal[False] = False
    error_code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.status == "COMPLETED":
            if (
                self.result is None
                or self.execution_calls != 1
                or self.error_code is not None
                or self.next_action is not None
            ):
                raise ValueError("completed child outcome requires only a typed result")
        elif self.result is not None or self.error_code is None or self.next_action is None:
            raise ValueError("failed child outcome requires error and next action without result")
        if self.aggregation_ready and (self.status != "COMPLETED" or self.review_required):
            raise ValueError("only completed non-review results may be aggregation ready")
        return self
