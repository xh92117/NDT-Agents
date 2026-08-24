"""S1-07 checkpoint, idempotency, interrupt, and restart recovery tests."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Coroutine, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ndt_agents.contracts.v1 import AgentResult, TaskContext
from ndt_agents.orchestration.budget import default_budget_policy
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import (
    AgentDefinition,
    ChildAgentKind,
    ChildTaskContext,
)
from ndt_agents.orchestration.models import DispatchPlan, RouteKind
from ndt_agents.orchestration.recovery import (
    InMemoryRecoveryBackend,
    RecoveryControl,
    RecoveryError,
    RecoveryFaultPoint,
    RecoveryPhase,
    SimulatedProcessTermination,
    TaskRecoveryRuntime,
)
from ndt_agents.orchestration.registry import AgentRegistry
from ndt_agents.storage.artifacts import ArtifactStorageService, InMemoryObjectBackend

ROOT = Path(__file__).resolve().parents[2]
TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
RESULT_TEMPLATE = AgentResult.model_validate_json(
    (ROOT / "examples/contracts/v1/agent-result.valid.json").read_text("utf-8")
)


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def context_for(task: TaskContext = TASK) -> ChildTaskContext:
    task = task.model_copy(update={"task_class": "G0", "budget": default_budget_policy("G0")})
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
        task_id=task.task_id,
        route=RouteKind.GENERAL_SYNC,
        general_agent=True,
        professional_assignments=(),
        asynchronous=False,
        review_required=False,
        human_required=False,
    )
    return ChildContextFactory(registry).prepare(task, dispatch)[0]


class RecoveryProbe:
    def __init__(
        self,
        *,
        terminate: bool = False,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.calls = 0
        self.terminate = terminate
        self.started = started
        self.release = release

    async def execute(
        self, context: ChildTaskContext, control: RecoveryControl
    ) -> Mapping[str, Any]:
        del control
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.terminate:
            raise SimulatedProcessTermination()
        return RESULT_TEMPLATE.model_copy(
            update={"task_id": context.parent_task_id, "run_id": context.run_id}
        ).model_dump(mode="json")


class SideEffectProbe:
    def __init__(
        self,
        side_effect_id: UUID,
        *,
        terminate_after_effect: bool = False,
    ) -> None:
        self.side_effect_id = side_effect_id
        self.terminate_after_effect = terminate_after_effect
        self.calls = 0
        self.effect_calls = 0

    async def execute(
        self, context: ChildTaskContext, control: RecoveryControl
    ) -> Mapping[str, Any]:
        self.calls += 1

        async def operation() -> Mapping[str, Any]:
            self.effect_calls += 1
            if self.terminate_after_effect:
                raise SimulatedProcessTermination()
            return {"receipt": "committed"}

        await control.execute_side_effect(
            side_effect_id=self.side_effect_id,
            request_sha256=hashlib.sha256(b"exact-side-effect-input").hexdigest(),
            operation=operation,
        )
        return RESULT_TEMPLATE.model_copy(
            update={"task_id": context.parent_task_id, "run_id": context.run_id}
        ).model_dump(mode="json")


def services(
    *,
    backend: InMemoryRecoveryBackend | None = None,
    objects: InMemoryObjectBackend | None = None,
    fault: object | None = None,
) -> tuple[
    TaskRecoveryRuntime,
    InMemoryRecoveryBackend,
    InMemoryObjectBackend,
    ArtifactStorageService,
]:
    recovery_backend = backend or InMemoryRecoveryBackend()
    object_backend = objects or InMemoryObjectBackend()
    artifact_service = ArtifactStorageService(
        backend=object_backend,
        bucket="recovery-artifacts",
    )
    runtime = TaskRecoveryRuntime(
        backend=recovery_backend,
        artifact_service=artifact_service,
        fault_injector=fault if callable(fault) else None,
    )
    return runtime, recovery_backend, object_backend, artifact_service


def test_submit_is_exact_request_idempotent_and_conflicts_on_changed_input() -> None:
    async def scenario() -> None:
        runtime, _, _, _ = services()
        context = context_for()
        executor = RecoveryProbe()
        first = await runtime.submit(
            (context,), {"general": executor}, idempotency_key="request-001"
        )
        second = await runtime.submit(
            (context,), {"general": executor}, idempotency_key="request-001"
        )
        changed_task = TASK.model_copy(update={"goal": "A different exact request"})
        changed_context = context_for(changed_task)

        assert first.reused is False
        assert second.reused is True
        assert second.recovery_id == first.recovery_id
        assert executor.calls == 0
        with pytest.raises(RecoveryError) as raised:
            await runtime.submit(
                (changed_context,),
                {"general": executor},
                idempotency_key="request-001",
            )
        assert raised.value.code == "IDEMPOTENCY_CONFLICT"

    run(scenario())


def test_successful_run_writes_monotonic_immutable_checkpoints() -> None:
    async def scenario() -> None:
        runtime, backend, _, artifact_service = services()
        context = context_for()
        executor = RecoveryProbe()
        handle = await runtime.submit(
            (context,), {"general": executor}, idempotency_key="checkpoint-001"
        )

        outcome = await runtime.advance(
            handle.recovery_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
        )

        assert outcome.phase is RecoveryPhase.COMPLETED
        assert outcome.checkpoint.sequence == 3
        assert await backend.checkpoint_sequences(handle.recovery_id, context.scope) == (
            0,
            1,
            2,
            3,
        )
        assert outcome.checkpoint.state_sha256 == outcome.checkpoint.state_artifact.sha256
        assert await artifact_service.get(context.scope, outcome.checkpoint.state_artifact)
        assert executor.calls == 1
        assert outcome.budget_telemetry.counters.graph_steps == 4
        assert outcome.budget_telemetry.counters.reserved_graph_steps == 0

    run(scenario())


@pytest.mark.parametrize(
    "fault_point",
    [RecoveryFaultPoint.AFTER_RUNNING_CHECKPOINT, RecoveryFaultPoint.AFTER_ASSIGNMENT_OUTPUTS],
)
def test_new_runtime_recovers_at_fault_boundaries_without_duplicate_output_call(
    fault_point: RecoveryFaultPoint,
) -> None:
    async def scenario() -> None:
        triggered = False

        def inject(point: RecoveryFaultPoint, _snapshot: object) -> None:
            nonlocal triggered
            if point is fault_point and not triggered:
                triggered = True
                raise SimulatedProcessTermination()

        runtime, backend, objects, artifact_service = services(fault=inject)
        context = context_for()
        first_executor = RecoveryProbe()
        handle = await runtime.submit(
            (context,), {"general": first_executor}, idempotency_key=f"fault-{fault_point.value}"
        )
        with pytest.raises(SimulatedProcessTermination):
            await runtime.advance(
                handle.recovery_id,
                scope=context.scope,
                parent_task_id=context.parent_task_id,
            )

        replacement = RecoveryProbe()
        recovered = TaskRecoveryRuntime(
            backend=backend,
            artifact_service=artifact_service,
        )
        outcome = await recovered.advance(
            handle.recovery_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
            executors={"general": replacement},
        )

        assert objects is not None
        assert outcome.phase is RecoveryPhase.COMPLETED
        assert outcome.recovered is True
        assert first_executor.calls == (
            0 if fault_point is RecoveryFaultPoint.AFTER_RUNNING_CHECKPOINT else 1
        )
        assert replacement.calls == (
            1 if fault_point is RecoveryFaultPoint.AFTER_RUNNING_CHECKPOINT else 0
        )
        assert outcome.budget_telemetry.counters.graph_steps == (
            8 if fault_point is RecoveryFaultPoint.AFTER_RUNNING_CHECKPOINT else 4
        )
        assert outcome.budget_telemetry.counters.retries == (
            1 if fault_point is RecoveryFaultPoint.AFTER_RUNNING_CHECKPOINT else 0
        )

    run(scenario())


def test_process_loss_during_child_recovers_from_running_checkpoint() -> None:
    async def scenario() -> None:
        runtime, backend, _, artifact_service = services()
        context = context_for()
        terminated = RecoveryProbe(terminate=True)
        handle = await runtime.submit(
            (context,), {"general": terminated}, idempotency_key="during-child"
        )
        with pytest.raises(SimulatedProcessTermination):
            await runtime.advance(
                handle.recovery_id,
                scope=context.scope,
                parent_task_id=context.parent_task_id,
            )

        replacement = RecoveryProbe()
        recovered = TaskRecoveryRuntime(backend=backend, artifact_service=artifact_service)
        outcome = await recovered.advance(
            handle.recovery_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
            executors={"general": replacement},
        )

        assert outcome.phase is RecoveryPhase.COMPLETED
        assert outcome.recovered is True
        assert terminated.calls == replacement.calls == 1
        assert outcome.budget_telemetry.counters.graph_steps == 8
        assert outcome.budget_telemetry.counters.retries == 1

    run(scenario())


def test_repeated_process_loss_exhausts_recovery_budget_before_executor_call() -> None:
    async def scenario() -> None:
        def terminate_after_running(point: RecoveryFaultPoint, _snapshot: object) -> None:
            if point is RecoveryFaultPoint.AFTER_RUNNING_CHECKPOINT:
                raise SimulatedProcessTermination()

        first_runtime, backend, _, artifact_service = services(fault=terminate_after_running)
        context = context_for()
        first_executor = RecoveryProbe()
        handle = await first_runtime.submit(
            (context,), {"general": first_executor}, idempotency_key="budget-exhaustion"
        )
        with pytest.raises(SimulatedProcessTermination):
            await first_runtime.advance(
                handle.recovery_id,
                scope=context.scope,
                parent_task_id=context.parent_task_id,
            )

        second_executor = RecoveryProbe()
        second_runtime = TaskRecoveryRuntime(
            backend=backend,
            artifact_service=artifact_service,
            fault_injector=terminate_after_running,
        )
        with pytest.raises(SimulatedProcessTermination):
            await second_runtime.advance(
                handle.recovery_id,
                scope=context.scope,
                parent_task_id=context.parent_task_id,
                executors={"general": second_executor},
            )

        final_executor = RecoveryProbe()
        final_runtime = TaskRecoveryRuntime(
            backend=backend,
            artifact_service=artifact_service,
        )
        outcome = await final_runtime.advance(
            handle.recovery_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
            executors={"general": final_executor},
        )

        assert outcome.phase is RecoveryPhase.FAILED
        assert outcome.schedule_result is not None
        assignment = outcome.schedule_result.assignments[0]
        assert assignment.execution_calls == 0
        assert assignment.error_code == "BUDGET_ACTIVE_LIMIT_EXCEEDED"
        assert first_executor.calls == second_executor.calls == final_executor.calls == 0
        counters = outcome.budget_telemetry.counters
        assert counters.graph_steps == 8
        assert counters.reserved_graph_steps == 0
        assert counters.retries == 2
        assert counters.terminal_budget_stops == 1

    run(scenario())


def test_interrupt_during_child_pauses_after_result_and_resume_does_not_rerun() -> None:
    async def scenario() -> None:
        runtime, backend, _, artifact_service = services()
        context = context_for()
        started = asyncio.Event()
        release = asyncio.Event()
        executor = RecoveryProbe(started=started, release=release)
        handle = await runtime.submit(
            (context,), {"general": executor}, idempotency_key="interrupt-001"
        )
        advancing = asyncio.create_task(
            runtime.advance(
                handle.recovery_id,
                scope=context.scope,
                parent_task_id=context.parent_task_id,
            )
        )
        await started.wait()
        await runtime.request_interrupt(
            handle.recovery_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
            reason="Operator requested a safe pause.",
        )
        release.set()
        interrupted = await advancing

        assert interrupted.phase is RecoveryPhase.INTERRUPTED
        assert interrupted.schedule_result is not None
        assert executor.calls == 1

        replacement = RecoveryProbe()
        recovered = TaskRecoveryRuntime(backend=backend, artifact_service=artifact_service)
        completed = await recovered.resume(
            handle.recovery_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
            executors={"general": replacement},
        )
        assert completed.phase is RecoveryPhase.COMPLETED
        assert completed.recovered is True
        assert replacement.calls == 0

    run(scenario())


def test_committed_side_effect_is_recorded_and_not_repeated_after_fault() -> None:
    async def scenario() -> None:
        def inject(point: RecoveryFaultPoint, _snapshot: object) -> None:
            if point is RecoveryFaultPoint.AFTER_ASSIGNMENT_OUTPUTS:
                raise SimulatedProcessTermination()

        runtime, backend, _, artifact_service = services(fault=inject)
        context = context_for()
        effect_id = UUID("00000000-0000-4000-8000-000000000701")
        executor = SideEffectProbe(effect_id)
        handle = await runtime.submit(
            (context,), {"general": executor}, idempotency_key="side-effect-committed"
        )
        with pytest.raises(SimulatedProcessTermination):
            await runtime.advance(
                handle.recovery_id,
                scope=context.scope,
                parent_task_id=context.parent_task_id,
            )

        replacement = SideEffectProbe(effect_id)
        recovered = TaskRecoveryRuntime(backend=backend, artifact_service=artifact_service)
        outcome = await recovered.advance(
            handle.recovery_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
            executors={"general": replacement},
        )

        assert outcome.phase is RecoveryPhase.COMPLETED
        assert outcome.checkpoint.committed_side_effect_ids == (effect_id,)
        assert executor.effect_calls == 1
        assert replacement.calls == replacement.effect_calls == 0

    run(scenario())


def test_ambiguous_side_effect_requires_reconciliation_without_repeating_operation() -> None:
    async def scenario() -> None:
        runtime, backend, _, artifact_service = services()
        context = context_for()
        effect_id = UUID("00000000-0000-4000-8000-000000000702")
        first = SideEffectProbe(effect_id, terminate_after_effect=True)
        handle = await runtime.submit(
            (context,), {"general": first}, idempotency_key="side-effect-ambiguous"
        )
        with pytest.raises(SimulatedProcessTermination):
            await runtime.advance(
                handle.recovery_id,
                scope=context.scope,
                parent_task_id=context.parent_task_id,
            )

        replacement = SideEffectProbe(effect_id)
        recovered = TaskRecoveryRuntime(backend=backend, artifact_service=artifact_service)
        outcome = await recovered.advance(
            handle.recovery_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
            executors={"general": replacement},
        )

        assert outcome.phase is RecoveryPhase.FAILED
        assert outcome.schedule_result is not None
        assignment = outcome.schedule_result.assignments[0]
        assert assignment.error_code == "SIDE_EFFECT_RECONCILIATION_REQUIRED"
        assert first.effect_calls == 1
        assert replacement.calls == 1
        assert replacement.effect_calls == 0

    run(scenario())


def test_cross_scope_and_corrupt_checkpoint_restore_are_denied() -> None:
    async def scenario() -> None:
        runtime, backend, objects, artifact_service = services()
        context = context_for()
        executor = RecoveryProbe()
        handle = await runtime.submit(
            (context,), {"general": executor}, idempotency_key="integrity-001"
        )
        wrong_scope = context.scope.model_copy(update={"permission_version": "stale"})

        with pytest.raises(RecoveryError) as scope_error:
            await runtime.inspect(
                handle.recovery_id,
                scope=wrong_scope,
                parent_task_id=context.parent_task_id,
            )
        assert scope_error.value.code == "RECOVERY_SCOPE_DENIED"

        checkpoint = await backend.latest_checkpoint(handle.recovery_id, context.scope)
        object_key = checkpoint.state_artifact.uri.removeprefix("artifact://recovery-artifacts/")
        objects.corrupt(object_key, b"corrupt-checkpoint")
        restarted = TaskRecoveryRuntime(backend=backend, artifact_service=artifact_service)
        with pytest.raises(RecoveryError) as integrity_error:
            await restarted.inspect(
                handle.recovery_id,
                scope=context.scope,
                parent_task_id=context.parent_task_id,
            )
        assert integrity_error.value.code == "CHECKPOINT_INTEGRITY_FAILED"

    run(scenario())
