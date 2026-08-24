"""S1-09 independent review, targeted correction, and cross-result tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import (
    AgentResult,
    BudgetPolicy,
    Issue,
    Limit,
    ReviewDecision,
    ReviewResult,
    TaskContext,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import (
    AgentDefinition,
    ChildAgentKind,
    ChildInput,
    ChildTaskContext,
)
from ndt_agents.orchestration.models import (
    DispatchPlan,
    ProfessionalAssignment,
    RouteKind,
)
from ndt_agents.orchestration.registry import AgentRegistry
from ndt_agents.orchestration.review import (
    CorrectionContext,
    MainAggregationGate,
    ReviewContext,
    ReviewerDefinition,
    ReviewError,
    ReviewKind,
    ReviewWorkflow,
    ReviewWorkflowResult,
    ReviewWorkflowStatus,
)
from ndt_agents.orchestration.review_recovery import (
    InMemoryReviewRecoveryRepository,
    RecoverableReviewWorkflow,
    ReviewRecoveryError,
    ReviewRecoveryFaultPoint,
    SimulatedReviewTermination,
)
from ndt_agents.orchestration.scheduler import ScheduleResult, TaskScheduler

ROOT = Path(__file__).resolve().parents[2]
TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
RESULT_TEMPLATE = AgentResult.model_validate_json(
    (ROOT / "examples/contracts/v1/agent-result.valid.json").read_text("utf-8")
)
REVIEWER = ReviewerDefinition(
    reviewer_version="reviewer-1",
    prompt_version="review-prompt-1",
    model_version="review-model-1",
)
REVIEW_NAMESPACE = UUID("00000000-0000-4000-8000-000000000909")


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


class ChildProbe:
    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]:
        return RESULT_TEMPLATE.model_copy(
            update={
                "task_id": context.parent_task_id,
                "run_id": context.run_id,
                "summary": f"Initial {context.assignment_id}",
            }
        ).model_dump(mode="json")


class ReviewerProbe:
    def __init__(
        self,
        decide: Callable[[ReviewContext], tuple[ReviewDecision, tuple[Issue, ...]]],
        *,
        delay: float = 0.0,
        mutate: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.decide = decide
        self.delay = delay
        self.mutate = mutate
        self.contexts: list[ReviewContext] = []

    async def review(self, context: ReviewContext) -> Mapping[str, Any]:
        self.contexts.append(context)
        if self.delay:
            await asyncio.sleep(self.delay)
        decision, findings = self.decide(context)
        payload = ReviewResult(
            review_id=uuid5(
                REVIEW_NAMESPACE,
                f"{context.kind}:{context.review_target_sha256}:{context.correction_count}",
            ),
            task_id=context.task_id,
            target_run_id=context.review_target_run_id,
            target_sha256=context.review_target_sha256,
            reviewer_version=context.reviewer_version,
            decision=decision,
            findings=findings,
            correction_count=context.correction_count,
            completed_at=datetime(2026, 8, 22, tzinfo=UTC),
        ).model_dump(mode="json")
        if self.mutate is not None:
            self.mutate(payload)
        return payload


class CorrectorProbe:
    def __init__(self, *, invalid: bool = False, no_change: bool = False) -> None:
        self.invalid = invalid
        self.no_change = no_change
        self.contexts: list[CorrectionContext] = []

    async def correct(self, context: CorrectionContext) -> Mapping[str, Any]:
        self.contexts.append(context)
        if self.invalid:
            return {"invalid": True}
        if self.no_change:
            return context.current_result.model_dump(mode="json")
        return context.current_result.model_copy(
            update={"summary": f"Corrected {context.assignment_id} {context.correction_count}"}
        ).model_dump(mode="json")


def finding(
    code: str = "REVIEW_DEFECT",
    *,
    path: str | None = "structured_data.value",
    severity: str = "ERROR",
) -> Issue:
    return Issue.model_validate(
        {
            "code": code,
            "severity": severity,
            "message": "The result needs a bounded repair.",
            "affected_path": path,
            "next_action": "Repair only the identified field and preserve evidence.",
        }
    )


def policy_with_review_rounds(active: int = 1) -> BudgetPolicy:
    policy = default_budget_policy("P3")
    return policy.model_copy(update={"review_rounds": Limit(default=1, active=active, hard=2)})


def professional_contexts(
    *,
    count: int = 1,
    dependent: bool = False,
    review_rounds: int = 1,
) -> tuple[ChildTaskContext, ...]:
    names = ("alpha", "beta", "gamma")[:count]
    policy = policy_with_review_rounds(review_rounds)
    task = TASK.model_copy(update={"task_class": "P3", "budget": policy})
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset(),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="general-model-1",
            ),
            *tuple(
                AgentDefinition(
                    agent_type=name,
                    kind=ChildAgentKind.PROFESSIONAL,
                    allowed_tools=frozenset(),
                    skill_version=f"{name}-1",
                    prompt_version=f"{name}-1",
                    model_version="child-model-1",
                )
                for name in names
            ),
        )
    )
    assignments = tuple(
        ProfessionalAssignment(
            assignment_id=name,
            agent_type=name,
            depends_on=((names[index - 1],) if dependent and index else ()),
        )
        for index, name in enumerate(names)
    )
    dispatch = DispatchPlan(
        task_id=task.task_id,
        route=(
            RouteKind.ONE_PROFESSIONAL_SYNC_REVIEW
            if count == 1
            else RouteKind.MULTIPLE_DEPENDENT_ASYNC_REVIEW
            if dependent
            else RouteKind.MULTIPLE_INDEPENDENT_ASYNC_REVIEW
        ),
        general_agent=False,
        professional_assignments=assignments,
        asynchronous=count > 1,
        review_required=True,
        human_required=False,
    )
    inputs = tuple(
        ChildInput(
            assignment_id=name,
            goal=f"Produce {name}",
            success_criteria=("Return a typed result",),
        )
        for name in names
    )
    return ChildContextFactory(registry).prepare(task, dispatch, professional_inputs=inputs)


def general_context() -> ChildTaskContext:
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset(),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="general-model-1",
            ),
        )
    )
    dispatch = DispatchPlan(
        task_id=TASK.task_id,
        route=RouteKind.GENERAL_SYNC,
        general_agent=True,
        professional_assignments=(),
        asynchronous=False,
        review_required=False,
        human_required=False,
    )
    return ChildContextFactory(registry).prepare(TASK, dispatch)[0]


def schedule_for(contexts: tuple[ChildTaskContext, ...]) -> tuple[ScheduleResult, BudgetGuard]:
    guard = BudgetGuard(contexts[0].budget)
    executors = {context.assignment_id: ChildProbe() for context in contexts}
    schedule = run(TaskScheduler(budget_guard=guard).run_sync(contexts, executors))
    return schedule, guard


def pass_decision(_context: ReviewContext) -> tuple[ReviewDecision, tuple[Issue, ...]]:
    return ReviewDecision.PASS, ()


def test_single_professional_passes_read_only_review_before_aggregation() -> None:
    contexts = professional_contexts()
    schedule, guard = schedule_for(contexts)
    reviewer = ReviewerProbe(pass_decision)

    result = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=reviewer,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=guard,
        )
    )

    assert result.status is ReviewWorkflowStatus.APPROVED
    assert result.aggregation_ready is True
    assert result.assignments[0].aggregation_ready is True
    assert result.review_calls == 1
    review_context = reviewer.contexts[0]
    assert review_context.read_only is True
    assert review_context.allowed_tools == ()
    assert review_context.user_delivery_allowed is False
    assert not hasattr(review_context, "scratch_namespace")
    assert len(result.review_manifest_sha256) == 64
    assert result.budget_telemetry.counters.review_rounds == 1
    aggregation = MainAggregationGate.professional(result)
    assert aggregation.review_manifest_sha256 == result.review_manifest_sha256
    assert aggregation.results == (result.assignments[0].current_result,)


def test_main_aggregation_gate_accepts_general_and_rejects_unreviewed_professional() -> None:
    general = general_context()
    general_schedule = run(TaskScheduler().run_sync((general,), {"general": ChildProbe()}))
    general_outcome = general_schedule.assignments[0].outcome
    assert general_outcome is not None
    general_input = MainAggregationGate.general(general, general_outcome)
    assert general_input.review_manifest_sha256 is None

    contexts = professional_contexts()
    schedule, guard = schedule_for(contexts)
    professional_outcome = schedule.assignments[0].outcome
    assert professional_outcome is not None
    with pytest.raises(ReviewError) as raw_bypass:
        MainAggregationGate.general(contexts[0], professional_outcome)
    assert raw_bypass.value.code == "AGGREGATION_GENERAL_INVALID"
    blocked = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=ReviewerProbe(lambda _context: (ReviewDecision.CONFLICT, (finding(),))),
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=guard,
        )
    )
    with pytest.raises(ReviewError) as raised:
        MainAggregationGate.professional(blocked)
    assert raised.value.code == "AGGREGATION_REVIEW_REQUIRED"


def test_general_schedule_cannot_enter_review_graph() -> None:
    context = general_context()
    schedule = run(TaskScheduler().run_sync((context,), {"general": ChildProbe()}))
    reviewer = ReviewerProbe(pass_decision)

    with pytest.raises(ReviewError) as raised:
        run(
            ReviewWorkflow().run(
                schedule,
                (context,),
                reviewer=reviewer,
                reviewer_definition=REVIEWER,
                correctors={},
                budget_guard=BudgetGuard(context.budget),
            )
        )

    assert raised.value.code == "REVIEW_TOPOLOGY_DENIED"
    assert reviewer.contexts == []


def test_tampered_child_context_is_rejected_before_reviewer_call() -> None:
    contexts = professional_contexts()
    schedule, guard = schedule_for(contexts)
    tampered = contexts[0].model_copy(
        update={"review_checklist": ("Unverified replacement checklist",)}
    )
    reviewer = ReviewerProbe(pass_decision)

    with pytest.raises(ReviewError) as raised:
        run(
            ReviewWorkflow().run(
                schedule,
                (tampered,),
                reviewer=reviewer,
                reviewer_definition=REVIEWER,
                correctors={},
                budget_guard=guard,
            )
        )

    assert raised.value.code == "REVIEW_CONTEXT_INTEGRITY_FAILED"
    assert reviewer.contexts == []


def test_revise_targets_responsible_child_and_rereviews_only_changed_result() -> None:
    contexts = professional_contexts(review_rounds=2)
    schedule, guard = schedule_for(contexts)
    reviewer = ReviewerProbe(
        lambda context: (
            (ReviewDecision.REVISE, (finding(),))
            if context.correction_count == 0
            else (ReviewDecision.PASS, ())
        )
    )
    corrector = CorrectorProbe()

    result = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=reviewer,
            reviewer_definition=REVIEWER,
            correctors={"alpha": corrector},
            budget_guard=guard,
        )
    )

    assignment = result.assignments[0]
    assert result.status is ReviewWorkflowStatus.APPROVED
    assert result.review_calls == 2
    assert result.correction_calls == 1
    assert assignment.correction_count == 1
    assert len(assignment.review_history) == 2
    assert assignment.current_result.summary == "Corrected alpha 1"
    assert corrector.contexts[0].assignment_id == "alpha"
    assert corrector.contexts[0].related_targets == ()
    assert not hasattr(corrector.contexts[0], "scratch_namespace")
    assert result.budget_telemetry.counters.review_rounds == 2
    assert result.budget_telemetry.counters.correction_rounds == 1


def test_dependent_results_require_individual_then_cross_result_review() -> None:
    contexts = professional_contexts(count=2, dependent=True)
    schedule, guard = schedule_for(contexts)
    reviewer = ReviewerProbe(pass_decision)

    result = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=reviewer,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=guard,
        )
    )

    assert result.status is ReviewWorkflowStatus.APPROVED
    assert [context.kind for context in reviewer.contexts] == [
        ReviewKind.PER_RESULT,
        ReviewKind.PER_RESULT,
        ReviewKind.CROSS_RESULT,
    ]
    assert len(reviewer.contexts[-1].targets) == 2
    assert len(result.cross_review_history) == 1

    with pytest.raises(ReviewError) as bypass:
        run(
            ReviewWorkflow().run(
                schedule,
                contexts,
                reviewer=ReviewerProbe(pass_decision),
                reviewer_definition=REVIEWER,
                correctors={},
                budget_guard=BudgetGuard(contexts[0].budget),
                cross_result_required=False,
            )
        )
    assert bypass.value.code == "CROSS_REVIEW_REQUIRED"


def test_independent_results_skip_cross_review_unless_explicitly_required() -> None:
    contexts = professional_contexts(count=2)
    schedule, guard = schedule_for(contexts)
    reviewer = ReviewerProbe(pass_decision)
    result = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=reviewer,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=guard,
        )
    )
    assert result.review_calls == 2
    assert result.cross_review_history == ()

    forced = ReviewerProbe(pass_decision)
    forced_result = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=forced,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=BudgetGuard(contexts[0].budget),
            cross_result_required=True,
        )
    )
    assert forced_result.review_calls == 3
    assert forced.contexts[-1].kind is ReviewKind.CROSS_RESULT


def test_cross_review_revises_only_named_assignment_then_rereviews_consistency() -> None:
    contexts = professional_contexts(count=2, dependent=True, review_rounds=2)
    schedule, guard = schedule_for(contexts)

    def decide(context: ReviewContext) -> tuple[ReviewDecision, tuple[Issue, ...]]:
        if context.kind is ReviewKind.CROSS_RESULT and context.correction_count == 0:
            return ReviewDecision.REVISE, (finding(path="assignment:beta"),)
        return ReviewDecision.PASS, ()

    reviewer = ReviewerProbe(decide)
    alpha = CorrectorProbe()
    beta = CorrectorProbe()
    result = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=reviewer,
            reviewer_definition=REVIEWER,
            correctors={"alpha": alpha, "beta": beta},
            budget_guard=guard,
        )
    )

    by_id = {item.assignment_id: item for item in result.assignments}
    assert result.status is ReviewWorkflowStatus.APPROVED
    assert result.review_calls == 5
    assert result.correction_calls == 1
    assert alpha.contexts == []
    assert len(beta.contexts) == 1
    assert len(beta.contexts[0].related_targets) == 1
    assert len(by_id["alpha"].review_history) == 1
    assert len(by_id["beta"].review_history) == 2
    assert len(result.cross_review_history) == 2


@pytest.mark.parametrize(
    ("decision", "status", "code"),
    [
        (ReviewDecision.CONFLICT, ReviewWorkflowStatus.CONFLICT, "REVIEW_CONFLICT"),
        (
            ReviewDecision.HUMAN_REQUIRED,
            ReviewWorkflowStatus.HUMAN_REQUIRED,
            "REVIEW_HUMAN_REQUIRED",
        ),
        (ReviewDecision.FAILED, ReviewWorkflowStatus.FAILED, "REVIEW_FAILED"),
    ],
)
def test_non_pass_terminal_decisions_block_aggregation(
    decision: ReviewDecision, status: ReviewWorkflowStatus, code: str
) -> None:
    contexts = professional_contexts()
    schedule, guard = schedule_for(contexts)
    reviewer = ReviewerProbe(lambda _context: (decision, (finding(),)))
    result = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=reviewer,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=guard,
        )
    )
    assert result.status is status
    assert result.error_code == code
    assert result.aggregation_ready is False
    assert result.assignments[0].aggregation_ready is False


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda payload: payload.update(target_sha256="f" * 64), "REVIEW_RESULT_BINDING_INVALID"),
        (lambda payload: payload.update(reviewer_version="wrong"), "REVIEW_RESULT_BINDING_INVALID"),
        (lambda payload: payload.update(correction_count=1), "REVIEW_RESULT_BINDING_INVALID"),
        (lambda payload: payload.update(extra="denied"), "REVIEW_RESULT_INVALID"),
    ],
)
def test_invalid_review_payload_is_a_typed_failure(
    mutation: Callable[[dict[str, Any]], None], expected: str
) -> None:
    contexts = professional_contexts()
    schedule, guard = schedule_for(contexts)
    result = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=ReviewerProbe(pass_decision, mutate=mutation),
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=guard,
        )
    )

    assert result.error_code == expected
    assert result.aggregation_ready is False


def test_invalid_pass_findings_are_a_typed_failure() -> None:
    contexts = professional_contexts()
    schedule, guard = schedule_for(contexts)

    severe_pass = ReviewerProbe(
        lambda _context: (ReviewDecision.PASS, (finding(severity="CRITICAL"),))
    )
    invalid_findings = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=severe_pass,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=guard,
        )
    )
    assert invalid_findings.error_code == "REVIEW_FINDINGS_INVALID"
    assert invalid_findings.aggregation_ready is False


def test_timeout_missing_corrector_and_invalid_correction_are_explicit() -> None:
    contexts = professional_contexts()
    schedule, _ = schedule_for(contexts)
    short = REVIEWER.model_copy(update={"review_timeout_ms": 1})
    timeout = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=ReviewerProbe(pass_decision, delay=0.02),
            reviewer_definition=short,
            correctors={},
            budget_guard=BudgetGuard(contexts[0].budget),
        )
    )
    assert timeout.error_code == "REVIEW_TIMEOUT"

    revise = ReviewerProbe(lambda _context: (ReviewDecision.REVISE, (finding(),)))
    missing = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=revise,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=BudgetGuard(contexts[0].budget),
        )
    )
    assert missing.error_code == "CORRECTION_EXECUTOR_REQUIRED"
    assert "alpha" in (missing.next_action or "")

    invalid = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=ReviewerProbe(lambda _context: (ReviewDecision.REVISE, (finding(),))),
            reviewer_definition=REVIEWER,
            correctors={"alpha": CorrectorProbe(invalid=True)},
            budget_guard=BudgetGuard(contexts[0].budget),
        )
    )
    assert invalid.error_code == "CORRECTION_RESULT_INVALID"

    unchanged = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=ReviewerProbe(lambda _context: (ReviewDecision.REVISE, (finding(),))),
            reviewer_definition=REVIEWER,
            correctors={"alpha": CorrectorProbe(no_change=True)},
            budget_guard=BudgetGuard(contexts[0].budget),
        )
    )
    assert unchanged.error_code == "CORRECTION_NO_CHANGE"


def test_review_and_correction_budget_exhaustion_make_zero_extra_calls() -> None:
    contexts = professional_contexts()
    schedule, _ = schedule_for(contexts)
    review_guard = BudgetGuard(contexts[0].budget)
    review_guard.record_review()
    reviewer = ReviewerProbe(pass_decision)
    stopped = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=reviewer,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=review_guard,
        )
    )
    assert stopped.error_code == "BUDGET_ACTIVE_LIMIT_EXCEEDED"
    assert stopped.review_calls == 0
    assert reviewer.contexts == []

    correction_guard = BudgetGuard(contexts[0].budget)
    correction_guard.record_correction()
    corrector = CorrectorProbe()
    correction_stopped = run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=ReviewerProbe(lambda _context: (ReviewDecision.REVISE, (finding(),))),
            reviewer_definition=REVIEWER,
            correctors={"alpha": corrector},
            budget_guard=correction_guard,
        )
    )
    assert correction_stopped.error_code == "BUDGET_ACTIVE_LIMIT_EXCEEDED"
    assert correction_stopped.review_calls == 1
    assert correction_stopped.correction_calls == 0
    assert corrector.contexts == []


def test_review_manifest_is_deterministic_for_identical_bound_results_and_reviews() -> None:
    contexts = professional_contexts(count=2)
    schedule, _ = schedule_for(contexts)

    def execute_once() -> ReviewWorkflowResult:
        result = run(
            ReviewWorkflow().run(
                schedule,
                contexts,
                reviewer=ReviewerProbe(pass_decision),
                reviewer_definition=REVIEWER,
                correctors={},
                budget_guard=BudgetGuard(contexts[0].budget),
            )
        )
        return result

    first = execute_once()
    second = execute_once()
    assert first.review_manifest_sha256 == second.review_manifest_sha256
    tampered = first.model_dump(mode="json")
    tampered["review_manifest_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        type(first).model_validate(tampered)


def test_review_recovery_before_review_starts_with_zero_duplicate_calls() -> None:
    contexts = professional_contexts()
    schedule, guard = schedule_for(contexts)
    repository = InMemoryReviewRecoveryRepository()
    recovery_id = uuid5(REVIEW_NAMESPACE, "recovery-before-review")
    reviewer = ReviewerProbe(pass_decision)
    runtime = RecoverableReviewWorkflow(repository)

    with pytest.raises(SimulatedReviewTermination):
        run(
            runtime.run(
                recovery_id,
                schedule,
                contexts,
                reviewer=reviewer,
                reviewer_definition=REVIEWER,
                correctors={},
                budget_guard=guard,
                fault=ReviewRecoveryFaultPoint.BEFORE_REVIEW,
            )
        )
    assert reviewer.contexts == []

    recovered = run(
        RecoverableReviewWorkflow(repository).run(
            recovery_id,
            schedule,
            contexts,
            reviewer=reviewer,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=BudgetGuard(contexts[0].budget),
        )
    )
    assert recovered.recovered and recovered.result.aggregation_ready
    assert len(reviewer.contexts) == 1


def test_review_recovery_replays_completed_call_then_finishes_correction() -> None:
    contexts = professional_contexts(review_rounds=2)
    schedule, guard = schedule_for(contexts)
    repository = InMemoryReviewRecoveryRepository()
    recovery_id = uuid5(REVIEW_NAMESPACE, "recovery-mid-review")
    reviewer = ReviewerProbe(
        lambda context: (
            (ReviewDecision.REVISE, (finding(),))
            if context.correction_count == 0
            else (ReviewDecision.PASS, ())
        )
    )
    corrector = CorrectorProbe()

    with pytest.raises(SimulatedReviewTermination):
        run(
            RecoverableReviewWorkflow(repository).run(
                recovery_id,
                schedule,
                contexts,
                reviewer=reviewer,
                reviewer_definition=REVIEWER,
                correctors={"alpha": corrector},
                budget_guard=guard,
                fault=ReviewRecoveryFaultPoint.AFTER_FIRST_COMPLETED_CALL,
            )
        )
    assert len(reviewer.contexts) == 1
    assert corrector.contexts == []

    recovered = run(
        RecoverableReviewWorkflow(repository).run(
            recovery_id,
            schedule,
            contexts,
            reviewer=reviewer,
            reviewer_definition=REVIEWER,
            correctors={"alpha": corrector},
            budget_guard=BudgetGuard(contexts[0].budget),
        )
    )
    assert recovered.result.aggregation_ready
    assert len(reviewer.contexts) == 2
    assert len(corrector.contexts) == 1
    assert recovered.result.review_calls == 2
    assert recovered.result.correction_calls == 1


def test_committed_manifest_recovers_without_calls_before_main_aggregation() -> None:
    contexts = professional_contexts()
    schedule, guard = schedule_for(contexts)
    repository = InMemoryReviewRecoveryRepository()
    recovery_id = uuid5(REVIEW_NAMESPACE, "recovery-before-aggregation")
    reviewer = ReviewerProbe(pass_decision)

    with pytest.raises(SimulatedReviewTermination):
        run(
            RecoverableReviewWorkflow(repository).run(
                recovery_id,
                schedule,
                contexts,
                reviewer=reviewer,
                reviewer_definition=REVIEWER,
                correctors={},
                budget_guard=guard,
                fault=ReviewRecoveryFaultPoint.BEFORE_MAIN_AGGREGATION,
            )
        )
    assert len(reviewer.contexts) == 1

    unused_reviewer = ReviewerProbe(pass_decision)
    recovered = run(
        RecoverableReviewWorkflow(repository).run(
            recovery_id,
            schedule,
            contexts,
            reviewer=unused_reviewer,
            reviewer_definition=REVIEWER,
            correctors={},
            budget_guard=BudgetGuard(contexts[0].budget),
        )
    )
    assert recovered.recovered
    assert unused_reviewer.contexts == []
    aggregation = MainAggregationGate.professional(recovered.result)
    assert aggregation.review_manifest_sha256 == recovered.result.review_manifest_sha256


def test_review_recovery_rejects_conflicting_scope_input_and_tampering() -> None:
    contexts = professional_contexts()
    schedule, guard = schedule_for(contexts)
    repository = InMemoryReviewRecoveryRepository()
    recovery_id = uuid5(REVIEW_NAMESPACE, "recovery-integrity")
    with pytest.raises(SimulatedReviewTermination):
        run(
            RecoverableReviewWorkflow(repository).run(
                recovery_id,
                schedule,
                contexts,
                reviewer=ReviewerProbe(pass_decision),
                reviewer_definition=REVIEWER,
                correctors={},
                budget_guard=guard,
                fault=ReviewRecoveryFaultPoint.BEFORE_REVIEW,
            )
        )
    changed_definition = REVIEWER.model_copy(update={"prompt_version": "changed"})
    with pytest.raises(ReviewRecoveryError) as conflict:
        run(
            RecoverableReviewWorkflow(repository).run(
                recovery_id,
                schedule,
                contexts,
                reviewer=ReviewerProbe(pass_decision),
                reviewer_definition=changed_definition,
                correctors={},
                budget_guard=BudgetGuard(contexts[0].budget),
            )
        )
    assert conflict.value.code == "REVIEW_RECOVERY_IDEMPOTENCY_CONFLICT"

    other_scope = schedule.scope.model_copy(update={"project_id": uuid5(REVIEW_NAMESPACE, "other")})
    with pytest.raises(ReviewRecoveryError) as scope_error:
        repository.list(other_scope, recovery_id)
    assert scope_error.value.code == "REVIEW_RECOVERY_SCOPE_MISMATCH"

    events = repository.list(schedule.scope, recovery_id)
    tampered = events[0].model_copy(update={"payload_sha256": "0" * 64})
    with pytest.raises(ReviewRecoveryError) as integrity:
        InMemoryReviewRecoveryRepository.verify((tampered,))
    assert integrity.value.code == "REVIEW_RECOVERY_CHAIN_INVALID"
