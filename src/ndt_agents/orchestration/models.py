"""Strict Main Graph route, dispatch, and state-transition contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrchestrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RouteKind(StrEnum):
    GENERAL_SYNC = "GENERAL_SYNC"
    ONE_PROFESSIONAL_SYNC_REVIEW = "ONE_PROFESSIONAL_SYNC_REVIEW"
    ONE_PROFESSIONAL_ASYNC_REVIEW = "ONE_PROFESSIONAL_ASYNC_REVIEW"
    MULTIPLE_INDEPENDENT_ASYNC_REVIEW = "MULTIPLE_INDEPENDENT_ASYNC_REVIEW"
    MULTIPLE_DEPENDENT_ASYNC_REVIEW = "MULTIPLE_DEPENDENT_ASYNC_REVIEW"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class MainGraphPhase(StrEnum):
    RECEIVED = "RECEIVED"
    OBSERVE = "OBSERVE"
    PLAN = "PLAN"
    ACT = "ACT"
    VERIFY = "VERIFY"
    DISPATCH_READY = "DISPATCH_READY"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ProfessionalAssignment(OrchestrationModel):
    assignment_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")
    agent_type: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")
    depends_on: tuple[str, ...] = Field(default=(), max_length=4)


class RouteSignals(OrchestrationModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    general_eligible: bool
    professional_assignments: tuple[ProfessionalAssignment, ...] = Field(default=(), max_length=4)
    human_required: bool = False
    asynchronous_required: bool = False

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        identifiers = [item.assignment_id for item in self.professional_assignments]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("professional assignment IDs must be unique")
        if self.general_eligible and (self.professional_assignments or self.human_required):
            raise ValueError("general route cannot declare professional or human work")
        if self.general_eligible and self.asynchronous_required:
            raise ValueError("general route cannot require asynchronous professional work")
        if not self.general_eligible and not self.professional_assignments:
            raise ValueError("non-general route requires a professional assignment")
        if self.human_required and not self.professional_assignments:
            raise ValueError("human route requires a responsible professional assignment")
        if self.human_required and self.asynchronous_required:
            raise ValueError("human route cannot also require asynchronous dispatch")
        known = set(identifiers)
        for assignment in self.professional_assignments:
            if assignment.assignment_id in assignment.depends_on:
                raise ValueError("assignment cannot depend on itself")
            if not set(assignment.depends_on) <= known:
                raise ValueError("assignment dependency is unknown")
        return self


class RouteDecision(OrchestrationModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    route: RouteKind
    rule_id: str = Field(min_length=1, max_length=128)
    target_agents: tuple[str, ...]
    asynchronous: bool
    review_required: bool
    human_required: bool


class DispatchPlan(OrchestrationModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    route: RouteKind
    general_agent: bool
    professional_assignments: tuple[ProfessionalAssignment, ...]
    asynchronous: bool
    review_required: bool
    human_required: bool
    main_allowed_tools: tuple[()] = ()
    main_llm_calls: Literal[0] = 0


class GraphTransition(OrchestrationModel):
    sequence: int = Field(ge=1)
    source: MainGraphPhase
    target: MainGraphPhase
    event: str = Field(min_length=1, max_length=128)


class MainGraphResult(OrchestrationModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    status: Literal["DISPATCH_READY", "BLOCKED", "FAILED"]
    phase: MainGraphPhase
    decision: RouteDecision | None
    dispatch: DispatchPlan | None
    transitions: tuple[GraphTransition, ...] = Field(min_length=1)
    error_code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.status == "DISPATCH_READY":
            if self.decision is None or self.dispatch is None or self.error_code is not None:
                raise ValueError("ready graph requires decision and dispatch only")
        elif self.error_code is None or self.next_action is None:
            raise ValueError("non-ready graph requires error and next action")
        return self
