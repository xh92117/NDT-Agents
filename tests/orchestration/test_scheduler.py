"""S1-06 synchronous, queued-asynchronous, serial, and parallel scheduler tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from pathlib import Path
from typing import Any

import pytest

from ndt_agents.contracts.v1 import AgentResult, AgentStatus, Limit, TaskContext
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import (
    AgentDefinition,
    ChildAgentKind,
    ChildInput,
    ChildSideEffectClass,
    ChildTaskContext,
)
from ndt_agents.orchestration.models import DispatchPlan, ProfessionalAssignment, RouteKind
from ndt_agents.orchestration.registry import AgentRegistry
from ndt_agents.orchestration.scheduler import (
    AssignmentStatus,
    ScheduleHandle,
    ScheduleMode,
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


class ConcurrencyProbe:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0


class ProbeExecutor:
    def __init__(
        self,
        *,
        probe: ConcurrencyProbe | None = None,
        order: list[str] | None = None,
        delay: float = 0.0,
        fail: bool = False,
        result_status: AgentStatus = AgentStatus.SUCCESS,
    ) -> None:
        self.calls = 0
        self.probe = probe
        self.order = order
        self.delay = delay
        self.fail = fail
        self.result_status = result_status

    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]:
        self.calls += 1
        if self.order is not None:
            self.order.append(context.assignment_id)
        if self.probe is not None:
            self.probe.active += 1
            self.probe.maximum = max(self.probe.maximum, self.probe.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("deterministic child failure")
            failure_code = (
                "PROBE_FAILURE"
                if self.result_status in {AgentStatus.FAILED, AgentStatus.BLOCKED}
                else None
            )
            result = RESULT_TEMPLATE.model_copy(
                update={
                    "task_id": context.parent_task_id,
                    "run_id": context.run_id,
                    "status": self.result_status,
                    "failure_code": failure_code,
                }
            )
            return result.model_dump(mode="json")
        finally:
            if self.probe is not None:
                self.probe.active -= 1


def registry() -> AgentRegistry:
    definitions = [
        AgentDefinition(
            agent_type="general",
            kind=ChildAgentKind.GENERAL,
            allowed_tools=frozenset({"artifact.read@1"}),
            skill_version="general-1",
            prompt_version="general-1",
            model_version="model-1",
        )
    ]
    definitions.extend(
        AgentDefinition(
            agent_type=name,
            kind=ChildAgentKind.PROFESSIONAL,
            allowed_tools=frozenset({"artifact.read@1", "artifact.write@1"}),
            skill_version=f"{name}-1",
            prompt_version=f"{name}-1",
            model_version="model-1",
        )
        for name in ("alpha", "beta", "gamma")
    )
    return AgentRegistry(definitions=tuple(definitions))


def task_with_concurrency(active: int, hard: int) -> TaskContext:
    limit = Limit(default=1, active=active, hard=hard)
    budget = TASK.budget.model_copy(
        update={
            "policy_id": f"test-p3-{active}-{hard}",
            "task_class": "P3",
            "professional_concurrency": limit,
        }
    )
    return TASK.model_copy(update={"task_class": "P3", "budget": budget})


def professional_contexts(
    assignments: tuple[ProfessionalAssignment, ...],
    *,
    active: int = 2,
    hard: int = 2,
    mutating: frozenset[str] = frozenset(),
) -> tuple[ChildTaskContext, ...]:
    task = task_with_concurrency(active, hard)
    route = (
        RouteKind.MULTIPLE_DEPENDENT_ASYNC_REVIEW
        if any(item.depends_on for item in assignments)
        else RouteKind.MULTIPLE_INDEPENDENT_ASYNC_REVIEW
    )
    dispatch = DispatchPlan(
        task_id=task.task_id,
        route=route,
        general_agent=False,
        professional_assignments=assignments,
        asynchronous=True,
        review_required=True,
        human_required=False,
    )
    inputs = tuple(
        ChildInput(
            assignment_id=item.assignment_id,
            goal=f"Run {item.assignment_id}",
            success_criteria=("Return a typed result",),
            requested_tools=(
                ("artifact.write@1",) if item.assignment_id in mutating else ("artifact.read@1",)
            ),
            side_effect_class=(
                ChildSideEffectClass.MUTATING
                if item.assignment_id in mutating
                else ChildSideEffectClass.READ_ONLY
            ),
        )
        for item in assignments
    )
    return ChildContextFactory(registry()).prepare(
        task,
        dispatch,
        professional_inputs=inputs,
    )


def general_context() -> ChildTaskContext:
    dispatch = DispatchPlan(
        task_id=TASK.task_id,
        route=RouteKind.GENERAL_SYNC,
        general_agent=True,
        professional_assignments=(),
        asynchronous=False,
        review_required=False,
        human_required=False,
    )
    return ChildContextFactory(registry()).prepare(TASK, dispatch)[0]


def assignments() -> tuple[ProfessionalAssignment, ...]:
    return tuple(
        ProfessionalAssignment(assignment_id=name, agent_type=name)
        for name in ("alpha", "beta", "gamma")
    )


def test_general_sync_completes_before_return() -> None:
    context = general_context()
    executor = ProbeExecutor()

    result = run(TaskScheduler().run_sync((context,), {"general": executor}))

    assert result.mode is ScheduleMode.SYNC
    assert result.status is ScheduleStatus.COMPLETED
    assert result.max_concurrency_observed == 1
    assert result.assignments[0].execution_calls == 1
    assert executor.calls == 1


def test_async_enqueue_has_no_hidden_execution_and_advance_is_stable() -> None:
    context = professional_contexts((assignments()[0],), active=1, hard=1)[0]
    executor = ProbeExecutor()
    scheduler = TaskScheduler()

    handle = scheduler.enqueue((context,), {"alpha": executor})

    assert isinstance(handle, ScheduleHandle)
    assert handle.status is ScheduleStatus.QUEUED
    assert handle.parent_task_id == context.parent_task_id
    assert handle.scope == context.scope
    assert executor.calls == 0

    first = run(
        scheduler.advance(
            handle.schedule_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
        )
    )
    second = run(
        scheduler.advance(
            handle.schedule_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
        )
    )

    assert first == second
    assert first.mode is ScheduleMode.ASYNC
    assert first.status is ScheduleStatus.COMPLETED
    assert executor.calls == 1


def test_cancel_before_advance_calls_no_executor() -> None:
    context = professional_contexts((assignments()[0],), active=1, hard=1)[0]
    executor = ProbeExecutor()
    scheduler = TaskScheduler()
    handle = scheduler.enqueue((context,), {"alpha": executor})

    result = scheduler.cancel(
        handle.schedule_id,
        scope=context.scope,
        parent_task_id=context.parent_task_id,
    )

    assert result.status is ScheduleStatus.CANCELLED
    assert result.assignments[0].status is AssignmentStatus.CANCELLED
    assert result.assignments[0].execution_calls == 0
    assert executor.calls == 0


def test_cancelled_prerequisite_blocks_dependent_without_calls() -> None:
    planned = (
        ProfessionalAssignment(assignment_id="alpha", agent_type="alpha"),
        ProfessionalAssignment(assignment_id="beta", agent_type="beta", depends_on=("alpha",)),
    )
    contexts = professional_contexts(planned, active=2, hard=2)
    executors = {"alpha": ProbeExecutor(), "beta": ProbeExecutor()}
    scheduler = TaskScheduler()
    handle = scheduler.enqueue(contexts, executors)

    scheduler.cancel_assignment(
        handle.schedule_id,
        "alpha",
        scope=contexts[0].scope,
        parent_task_id=contexts[0].parent_task_id,
    )
    result = run(
        scheduler.advance(
            handle.schedule_id,
            scope=contexts[0].scope,
            parent_task_id=contexts[0].parent_task_id,
        )
    )

    assert result.status is ScheduleStatus.FAILED
    assert result.assignments[0].status is AssignmentStatus.CANCELLED
    assert result.assignments[1].status is AssignmentStatus.BLOCKED
    assert all(item.execution_calls == 0 for item in result.assignments)
    assert all(executor.calls == 0 for executor in executors.values())


def test_independent_read_only_work_respects_active_parallel_limit() -> None:
    contexts = professional_contexts(assignments(), active=2, hard=2)
    probe = ConcurrencyProbe()
    executors = {
        context.assignment_id: ProbeExecutor(probe=probe, delay=0.01) for context in contexts
    }

    result = run(TaskScheduler().run_sync(contexts, executors))

    assert result.status is ScheduleStatus.COMPLETED
    assert result.waves_completed == 1
    assert result.max_concurrency_observed == 2
    assert probe.maximum == 2
    assert all(executor.calls == 1 for executor in executors.values())


def test_dependencies_run_in_topological_serial_waves() -> None:
    planned = (
        ProfessionalAssignment(assignment_id="alpha", agent_type="alpha"),
        ProfessionalAssignment(assignment_id="beta", agent_type="beta", depends_on=("alpha",)),
        ProfessionalAssignment(assignment_id="gamma", agent_type="gamma", depends_on=("beta",)),
    )
    contexts = professional_contexts(planned, active=3, hard=3)
    order: list[str] = []
    executors = {
        context.assignment_id: ProbeExecutor(order=order, delay=0.001) for context in contexts
    }

    result = run(TaskScheduler().run_sync(contexts, executors))

    assert result.status is ScheduleStatus.COMPLETED
    assert result.waves_completed == 3
    assert result.max_concurrency_observed == 1
    assert order == ["alpha", "beta", "gamma"]
    assert [item.wave for item in result.assignments] == [1, 2, 3]


def test_independent_mutations_are_serial() -> None:
    planned = assignments()[:2]
    contexts = professional_contexts(
        planned,
        active=2,
        hard=2,
        mutating=frozenset({"alpha", "beta"}),
    )
    probe = ConcurrencyProbe()
    executors = {
        context.assignment_id: ProbeExecutor(probe=probe, delay=0.005) for context in contexts
    }

    result = run(TaskScheduler().run_sync(contexts, executors))

    assert result.status is ScheduleStatus.COMPLETED
    assert result.max_concurrency_observed == 1
    assert probe.maximum == 1


@pytest.mark.parametrize("fail_as_result", [False, True])
def test_failed_prerequisite_blocks_dependent_without_call(fail_as_result: bool) -> None:
    planned = (
        ProfessionalAssignment(assignment_id="alpha", agent_type="alpha"),
        ProfessionalAssignment(assignment_id="beta", agent_type="beta", depends_on=("alpha",)),
    )
    contexts = professional_contexts(planned, active=2, hard=2)
    alpha = ProbeExecutor(
        fail=not fail_as_result,
        result_status=AgentStatus.FAILED if fail_as_result else AgentStatus.SUCCESS,
    )
    beta = ProbeExecutor()

    result = run(TaskScheduler().run_sync(contexts, {"alpha": alpha, "beta": beta}))

    assert result.status is ScheduleStatus.FAILED
    assert result.assignments[0].status is AssignmentStatus.FAILED
    assert result.assignments[0].execution_calls == 1
    assert result.assignments[1].status is AssignmentStatus.BLOCKED
    assert result.assignments[1].execution_calls == 0
    assert alpha.calls == 1
    assert beta.calls == 0


def test_cycle_is_rejected_before_any_child_call() -> None:
    cyclic = professional_contexts(
        (
            ProfessionalAssignment(assignment_id="alpha", agent_type="alpha", depends_on=("beta",)),
            ProfessionalAssignment(assignment_id="beta", agent_type="beta", depends_on=("alpha",)),
        ),
        active=2,
        hard=2,
    )
    alpha = ProbeExecutor()
    beta = ProbeExecutor()

    with pytest.raises(SchedulerError) as raised:
        TaskScheduler().enqueue(cyclic, {"alpha": alpha, "beta": beta})

    assert raised.value.code == "SCHEDULE_DEPENDENCY_CYCLE"
    assert alpha.calls == beta.calls == 0


def test_scope_and_hard_limit_are_rejected_before_execution() -> None:
    contexts = professional_contexts(assignments()[:2], active=2, hard=4)
    mismatched = (
        contexts[0],
        contexts[1].model_copy(
            update={
                "scope": contexts[1].scope.model_copy(
                    update={"permission_version": "different-policy"}
                )
            }
        ),
    )
    executors = {"alpha": ProbeExecutor(), "beta": ProbeExecutor()}

    with pytest.raises(SchedulerError) as scope_error:
        TaskScheduler().enqueue(mismatched, executors)
    with pytest.raises(SchedulerError) as hard_error:
        TaskScheduler(hard_professional_concurrency=2).enqueue(contexts, executors)

    assert scope_error.value.code == "SCHEDULE_SCOPE_MISMATCH"
    assert hard_error.value.code == "SCHEDULE_HARD_LIMIT_DENIED"
    assert all(executor.calls == 0 for executor in executors.values())


def test_async_advance_rejects_wrong_caller_binding_without_dequeue() -> None:
    context = professional_contexts((assignments()[0],), active=1, hard=1)[0]
    executor = ProbeExecutor()
    scheduler = TaskScheduler()
    handle = scheduler.enqueue((context,), {"alpha": executor})
    wrong_scope = context.scope.model_copy(update={"permission_version": "stale-policy"})

    with pytest.raises(SchedulerError) as raised:
        run(
            scheduler.advance(
                handle.schedule_id,
                scope=wrong_scope,
                parent_task_id=context.parent_task_id,
            )
        )

    assert raised.value.code == "SCHEDULE_BINDING_DENIED"
    assert executor.calls == 0
    result = run(
        scheduler.advance(
            handle.schedule_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
        )
    )
    assert result.status is ScheduleStatus.COMPLETED
    assert executor.calls == 1


def test_tampered_child_context_is_rejected_before_execution() -> None:
    context = general_context()
    tampered = context.model_copy(update={"goal": "Unmanifested changed goal"})
    executor = ProbeExecutor()

    with pytest.raises(SchedulerError) as raised:
        TaskScheduler().enqueue((tampered,), {"general": executor})

    assert raised.value.code == "SCHEDULE_CONTEXT_INTEGRITY_FAILED"
    assert executor.calls == 0
