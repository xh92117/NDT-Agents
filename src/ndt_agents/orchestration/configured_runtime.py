"""Configuration-owned Main Graph, scheduler, and recovery assembly."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver

from ndt_agents.contracts.v1 import TaskContext, TenantScope
from ndt_agents.models.instructions import ApplicationInstruction
from ndt_agents.orchestration.agent_config import (
    AgentRuntimeConfigurationError,
    ConfiguredAgentRuntime,
    ResolvedAgentProfile,
)
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import (
    ChildAgentKind,
    ChildInput,
    ChildTaskContext,
)
from ndt_agents.orchestration.langgraph_runtime import (
    ConfiguredChildDelegate,
    LangGraphChildExecutor,
)
from ndt_agents.orchestration.main_graph import MainGraph
from ndt_agents.orchestration.models import MainGraphResult, RouteSignals
from ndt_agents.orchestration.recovery import (
    RecoverableChildExecutor,
    RecoveryControl,
    RecoveryError,
)
from ndt_agents.orchestration.scheduler import (
    ScheduleHandle,
    ScheduleResult,
    TaskScheduler,
)
from ndt_agents.orchestration.subgraph import ChildExecutor

CheckpointerFactory = Callable[[ResolvedAgentProfile], BaseCheckpointSaver[str] | None]


class ConfiguredRecoverableDelegate(Protocol):
    async def execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
        control: RecoveryControl,
    ) -> Mapping[str, Any]: ...


class ConfiguredRuntimeError(RuntimeError):
    """Stable configuration-to-execution assembly rejection."""

    def __init__(self, code: str, message: str, next_action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action


class ConfiguredRunStatus(StrEnum):
    ROUTE_STOPPED = "ROUTE_STOPPED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    SCHEDULED = "SCHEDULED"


@dataclass(frozen=True, slots=True)
class ConfiguredRunResult:
    """Application-internal result that keeps framework state out of public contracts."""

    configuration_sha256: str
    status: ConfiguredRunStatus
    main_result: MainGraphResult
    contexts: tuple[ChildTaskContext, ...]
    schedule: ScheduleHandle | ScheduleResult | None


def _validate_catalog(
    runtime: ConfiguredAgentRuntime,
    delegates: Mapping[str, object],
) -> None:
    configured = {profile.name for profile in runtime.profiles}
    supplied = set(delegates)
    if supplied != configured:
        raise ConfiguredRuntimeError(
            "CONFIGURED_DELEGATE_CATALOG_MISMATCH",
            "The child delegate catalog does not match the configured agent profiles.",
            "Register exactly one application-owned delegate for every configured profile.",
        )


def validate_configured_child_context(
    runtime: ConfiguredAgentRuntime,
    context: ChildTaskContext,
) -> ResolvedAgentProfile:
    """Validate one private child context against the exact active configuration."""

    profile = _resolve_profile(runtime, context)
    if (
        context.agent_type != profile.name
        or context.kind is not profile.kind
        or context.agent_configuration_sha256 != runtime.configuration_sha256
        or context.model_version != profile.model_name
        or context.prompt_version != profile.prompt_version
        or context.skill_version != profile.skill_version
        or tuple(sorted(context.allowed_tools)) != profile.allowed_tools
    ):
        raise ConfiguredRuntimeError(
            "CONFIGURED_CHILD_CONTEXT_MISMATCH",
            "A child context does not match the current immutable agent configuration.",
            "Rebuild the child context from the active configuration before scheduling.",
        )
    return profile


def _resolve_profile(
    runtime: ConfiguredAgentRuntime, context: ChildTaskContext
) -> ResolvedAgentProfile:
    try:
        return runtime.profile(context.agent_type)
    except AgentRuntimeConfigurationError as error:
        raise ConfiguredRuntimeError(
            "CONFIGURED_AGENT_PROFILE_NOT_FOUND",
            "A child context references an agent profile that is not configured.",
            "Rebuild the verified dispatch from the active agent configuration.",
        ) from error


class ConfiguredExecutorFactory:
    """Bind assignment IDs to profile-selected LangGraph child executors."""

    def __init__(
        self,
        runtime: ConfiguredAgentRuntime,
        delegates: Mapping[str, ConfiguredChildDelegate],
        *,
        checkpointer_factory: CheckpointerFactory | None = None,
    ) -> None:
        _validate_catalog(runtime, delegates)
        self.runtime = runtime
        self._delegates = dict(delegates)
        self._checkpointer_factory = checkpointer_factory

    def bind(self, contexts: Sequence[ChildTaskContext]) -> Mapping[str, ChildExecutor]:
        bound: dict[str, ChildExecutor] = {}
        for context in contexts:
            if context.assignment_id in bound:
                raise ConfiguredRuntimeError(
                    "CONFIGURED_ASSIGNMENT_DUPLICATE",
                    "Configured execution received a duplicate assignment ID.",
                    "Rebuild one isolated child context per verified assignment.",
                )
            profile = validate_configured_child_context(self.runtime, context)
            checkpointer = (
                self._checkpointer_factory(profile)
                if self._checkpointer_factory is not None
                else None
            )
            bound[context.assignment_id] = LangGraphChildExecutor(
                profile,
                self.runtime.prompt_instruction(profile.name),
                self._delegates[profile.name],
                checkpointer=checkpointer,
            )
        return bound


class _RecoveryDelegateBridge:
    def __init__(self, delegate: ConfiguredRecoverableDelegate) -> None:
        self._delegate = delegate
        self._control: RecoveryControl | None = None

    def set_control(self, control: RecoveryControl | None) -> None:
        self._control = control

    async def execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        control = self._control
        if control is None:
            raise RecoveryError(
                "RECOVERY_CONTROL_MISSING",
                "The configured recoverable child has no active recovery control.",
                "Execute the child only through TaskRecoveryRuntime.",
            )
        return await self._delegate.execute(context, instruction, control)


class _ConfiguredRecoverableExecutor:
    def __init__(
        self,
        profile: ResolvedAgentProfile,
        instruction: ApplicationInstruction,
        delegate: ConfiguredRecoverableDelegate,
        checkpointer: BaseCheckpointSaver[str] | None,
    ) -> None:
        self._bridge = _RecoveryDelegateBridge(delegate)
        self._executor = LangGraphChildExecutor(
            profile,
            instruction,
            self._bridge,
            checkpointer=checkpointer,
        )
        self._lock = asyncio.Lock()

    async def execute(
        self, context: ChildTaskContext, control: RecoveryControl
    ) -> Mapping[str, Any]:
        async with self._lock:
            self._bridge.set_control(control)
            try:
                return await self._executor.execute(context)
            finally:
                self._bridge.set_control(None)


class ConfiguredRecoverableExecutorBinder:
    """Recreate recoverable assignment bindings from persisted child contexts."""

    def __init__(
        self,
        runtime: ConfiguredAgentRuntime,
        delegates: Mapping[str, ConfiguredRecoverableDelegate],
        *,
        checkpointer_factory: CheckpointerFactory | None = None,
    ) -> None:
        _validate_catalog(runtime, delegates)
        self.runtime = runtime
        self._delegates = dict(delegates)
        self._checkpointer_factory = checkpointer_factory

    def bind(self, contexts: Sequence[ChildTaskContext]) -> Mapping[str, RecoverableChildExecutor]:
        try:
            bound: dict[str, RecoverableChildExecutor] = {}
            for context in contexts:
                if context.assignment_id in bound:
                    raise ConfiguredRuntimeError(
                        "CONFIGURED_ASSIGNMENT_DUPLICATE",
                        "Configured recovery received a duplicate assignment ID.",
                        "Restore one isolated context per verified assignment.",
                    )
                profile = validate_configured_child_context(self.runtime, context)
                checkpointer = (
                    self._checkpointer_factory(profile)
                    if self._checkpointer_factory is not None
                    else None
                )
                bound[context.assignment_id] = _ConfiguredRecoverableExecutor(
                    profile,
                    self.runtime.prompt_instruction(profile.name),
                    self._delegates[profile.name],
                    checkpointer,
                )
            return bound
        except ConfiguredRuntimeError as error:
            raise RecoveryError(
                "RECOVERY_AGENT_CONFIGURATION_MISMATCH",
                error.message,
                error.next_action,
            ) from error


class ConfiguredOrchestrationRuntime:
    """Run Main Graph and schedule children through configuration-owned bindings."""

    def __init__(
        self,
        executor_factory: ConfiguredExecutorFactory,
        *,
        main_graph: MainGraph | None = None,
        scheduler: TaskScheduler | None = None,
    ) -> None:
        self._factory = executor_factory
        self._main_graph = main_graph or MainGraph()
        hard_concurrency = executor_factory.runtime.document.subagents.hard_max_concurrent
        self._scheduler = scheduler or TaskScheduler(hard_professional_concurrency=hard_concurrency)
        self._context_factory = ChildContextFactory(executor_factory.runtime.build_agent_registry())

    @property
    def agent_runtime(self) -> ConfiguredAgentRuntime:
        return self._factory.runtime

    async def start(
        self,
        task: TaskContext,
        signals: RouteSignals,
        *,
        professional_inputs: tuple[ChildInput, ...] = (),
    ) -> ConfiguredRunResult:
        main_result = self._main_graph.run(task, signals)
        config_sha256 = self._factory.runtime.configuration_sha256
        if main_result.status != "DISPATCH_READY":
            return ConfiguredRunResult(
                configuration_sha256=config_sha256,
                status=ConfiguredRunStatus.ROUTE_STOPPED,
                main_result=main_result,
                contexts=(),
                schedule=None,
            )
        assert main_result.dispatch is not None
        if main_result.dispatch.human_required:
            return ConfiguredRunResult(
                configuration_sha256=config_sha256,
                status=ConfiguredRunStatus.HUMAN_REQUIRED,
                main_result=main_result,
                contexts=(),
                schedule=None,
            )
        contexts = self._context_factory.prepare(
            task,
            main_result.dispatch,
            professional_inputs=professional_inputs,
        )
        self._validate_configured_limits(contexts)
        executors = self._factory.bind(contexts)
        schedule = await self._scheduler.schedule(
            contexts,
            executors,
            asynchronous=main_result.dispatch.asynchronous,
        )
        return ConfiguredRunResult(
            configuration_sha256=config_sha256,
            status=ConfiguredRunStatus.SCHEDULED,
            main_result=main_result,
            contexts=contexts,
            schedule=schedule,
        )

    def _validate_configured_limits(self, contexts: tuple[ChildTaskContext, ...]) -> None:
        limits = self._factory.runtime.document.subagents
        if len(contexts) > limits.max_total_per_run:
            raise ConfiguredRuntimeError(
                "CONFIGURED_SUBAGENT_TOTAL_DENIED",
                "The verified dispatch exceeds the configured subagent total limit.",
                "Reduce the dispatch or approve a bounded configuration change.",
            )
        if (
            contexts[0].kind is ChildAgentKind.PROFESSIONAL
            and contexts[0].budget.professional_concurrency.active > limits.max_concurrent
        ):
            raise ConfiguredRuntimeError(
                "CONFIGURED_SUBAGENT_CONCURRENCY_DENIED",
                "The task concurrency exceeds the configured active subagent limit.",
                "Use a task budget within the active configured concurrency ceiling.",
            )

    async def advance(
        self,
        schedule_id: UUID,
        *,
        scope: TenantScope,
        parent_task_id: UUID,
    ) -> ScheduleResult:
        return await self._scheduler.advance(
            schedule_id,
            scope=scope,
            parent_task_id=parent_task_id,
        )
