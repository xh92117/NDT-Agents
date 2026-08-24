"""Independent per-result and cross-result review with bounded targeted correction."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from ndt_agents.contracts.v1 import (
    AgentResult,
    AgentStatus,
    Issue,
    ReviewDecision,
    ReviewResult,
    TenantScope,
)
from ndt_agents.orchestration.budget import (
    BudgetActionClass,
    BudgetExceeded,
    BudgetGuard,
    BudgetTelemetry,
)
from ndt_agents.orchestration.child_context import child_context_manifest_sha256
from ndt_agents.orchestration.child_models import (
    ChildAgentKind,
    ChildModel,
    ChildRunOutcome,
    ChildTaskContext,
)
from ndt_agents.orchestration.scheduler import (
    AssignmentStatus,
    ScheduleResult,
)


class ReviewKind(StrEnum):
    PER_RESULT = "PER_RESULT"
    CROSS_RESULT = "CROSS_RESULT"


class ReviewPhase(StrEnum):
    PREPARED = "PREPARED"
    PER_RESULT_REVIEW = "PER_RESULT_REVIEW"
    CORRECTION = "CORRECTION"
    CROSS_RESULT_REVIEW = "CROSS_RESULT_REVIEW"
    COMPLETED = "COMPLETED"
    CONFLICT = "CONFLICT"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    FAILED = "FAILED"


class ReviewWorkflowStatus(StrEnum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    CONFLICT = "CONFLICT"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    FAILED = "FAILED"


class AggregationSource(StrEnum):
    GENERAL = "GENERAL"
    REVIEWED_PROFESSIONAL = "REVIEWED_PROFESSIONAL"


class ReviewerDefinition(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    reviewer_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    review_timeout_ms: int = Field(default=30_000, ge=1, le=300_000)
    correction_timeout_ms: int = Field(default=30_000, ge=1, le=300_000)
    read_only: Literal[True] = True
    allowed_tools: tuple[str, ...] = Field(default=(), max_length=0)


class ReviewTarget(ChildModel):
    assignment_id: str = Field(min_length=1, max_length=128)
    run_id: UUID
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: AgentResult

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if (
            self.result.run_id != self.run_id
            or agent_result_sha256(self.result) != self.result_sha256
        ):
            raise ValueError("review target identity or hash does not match result")
        return self


class ReviewContext(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: ReviewKind
    task_id: UUID
    scope: TenantScope
    schedule_id: UUID
    review_target_run_id: UUID
    review_target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    targets: tuple[ReviewTarget, ...] = Field(min_length=1, max_length=4)
    review_checklist: tuple[str, ...] = Field(min_length=1, max_length=50)
    reviewer_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    correction_count: int = Field(ge=0, le=2)
    context_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    read_only: Literal[True] = True
    allowed_tools: tuple[str, ...] = Field(default=(), max_length=0)
    user_delivery_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if review_context_manifest_sha256(self) != self.context_manifest_sha256:
            raise ValueError("review context manifest does not match payload")
        if any(target.result.task_id != self.task_id for target in self.targets):
            raise ValueError("review targets must belong to the scoped task")
        return self


class CorrectionContext(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    scope: TenantScope
    schedule_id: UUID
    assignment_id: str
    run_id: UUID
    agent_type: str
    goal: str
    success_criteria: tuple[str, ...]
    output_schema_id: str
    current_result: AgentResult
    current_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    findings: tuple[Issue, ...] = Field(min_length=1)
    targeted_instruction: str = Field(min_length=1, max_length=8000)
    related_targets: tuple[ReviewTarget, ...] = Field(default=(), max_length=3)
    correction_count: int = Field(ge=1, le=2)
    context_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_delivery_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.current_result.task_id != self.task_id or self.current_result.run_id != self.run_id:
            raise ValueError("correction target identity does not match current result")
        if agent_result_sha256(self.current_result) != self.current_result_sha256:
            raise ValueError("correction target hash does not match current result")
        if correction_context_manifest_sha256(self) != self.context_manifest_sha256:
            raise ValueError("correction context manifest does not match payload")
        return self


class ReviewTransition(ChildModel):
    sequence: int = Field(ge=1)
    source: ReviewPhase
    target: ReviewPhase
    event: str = Field(min_length=1, max_length=128)


class ReviewedAssignment(ChildModel):
    assignment_id: str
    run_id: UUID
    original_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_result: AgentResult
    review_history: tuple[ReviewResult, ...]
    correction_count: int = Field(ge=0, le=2)
    decision: ReviewDecision | None
    aggregation_ready: bool

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if agent_result_sha256(self.current_result) != self.current_result_sha256:
            raise ValueError("reviewed assignment result hash mismatch")
        if self.aggregation_ready and self.decision is not ReviewDecision.PASS:
            raise ValueError("only a passed assignment can be aggregation ready")
        return self


class ReviewWorkflowResult(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    schedule_id: UUID
    task_id: UUID
    scope: TenantScope
    status: ReviewWorkflowStatus
    assignments: tuple[ReviewedAssignment, ...] = Field(min_length=1, max_length=4)
    skipped_assignment_ids: tuple[str, ...] = Field(max_length=4)
    cross_review_history: tuple[ReviewResult, ...]
    transitions: tuple[ReviewTransition, ...] = Field(min_length=1)
    review_calls: int = Field(ge=0)
    correction_calls: int = Field(ge=0)
    aggregation_ready: bool
    review_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget_telemetry: BudgetTelemetry
    error_code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=2000)
    completed_at: datetime
    user_delivery_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_terminal_state(self) -> Self:
        if self.aggregation_ready != (
            self.status in {ReviewWorkflowStatus.APPROVED, ReviewWorkflowStatus.PARTIAL}
        ):
            raise ValueError("workflow aggregation state does not match status")
        if self.aggregation_ready:
            if self.error_code is not None or self.next_action is not None:
                raise ValueError("aggregatable workflow cannot contain a terminal error")
            if any(not assignment.aggregation_ready for assignment in self.assignments):
                raise ValueError("every reviewed assignment must pass before aggregation")
        elif self.error_code is None or self.next_action is None:
            raise ValueError("non-aggregatable workflow requires error and next action")
        if review_manifest_sha256(self) != self.review_manifest_sha256:
            raise ValueError("review manifest hash does not match bound results and reviews")
        return self


class MainAggregationInput(ChildModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: UUID
    scope: TenantScope
    source: AggregationSource
    results: tuple[AgentResult, ...] = Field(min_length=1, max_length=4)
    review_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    aggregation_ready: Literal[True] = True
    user_delivery_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.source is AggregationSource.GENERAL:
            if self.review_manifest_sha256 is not None or len(self.results) != 1:
                raise ValueError("General aggregation requires one unreviewed General result")
        elif self.review_manifest_sha256 is None:
            raise ValueError("professional aggregation requires a review manifest")
        return self


class ReviewExecutor(Protocol):
    async def review(self, context: ReviewContext) -> Mapping[str, Any]: ...


class CorrectionExecutor(Protocol):
    async def correct(self, context: CorrectionContext) -> Mapping[str, Any]: ...


class ReviewError(ValueError):
    def __init__(self, code: str, message: str, next_action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action


class MainAggregationGate:
    """Create Main-only aggregation input without a raw professional bypass."""

    @staticmethod
    def general(context: ChildTaskContext, outcome: ChildRunOutcome) -> MainAggregationInput:
        if (
            context.kind is not ChildAgentKind.GENERAL
            or outcome.parent_task_id != context.parent_task_id
            or outcome.run_id != context.run_id
            or outcome.result is None
            or outcome.status != "COMPLETED"
            or outcome.review_required
            or not outcome.aggregation_ready
        ):
            raise ReviewError(
                "AGGREGATION_GENERAL_INVALID",
                "The General result is not a completed direct-aggregation child outcome.",
                "Use the exact verified General child context and outcome.",
            )
        return MainAggregationInput(
            task_id=context.parent_task_id,
            scope=context.scope,
            source=AggregationSource.GENERAL,
            results=(outcome.result,),
        )

    @staticmethod
    def professional(review: ReviewWorkflowResult) -> MainAggregationInput:
        if not review.aggregation_ready:
            raise ReviewError(
                "AGGREGATION_REVIEW_REQUIRED",
                "Professional results have not passed the complete review workflow.",
                review.next_action or "Complete per-result and required cross-result review.",
            )
        return MainAggregationInput(
            task_id=review.task_id,
            scope=review.scope,
            source=AggregationSource.REVIEWED_PROFESSIONAL,
            results=tuple(item.current_result for item in review.assignments),
            review_manifest_sha256=review.review_manifest_sha256,
        )


class _ReviewRuntimeError(RuntimeError):
    def __init__(self, code: str, next_action: str) -> None:
        super().__init__(code)
        self.code = code
        self.next_action = next_action


class _AssignmentState:
    def __init__(self, context: ChildTaskContext, result: AgentResult) -> None:
        self.context = context
        self.original_sha256 = agent_result_sha256(result)
        self.result = result
        self.result_sha256 = self.original_sha256
        self.history: list[ReviewResult] = []
        self.correction_count = 0
        self.decision: ReviewDecision | None = None


class ReviewWorkflow:
    """Review every completed professional result before Main aggregation."""

    async def run(
        self,
        schedule: ScheduleResult,
        contexts: Sequence[ChildTaskContext],
        *,
        reviewer: ReviewExecutor,
        reviewer_definition: ReviewerDefinition,
        correctors: Mapping[str, CorrectionExecutor],
        budget_guard: BudgetGuard,
        cross_result_required: bool | None = None,
    ) -> ReviewWorkflowResult:
        prepared, reviewable, skipped, require_cross = self._validate(
            schedule,
            contexts,
            correctors,
            budget_guard,
            cross_result_required,
        )
        states = {
            item.assignment_id: _AssignmentState(item, reviewable[item.assignment_id])
            for item in prepared
            if item.assignment_id in reviewable
        }
        transitions: list[ReviewTransition] = []
        cross_history: list[ReviewResult] = []
        review_calls = 0
        correction_calls = 0
        phase = ReviewPhase.PREPARED

        def move(target: ReviewPhase, event: str, *, budget_stop: bool = False) -> None:
            nonlocal phase
            if target in {
                ReviewPhase.COMPLETED,
                ReviewPhase.CONFLICT,
                ReviewPhase.HUMAN_REQUIRED,
                ReviewPhase.FAILED,
            }:
                budget_guard.record_terminal_transition(budget_stop=budget_stop)
            else:
                budget_guard.record_graph_step(action_class=BudgetActionClass.VALIDATION)
            transitions.append(
                ReviewTransition(
                    sequence=len(transitions) + 1,
                    source=phase,
                    target=target,
                    event=event,
                )
            )
            phase = target

        pending = tuple(states)
        try:
            while True:
                move(ReviewPhase.PER_RESULT_REVIEW, "per_result_review_started")
                budget_guard.record_review()
                decisions: dict[str, ReviewResult] = {}
                for assignment_id in pending:
                    state = states[assignment_id]
                    context = _review_context(
                        schedule,
                        reviewer_definition,
                        (state,),
                        ReviewKind.PER_RESULT,
                    )
                    review_calls += 1
                    review = await self._call_reviewer(
                        reviewer,
                        context,
                        reviewer_definition.review_timeout_ms,
                    )
                    state.history.append(review)
                    state.decision = review.decision
                    decisions[assignment_id] = review

                blocking = self._blocking_decision(decisions.values())
                if blocking is not None:
                    target_phase, status, code, action = blocking
                    move(target_phase, f"per_result_{code.lower()}")
                    return self._result(
                        schedule,
                        states,
                        skipped,
                        cross_history,
                        transitions,
                        review_calls,
                        correction_calls,
                        budget_guard,
                        status=status,
                        error_code=code,
                        next_action=action,
                    )

                revise_ids = tuple(
                    assignment_id
                    for assignment_id, review in decisions.items()
                    if review.decision is ReviewDecision.REVISE
                )
                if revise_ids:
                    move(ReviewPhase.CORRECTION, "targeted_correction_started")
                    correction_calls += await self._correct(
                        schedule,
                        states,
                        revise_ids,
                        decisions,
                        correctors,
                        reviewer_definition,
                        budget_guard,
                        cross=False,
                    )
                    pending = revise_ids
                    continue

                if require_cross:
                    move(ReviewPhase.CROSS_RESULT_REVIEW, "cross_result_review_started")
                    context = _review_context(
                        schedule,
                        reviewer_definition,
                        tuple(states.values()),
                        ReviewKind.CROSS_RESULT,
                    )
                    review_calls += 1
                    cross_review = await self._call_reviewer(
                        reviewer,
                        context,
                        reviewer_definition.review_timeout_ms,
                    )
                    cross_history.append(cross_review)
                    if cross_review.decision is ReviewDecision.REVISE:
                        targets = self._cross_revision_targets(cross_review, states)
                        move(ReviewPhase.CORRECTION, "cross_result_correction_started")
                        correction_calls += await self._correct(
                            schedule,
                            states,
                            targets,
                            {assignment_id: cross_review for assignment_id in targets},
                            correctors,
                            reviewer_definition,
                            budget_guard,
                            cross=True,
                        )
                        pending = targets
                        continue
                    blocking = self._blocking_decision((cross_review,))
                    if blocking is not None:
                        target_phase, status, code, action = blocking
                        move(target_phase, f"cross_result_{code.lower()}")
                        return self._result(
                            schedule,
                            states,
                            skipped,
                            cross_history,
                            transitions,
                            review_calls,
                            correction_calls,
                            budget_guard,
                            status=status,
                            error_code=code,
                            next_action=action,
                        )

                move(ReviewPhase.COMPLETED, "review_manifest_ready")
                return self._result(
                    schedule,
                    states,
                    skipped,
                    cross_history,
                    transitions,
                    review_calls,
                    correction_calls,
                    budget_guard,
                    status=(
                        ReviewWorkflowStatus.PARTIAL if skipped else ReviewWorkflowStatus.APPROVED
                    ),
                )
        except BudgetExceeded as error:
            budget_guard.record_terminal_transition(budget_stop=True)
            transitions.append(
                ReviewTransition(
                    sequence=len(transitions) + 1,
                    source=phase,
                    target=ReviewPhase.FAILED,
                    event="review_budget_stopped",
                )
            )
            return self._result(
                schedule,
                states,
                skipped,
                cross_history,
                transitions,
                review_calls,
                correction_calls,
                budget_guard,
                status=ReviewWorkflowStatus.FAILED,
                error_code=error.code,
                next_action=error.next_action,
            )
        except _ReviewRuntimeError as error:
            move(ReviewPhase.FAILED, error.code.lower())
            return self._result(
                schedule,
                states,
                skipped,
                cross_history,
                transitions,
                review_calls,
                correction_calls,
                budget_guard,
                status=ReviewWorkflowStatus.FAILED,
                error_code=error.code,
                next_action=error.next_action,
            )

    @staticmethod
    async def _call_reviewer(
        reviewer: ReviewExecutor,
        context: ReviewContext,
        timeout_ms: int,
    ) -> ReviewResult:
        try:
            payload = await asyncio.wait_for(reviewer.review(context), timeout=timeout_ms / 1000)
        except TimeoutError as error:
            raise _ReviewRuntimeError(
                "REVIEW_TIMEOUT", "Retry with an available reviewer or require human review."
            ) from error
        except Exception as error:
            raise _ReviewRuntimeError(
                "REVIEW_EXECUTION_FAILED", "Inspect reviewer availability and preserved evidence."
            ) from error
        try:
            result = ReviewResult.model_validate(payload)
        except ValidationError as error:
            raise _ReviewRuntimeError(
                "REVIEW_RESULT_INVALID", "Repair the reviewer output contract before retrying."
            ) from error
        if (
            result.task_id != context.task_id
            or result.target_run_id != context.review_target_run_id
            or result.target_sha256 != context.review_target_sha256
            or result.reviewer_version != context.reviewer_version
            or result.correction_count != context.correction_count
        ):
            raise _ReviewRuntimeError(
                "REVIEW_RESULT_BINDING_INVALID",
                "Rerun the reviewer against the exact current result and registered version.",
            )
        _validate_findings(result)
        return result

    async def _correct(
        self,
        schedule: ScheduleResult,
        states: Mapping[str, _AssignmentState],
        assignment_ids: tuple[str, ...],
        decisions: Mapping[str, ReviewResult],
        correctors: Mapping[str, CorrectionExecutor],
        definition: ReviewerDefinition,
        guard: BudgetGuard,
        *,
        cross: bool,
    ) -> int:
        guard.record_correction()
        calls = 0
        for assignment_id in assignment_ids:
            state = states[assignment_id]
            corrector = correctors.get(assignment_id)
            if corrector is None:
                raise _ReviewRuntimeError(
                    "CORRECTION_EXECUTOR_REQUIRED",
                    f"Bind the responsible corrector for assignment {assignment_id}.",
                )
            review = decisions[assignment_id]
            findings = (
                tuple(
                    finding
                    for finding in review.findings
                    if not cross or finding.affected_path == f"assignment:{assignment_id}"
                )
                or review.findings
            )
            next_count = state.correction_count + 1
            if next_count > state.context.budget.correction_rounds.hard:
                raise _ReviewRuntimeError(
                    "CORRECTION_HARD_LIMIT_EXCEEDED",
                    "Return the unrepaired result for human or Main Agent handling.",
                )
            correction_context = _correction_context(
                schedule,
                state,
                findings,
                next_count,
                tuple(other for key, other in states.items() if cross and key != assignment_id),
            )
            calls += 1
            try:
                payload = await asyncio.wait_for(
                    corrector.correct(correction_context),
                    timeout=definition.correction_timeout_ms / 1000,
                )
            except TimeoutError as error:
                raise _ReviewRuntimeError(
                    "CORRECTION_TIMEOUT",
                    "Retry the bounded repair with an available responsible executor.",
                ) from error
            except Exception as error:
                raise _ReviewRuntimeError(
                    "CORRECTION_EXECUTION_FAILED",
                    "Inspect the responsible executor and preserved review findings.",
                ) from error
            try:
                corrected = AgentResult.model_validate(payload)
            except ValidationError as error:
                raise _ReviewRuntimeError(
                    "CORRECTION_RESULT_INVALID",
                    "Repair the correction output contract and revalidate the target.",
                ) from error
            if (
                corrected.task_id != schedule.parent_task_id
                or corrected.run_id != state.context.run_id
            ):
                raise _ReviewRuntimeError(
                    "CORRECTION_RESULT_BINDING_INVALID",
                    "Return a result for the exact task and responsible child run.",
                )
            if corrected.status not in {AgentStatus.SUCCESS, AgentStatus.PARTIAL_SUCCESS}:
                raise _ReviewRuntimeError(
                    "CORRECTION_UNSUCCESSFUL",
                    "Preserve the failure and require different input, executor, or human review.",
                )
            if any(artifact.scope != schedule.scope for artifact in corrected.artifacts):
                raise _ReviewRuntimeError(
                    "CORRECTION_RESULT_SCOPE_DENIED",
                    "Remove cross-scope artifacts and rerun the bounded repair.",
                )
            corrected_sha256 = agent_result_sha256(corrected)
            if corrected_sha256 == state.result_sha256:
                raise _ReviewRuntimeError(
                    "CORRECTION_NO_CHANGE",
                    "Return changed evidence or stop with the unrepaired result.",
                )
            state.result = corrected
            state.result_sha256 = corrected_sha256
            state.correction_count = next_count
            state.decision = None
        return calls

    @staticmethod
    def _cross_revision_targets(
        review: ReviewResult, states: Mapping[str, _AssignmentState]
    ) -> tuple[str, ...]:
        targets: list[str] = []
        for finding in review.findings:
            path = finding.affected_path or ""
            if not path.startswith("assignment:"):
                raise _ReviewRuntimeError(
                    "CROSS_REVIEW_TARGET_INVALID",
                    "Identify every repair target as assignment:<assignment_id>.",
                )
            assignment_id = path.removeprefix("assignment:")
            if assignment_id not in states:
                raise _ReviewRuntimeError(
                    "CROSS_REVIEW_TARGET_INVALID",
                    "Use an assignment ID from the current reviewed schedule.",
                )
            if assignment_id not in targets:
                targets.append(assignment_id)
        if not targets:
            raise _ReviewRuntimeError(
                "CROSS_REVIEW_TARGET_INVALID",
                "Provide at least one exact assignment repair target.",
            )
        return tuple(targets)

    @staticmethod
    def _blocking_decision(
        reviews: Iterable[ReviewResult],
    ) -> tuple[ReviewPhase, ReviewWorkflowStatus, str, str] | None:
        decisions = {review.decision for review in reviews}
        if ReviewDecision.HUMAN_REQUIRED in decisions:
            return (
                ReviewPhase.HUMAN_REQUIRED,
                ReviewWorkflowStatus.HUMAN_REQUIRED,
                "REVIEW_HUMAN_REQUIRED",
                "Pause aggregation and obtain a qualified human decision.",
            )
        if ReviewDecision.CONFLICT in decisions:
            return (
                ReviewPhase.CONFLICT,
                ReviewWorkflowStatus.CONFLICT,
                "REVIEW_CONFLICT",
                "Return the conflict evidence to Main for one optional bounded replan.",
            )
        if ReviewDecision.FAILED in decisions:
            return (
                ReviewPhase.FAILED,
                ReviewWorkflowStatus.FAILED,
                "REVIEW_FAILED",
                "Inspect the preserved findings and use a different input or reviewer.",
            )
        return None

    @staticmethod
    def _validate(
        schedule: ScheduleResult,
        contexts: Sequence[ChildTaskContext],
        correctors: Mapping[str, CorrectionExecutor],
        guard: BudgetGuard,
        cross_result_required: bool | None,
    ) -> tuple[
        tuple[ChildTaskContext, ...],
        dict[str, AgentResult],
        tuple[str, ...],
        bool,
    ]:
        prepared = tuple(contexts)
        assignment_ids = tuple(item.assignment_id for item in prepared)
        if not prepared or len(set(assignment_ids)) != len(prepared):
            raise ReviewError(
                "REVIEW_CONTEXT_SET_INVALID",
                "Review requires one unique context per scheduled assignment.",
                "Rebuild the contexts from the exact schedule.",
            )
        if set(assignment_ids) != {item.assignment_id for item in schedule.assignments}:
            raise ReviewError(
                "REVIEW_ASSIGNMENT_MISMATCH",
                "Review contexts do not match the schedule assignments.",
                "Provide every and only the exact scheduled contexts.",
            )
        if any(
            item.context_manifest_sha256 != child_context_manifest_sha256(item) for item in prepared
        ):
            raise ReviewError(
                "REVIEW_CONTEXT_INTEGRITY_FAILED",
                "A professional context does not match its immutable manifest.",
                "Rebuild review inputs from the verified dispatch context.",
            )
        first = prepared[0]
        if any(
            item.kind is not ChildAgentKind.PROFESSIONAL
            or item.parent_task_id != schedule.parent_task_id
            or item.scope != schedule.scope
            for item in prepared
        ):
            raise ReviewError(
                "REVIEW_TOPOLOGY_DENIED",
                "Only one scope-bound professional schedule may enter Review Graph.",
                "Send General output directly to Main or rebuild the professional binding.",
            )
        if guard.policy != first.budget or any(item.budget != first.budget for item in prepared):
            raise ReviewError(
                "REVIEW_BUDGET_MISMATCH",
                "Review must use the exact professional task budget.",
                "Continue with the parent-bound guard and matching child contexts.",
            )
        if not set(correctors) <= set(assignment_ids):
            raise ReviewError(
                "REVIEW_CORRECTOR_UNKNOWN",
                "A corrector is bound to an unknown assignment.",
                "Bind correctors only to responsible scheduled children.",
            )
        by_id = {item.assignment_id: item for item in schedule.assignments}
        reviewable: dict[str, AgentResult] = {}
        skipped: list[str] = []
        for context in prepared:
            assignment = by_id[context.assignment_id]
            if assignment.status is not AssignmentStatus.COMPLETED:
                skipped.append(context.assignment_id)
                continue
            outcome = assignment.outcome
            if (
                outcome is None
                or outcome.result is None
                or not outcome.review_required
                or outcome.aggregation_ready
                or outcome.run_id != context.run_id
            ):
                raise ReviewError(
                    "REVIEW_PENDING_INVARIANT_FAILED",
                    "A completed professional result is not review-pending or identity-bound.",
                    "Restore the verified child outcome before review.",
                )
            reviewable[context.assignment_id] = outcome.result
            if any(artifact.scope != schedule.scope for artifact in outcome.result.artifacts):
                raise ReviewError(
                    "REVIEW_RESULT_SCOPE_DENIED",
                    "A professional result contains an artifact outside the review scope.",
                    "Quarantine the result and restore scope-bound evidence.",
                )
        if not reviewable:
            raise ReviewError(
                "REVIEW_RESULT_REQUIRED",
                "The schedule contains no completed professional result to review.",
                "Resolve schedule failures before entering Review Graph.",
            )
        interacts = any(context.dependency_assignment_ids for context in prepared)
        if cross_result_required is False and interacts:
            raise ReviewError(
                "CROSS_REVIEW_REQUIRED",
                "Interacting professional results cannot bypass cross-result review.",
                "Enable cross-result review for this schedule.",
            )
        require_cross = interacts if cross_result_required is None else cross_result_required
        require_cross = bool(require_cross and len(reviewable) > 1)
        return prepared, reviewable, tuple(skipped), require_cross

    @staticmethod
    def _result(
        schedule: ScheduleResult,
        states: Mapping[str, _AssignmentState],
        skipped: tuple[str, ...],
        cross_history: Sequence[ReviewResult],
        transitions: Sequence[ReviewTransition],
        review_calls: int,
        correction_calls: int,
        guard: BudgetGuard,
        *,
        status: ReviewWorkflowStatus,
        error_code: str | None = None,
        next_action: str | None = None,
    ) -> ReviewWorkflowResult:
        aggregatable = status in {ReviewWorkflowStatus.APPROVED, ReviewWorkflowStatus.PARTIAL}
        assignments = tuple(
            ReviewedAssignment(
                assignment_id=assignment_id,
                run_id=state.context.run_id,
                original_result_sha256=state.original_sha256,
                current_result_sha256=state.result_sha256,
                current_result=state.result,
                review_history=tuple(state.history),
                correction_count=state.correction_count,
                decision=state.decision,
                aggregation_ready=aggregatable and state.decision is ReviewDecision.PASS,
            )
            for assignment_id, state in states.items()
        )
        manifest_payload = {
            "schema_version": "1.0.0",
            "schedule_id": str(schedule.schedule_id),
            "task_id": str(schedule.parent_task_id),
            "scope": schedule.scope.model_dump(mode="json"),
            "status": status.value,
            "assignments": [item.model_dump(mode="json") for item in assignments],
            "skipped_assignment_ids": skipped,
            "cross_review_history": [item.model_dump(mode="json") for item in cross_history],
        }
        return ReviewWorkflowResult(
            schedule_id=schedule.schedule_id,
            task_id=schedule.parent_task_id,
            scope=schedule.scope,
            status=status,
            assignments=assignments,
            skipped_assignment_ids=skipped,
            cross_review_history=tuple(cross_history),
            transitions=tuple(transitions),
            review_calls=review_calls,
            correction_calls=correction_calls,
            aggregation_ready=aggregatable,
            review_manifest_sha256=_sha256(manifest_payload),
            budget_telemetry=guard.telemetry(),
            error_code=error_code,
            next_action=next_action,
            completed_at=datetime.now(UTC),
        )


def agent_result_sha256(result: AgentResult) -> str:
    return _sha256(result.model_dump(mode="json"))


def review_context_manifest_sha256(context: ReviewContext) -> str:
    return _sha256(context.model_dump(mode="json", exclude={"context_manifest_sha256"}))


def correction_context_manifest_sha256(context: CorrectionContext) -> str:
    return _sha256(context.model_dump(mode="json", exclude={"context_manifest_sha256"}))


def review_manifest_sha256(result: ReviewWorkflowResult) -> str:
    return _sha256(
        {
            "schema_version": result.schema_version,
            "schedule_id": str(result.schedule_id),
            "task_id": str(result.task_id),
            "scope": result.scope.model_dump(mode="json"),
            "status": result.status.value,
            "assignments": [item.model_dump(mode="json") for item in result.assignments],
            "skipped_assignment_ids": result.skipped_assignment_ids,
            "cross_review_history": [
                item.model_dump(mode="json") for item in result.cross_review_history
            ],
        }
    )


def _review_context(
    schedule: ScheduleResult,
    definition: ReviewerDefinition,
    states: tuple[_AssignmentState, ...],
    kind: ReviewKind,
) -> ReviewContext:
    targets = tuple(
        ReviewTarget(
            assignment_id=state.context.assignment_id,
            run_id=state.context.run_id,
            result_sha256=state.result_sha256,
            result=state.result,
        )
        for state in states
    )
    target_run_id = targets[0].run_id if kind is ReviewKind.PER_RESULT else schedule.schedule_id
    target_sha256 = (
        targets[0].result_sha256
        if kind is ReviewKind.PER_RESULT
        else _sha256(
            [
                {"assignment_id": target.assignment_id, "sha256": target.result_sha256}
                for target in targets
            ]
        )
    )
    checklist = tuple(
        dict.fromkeys(item for state in states for item in state.context.review_checklist)
    )
    payload: dict[str, Any] = {
        "kind": kind,
        "task_id": schedule.parent_task_id,
        "scope": schedule.scope,
        "schedule_id": schedule.schedule_id,
        "review_target_run_id": target_run_id,
        "review_target_sha256": target_sha256,
        "targets": targets,
        "review_checklist": checklist,
        "reviewer_version": definition.reviewer_version,
        "prompt_version": definition.prompt_version,
        "model_version": definition.model_version,
        "correction_count": max(state.correction_count for state in states),
    }
    payload["context_manifest_sha256"] = _sha256(
        ReviewContext.model_construct(**payload, context_manifest_sha256="0" * 64).model_dump(
            mode="json", exclude={"context_manifest_sha256"}
        )
    )
    return ReviewContext.model_validate(payload)


def _correction_context(
    schedule: ScheduleResult,
    state: _AssignmentState,
    findings: tuple[Issue, ...],
    correction_count: int,
    related: tuple[_AssignmentState, ...],
) -> CorrectionContext:
    instruction = "\n".join(finding.next_action or finding.message for finding in findings)
    payload: dict[str, Any] = {
        "task_id": schedule.parent_task_id,
        "scope": schedule.scope,
        "schedule_id": schedule.schedule_id,
        "assignment_id": state.context.assignment_id,
        "run_id": state.context.run_id,
        "agent_type": state.context.agent_type,
        "goal": state.context.goal,
        "success_criteria": state.context.success_criteria,
        "output_schema_id": state.context.output_schema_id,
        "current_result": state.result,
        "current_result_sha256": state.result_sha256,
        "findings": findings,
        "targeted_instruction": instruction,
        "related_targets": tuple(
            ReviewTarget(
                assignment_id=item.context.assignment_id,
                run_id=item.context.run_id,
                result_sha256=item.result_sha256,
                result=item.result,
            )
            for item in related
        ),
        "correction_count": correction_count,
    }
    payload["context_manifest_sha256"] = _sha256(
        CorrectionContext.model_construct(**payload, context_manifest_sha256="0" * 64).model_dump(
            mode="json", exclude={"context_manifest_sha256"}
        )
    )
    return CorrectionContext.model_validate(payload)


def _validate_findings(result: ReviewResult) -> None:
    severe = {"ERROR", "CRITICAL"}
    if result.decision is ReviewDecision.PASS:
        if any(finding.severity in severe for finding in result.findings):
            raise _ReviewRuntimeError(
                "REVIEW_FINDINGS_INVALID",
                "Resolve error or critical findings before returning PASS.",
            )
        return
    if not result.findings or any(finding.next_action is None for finding in result.findings):
        raise _ReviewRuntimeError(
            "REVIEW_FINDINGS_INVALID",
            "Return at least one actionable finding for every non-pass decision.",
        )


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
