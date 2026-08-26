"""S1-15 configured Main Graph, scheduler, and recovery assembly tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ndt_agents.contracts.v1 import AgentResult, Limit, TaskContext
from ndt_agents.models.config import load_model_runtime_configuration
from ndt_agents.models.instructions import ApplicationInstruction
from ndt_agents.orchestration.agent_config import (
    ConfiguredAgentRuntime,
    load_agent_runtime_configuration,
)
from ndt_agents.orchestration.budget import default_budget_policy
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import (
    ChildAgentKind,
    ChildInput,
    ChildSideEffectClass,
    ChildTaskContext,
)
from ndt_agents.orchestration.configured_runtime import (
    ConfiguredExecutorFactory,
    ConfiguredOrchestrationRuntime,
    ConfiguredRecoverableExecutorBinder,
    ConfiguredRunStatus,
    ConfiguredRuntimeError,
)
from ndt_agents.orchestration.main_graph import MainGraph
from ndt_agents.orchestration.models import ProfessionalAssignment, RouteSignals
from ndt_agents.orchestration.prompt_registry import load_prompt_registry
from ndt_agents.orchestration.recovery import (
    InMemoryRecoveryBackend,
    RecoveryControl,
    RecoveryError,
    RecoveryFaultPoint,
    RecoveryPhase,
    SimulatedProcessTermination,
    TaskRecoveryRuntime,
)
from ndt_agents.orchestration.scheduler import ScheduleHandle, ScheduleStatus
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings
from ndt_agents.storage.artifacts import ArtifactStorageService, InMemoryObjectBackend

ROOT = Path(__file__).resolve().parents[2]
TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
RESULT = AgentResult.model_validate_json(
    (ROOT / "examples/contracts/v1/agent-result.valid.json").read_text("utf-8")
)
PROMPT_CONFIG = ROOT / "prompts/professional/catalog.v1.yaml"


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def configured_runtime(*, professional: bool = False) -> ConfiguredAgentRuntime:
    models = load_model_runtime_configuration(
        ROOT / "config/runtime/model-bindings.example.yaml", environ={}
    )
    base = load_agent_runtime_configuration(
        ROOT / "config/runtime/agent-runtime.example.yaml",
        model_runtime=models,
        prompt_registry=load_prompt_registry(PROMPT_CONFIG),
    )
    if not professional:
        return base
    general = base.profile("general")
    alpha = general.model_copy(
        update={
            "name": "alpha",
            "kind": ChildAgentKind.PROFESSIONAL,
            "description": "Professional alpha test profile.",
            "skill_version": "alpha-1",
        }
    )
    return replace(
        base,
        profiles=(alpha, general),
        configuration_sha256="1" * 64,
    )


class Delegate:
    def __init__(self) -> None:
        self.calls = 0
        self.instructions: list[ApplicationInstruction] = []

    async def execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        self.calls += 1
        self.instructions.append(instruction)
        return RESULT.model_copy(
            update={"task_id": context.parent_task_id, "run_id": context.run_id}
        ).model_dump(mode="json")


class RecoverableDelegate:
    def __init__(self) -> None:
        self.calls = 0
        self.controls: list[RecoveryControl] = []
        self.instructions: list[ApplicationInstruction] = []

    async def execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
        control: RecoveryControl,
    ) -> Mapping[str, Any]:
        self.calls += 1
        self.instructions.append(instruction)
        self.controls.append(control)
        return RESULT.model_copy(
            update={"task_id": context.parent_task_id, "run_id": context.run_id}
        ).model_dump(mode="json")


def delegate_catalog(
    runtime: ConfiguredAgentRuntime,
    general: Delegate,
) -> dict[str, Delegate]:
    return {
        profile.name: general if profile.name == "general" else Delegate()
        for profile in runtime.profiles
    }


def recoverable_delegate_catalog(
    runtime: ConfiguredAgentRuntime,
    general: RecoverableDelegate,
) -> dict[str, RecoverableDelegate]:
    return {
        profile.name: general if profile.name == "general" else RecoverableDelegate()
        for profile in runtime.profiles
    }


def general_signals() -> RouteSignals:
    return RouteSignals(
        task_id=TASK.task_id,
        general_eligible=True,
    )


def general_context(runtime: ConfiguredAgentRuntime) -> ChildTaskContext:
    task = TASK.model_copy(update={"task_class": "G0", "budget": default_budget_policy("G0")})
    main = MainGraph().run(task, general_signals())
    assert main.dispatch is not None
    return ChildContextFactory(runtime.build_agent_registry()).prepare(task, main.dispatch)[0]


def test_general_route_runs_through_configured_langgraph_and_sync_scheduler() -> None:
    runtime = configured_runtime()
    delegate = Delegate()
    configured = ConfiguredOrchestrationRuntime(
        ConfiguredExecutorFactory(runtime, delegate_catalog(runtime, delegate))
    )

    result = run(configured.start(TASK, general_signals()))

    assert result.status is ConfiguredRunStatus.SCHEDULED
    assert result.configuration_sha256 == runtime.configuration_sha256
    assert result.contexts[0].agent_configuration_sha256 == runtime.configuration_sha256
    assert result.schedule is not None
    assert not isinstance(result.schedule, ScheduleHandle)
    assert result.schedule.status is ScheduleStatus.COMPLETED
    assert result.schedule.assignments[0].outcome is not None
    assert result.schedule.assignments[0].outcome.aggregation_ready is True
    assert delegate.calls == 1
    assert [item.instruction_id for item in delegate.instructions] == ["general"]
    assert delegate.instructions[0] == runtime.prompt_instruction("general")


def test_startup_can_publish_the_configured_orchestration_runtime() -> None:
    runtime = configured_runtime()
    delegate = Delegate()
    app = create_app(
        AppSettings(
            model_config_path=str(ROOT / "config/runtime/model-bindings.example.yaml"),
            prompt_config_path=str(PROMPT_CONFIG),
            agent_config_path=str(ROOT / "config/runtime/agent-runtime.example.yaml"),
        ),
        configure_logs=False,
        model_environment={},
        agent_delegates=delegate_catalog(runtime, delegate),
    )

    result = run(app.state.orchestration_runtime.start(TASK, general_signals()))

    assert result.status is ConfiguredRunStatus.SCHEDULED
    assert delegate.calls == 1


def test_professional_route_is_queued_and_remains_review_required() -> None:
    runtime = configured_runtime(professional=True)
    general = Delegate()
    alpha = Delegate()
    configured = ConfiguredOrchestrationRuntime(
        ConfiguredExecutorFactory(runtime, {"general": general, "alpha": alpha})
    )
    assignment = ProfessionalAssignment(assignment_id="analysis", agent_type="alpha")
    signals = RouteSignals(
        task_id=TASK.task_id,
        general_eligible=False,
        professional_assignments=(assignment,),
        asynchronous_required=True,
    )
    child_input = ChildInput(
        assignment_id="analysis",
        goal=TASK.goal,
        success_criteria=TASK.success_criteria,
        side_effect_class=ChildSideEffectClass.READ_ONLY,
    )

    started = run(configured.start(TASK, signals, professional_inputs=(child_input,)))

    assert started.status is ConfiguredRunStatus.SCHEDULED
    assert isinstance(started.schedule, ScheduleHandle)
    assert general.calls == alpha.calls == 0
    completed = run(
        configured.advance(
            started.schedule.schedule_id,
            scope=TASK.scope,
            parent_task_id=TASK.task_id,
        )
    )
    assignment_result = completed.assignments[0]
    assert assignment_result.outcome is not None
    assert assignment_result.outcome.review_required is True
    assert assignment_result.outcome.aggregation_ready is False
    assert assignment_result.outcome.user_delivery_allowed is False
    assert alpha.calls == 1
    assert general.calls == 0


@pytest.mark.parametrize(
    "delegates",
    ({}, {"general": Delegate(), "unknown": Delegate()}),
)
def test_delegate_catalog_must_match_configured_profiles_exactly(
    delegates: Mapping[str, Delegate],
) -> None:
    with pytest.raises(ConfiguredRuntimeError) as raised:
        ConfiguredExecutorFactory(configured_runtime(), delegates)

    assert raised.value.code == "CONFIGURED_DELEGATE_CATALOG_MISMATCH"
    assert all(delegate.calls == 0 for delegate in delegates.values())


def test_human_required_route_stops_before_context_or_delegate_execution() -> None:
    runtime = configured_runtime(professional=True)
    general = Delegate()
    alpha = Delegate()
    configured = ConfiguredOrchestrationRuntime(
        ConfiguredExecutorFactory(runtime, {"general": general, "alpha": alpha})
    )
    signals = RouteSignals(
        task_id=TASK.task_id,
        general_eligible=False,
        professional_assignments=(
            ProfessionalAssignment(assignment_id="analysis", agent_type="alpha"),
        ),
        human_required=True,
    )

    result = run(configured.start(TASK, signals))

    assert result.status is ConfiguredRunStatus.HUMAN_REQUIRED
    assert result.contexts == ()
    assert result.schedule is None
    assert general.calls == alpha.calls == 0


def test_configured_active_concurrency_stops_before_delegate_execution() -> None:
    runtime = configured_runtime(professional=True)
    limited_subagents = runtime.document.subagents.model_copy(update={"max_concurrent": 1})
    limited = replace(
        runtime,
        document=runtime.document.model_copy(update={"subagents": limited_subagents}),
        configuration_sha256="3" * 64,
    )
    general = Delegate()
    alpha = Delegate()
    configured = ConfiguredOrchestrationRuntime(
        ConfiguredExecutorFactory(limited, {"general": general, "alpha": alpha})
    )
    task = TASK.model_copy(
        update={
            "budget": TASK.budget.model_copy(
                update={"professional_concurrency": Limit(default=1, active=2, hard=4)}
            )
        }
    )
    signals = RouteSignals(
        task_id=task.task_id,
        general_eligible=False,
        professional_assignments=(
            ProfessionalAssignment(assignment_id="analysis", agent_type="alpha"),
        ),
        asynchronous_required=True,
    )
    child_input = ChildInput(
        assignment_id="analysis",
        goal=task.goal,
        success_criteria=task.success_criteria,
    )

    with pytest.raises(ConfiguredRuntimeError) as raised:
        run(configured.start(task, signals, professional_inputs=(child_input,)))

    assert raised.value.code == "CONFIGURED_SUBAGENT_CONCURRENCY_DENIED"
    assert general.calls == alpha.calls == 0


def test_stale_context_is_rejected_while_binding_before_delegate_call() -> None:
    runtime = configured_runtime()
    delegate = Delegate()
    factory = ConfiguredExecutorFactory(runtime, delegate_catalog(runtime, delegate))
    stale = general_context(runtime).model_copy(update={"prompt_version": "stale"})

    with pytest.raises(ConfiguredRuntimeError) as raised:
        factory.bind((stale,))

    assert raised.value.code == "CONFIGURED_CHILD_CONTEXT_MISMATCH"
    assert delegate.calls == 0


def test_restart_rebuilds_bindings_and_reuses_durable_assignment_output() -> None:
    async def scenario() -> None:
        runtime = configured_runtime()
        context = general_context(runtime)
        backend = InMemoryRecoveryBackend()
        artifacts = ArtifactStorageService(
            backend=InMemoryObjectBackend(),
            bucket="configured-recovery",
        )
        first_delegate = RecoverableDelegate()
        first_binder = ConfiguredRecoverableExecutorBinder(
            runtime,
            recoverable_delegate_catalog(runtime, first_delegate),
        )
        triggered = False

        def terminate_after_output(point: RecoveryFaultPoint, _snapshot: object) -> None:
            nonlocal triggered
            if point is RecoveryFaultPoint.AFTER_ASSIGNMENT_OUTPUTS and not triggered:
                triggered = True
                raise SimulatedProcessTermination()

        first = TaskRecoveryRuntime(
            backend=backend,
            artifact_service=artifacts,
            executor_binder=first_binder,
            fault_injector=terminate_after_output,
        )
        handle = await first.submit((context,), idempotency_key="configured-restart")
        with pytest.raises(SimulatedProcessTermination):
            await first.advance(
                handle.recovery_id,
                scope=context.scope,
                parent_task_id=context.parent_task_id,
            )

        replacement_delegate = RecoverableDelegate()
        replacement = TaskRecoveryRuntime(
            backend=backend,
            artifact_service=artifacts,
            executor_binder=ConfiguredRecoverableExecutorBinder(
                runtime,
                recoverable_delegate_catalog(runtime, replacement_delegate),
            ),
        )
        outcome = await replacement.advance(
            handle.recovery_id,
            scope=context.scope,
            parent_task_id=context.parent_task_id,
        )

        assert outcome.phase is RecoveryPhase.COMPLETED
        assert outcome.recovered is True
        assert first_delegate.calls == 1
        assert len(first_delegate.controls) == 1
        assert replacement_delegate.calls == 0

    run(scenario())


def test_changed_configuration_cannot_bind_persisted_context() -> None:
    runtime = configured_runtime()
    context = general_context(runtime)
    changed_profile = runtime.profile("general").model_copy(
        update={"graph_version": "child-react-2.0.0"}
    )
    changed = replace(
        runtime,
        profiles=(changed_profile,),
        configuration_sha256="2" * 64,
    )
    delegate = RecoverableDelegate()
    binder = ConfiguredRecoverableExecutorBinder(changed, {"general": delegate})

    with pytest.raises(RecoveryError) as raised:
        binder.bind((context,))

    assert raised.value.code == "RECOVERY_AGENT_CONFIGURATION_MISMATCH"
    assert delegate.calls == 0
