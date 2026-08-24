"""Explicit synchronous and queued-asynchronous child task scheduler."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import AgentStatus, TenantScope
from ndt_agents.orchestration.budget import BudgetExceeded, BudgetGuard
from ndt_agents.orchestration.child_context import child_context_manifest_sha256
from ndt_agents.orchestration.child_models import (
    ChildAgentKind,
    ChildModel,
    ChildRunOutcome,
    ChildSideEffectClass,
    ChildTaskContext,
)
from ndt_agents.orchestration.subgraph import ChildExecutor, ChildSubgraph


class ScheduleMode(StrEnum):
    SYNC = "SYNC"
    ASYNC = "ASYNC"


class ScheduleStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class ScheduleHandle(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    schedule_id: UUID
    parent_task_id: UUID
    scope: TenantScope
    mode: Literal[ScheduleMode.ASYNC] = ScheduleMode.ASYNC
    status: Literal[ScheduleStatus.QUEUED] = ScheduleStatus.QUEUED
    assignment_ids: tuple[str, ...] = Field(min_length=1, max_length=4)


class ScheduledAssignment(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    assignment_id: str = Field(min_length=1, max_length=128)
    run_id: UUID
    wave: int = Field(ge=1)
    status: AssignmentStatus
    execution_calls: Literal[0, 1]
    outcome: ChildRunOutcome | None
    error_code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.execution_calls == 1:
            if self.outcome is None:
                raise ValueError("an executed assignment requires a child outcome")
        if self.status is AssignmentStatus.COMPLETED:
            if self.outcome is None or self.error_code is not None or self.next_action is not None:
                raise ValueError("a completed assignment requires only a successful child outcome")
        elif self.error_code is None or self.next_action is None:
            raise ValueError("a non-completed assignment requires an error and next action")
        return self


class ScheduleResult(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    schedule_id: UUID
    parent_task_id: UUID
    scope: TenantScope
    mode: ScheduleMode
    status: ScheduleStatus
    assignments: tuple[ScheduledAssignment, ...] = Field(min_length=1, max_length=4)
    waves_completed: int = Field(ge=0, le=4)
    max_concurrency_observed: int = Field(ge=0, le=4)

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.status in {ScheduleStatus.QUEUED, ScheduleStatus.RUNNING}:
            raise ValueError("a schedule result requires a terminal status")
        statuses = {item.status for item in self.assignments}
        if self.status is ScheduleStatus.COMPLETED and statuses != {AssignmentStatus.COMPLETED}:
            raise ValueError("completed schedule requires every assignment to complete")
        if self.status is ScheduleStatus.CANCELLED and statuses != {AssignmentStatus.CANCELLED}:
            raise ValueError("cancelled schedule requires every assignment to be cancelled")
        if self.status is ScheduleStatus.PARTIAL and AssignmentStatus.COMPLETED not in statuses:
            raise ValueError("partial schedule requires at least one completed assignment")
        if self.status is ScheduleStatus.FAILED and AssignmentStatus.COMPLETED in statuses:
            raise ValueError("failed schedule cannot contain completed assignments")
        return self


class SchedulerError(ValueError):
    """Stable pre-execution scheduler rejection."""

    def __init__(self, code: str, message: str, next_action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action


@dataclass(frozen=True, slots=True)
class _QueuedSchedule:
    handle: ScheduleHandle
    contexts: tuple[ChildTaskContext, ...]
    executors: Mapping[str, ChildExecutor]
    cancelled_assignment_ids: frozenset[str] = frozenset()


class TaskScheduler:
    """Run child DAGs without hidden workers, retries, or user-delivery paths."""

    def __init__(
        self,
        subgraph: ChildSubgraph | None = None,
        *,
        hard_professional_concurrency: int = 4,
        budget_guard: BudgetGuard | None = None,
    ) -> None:
        if not 1 <= hard_professional_concurrency <= 4:
            raise ValueError("scheduler hard concurrency must be between one and four")
        self._subgraph = subgraph or ChildSubgraph()
        self._hard_professional_concurrency = hard_professional_concurrency
        self._budget_guard = budget_guard
        self._queued: dict[UUID, _QueuedSchedule] = {}
        self._terminal: dict[UUID, ScheduleResult] = {}

    async def schedule(
        self,
        contexts: Sequence[ChildTaskContext],
        executors: Mapping[str, ChildExecutor],
        *,
        asynchronous: bool,
    ) -> ScheduleHandle | ScheduleResult:
        if asynchronous:
            return self.enqueue(contexts, executors)
        return await self.run_sync(contexts, executors)

    def validate(
        self,
        contexts: Sequence[ChildTaskContext],
        executors: Mapping[str, ChildExecutor],
    ) -> tuple[ChildTaskContext, ...]:
        """Validate a complete schedule without storing or executing it."""

        return self._validate(contexts, executors)

    async def run_sync(
        self,
        contexts: Sequence[ChildTaskContext],
        executors: Mapping[str, ChildExecutor],
        *,
        schedule_id: UUID | None = None,
    ) -> ScheduleResult:
        prepared = self._validate(contexts, executors)
        return await self._execute(schedule_id or uuid4(), prepared, executors, ScheduleMode.SYNC)

    def enqueue(
        self,
        contexts: Sequence[ChildTaskContext],
        executors: Mapping[str, ChildExecutor],
    ) -> ScheduleHandle:
        prepared = self._validate(contexts, executors)
        schedule_id = uuid4()
        first = prepared[0]
        if self._budget_guard is not None and self._budget_guard.policy != first.budget:
            raise SchedulerError(
                "SCHEDULE_BUDGET_GUARD_MISMATCH",
                "The budget guard is not bound to the child task policy.",
                "Create one fresh guard from the exact parent task budget.",
            )
        handle = ScheduleHandle(
            schedule_id=schedule_id,
            parent_task_id=first.parent_task_id,
            scope=first.scope,
            assignment_ids=tuple(item.assignment_id for item in prepared),
        )
        self._queued[schedule_id] = _QueuedSchedule(
            handle=handle,
            contexts=prepared,
            executors=dict(executors),
        )
        return handle

    async def advance(
        self,
        schedule_id: UUID,
        *,
        scope: TenantScope,
        parent_task_id: UUID,
    ) -> ScheduleResult:
        if schedule_id in self._terminal:
            result = self._terminal[schedule_id]
            self._require_binding(result.scope, result.parent_task_id, scope, parent_task_id)
            return result
        queued = self._queued.get(schedule_id)
        if queued is None:
            raise SchedulerError(
                "SCHEDULE_NOT_FOUND",
                "The queued schedule does not exist in this scheduler instance.",
                "Use an active scoped schedule ID or restore it through S1-07 recovery.",
            )
        self._require_binding(
            queued.handle.scope,
            queued.handle.parent_task_id,
            scope,
            parent_task_id,
        )
        self._queued.pop(schedule_id)
        result = await self._execute(
            schedule_id,
            queued.contexts,
            queued.executors,
            ScheduleMode.ASYNC,
            cancelled_assignment_ids=queued.cancelled_assignment_ids,
        )
        self._terminal[schedule_id] = result
        return result

    def cancel_assignment(
        self,
        schedule_id: UUID,
        assignment_id: str,
        *,
        scope: TenantScope,
        parent_task_id: UUID,
    ) -> ScheduleHandle:
        queued = self._queued.get(schedule_id)
        if queued is None:
            raise SchedulerError(
                "SCHEDULE_NOT_QUEUED",
                "Only an assignment in a queued schedule can be cancelled.",
                "Cancel before explicit schedule advancement.",
            )
        self._require_binding(
            queued.handle.scope,
            queued.handle.parent_task_id,
            scope,
            parent_task_id,
        )
        if assignment_id not in queued.handle.assignment_ids:
            raise SchedulerError(
                "SCHEDULE_ASSIGNMENT_UNKNOWN",
                "The requested assignment is not part of this schedule.",
                "Use an assignment ID from the scoped schedule handle.",
            )
        self._queued[schedule_id] = _QueuedSchedule(
            handle=queued.handle,
            contexts=queued.contexts,
            executors=queued.executors,
            cancelled_assignment_ids=(queued.cancelled_assignment_ids | frozenset({assignment_id})),
        )
        return queued.handle

    def cancel(
        self,
        schedule_id: UUID,
        *,
        scope: TenantScope,
        parent_task_id: UUID,
    ) -> ScheduleResult:
        if schedule_id in self._terminal:
            result = self._terminal[schedule_id]
            self._require_binding(result.scope, result.parent_task_id, scope, parent_task_id)
            return result
        queued = self._queued.get(schedule_id)
        if queued is None:
            raise SchedulerError(
                "SCHEDULE_NOT_FOUND",
                "The queued schedule does not exist in this scheduler instance.",
                "Use an active scoped schedule ID or restore it through S1-07 recovery.",
            )
        self._require_binding(
            queued.handle.scope,
            queued.handle.parent_task_id,
            scope,
            parent_task_id,
        )
        self._queued.pop(schedule_id)
        assignments = tuple(
            ScheduledAssignment(
                assignment_id=context.assignment_id,
                run_id=context.run_id,
                wave=1,
                status=AssignmentStatus.CANCELLED,
                execution_calls=0,
                outcome=None,
                error_code="SCHEDULE_CANCELLED",
                next_action="Submit a new scoped schedule if the work is still required.",
            )
            for context in queued.contexts
        )
        result = ScheduleResult(
            schedule_id=schedule_id,
            parent_task_id=queued.handle.parent_task_id,
            scope=queued.handle.scope,
            mode=ScheduleMode.ASYNC,
            status=ScheduleStatus.CANCELLED,
            assignments=assignments,
            waves_completed=0,
            max_concurrency_observed=0,
        )
        self._terminal[schedule_id] = result
        return result

    @staticmethod
    def _require_binding(
        stored_scope: TenantScope,
        stored_task_id: UUID,
        requested_scope: TenantScope,
        requested_task_id: UUID,
    ) -> None:
        if stored_scope != requested_scope or stored_task_id != requested_task_id:
            raise SchedulerError(
                "SCHEDULE_BINDING_DENIED",
                "The schedule is not bound to the requested task and identity scope.",
                "Use the authenticated tenant, project, user, permission, and parent task binding.",
            )

    def _validate(
        self,
        contexts: Sequence[ChildTaskContext],
        executors: Mapping[str, ChildExecutor],
    ) -> tuple[ChildTaskContext, ...]:
        prepared = tuple(contexts)
        if not prepared or len(prepared) > 4:
            raise SchedulerError(
                "SCHEDULE_SIZE_INVALID",
                "A schedule requires between one and four child assignments.",
                "Submit the minimum bounded child set for this task.",
            )
        first = prepared[0]
        if any(
            item.parent_task_id != first.parent_task_id or item.scope != first.scope
            for item in prepared
        ):
            raise SchedulerError(
                "SCHEDULE_SCOPE_MISMATCH",
                "Every child must belong to the same parent task and complete identity scope.",
                "Rebuild the schedule from one verified scoped dispatch.",
            )
        assignment_ids = tuple(item.assignment_id for item in prepared)
        known = set(assignment_ids)
        if len(known) != len(assignment_ids):
            raise SchedulerError(
                "SCHEDULE_ASSIGNMENT_DUPLICATE",
                "Assignment IDs must be unique within a schedule.",
                "Create one isolated context per assignment.",
            )
        if any(
            item.context_manifest_sha256 != child_context_manifest_sha256(item) for item in prepared
        ):
            raise SchedulerError(
                "SCHEDULE_CONTEXT_INTEGRITY_FAILED",
                "A child context does not match its immutable manifest.",
                "Rebuild contexts from the verified dispatch before scheduling.",
            )
        if set(executors) != known:
            raise SchedulerError(
                "SCHEDULE_EXECUTOR_MISMATCH",
                "Executors must match the scheduled assignments exactly.",
                "Bind one authorized executor to every assignment and no others.",
            )
        for item in prepared:
            dependencies = set(item.dependency_assignment_ids)
            if item.assignment_id in dependencies or not dependencies <= known:
                raise SchedulerError(
                    "SCHEDULE_DEPENDENCY_INVALID",
                    "An assignment has a self-reference or unknown dependency.",
                    "Use only other assignment IDs from the same verified dispatch.",
                )
        kinds = {item.kind for item in prepared}
        if ChildAgentKind.GENERAL in kinds:
            if len(prepared) != 1 or first.dependency_assignment_ids:
                raise SchedulerError(
                    "SCHEDULE_GENERAL_INVALID",
                    "General work must be one dependency-free child schedule.",
                    "Schedule the General child alone.",
                )
        else:
            policies = {item.budget.model_dump_json() for item in prepared}
            if len(policies) != 1:
                raise SchedulerError(
                    "SCHEDULE_BUDGET_MISMATCH",
                    "Professional children in one schedule require one budget policy.",
                    "Rebuild all child contexts from the same parent task budget.",
                )
            limit = first.budget.professional_concurrency
            if limit.active < 1 or limit.active > self._hard_professional_concurrency:
                raise SchedulerError(
                    "SCHEDULE_CONCURRENCY_DENIED",
                    "The active professional concurrency is outside scheduler limits.",
                    "Use an approved active limit within the configured hard ceiling.",
                )
            if limit.hard > self._hard_professional_concurrency:
                raise SchedulerError(
                    "SCHEDULE_HARD_LIMIT_DENIED",
                    "The task hard concurrency exceeds the configured scheduler ceiling.",
                    "Use a policy bounded by the configured non-overridable ceiling.",
                )
        self._topological_waves(prepared)
        return prepared

    @staticmethod
    def _topological_waves(
        contexts: tuple[ChildTaskContext, ...],
    ) -> tuple[tuple[ChildTaskContext, ...], ...]:
        remaining = {item.assignment_id: item for item in contexts}
        resolved: set[str] = set()
        waves: list[tuple[ChildTaskContext, ...]] = []
        while remaining:
            ready = tuple(
                item
                for item in contexts
                if item.assignment_id in remaining
                and set(item.dependency_assignment_ids) <= resolved
            )
            if not ready:
                raise SchedulerError(
                    "SCHEDULE_DEPENDENCY_CYCLE",
                    "The assignment graph contains a dependency cycle.",
                    "Remove the cycle and submit an acyclic verified dispatch.",
                )
            waves.append(ready)
            for item in ready:
                remaining.pop(item.assignment_id)
                resolved.add(item.assignment_id)
        return tuple(waves)

    async def _execute(
        self,
        schedule_id: UUID,
        contexts: tuple[ChildTaskContext, ...],
        executors: Mapping[str, ChildExecutor],
        mode: ScheduleMode,
        *,
        cancelled_assignment_ids: frozenset[str] = frozenset(),
    ) -> ScheduleResult:
        waves = self._topological_waves(contexts)
        completed: dict[str, ScheduledAssignment] = {}
        current_concurrency = 0
        max_concurrency = 0

        async def launch(context: ChildTaskContext, wave: int) -> ScheduledAssignment:
            nonlocal current_concurrency, max_concurrency

            async def execute_child() -> ChildRunOutcome:
                nonlocal current_concurrency, max_concurrency
                current_concurrency += 1
                max_concurrency = max(max_concurrency, current_concurrency)
                try:
                    return await self._subgraph.run(
                        context,
                        executors[context.assignment_id],
                        budget_guard=self._budget_guard,
                    )
                finally:
                    current_concurrency -= 1

            try:
                if self._budget_guard is not None and context.kind is ChildAgentKind.PROFESSIONAL:
                    async with self._budget_guard.professional_slot():
                        outcome = await execute_child()
                else:
                    outcome = await execute_child()
            except BudgetExceeded as error:
                return ScheduledAssignment(
                    assignment_id=context.assignment_id,
                    run_id=context.run_id,
                    wave=wave,
                    status=AssignmentStatus.BLOCKED,
                    execution_calls=0,
                    outcome=None,
                    error_code=error.code,
                    next_action=error.next_action,
                )
            return self._from_outcome(context, outcome, wave)

        for wave_number, wave_contexts in enumerate(waves, start=1):
            runnable: list[ChildTaskContext] = []
            for context in wave_contexts:
                if context.assignment_id in cancelled_assignment_ids:
                    completed[context.assignment_id] = ScheduledAssignment(
                        assignment_id=context.assignment_id,
                        run_id=context.run_id,
                        wave=wave_number,
                        status=AssignmentStatus.CANCELLED,
                        execution_calls=0,
                        outcome=None,
                        error_code="SCHEDULE_ASSIGNMENT_CANCELLED",
                        next_action="Submit a new schedule if this assignment is still required.",
                    )
                    continue
                failed_dependencies = tuple(
                    dependency
                    for dependency in context.dependency_assignment_ids
                    if completed[dependency].status is not AssignmentStatus.COMPLETED
                )
                if failed_dependencies:
                    completed[context.assignment_id] = ScheduledAssignment(
                        assignment_id=context.assignment_id,
                        run_id=context.run_id,
                        wave=wave_number,
                        status=AssignmentStatus.BLOCKED,
                        execution_calls=0,
                        outcome=None,
                        error_code="SCHEDULE_PREREQUISITE_FAILED",
                        next_action=(
                            "Repair or rerun prerequisites: " + ", ".join(failed_dependencies)
                        ),
                    )
                else:
                    runnable.append(context)

            read_only = tuple(
                item
                for item in runnable
                if item.side_effect_class is ChildSideEffectClass.READ_ONLY
            )
            mutating = tuple(
                item for item in runnable if item.side_effect_class is ChildSideEffectClass.MUTATING
            )
            active_limit = (
                1
                if contexts[0].kind is ChildAgentKind.GENERAL
                else contexts[0].budget.professional_concurrency.active
            )
            for start in range(0, len(read_only), active_limit):
                batch = read_only[start : start + active_limit]
                results = await asyncio.gather(*(launch(context, wave_number) for context in batch))
                completed.update((item.assignment_id, item) for item in results)
            for context in mutating:
                item = await launch(context, wave_number)
                completed[item.assignment_id] = item

        assignments = tuple(completed[item.assignment_id] for item in contexts)
        statuses = {item.status for item in assignments}
        if statuses == {AssignmentStatus.COMPLETED}:
            status = ScheduleStatus.COMPLETED
        elif AssignmentStatus.COMPLETED in statuses:
            status = ScheduleStatus.PARTIAL
        else:
            status = ScheduleStatus.FAILED
        return ScheduleResult(
            schedule_id=schedule_id,
            parent_task_id=contexts[0].parent_task_id,
            scope=contexts[0].scope,
            mode=mode,
            status=status,
            assignments=assignments,
            waves_completed=len(waves),
            max_concurrency_observed=max_concurrency,
        )

    @staticmethod
    def _from_outcome(
        context: ChildTaskContext,
        outcome: ChildRunOutcome,
        wave: int,
    ) -> ScheduledAssignment:
        if outcome.status == "FAILED":
            return ScheduledAssignment(
                assignment_id=context.assignment_id,
                run_id=context.run_id,
                wave=wave,
                status=AssignmentStatus.FAILED,
                execution_calls=outcome.execution_calls,
                outcome=outcome,
                error_code=outcome.error_code,
                next_action=outcome.next_action,
            )
        assert outcome.result is not None
        if outcome.result.status in {AgentStatus.SUCCESS, AgentStatus.PARTIAL_SUCCESS}:
            return ScheduledAssignment(
                assignment_id=context.assignment_id,
                run_id=context.run_id,
                wave=wave,
                status=AssignmentStatus.COMPLETED,
                execution_calls=1,
                outcome=outcome,
                error_code=None,
                next_action=None,
            )
        status = (
            AssignmentStatus.FAILED
            if outcome.result.status is AgentStatus.FAILED
            else AssignmentStatus.BLOCKED
        )
        return ScheduledAssignment(
            assignment_id=context.assignment_id,
            run_id=context.run_id,
            wave=wave,
            status=status,
            execution_calls=1,
            outcome=outcome,
            error_code=outcome.result.failure_code or f"CHILD_{outcome.result.status.value}",
            next_action="Inspect the typed child result before rescheduling dependent work.",
        )
