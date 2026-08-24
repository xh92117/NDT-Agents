"""S1-08 central budget policy, guards, telemetry, and scheduler integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from pathlib import Path
from typing import Any

import pytest

from ndt_agents.contracts.v1 import AgentResult, BudgetPolicy, Limit, TaskContext
from ndt_agents.orchestration.budget import (
    BudgetActionClass,
    BudgetContractError,
    BudgetDimension,
    BudgetElevationAuthority,
    BudgetExceeded,
    BudgetGuard,
    DegradationStage,
    default_budget_policy,
    elevate_budget_policy,
)
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import (
    AgentDefinition,
    ChildAgentKind,
    ChildInput,
    ChildTaskContext,
)
from ndt_agents.orchestration.models import DispatchPlan, ProfessionalAssignment, RouteKind
from ndt_agents.orchestration.registry import AgentRegistry
from ndt_agents.orchestration.scheduler import (
    AssignmentStatus,
    SchedulerError,
    ScheduleStatus,
    TaskScheduler,
)

ROOT = Path(__file__).resolve().parents[2]
TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
RESULT_TEMPLATE = AgentResult.model_validate_json(
    (ROOT / "examples/contracts/v1/agent-result.valid.json").read_text("utf-8")
)


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def with_limit(
    policy: BudgetPolicy,
    dimension: BudgetDimension,
    *,
    default: int,
    active: int,
    hard: int,
) -> BudgetPolicy:
    return policy.model_copy(
        update={dimension.value: Limit(default=default, active=active, hard=hard)}
    )


@pytest.mark.parametrize(
    ("task_class", "expected"),
    [
        ("G0", (3, 4, 2, 4, 8, 12, 4_000, 8_000, 30_000, 60_000, 0, 0)),
        ("P1", (6, 10, 6, 10, 16, 24, 10_000, 20_000, 120_000, 300_000, 1, 1)),
        (
            "P2",
            (18, 32, 16, 24, 32, 48, 35_000, 60_000, 900_000, 1_800_000, 1, 2),
        ),
        (
            "P3",
            (24, 40, 30, 48, 48, 64, 60_000, 120_000, 3_600_000, 7_200_000, 3, 4),
        ),
        (
            "K1",
            (7, 12, 15, 24, 48, 64, 20_000, 40_000, 7_200_000, 14_400_000, 2, 4),
        ),
    ],
)
def test_default_policy_matches_controlled_task_class_table(
    task_class: str, expected: tuple[int, ...]
) -> None:
    policy = default_budget_policy(task_class, file_count=3)  # type: ignore[arg-type]

    assert (
        policy.llm_calls.default,
        policy.llm_calls.hard,
        policy.tool_calls.default,
        policy.tool_calls.hard,
        policy.graph_steps.default,
        policy.graph_steps.hard,
        policy.total_tokens.default,
        policy.total_tokens.hard,
        policy.wall_time_ms.default,
        policy.wall_time_ms.hard,
        policy.professional_concurrency.default,
        policy.professional_concurrency.hard,
    ) == expected
    assert policy.review_rounds == Limit(default=1, active=1, hard=2)
    assert policy.correction_rounds == Limit(default=1, active=1, hard=2)


def test_k1_file_budget_caps_default_at_hard_limit() -> None:
    policy = default_budget_policy("K1", file_count=100)

    assert policy.tool_calls == Limit(default=400, active=400, hard=400)


def test_elevation_requires_authority_distinct_policy_and_hard_bound() -> None:
    policy = default_budget_policy("P2")
    authority = BudgetElevationAuthority(
        kind="DETERMINISTIC_RISK_POLICY", reference_id="risk-policy-7"
    )
    record = elevate_budget_policy(
        policy,
        new_policy_id="budget-p2-v1-risk-7",
        active_limits={BudgetDimension.PROFESSIONAL_CONCURRENCY: 2},
        authority=authority,
    )

    assert record.source_policy_id == policy.policy_id
    assert record.elevated_policy.professional_concurrency.active == 2
    assert policy.professional_concurrency.active == 1
    with pytest.raises(BudgetContractError) as raised:
        elevate_budget_policy(
            policy,
            new_policy_id="budget-p2-invalid",
            active_limits={BudgetDimension.PROFESSIONAL_CONCURRENCY: 3},
            authority=authority,
        )
    assert raised.value.code == "BUDGET_ELEVATION_DENIED"


@pytest.mark.parametrize(
    ("active", "hard", "expected_code"),
    [(2, 4, "BUDGET_ACTIVE_LIMIT_EXCEEDED"), (2, 2, "BUDGET_HARD_LIMIT_EXCEEDED")],
)
def test_graph_step_stops_before_exceeding_active_or_hard_limit(
    active: int, hard: int, expected_code: str
) -> None:
    policy = with_limit(
        default_budget_policy("G0"),
        BudgetDimension.GRAPH_STEPS,
        default=2,
        active=active,
        hard=hard,
    )
    guard = BudgetGuard(policy)
    guard.record_graph_step(action_class=BudgetActionClass.FINALIZATION)
    guard.record_graph_step(action_class=BudgetActionClass.FINALIZATION)

    with pytest.raises(BudgetExceeded) as raised:
        guard.record_graph_step(action_class=BudgetActionClass.FINALIZATION)

    assert raised.value.code == expected_code
    assert raised.value.telemetry.counters.graph_steps == 2
    assert raised.value.telemetry.events[-1].decision.value == "DENIED"
    stop = raised.value.to_stop(
        completed_work=("validated child A",),
        partial=True,
    )
    assert stop.status == "PARTIAL"
    assert stop.completed_work == ("validated child A",)
    assert stop.impact and stop.next_action


def guard_at_graph_count(count: int) -> BudgetGuard:
    policy = with_limit(
        default_budget_policy("G0"),
        BudgetDimension.GRAPH_STEPS,
        default=20,
        active=20,
        hard=20,
    )
    guard = BudgetGuard(policy)
    for _ in range(count):
        guard.record_graph_step(action_class=BudgetActionClass.FINALIZATION)
    return guard


@pytest.mark.parametrize(
    ("count", "stage", "action"),
    [
        (14, DegradationStage.REDUCE_LOW_VALUE, BudgetActionClass.LOW_VALUE),
        (17, DegradationStage.STOP_EXPANSION, BudgetActionClass.QUERY_EXPANSION),
        (19, DegradationStage.FINALIZE_ONLY, BudgetActionClass.STANDARD),
    ],
)
def test_degradation_thresholds_deny_only_documented_action_classes(
    count: int, stage: DegradationStage, action: BudgetActionClass
) -> None:
    guard = guard_at_graph_count(count)

    assert guard.telemetry().degradation_stage is stage
    with pytest.raises(BudgetExceeded) as raised:
        guard.authorize_action(action)
    assert raised.value.code == f"BUDGET_DEGRADATION_{stage.value}"


def test_finalization_remains_allowed_at_ninety_five_percent() -> None:
    guard = guard_at_graph_count(19)

    guard.record_graph_step(action_class=BudgetActionClass.FINALIZATION)

    assert guard.telemetry().counters.graph_steps == 20
    assert guard.telemetry().degradation_stage is DegradationStage.STOPPED


def test_llm_reservations_count_failed_calls_retries_and_actual_tokens_separately() -> None:
    policy = with_limit(
        default_budget_policy("G0"),
        BudgetDimension.LLM_CALLS,
        default=2,
        active=2,
        hard=4,
    )
    policy = with_limit(
        policy,
        BudgetDimension.TOTAL_TOKENS,
        default=100,
        active=100,
        hard=120,
    )
    guard = BudgetGuard(policy)
    first = guard.begin_llm_call(maximum_total_tokens=60)
    assert guard.telemetry().counters.reserved_total_tokens == 60
    guard.complete_llm_call(first, input_tokens=30, output_tokens=20, success=False)
    second = guard.begin_llm_call(maximum_total_tokens=40, retry=True)
    guard.complete_llm_call(second, input_tokens=20, output_tokens=15, success=True)

    with pytest.raises(BudgetExceeded) as raised:
        guard.begin_llm_call(maximum_total_tokens=1)

    counters = raised.value.telemetry.counters
    assert raised.value.code == "BUDGET_ACTIVE_LIMIT_EXCEEDED"
    assert counters.physical_llm_calls == 2
    assert counters.actual_total_tokens == 85
    assert counters.reserved_total_tokens == 0
    assert counters.llm_failures == 1
    assert counters.retries == 1


def test_token_preflight_denial_makes_zero_llm_calls_and_overrun_is_typed() -> None:
    policy = with_limit(
        default_budget_policy("G0"),
        BudgetDimension.TOTAL_TOKENS,
        default=10,
        active=10,
        hard=20,
    )
    guard = BudgetGuard(policy)
    with pytest.raises(BudgetExceeded) as preflight:
        guard.begin_llm_call(maximum_total_tokens=11)
    assert preflight.value.telemetry.counters.physical_llm_calls == 0

    reservation = guard.begin_llm_call(maximum_total_tokens=10)
    with pytest.raises(BudgetExceeded) as overrun:
        guard.complete_llm_call(
            reservation,
            input_tokens=8,
            output_tokens=3,
            success=True,
        )
    assert overrun.value.code == "BUDGET_TOKEN_RESERVATION_EXCEEDED"
    assert overrun.value.telemetry.counters.actual_total_tokens == 11


def test_identical_tool_call_is_denied_without_new_evidence_but_new_observation_allows() -> None:
    policy = with_limit(
        default_budget_policy("G0"),
        BudgetDimension.TOOL_CALLS,
        default=2,
        active=2,
        hard=4,
    )
    guard = BudgetGuard(policy)
    observation_one = "1" * 64
    first = guard.begin_tool_call(
        tool_name="artifact.read",
        tool_version="1",
        arguments={"b": 2, "a": 1},
        observation_sha256=observation_one,
    )
    guard.complete_tool_call(first, success=False)

    with pytest.raises(BudgetExceeded) as repeated:
        guard.begin_tool_call(
            tool_name="artifact.read",
            tool_version="1",
            arguments={"a": 1, "b": 2},
            observation_sha256=observation_one,
        )
    assert repeated.value.code == "BUDGET_IDENTICAL_TOOL_CALL"
    assert repeated.value.telemetry.counters.physical_tool_calls == 1

    second = guard.begin_tool_call(
        tool_name="artifact.read",
        tool_version="1",
        arguments={"a": 1, "b": 2},
        observation_sha256="2" * 64,
        retry=True,
    )
    guard.complete_tool_call(second, success=True)
    counters = guard.telemetry().counters
    assert counters.physical_tool_calls == 2
    assert counters.tool_failures == 1
    assert counters.retries == 1


def test_cache_metrics_are_separate_from_physical_calls_and_count_graph_actions() -> None:
    guard = BudgetGuard(default_budget_policy("G0"))

    guard.record_cache_lookup(hit=True)
    guard.record_cache_lookup(hit=False)

    counters = guard.telemetry().counters
    assert counters.cache_lookups == 2
    assert counters.cache_hits == 1
    assert counters.graph_steps == 2
    assert counters.logical_actions == 2
    assert counters.physical_llm_calls == counters.physical_tool_calls == 0


def test_graph_reservations_restore_charge_abandoned_attempt_and_do_not_reset() -> None:
    guard = BudgetGuard(default_budget_policy("G0"))
    guard.reserve_graph_steps(4)

    restored = BudgetGuard.from_telemetry(guard.telemetry())
    restored.abandon_graph_reservation()
    restored.reserve_graph_steps(4)
    for _ in range(4):
        restored.record_graph_step()
    restored.record_terminal_transition()

    counters = restored.telemetry().counters
    assert counters.graph_steps == 8
    assert counters.reserved_graph_steps == 0
    assert counters.retries == 1
    assert counters.terminal_transitions == 1


def test_tool_repetition_history_survives_budget_restore() -> None:
    guard = BudgetGuard(default_budget_policy("G0"))
    reservation = guard.begin_tool_call(
        tool_name="artifact.read",
        tool_version="1",
        arguments={"artifact": "one"},
        observation_sha256="a" * 64,
    )
    guard.complete_tool_call(reservation, success=True)
    restored = BudgetGuard.from_telemetry(guard.telemetry())

    with pytest.raises(BudgetExceeded) as repeated:
        restored.begin_tool_call(
            tool_name="artifact.read",
            tool_version="1",
            arguments={"artifact": "one"},
            observation_sha256="a" * 64,
        )

    assert repeated.value.code == "BUDGET_IDENTICAL_TOOL_CALL"
    assert repeated.value.telemetry.counters.physical_tool_calls == 1


def test_budget_restore_rejects_in_flight_llm_reservation() -> None:
    guard = BudgetGuard(default_budget_policy("G0"))
    guard.begin_llm_call(maximum_total_tokens=10)

    with pytest.raises(BudgetContractError) as raised:
        BudgetGuard.from_telemetry(guard.telemetry())

    assert raised.value.code == "BUDGET_RESTORE_LLM_RESERVATION_ACTIVE"


def test_budget_restore_rejects_active_professional_lease() -> None:
    async def scenario() -> None:
        guard = BudgetGuard(default_budget_policy("P3"))
        async with guard.professional_slot():
            with pytest.raises(BudgetContractError) as raised:
                BudgetGuard.from_telemetry(guard.telemetry())
        assert raised.value.code == "BUDGET_RESTORE_CONCURRENCY_ACTIVE"

    run(scenario())


@pytest.mark.parametrize(
    ("active", "hard", "expected"),
    [(100, 200, "BUDGET_ACTIVE_TIME_EXCEEDED"), (100, 100, "BUDGET_HARD_TIME_EXCEEDED")],
)
def test_wall_time_stops_before_new_action(active: int, hard: int, expected: str) -> None:
    now = [0.0]
    policy = with_limit(
        default_budget_policy("G0"),
        BudgetDimension.WALL_TIME_MS,
        default=100,
        active=active,
        hard=hard,
    )
    guard = BudgetGuard(policy, clock=lambda: now[0])
    now[0] = 0.100

    with pytest.raises(BudgetExceeded) as raised:
        guard.record_graph_step()

    assert raised.value.code == expected
    assert raised.value.telemetry.counters.graph_steps == 0
    assert raised.value.telemetry.elapsed_ms == 100


def test_review_and_correction_limits_are_independent() -> None:
    guard = BudgetGuard(default_budget_policy("P1"))
    guard.record_review()
    guard.record_correction()

    with pytest.raises(BudgetExceeded) as review:
        guard.record_review()
    with pytest.raises(BudgetExceeded) as correction:
        guard.record_correction()

    assert review.value.code == correction.value.code == "BUDGET_ACTIVE_LIMIT_EXCEEDED"
    counters = guard.telemetry().counters
    assert counters.review_rounds == counters.correction_rounds == 1


def test_professional_concurrency_lease_enforces_active_limit_and_cleans_up() -> None:
    async def scenario() -> None:
        policy = with_limit(
            default_budget_policy("P3"),
            BudgetDimension.PROFESSIONAL_CONCURRENCY,
            default=2,
            active=2,
            hard=4,
        )
        guard = BudgetGuard(policy)
        entered = 0
        both_entered = asyncio.Event()
        release = asyncio.Event()

        async def hold() -> None:
            nonlocal entered
            async with guard.professional_slot():
                entered += 1
                if entered == 2:
                    both_entered.set()
                await release.wait()

        first = asyncio.create_task(hold())
        second = asyncio.create_task(hold())
        await both_entered.wait()
        with pytest.raises(BudgetExceeded) as raised:
            async with guard.professional_slot():
                raise AssertionError("denied slot entered")
        assert raised.value.code == "BUDGET_ACTIVE_LIMIT_EXCEEDED"
        release.set()
        await asyncio.gather(first, second)

        counters = guard.telemetry().counters
        assert counters.current_professional_concurrency == 0
        assert counters.peak_professional_concurrency == 2

        with pytest.raises(RuntimeError, match="probe"):
            async with guard.professional_slot():
                raise RuntimeError("probe")
        assert guard.telemetry().counters.current_professional_concurrency == 0

    run(scenario())


def test_professional_concurrency_hard_limit_is_non_overridable() -> None:
    async def scenario() -> None:
        policy = with_limit(
            default_budget_policy("P3"),
            BudgetDimension.PROFESSIONAL_CONCURRENCY,
            default=2,
            active=2,
            hard=2,
        )
        guard = BudgetGuard(policy)
        async with guard.professional_slot():
            async with guard.professional_slot():
                with pytest.raises(BudgetExceeded) as raised:
                    async with guard.professional_slot():
                        raise AssertionError("hard-denied slot entered")
        assert raised.value.code == "BUDGET_HARD_LIMIT_EXCEEDED"
        assert guard.telemetry().counters.peak_professional_concurrency == 2

    run(scenario())


class CountingExecutor:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.calls = 0
        self.delay = delay

    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return RESULT_TEMPLATE.model_copy(
            update={"task_id": context.parent_task_id, "run_id": context.run_id}
        ).model_dump(mode="json")


def general_context() -> ChildTaskContext:
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset({"artifact.read@1"}),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="model-1",
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


def test_guarded_child_stops_on_graph_budget_before_executor_call() -> None:
    context = general_context()
    guard = BudgetGuard(context.budget)
    executor = CountingExecutor()

    result = run(
        TaskScheduler(budget_guard=guard).run_sync(
            (context,),
            {"general": executor},
        )
    )

    assignment = result.assignments[0]
    assert result.status is ScheduleStatus.FAILED
    assert assignment.status is AssignmentStatus.FAILED
    assert assignment.execution_calls == 0
    assert assignment.error_code == "BUDGET_ACTIVE_LIMIT_EXCEEDED"
    assert executor.calls == 0
    assert guard.telemetry().counters.graph_steps == 1
    counters = guard.telemetry().counters
    assert counters.terminal_transitions == 1
    assert counters.terminal_budget_stops == 1


def professional_contexts_with_budget(
    policy: BudgetPolicy,
) -> tuple[ChildTaskContext, ...]:
    task = TASK.model_copy(update={"task_class": "P3", "budget": policy})
    names = ("alpha", "beta", "gamma")
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset(),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="model-1",
            ),
            *(
                AgentDefinition(
                    agent_type=name,
                    kind=ChildAgentKind.PROFESSIONAL,
                    allowed_tools=frozenset(),
                    skill_version=f"{name}-1",
                    prompt_version=f"{name}-1",
                    model_version="model-1",
                )
                for name in names
            ),
        )
    )
    assignments = tuple(
        ProfessionalAssignment(assignment_id=name, agent_type=name) for name in names
    )
    dispatch = DispatchPlan(
        task_id=task.task_id,
        route=RouteKind.MULTIPLE_INDEPENDENT_ASYNC_REVIEW,
        general_agent=False,
        professional_assignments=assignments,
        asynchronous=True,
        review_required=True,
        human_required=False,
    )
    inputs = tuple(
        ChildInput(
            assignment_id=name,
            goal=f"Run {name}",
            success_criteria=("Return typed output",),
        )
        for name in names
    )
    return ChildContextFactory(registry).prepare(
        task,
        dispatch,
        professional_inputs=inputs,
    )


def test_guarded_scheduler_never_exceeds_professional_concurrency() -> None:
    policy = with_limit(
        default_budget_policy("P3"),
        BudgetDimension.PROFESSIONAL_CONCURRENCY,
        default=2,
        active=2,
        hard=4,
    )
    contexts = professional_contexts_with_budget(policy)
    guard = BudgetGuard(policy)
    executors = {context.assignment_id: CountingExecutor(delay=0.005) for context in contexts}

    result = run(
        TaskScheduler(budget_guard=guard).run_sync(
            contexts,
            executors,
        )
    )

    assert result.status is ScheduleStatus.COMPLETED
    assert result.max_concurrency_observed == 2
    counters = guard.telemetry().counters
    assert counters.peak_professional_concurrency == 2
    assert counters.current_professional_concurrency == 0
    assert counters.graph_steps == 12
    assert counters.terminal_transitions == 3
    assert all(executor.calls == 1 for executor in executors.values())


def test_scheduler_rejects_guard_bound_to_different_policy() -> None:
    context = general_context()
    executor = CountingExecutor()

    with pytest.raises(SchedulerError) as raised:
        TaskScheduler(budget_guard=BudgetGuard(default_budget_policy("G0"))).enqueue(
            (context,), {"general": executor}
        )

    assert raised.value.code == "SCHEDULE_BUDGET_GUARD_MISMATCH"
    assert executor.calls == 0
