"""Strict S3-01 Knowledge Agent entry contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ndt_agents.approval.service import ApprovalStatus
from ndt_agents.contracts.v1 import StrictModel
from ndt_agents.orchestration.child_models import ChildTaskContext
from ndt_agents.orchestration.models import MainGraphResult

KNOWLEDGE_ENTRY_VERSION: Literal["1.0.0"] = "1.0.0"


class KnowledgeEntryTrigger(StrEnum):
    USER_INTENT = "USER_INTENT"
    UI_ACTION = "UI_ACTION"
    ADMIN_JOB = "ADMIN_JOB"


class KnowledgeIntent(StrEnum):
    IMPORT = "IMPORT"
    READ_ONLY_QUERY = "READ_ONLY_QUERY"


class KnowledgeEntryPhase(StrEnum):
    RECEIVED = "RECEIVED"
    OBSERVE = "OBSERVE"
    VALIDATE = "VALIDATE"
    PLAN = "PLAN"
    VERIFY = "VERIFY"
    DISPATCH_READY = "DISPATCH_READY"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class KnowledgeStartRequest(StrictModel):
    schema_version: Literal["1.0.0"] = KNOWLEDGE_ENTRY_VERSION
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    task_id: UUID
    trigger: KnowledgeEntryTrigger
    intent: KnowledgeIntent
    source_artifact_ids: tuple[UUID, ...] = Field(default=(), max_length=50)
    approval_status: ApprovalStatus | None = None

    @model_validator(mode="after")
    def validate_entry_shape(self) -> Self:
        if len(set(self.source_artifact_ids)) != len(self.source_artifact_ids):
            raise ValueError("source artifact IDs must be unique")
        if self.intent is KnowledgeIntent.READ_ONLY_QUERY:
            if self.trigger is not KnowledgeEntryTrigger.USER_INTENT:
                raise ValueError("read-only query is valid only for user-intent classification")
            if self.source_artifact_ids or self.approval_status is not None:
                raise ValueError("read-only query cannot carry import artifacts or approval")
            return self
        if not self.source_artifact_ids:
            raise ValueError("knowledge import requires at least one source artifact")
        if self.trigger is KnowledgeEntryTrigger.ADMIN_JOB:
            if self.approval_status is None:
                raise ValueError("administrator job requires an approval status")
        elif self.approval_status is not None:
            raise ValueError("user and UI starts cannot carry administrator approval state")
        return self


class KnowledgeUiStartRequest(StrictModel):
    schema_version: Literal["1.0.0"] = KNOWLEDGE_ENTRY_VERSION
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    task_id: UUID
    source_artifact_ids: tuple[UUID, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        if len(set(self.source_artifact_ids)) != len(self.source_artifact_ids):
            raise ValueError("source artifact IDs must be unique")
        return self


class KnowledgeEntryTransition(StrictModel):
    sequence: int = Field(ge=1)
    source: KnowledgeEntryPhase
    target: KnowledgeEntryPhase
    event: str = Field(min_length=1, max_length=128)


class KnowledgeEntryResult(StrictModel):
    schema_version: Literal["1.0.0"] = KNOWLEDGE_ENTRY_VERSION
    entry_id: UUID
    task_id: UUID
    status: Literal["DISPATCH_READY", "NOT_APPLICABLE", "BLOCKED", "FAILED"]
    phase: KnowledgeEntryPhase
    main_result: MainGraphResult | None
    child_context: ChildTaskContext | None
    transitions: tuple[KnowledgeEntryTransition, ...] = Field(min_length=1)
    physical_child_calls: Literal[0] = 0
    main_llm_calls: Literal[0] = 0
    main_tool_calls: Literal[0] = 0
    code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.status == "DISPATCH_READY":
            if (
                self.phase is not KnowledgeEntryPhase.DISPATCH_READY
                or self.main_result is None
                or self.child_context is None
                or self.code is not None
                or self.next_action is not None
            ):
                raise ValueError(
                    "ready knowledge entry requires verified dispatch and child context"
                )
        elif (
            self.main_result is not None
            or self.child_context is not None
            or self.code is None
            or self.next_action is None
        ):
            raise ValueError("non-ready knowledge entry requires only a code and next action")
        return self


class KnowledgeEntryResponse(StrictModel):
    schema_version: Literal["1.0.0"] = KNOWLEDGE_ENTRY_VERSION
    entry_id: UUID
    task_id: UUID
    status: Literal["DISPATCH_READY", "NOT_APPLICABLE", "BLOCKED", "FAILED"]
    asynchronous: bool
    review_required: bool
    code: str | None = None
    next_action: str | None = None
