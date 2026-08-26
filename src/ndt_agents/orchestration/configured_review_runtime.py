"""Automatic configured review and Main aggregation assembly."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid5

from ndt_agents.contracts.v1 import TaskContext, TenantScope
from ndt_agents.models.instructions import ApplicationInstruction
from ndt_agents.orchestration.agent_config import ConfiguredAgentRuntime
from ndt_agents.orchestration.budget import BudgetGuard
from ndt_agents.orchestration.child_models import (
    ChildAgentKind,
    ChildInput,
    ChildTaskContext,
)
from ndt_agents.orchestration.configured_runtime import (
    ConfiguredOrchestrationRuntime,
    ConfiguredRunResult,
    ConfiguredRunStatus,
    validate_configured_child_context,
)
from ndt_agents.orchestration.models import RouteSignals
from ndt_agents.orchestration.prompt_registry import PromptRegistryError
from ndt_agents.orchestration.review import (
    CorrectionContext,
    CorrectionExecutor,
    MainAggregationGate,
    MainAggregationInput,
    ReviewContext,
    ReviewerDefinition,
    ReviewError,
    ReviewExecutor,
    ReviewWorkflow,
    ReviewWorkflowResult,
)
from ndt_agents.orchestration.review_recovery import (
    RecoverableReviewWorkflow,
    ReviewRecoveryError,
    ReviewRecoveryRepository,
)
from ndt_agents.orchestration.scheduler import (
    AssignmentStatus,
    ScheduleHandle,
    ScheduleResult,
)

_REVIEW_RECOVERY_NAMESPACE = UUID("00000000-0000-4000-8000-000000001016")


class ConfiguredReviewerDelegate(Protocol):
    async def review(
        self,
        context: ReviewContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]: ...


class ConfiguredCorrectionDelegate(Protocol):
    async def correct(
        self,
        context: CorrectionContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]: ...


class _PromptBoundReviewer:
    def __init__(
        self,
        delegate: ConfiguredReviewerDelegate,
        instruction: ApplicationInstruction,
    ) -> None:
        self._delegate = delegate
        self._instruction = instruction

    async def review(self, context: ReviewContext) -> Mapping[str, Any]:
        return await self._delegate.review(context, self._instruction)


class _PromptBoundCorrector:
    def __init__(
        self,
        delegate: ConfiguredCorrectionDelegate,
        instruction: ApplicationInstruction,
    ) -> None:
        self._delegate = delegate
        self._instruction = instruction

    async def correct(self, context: CorrectionContext) -> Mapping[str, Any]:
        return await self._delegate.correct(context, self._instruction)


class ConfiguredReviewRuntimeError(RuntimeError):
    """Stable configured review-assembly rejection."""

    def __init__(self, code: str, message: str, next_action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action


class ConfiguredReviewedStatus(StrEnum):
    ROUTE_STOPPED = "ROUTE_STOPPED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    QUEUED = "QUEUED"
    EXECUTION_STOPPED = "EXECUTION_STOPPED"
    REVIEW_STOPPED = "REVIEW_STOPPED"
    AGGREGATION_READY = "AGGREGATION_READY"


@dataclass(frozen=True, slots=True)
class ConfiguredReviewedRunResult:
    configuration_sha256: str
    status: ConfiguredReviewedStatus
    execution: ConfiguredRunResult
    review: ReviewWorkflowResult | None
    aggregation: MainAggregationInput | None
    review_recovery_id: UUID | None
    error_code: str | None
    next_action: str | None


class ConfiguredReviewBindings:
    """Bind configured professional profile names to correction executors."""

    def __init__(
        self,
        runtime: ConfiguredAgentRuntime,
        *,
        reviewer: ConfiguredReviewerDelegate,
        reviewer_definition: ReviewerDefinition,
        correctors: Mapping[str, ConfiguredCorrectionDelegate],
        review_prompt_name: str = "review",
    ) -> None:
        professional = {
            profile.name
            for profile in runtime.profiles
            if profile.kind is ChildAgentKind.PROFESSIONAL
        }
        if set(correctors) != professional:
            raise ConfiguredReviewRuntimeError(
                "CONFIGURED_CORRECTOR_CATALOG_MISMATCH",
                "The correction catalog does not match configured professional profiles.",
                "Register exactly one correction executor for every professional profile.",
            )
        try:
            review_prompt = runtime.prompt_registry.resolve(review_prompt_name)
        except PromptRegistryError as error:
            raise ConfiguredReviewRuntimeError(
                "CONFIGURED_REVIEW_PROMPT_NOT_FOUND",
                "The configured Review Agent prompt is not available.",
                "Register the exact Review Agent prompt in the active prompt catalog.",
            ) from error
        if review_prompt.version != reviewer_definition.prompt_version:
            raise ConfiguredReviewRuntimeError(
                "CONFIGURED_REVIEW_PROMPT_MISMATCH",
                "The reviewer definition does not match the active Review Agent prompt.",
                "Use the exact active review prompt version in the reviewer definition.",
            )
        self.runtime = runtime
        self.review_instruction = review_prompt.instruction
        self.reviewer: ReviewExecutor = _PromptBoundReviewer(
            reviewer,
            review_prompt.instruction,
        )
        self.reviewer_definition = reviewer_definition
        self._correctors: dict[str, CorrectionExecutor] = {
            profile_name: _PromptBoundCorrector(
                corrector,
                runtime.prompt_instruction(profile_name),
            )
            for profile_name, corrector in correctors.items()
        }

    def bind_correctors(
        self, contexts: Sequence[ChildTaskContext]
    ) -> Mapping[str, CorrectionExecutor]:
        bound: dict[str, CorrectionExecutor] = {}
        for context in contexts:
            profile = validate_configured_child_context(self.runtime, context)
            if profile.kind is not ChildAgentKind.PROFESSIONAL:
                raise ConfiguredReviewRuntimeError(
                    "CONFIGURED_REVIEW_TOPOLOGY_DENIED",
                    "Only configured professional contexts may bind correction executors.",
                    "Send General work through the direct Main aggregation gate.",
                )
            if context.assignment_id in bound:
                raise ConfiguredReviewRuntimeError(
                    "CONFIGURED_REVIEW_ASSIGNMENT_DUPLICATE",
                    "Configured review received a duplicate assignment ID.",
                    "Rebuild one private context per verified assignment.",
                )
            bound[context.assignment_id] = self._correctors[profile.name]
        return bound


class ConfiguredReviewedOrchestrationRuntime:
    """Complete configured execution through review to the Main aggregation boundary."""

    def __init__(
        self,
        orchestration: ConfiguredOrchestrationRuntime,
        bindings: ConfiguredReviewBindings,
        *,
        review_recovery_repository: ReviewRecoveryRepository | None = None,
    ) -> None:
        if (
            orchestration.agent_runtime.configuration_sha256
            != bindings.runtime.configuration_sha256
        ):
            raise ConfiguredReviewRuntimeError(
                "CONFIGURED_REVIEW_RUNTIME_MISMATCH",
                "Review bindings do not belong to the configured orchestration runtime.",
                "Build execution and review bindings from the same immutable configuration.",
            )
        self._orchestration = orchestration
        self._bindings = bindings
        self._review_recovery = (
            RecoverableReviewWorkflow(review_recovery_repository)
            if review_recovery_repository is not None
            else None
        )
        self._pending: dict[UUID, ConfiguredRunResult] = {}
        self._terminal: dict[UUID, ConfiguredReviewedRunResult] = {}

    async def start(
        self,
        task: TaskContext,
        signals: RouteSignals,
        *,
        professional_inputs: tuple[ChildInput, ...] = (),
    ) -> ConfiguredReviewedRunResult:
        execution = await self._orchestration.start(
            task,
            signals,
            professional_inputs=professional_inputs,
        )
        if execution.status is ConfiguredRunStatus.ROUTE_STOPPED:
            return self._stopped(
                execution,
                ConfiguredReviewedStatus.ROUTE_STOPPED,
                execution.main_result.error_code,
                execution.main_result.next_action,
            )
        if execution.status is ConfiguredRunStatus.HUMAN_REQUIRED:
            return self._stopped(
                execution,
                ConfiguredReviewedStatus.HUMAN_REQUIRED,
                "CONFIGURED_HUMAN_REQUIRED",
                "Complete the required human checkpoint before child execution.",
            )
        if isinstance(execution.schedule, ScheduleHandle):
            self._pending[execution.schedule.schedule_id] = execution
            return ConfiguredReviewedRunResult(
                configuration_sha256=execution.configuration_sha256,
                status=ConfiguredReviewedStatus.QUEUED,
                execution=execution,
                review=None,
                aggregation=None,
                review_recovery_id=None,
                error_code=None,
                next_action=None,
            )
        assert isinstance(execution.schedule, ScheduleResult)
        return await self.finalize(execution)

    async def advance(
        self,
        schedule_id: UUID,
        *,
        scope: TenantScope,
        parent_task_id: UUID,
    ) -> ConfiguredReviewedRunResult:
        terminal = self._terminal.get(schedule_id)
        if terminal is not None:
            schedule = terminal.execution.schedule
            assert isinstance(schedule, ScheduleResult)
            if schedule.scope != scope or schedule.parent_task_id != parent_task_id:
                raise ConfiguredReviewRuntimeError(
                    "CONFIGURED_REVIEW_BINDING_DENIED",
                    "The reviewed schedule does not belong to the requested identity and task.",
                    "Use the original complete scope and parent task binding.",
                )
            return terminal
        execution = self._pending.get(schedule_id)
        if execution is None:
            raise ConfiguredReviewRuntimeError(
                "CONFIGURED_REVIEW_SCHEDULE_NOT_FOUND",
                "No configured queued review schedule has this ID.",
                "Advance a handle returned by this configured review runtime.",
            )
        schedule = await self._orchestration.advance(
            schedule_id,
            scope=scope,
            parent_task_id=parent_task_id,
        )
        completed = ConfiguredRunResult(
            configuration_sha256=execution.configuration_sha256,
            status=execution.status,
            main_result=execution.main_result,
            contexts=execution.contexts,
            schedule=schedule,
        )
        result = await self.finalize(completed)
        self._pending.pop(schedule_id, None)
        return result

    async def finalize(self, execution: ConfiguredRunResult) -> ConfiguredReviewedRunResult:
        """Review one exact completed configured schedule, including after recovery."""

        if (
            execution.configuration_sha256 != self._orchestration.agent_runtime.configuration_sha256
            or not execution.contexts
            or not isinstance(execution.schedule, ScheduleResult)
        ):
            raise ConfiguredReviewRuntimeError(
                "CONFIGURED_REVIEW_EXECUTION_INVALID",
                "Review requires an exact completed schedule from this configured runtime.",
                "Restore or execute the schedule with the same immutable configuration.",
            )
        schedule = execution.schedule
        terminal = self._terminal.get(schedule.schedule_id)
        if terminal is not None:
            if terminal.execution != execution:
                raise ConfiguredReviewRuntimeError(
                    "CONFIGURED_REVIEW_FINALIZE_CONFLICT",
                    "The schedule ID is already bound to different configured execution input.",
                    "Reuse the original exact execution or create a new schedule.",
                )
            return terminal
        result = await self._finalize_uncached(execution, schedule)
        self._terminal[schedule.schedule_id] = result
        return result

    async def _finalize_uncached(
        self,
        execution: ConfiguredRunResult,
        schedule: ScheduleResult,
    ) -> ConfiguredReviewedRunResult:
        if execution.contexts[0].kind is ChildAgentKind.GENERAL:
            assignment = schedule.assignments[0]
            if assignment.outcome is None:
                return self._stopped(
                    execution,
                    ConfiguredReviewedStatus.EXECUTION_STOPPED,
                    assignment.error_code or "CONFIGURED_GENERAL_EXECUTION_FAILED",
                    assignment.next_action or "Inspect the failed General child outcome.",
                )
            try:
                aggregation = MainAggregationGate.general(execution.contexts[0], assignment.outcome)
            except ReviewError as error:
                return self._stopped(
                    execution,
                    ConfiguredReviewedStatus.EXECUTION_STOPPED,
                    error.code,
                    error.next_action,
                )
            return ConfiguredReviewedRunResult(
                configuration_sha256=execution.configuration_sha256,
                status=ConfiguredReviewedStatus.AGGREGATION_READY,
                execution=execution,
                review=None,
                aggregation=aggregation,
                review_recovery_id=None,
                error_code=None,
                next_action=None,
            )

        completed_assignments = tuple(
            assignment
            for assignment in schedule.assignments
            if assignment.status is AssignmentStatus.COMPLETED
        )
        if not completed_assignments:
            first = schedule.assignments[0]
            return self._stopped(
                execution,
                ConfiguredReviewedStatus.EXECUTION_STOPPED,
                first.error_code or "CONFIGURED_PROFESSIONAL_EXECUTION_FAILED",
                first.next_action or "Repair the failed professional schedule before review.",
            )
        try:
            correctors = self._bindings.bind_correctors(execution.contexts)
            recovery_id = uuid5(
                _REVIEW_RECOVERY_NAMESPACE,
                f"{execution.configuration_sha256}:{schedule.schedule_id}",
            )
            guard = BudgetGuard(execution.contexts[0].budget)
            cross_result_required = len(execution.contexts) > 1
            if self._review_recovery is None:
                review = await ReviewWorkflow().run(
                    schedule,
                    execution.contexts,
                    reviewer=self._bindings.reviewer,
                    reviewer_definition=self._bindings.reviewer_definition,
                    correctors=correctors,
                    budget_guard=guard,
                    cross_result_required=cross_result_required,
                )
                used_recovery_id = None
            else:
                recovered = await self._review_recovery.run(
                    recovery_id,
                    schedule,
                    execution.contexts,
                    reviewer=self._bindings.reviewer,
                    reviewer_definition=self._bindings.reviewer_definition,
                    correctors=correctors,
                    budget_guard=guard,
                    cross_result_required=cross_result_required,
                )
                review = recovered.result
                used_recovery_id = recovery_id
            if not review.aggregation_ready:
                return ConfiguredReviewedRunResult(
                    configuration_sha256=execution.configuration_sha256,
                    status=ConfiguredReviewedStatus.REVIEW_STOPPED,
                    execution=execution,
                    review=review,
                    aggregation=None,
                    review_recovery_id=used_recovery_id,
                    error_code=review.error_code,
                    next_action=review.next_action,
                )
            aggregation = MainAggregationGate.professional(review)
        except (ConfiguredReviewRuntimeError, ReviewError, ReviewRecoveryError) as error:
            return self._stopped(
                execution,
                ConfiguredReviewedStatus.REVIEW_STOPPED,
                error.code,
                error.next_action,
            )
        return ConfiguredReviewedRunResult(
            configuration_sha256=execution.configuration_sha256,
            status=ConfiguredReviewedStatus.AGGREGATION_READY,
            execution=execution,
            review=review,
            aggregation=aggregation,
            review_recovery_id=used_recovery_id,
            error_code=None,
            next_action=None,
        )

    @staticmethod
    def _stopped(
        execution: ConfiguredRunResult,
        status: ConfiguredReviewedStatus,
        error_code: str | None,
        next_action: str | None,
    ) -> ConfiguredReviewedRunResult:
        return ConfiguredReviewedRunResult(
            configuration_sha256=execution.configuration_sha256,
            status=status,
            execution=execution,
            review=None,
            aggregation=None,
            review_recovery_id=None,
            error_code=error_code or "CONFIGURED_REVIEW_STOPPED",
            next_action=next_action or "Inspect the preserved configured execution evidence.",
        )
