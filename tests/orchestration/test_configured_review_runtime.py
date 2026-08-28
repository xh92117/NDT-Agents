"""S1-16 configured review, correction, recovery, and aggregation tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import pytest

from ndt_agents.contracts.v1 import (
    AgentResult,
    Issue,
    Limit,
    ReviewDecision,
    ReviewResult,
    TaskContext,
)
from ndt_agents.models.config import load_model_runtime_configuration
from ndt_agents.models.instructions import ApplicationInstruction
from ndt_agents.models.registry import canonical_sha256
from ndt_agents.orchestration.agent_config import (
    ConfiguredAgentRuntime,
    load_agent_runtime_configuration,
)
from ndt_agents.orchestration.budget import default_budget_policy
from ndt_agents.orchestration.child_models import (
    ChildAgentKind,
    ChildInput,
    ChildTaskContext,
)
from ndt_agents.orchestration.configured_review_runtime import (
    ConfiguredReviewBindings,
    ConfiguredReviewedOrchestrationRuntime,
    ConfiguredReviewedStatus,
    ConfiguredReviewRuntimeError,
)
from ndt_agents.orchestration.configured_runtime import (
    ConfiguredExecutorFactory,
    ConfiguredOrchestrationRuntime,
)
from ndt_agents.orchestration.models import ProfessionalAssignment, RouteSignals
from ndt_agents.orchestration.prompt_registry import load_prompt_registry
from ndt_agents.orchestration.review import (
    AggregationSource,
    CorrectionContext,
    ReviewContext,
    ReviewerDefinition,
    ReviewKind,
)
from ndt_agents.orchestration.review_recovery import InMemoryReviewRecoveryRepository
from ndt_agents.orchestration.scheduler import ScheduleHandle
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings

ROOT = Path(__file__).resolve().parents[2]
TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
RESULT = AgentResult.model_validate_json(
    (ROOT / "examples/contracts/v1/agent-result.valid.json").read_text("utf-8")
)
PROMPT_CONFIG = ROOT / "prompts/professional/catalog.v1.yaml"
REVIEW_NAMESPACE = UUID("00000000-0000-4000-8000-000000001116")
REVIEWER_DEFINITION = ReviewerDefinition(
    reviewer_version="configured-reviewer-1",
    prompt_version="1.2.0",
    model_version="configured-review-model-1",
)


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def agent_runtime(*professional_names: str) -> ConfiguredAgentRuntime:
    models = load_model_runtime_configuration(
        ROOT / "config/runtime/model-bindings.example.yaml", environ={}
    )
    base = load_agent_runtime_configuration(
        ROOT / "config/runtime/agent-runtime.example.yaml",
        model_runtime=models,
        prompt_registry=load_prompt_registry(PROMPT_CONFIG),
    )
    if not professional_names:
        return base
    general = base.profile("general")
    professionals = tuple(
        general.model_copy(
            update={
                "name": name,
                "kind": ChildAgentKind.PROFESSIONAL,
                "description": f"Configured {name} review profile.",
                "skill_version": f"{name}-1",
            }
        )
        for name in professional_names
    )
    configuration_sha256 = canonical_sha256(
        {
            "base": base.configuration_sha256,
            "professional_names": professional_names,
        }
    )
    return replace(
        base,
        profiles=tuple(sorted((general, *professionals), key=lambda item: item.name)),
        configuration_sha256=configuration_sha256,
    )


class ChildDelegate:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.instructions: list[ApplicationInstruction] = []

    async def execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        self.calls += 1
        self.instructions.append(instruction)
        if self.fail:
            raise RuntimeError("configured child failure")
        return RESULT.model_copy(
            update={
                "task_id": context.parent_task_id,
                "run_id": context.run_id,
                "summary": f"Configured {context.assignment_id} result",
            }
        ).model_dump(mode="json")


class ReviewerProbe:
    def __init__(
        self,
        decide: Callable[[ReviewContext], ReviewDecision] | None = None,
    ) -> None:
        self._decide = decide or (lambda _context: ReviewDecision.PASS)
        self.contexts: list[ReviewContext] = []
        self.instructions: list[ApplicationInstruction] = []

    async def review(
        self,
        context: ReviewContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        self.contexts.append(context)
        self.instructions.append(instruction)
        decision = self._decide(context)
        findings = (
            ()
            if decision is ReviewDecision.PASS
            else (
                Issue(
                    code="CONFIGURED_REVIEW_FINDING",
                    severity="ERROR",
                    message="The configured result requires attention.",
                    affected_path=(
                        f"assignment:{context.targets[0].assignment_id}"
                        if context.kind is ReviewKind.CROSS_RESULT
                        else "summary"
                    ),
                    next_action="Repair only the identified configured result.",
                ),
            )
        )
        return ReviewResult(
            review_id=uuid5(
                REVIEW_NAMESPACE,
                f"{context.review_target_sha256}:{context.correction_count}:{decision}",
            ),
            task_id=context.task_id,
            target_run_id=context.review_target_run_id,
            target_sha256=context.review_target_sha256,
            reviewer_version=context.reviewer_version,
            decision=decision,
            findings=findings,
            correction_count=context.correction_count,
            completed_at=datetime(2026, 8, 26, tzinfo=UTC),
        ).model_dump(mode="json")


class CorrectorProbe:
    def __init__(self) -> None:
        self.contexts: list[CorrectionContext] = []
        self.instructions: list[ApplicationInstruction] = []

    async def correct(
        self,
        context: CorrectionContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        self.contexts.append(context)
        self.instructions.append(instruction)
        return context.current_result.model_copy(
            update={"summary": f"Corrected {context.assignment_id}"}
        ).model_dump(mode="json")


def configured_review_runtime(
    runtime: ConfiguredAgentRuntime,
    reviewer: ReviewerProbe,
    *,
    child_failures: frozenset[str] = frozenset(),
    correctors: Mapping[str, CorrectorProbe] | None = None,
    repository: InMemoryReviewRecoveryRepository | None = None,
    reviewer_definition: ReviewerDefinition = REVIEWER_DEFINITION,
) -> tuple[
    ConfiguredReviewedOrchestrationRuntime,
    dict[str, ChildDelegate],
    dict[str, CorrectorProbe],
]:
    children = {
        profile.name: ChildDelegate(fail=profile.name in child_failures)
        for profile in runtime.profiles
    }
    professionals = {
        profile.name for profile in runtime.profiles if profile.kind is ChildAgentKind.PROFESSIONAL
    }
    active_correctors = dict(correctors or {name: CorrectorProbe() for name in professionals})
    execution = ConfiguredOrchestrationRuntime(ConfiguredExecutorFactory(runtime, children))
    bindings = ConfiguredReviewBindings(
        runtime,
        reviewer=reviewer,
        reviewer_definition=reviewer_definition,
        correctors=active_correctors,
    )
    return (
        ConfiguredReviewedOrchestrationRuntime(
            execution,
            bindings,
            review_recovery_repository=repository,
        ),
        children,
        active_correctors,
    )


def professional_request(
    *names: str,
    asynchronous: bool,
    review_rounds: int = 1,
) -> tuple[TaskContext, RouteSignals, tuple[ChildInput, ...]]:
    policy = default_budget_policy("P3").model_copy(
        update={"review_rounds": Limit(default=1, active=review_rounds, hard=2)}
    )
    task = TASK.model_copy(update={"task_class": "P3", "budget": policy})
    assignments = tuple(
        ProfessionalAssignment(assignment_id=f"work-{name}", agent_type=name) for name in names
    )
    signals = RouteSignals(
        task_id=task.task_id,
        general_eligible=False,
        professional_assignments=assignments,
        asynchronous_required=asynchronous,
    )
    inputs = tuple(
        ChildInput(
            assignment_id=assignment.assignment_id,
            goal=f"Produce {assignment.agent_type}",
            success_criteria=("Return one configured result",),
        )
        for assignment in assignments
    )
    return task, signals, inputs


def test_general_result_uses_main_aggregation_gate_without_review_call() -> None:
    runtime = agent_runtime()
    reviewer = ReviewerProbe()
    configured, children, _ = configured_review_runtime(runtime, reviewer)
    signals = RouteSignals(task_id=TASK.task_id, general_eligible=True)

    result = run(configured.start(TASK, signals))

    assert result.status is ConfiguredReviewedStatus.AGGREGATION_READY
    assert result.review is None
    assert result.aggregation is not None
    assert result.aggregation.source is AggregationSource.GENERAL
    assert result.aggregation.user_delivery_allowed is False
    assert reviewer.contexts == []
    assert children["general"].calls == 1


def test_synchronous_professional_result_is_reviewed_before_return() -> None:
    runtime = agent_runtime("alpha")
    reviewer = ReviewerProbe()
    configured, _, _ = configured_review_runtime(runtime, reviewer)
    task, signals, inputs = professional_request("alpha", asynchronous=False)

    result = run(configured.start(task, signals, professional_inputs=inputs))
    repeated = run(configured.finalize(result.execution))

    assert repeated is result
    assert result.status is ConfiguredReviewedStatus.AGGREGATION_READY
    assert result.review is not None and result.review.review_calls == 1
    assert [instruction.instruction_id for instruction in reviewer.instructions] == ["review"]
    assert result.aggregation is not None
    assert result.aggregation.source is AggregationSource.REVIEWED_PROFESSIONAL
    assert result.aggregation.review_manifest_sha256 == result.review.review_manifest_sha256
    assert result.aggregation.user_delivery_allowed is False


def test_queued_multiple_results_receive_per_result_and_cross_review() -> None:
    runtime = agent_runtime("alpha", "beta")
    reviewer = ReviewerProbe()
    configured, _, _ = configured_review_runtime(runtime, reviewer)
    task, signals, inputs = professional_request("alpha", "beta", asynchronous=True)

    queued = run(configured.start(task, signals, professional_inputs=inputs))

    assert queued.status is ConfiguredReviewedStatus.QUEUED
    assert isinstance(queued.execution.schedule, ScheduleHandle)
    assert reviewer.contexts == []
    completed = run(
        configured.advance(
            queued.execution.schedule.schedule_id,
            scope=task.scope,
            parent_task_id=task.task_id,
        )
    )
    repeated = run(
        configured.advance(
            queued.execution.schedule.schedule_id,
            scope=task.scope,
            parent_task_id=task.task_id,
        )
    )

    assert completed is repeated
    assert completed.status is ConfiguredReviewedStatus.AGGREGATION_READY
    assert completed.review is not None and completed.review.review_calls == 3
    assert [context.kind for context in reviewer.contexts] == [
        ReviewKind.PER_RESULT,
        ReviewKind.PER_RESULT,
        ReviewKind.CROSS_RESULT,
    ]


def test_revision_uses_profile_bound_corrector_then_re_reviews() -> None:
    runtime = agent_runtime("alpha")
    reviewer = ReviewerProbe(
        lambda context: (
            ReviewDecision.REVISE
            if context.kind is ReviewKind.PER_RESULT and context.correction_count == 0
            else ReviewDecision.PASS
        )
    )
    corrector = CorrectorProbe()
    configured, _, _ = configured_review_runtime(
        runtime,
        reviewer,
        correctors={"alpha": corrector},
    )
    task, signals, inputs = professional_request("alpha", asynchronous=False, review_rounds=2)

    result = run(configured.start(task, signals, professional_inputs=inputs))

    assert result.status is ConfiguredReviewedStatus.AGGREGATION_READY
    assert result.review is not None
    assert result.review.review_calls == 2
    assert result.review.correction_calls == 1
    assert len(corrector.contexts) == 1
    assert corrector.contexts[0].assignment_id == "work-alpha"
    assert [instruction.instruction_id for instruction in corrector.instructions] == ["general"]


@pytest.mark.parametrize(
    "decision",
    (ReviewDecision.CONFLICT, ReviewDecision.HUMAN_REQUIRED, ReviewDecision.FAILED),
)
def test_non_pass_review_never_reaches_main_aggregation(decision: ReviewDecision) -> None:
    runtime = agent_runtime("alpha")
    configured, _, _ = configured_review_runtime(runtime, ReviewerProbe(lambda _: decision))
    task, signals, inputs = professional_request("alpha", asynchronous=False)

    result = run(configured.start(task, signals, professional_inputs=inputs))

    assert result.status is ConfiguredReviewedStatus.REVIEW_STOPPED
    assert result.review is not None
    assert result.review.aggregation_ready is False
    assert result.aggregation is None
    assert result.error_code is not None


def test_failed_professional_schedule_stops_before_reviewer_call() -> None:
    runtime = agent_runtime("alpha")
    reviewer = ReviewerProbe()
    configured, _, _ = configured_review_runtime(
        runtime,
        reviewer,
        child_failures=frozenset({"alpha"}),
    )
    task, signals, inputs = professional_request("alpha", asynchronous=False)

    result = run(configured.start(task, signals, professional_inputs=inputs))

    assert result.status is ConfiguredReviewedStatus.EXECUTION_STOPPED
    assert result.aggregation is None
    assert reviewer.contexts == []


@pytest.mark.parametrize("correctors", ({}, {"alpha": CorrectorProbe(), "extra": CorrectorProbe()}))
def test_correction_catalog_must_match_professional_profiles_exactly(
    correctors: Mapping[str, CorrectorProbe],
) -> None:
    runtime = agent_runtime("alpha")

    with pytest.raises(ConfiguredReviewRuntimeError) as raised:
        ConfiguredReviewBindings(
            runtime,
            reviewer=ReviewerProbe(),
            reviewer_definition=REVIEWER_DEFINITION,
            correctors=correctors,
        )

    assert raised.value.code == "CONFIGURED_CORRECTOR_CATALOG_MISMATCH"


def test_reviewer_prompt_version_mismatch_stops_before_review_call() -> None:
    runtime = agent_runtime("alpha")
    reviewer = ReviewerProbe()
    changed = REVIEWER_DEFINITION.model_copy(update={"prompt_version": "9.0.0"})

    with pytest.raises(ConfiguredReviewRuntimeError) as raised:
        ConfiguredReviewBindings(
            runtime,
            reviewer=reviewer,
            reviewer_definition=changed,
            correctors={"alpha": CorrectorProbe()},
        )

    assert raised.value.code == "CONFIGURED_REVIEW_PROMPT_MISMATCH"
    assert reviewer.contexts == []
    assert reviewer.instructions == []


def test_execution_and_review_bindings_require_the_same_configuration() -> None:
    runtime = agent_runtime("alpha")
    children = {profile.name: ChildDelegate() for profile in runtime.profiles}
    execution = ConfiguredOrchestrationRuntime(ConfiguredExecutorFactory(runtime, children))
    changed = replace(runtime, configuration_sha256="f" * 64)
    bindings = ConfiguredReviewBindings(
        changed,
        reviewer=ReviewerProbe(),
        reviewer_definition=REVIEWER_DEFINITION,
        correctors={"alpha": CorrectorProbe()},
    )

    with pytest.raises(ConfiguredReviewRuntimeError) as raised:
        ConfiguredReviewedOrchestrationRuntime(execution, bindings)

    assert raised.value.code == "CONFIGURED_REVIEW_RUNTIME_MISMATCH"


def test_review_repository_replays_terminal_result_and_rejects_changed_definition() -> None:
    runtime = agent_runtime("alpha")
    repository = InMemoryReviewRecoveryRepository()
    first_reviewer = ReviewerProbe()
    first, _, _ = configured_review_runtime(runtime, first_reviewer, repository=repository)
    task, signals, inputs = professional_request("alpha", asynchronous=False)
    first_result = run(first.start(task, signals, professional_inputs=inputs))
    assert first_result.review_recovery_id is not None

    replacement_reviewer = ReviewerProbe()
    replacement, _, _ = configured_review_runtime(
        runtime,
        replacement_reviewer,
        repository=repository,
    )
    replayed = run(replacement.finalize(first_result.execution))

    assert replayed.status is ConfiguredReviewedStatus.AGGREGATION_READY
    assert replayed.review_recovery_id == first_result.review_recovery_id
    assert first_reviewer.contexts and replacement_reviewer.contexts == []

    changed_definition = REVIEWER_DEFINITION.model_copy(
        update={"model_version": "configured-review-model-2"}
    )
    changed, _, _ = configured_review_runtime(
        runtime,
        ReviewerProbe(),
        repository=repository,
        reviewer_definition=changed_definition,
    )
    denied = run(changed.finalize(first_result.execution))
    assert denied.status is ConfiguredReviewedStatus.REVIEW_STOPPED
    assert denied.error_code == "REVIEW_RECOVERY_IDEMPOTENCY_CONFLICT"
    assert denied.aggregation is None


def test_startup_can_publish_reviewed_orchestration_runtime() -> None:
    runtime = agent_runtime()
    reviewer = ReviewerProbe()
    professional_names = {
        profile.name for profile in runtime.profiles if profile.kind is ChildAgentKind.PROFESSIONAL
    }
    bindings = ConfiguredReviewBindings(
        runtime,
        reviewer=reviewer,
        reviewer_definition=REVIEWER_DEFINITION,
        correctors={name: CorrectorProbe() for name in professional_names},
    )
    child = ChildDelegate()
    children = {
        profile.name: child if profile.name == "general" else ChildDelegate()
        for profile in runtime.profiles
    }
    app = create_app(
        AppSettings(
            model_config_path=str(ROOT / "config/runtime/model-bindings.example.yaml"),
            prompt_config_path=str(PROMPT_CONFIG),
            agent_config_path=str(ROOT / "config/runtime/agent-runtime.example.yaml"),
        ),
        configure_logs=False,
        model_environment={},
        agent_delegates=children,
        review_bindings=bindings,
    )

    result = run(
        app.state.reviewed_orchestration_runtime.start(
            TASK,
            RouteSignals(task_id=TASK.task_id, general_eligible=True),
        )
    )

    assert result.status is ConfiguredReviewedStatus.AGGREGATION_READY
    assert child.calls == 1
