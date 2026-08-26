"""Strict S6-01 task and streamed-event client contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ndt_agents.contracts.v1 import TenantScope

CLIENT_CONTRACT_VERSION = "1.0.0"


class ClientModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClientTaskClass(StrEnum):
    GENERAL = "G0"
    PROFESSIONAL_SYNC = "P1"
    PROFESSIONAL_ASYNC = "P2"
    MULTI_PROFESSIONAL = "P3"
    KNOWLEDGE = "K1"


class TaskState(StrEnum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {
            TaskState.SUCCEEDED,
            TaskState.PARTIAL,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }


class TaskEventKind(StrEnum):
    STATUS = "STATUS"
    PROGRESS = "PROGRESS"
    REVIEW = "REVIEW"
    APPROVAL = "APPROVAL"
    RESULT = "RESULT"
    ISSUE = "ISSUE"


class TaskCreateRequest(ClientModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_class: ClientTaskClass
    goal: str = Field(min_length=1, max_length=8000)
    success_criteria: tuple[str, ...] = Field(min_length=1, max_length=20)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")

    @model_validator(mode="after")
    def validate_text(self) -> Self:
        if self.goal != self.goal.strip():
            raise ValueError("goal must not contain surrounding whitespace")
        if any(not item.strip() or item != item.strip() for item in self.success_criteria):
            raise ValueError("success criteria must be non-empty and trimmed")
        if len(set(self.success_criteria)) != len(self.success_criteria):
            raise ValueError("success criteria must be unique")
        return self


class WorkbenchTask(ClientModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    scope: TenantScope
    task_class: ClientTaskClass
    goal: str
    success_criteria: tuple[str, ...]
    state: TaskState
    last_sequence: int = Field(ge=1)
    review_required: bool
    review_completed: bool
    approval_required: bool
    formal_use_allowed: Literal[False] = False
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_review_state(self) -> Self:
        if not self.review_required and not self.review_completed:
            raise ValueError("tasks without review requirements are review-complete")
        return self


class TaskEvent(ClientModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: UUID
    task_id: UUID
    scope: TenantScope
    sequence: int = Field(ge=1)
    kind: TaskEventKind
    state: TaskState
    message: str = Field(min_length=1, max_length=4000)
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    retryable: bool = False
    error_code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        failed = self.state in {TaskState.PARTIAL, TaskState.BLOCKED, TaskState.FAILED}
        if failed and (self.error_code is None or self.next_action is None):
            raise ValueError("partial, blocked, or failed events require error and next action")
        if not failed and self.error_code is not None:
            raise ValueError("non-failure event cannot carry an error code")
        if self.state is TaskState.SUCCEEDED and self.progress_percent != 100:
            raise ValueError("successful event requires 100 percent progress")
        return self


class TaskEventBatch(ClientModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    after_sequence: int = Field(ge=0)
    last_sequence: int = Field(ge=0)
    terminal: bool
    events: tuple[TaskEvent, ...]
