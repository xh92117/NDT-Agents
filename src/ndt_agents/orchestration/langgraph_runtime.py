"""LangGraph implementation of the existing bounded child-execution port."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Protocol, TypedDict, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from ndt_agents.contracts.v1 import AgentResult
from ndt_agents.models.instructions import ApplicationInstruction
from ndt_agents.models.registry import canonical_sha256
from ndt_agents.orchestration.agent_config import ResolvedAgentProfile
from ndt_agents.orchestration.child_models import ChildTaskContext
from ndt_agents.orchestration.subgraph import ChildExecutorError


class _ChildRuntimeState(TypedDict, total=False):
    context: dict[str, Any]
    phase: str
    payload: dict[str, Any]


class ConfiguredChildDelegate(Protocol):
    """Application delegate that receives one verified prompt outside graph state."""

    async def execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]: ...


class LangGraphChildExecutor:
    """Compile one fixed child graph and delegate exactly one bounded Act call."""

    def __init__(
        self,
        profile: ResolvedAgentProfile,
        instruction: ApplicationInstruction,
        delegate: ConfiguredChildDelegate,
        *,
        checkpointer: BaseCheckpointSaver[str] | None = None,
    ) -> None:
        self._profile = profile
        if (
            instruction.instruction_id != profile.prompt_name
            or instruction.instruction_version != profile.prompt_version
            or instruction.instruction_sha256 != profile.prompt_sha256
        ):
            raise ChildExecutorError(
                "CHILD_PROMPT_CONFIGURATION_MISMATCH",
                "Reload the exact agent configuration and prompt catalog together.",
            )
        self._instruction = instruction
        self._profile_sha256 = canonical_sha256(profile.model_dump(mode="json"))
        self._delegate = delegate
        graph: StateGraph[_ChildRuntimeState, None, _ChildRuntimeState, _ChildRuntimeState] = (
            StateGraph(_ChildRuntimeState)
        )
        graph.add_node("observe", self._observe)
        graph.add_node("plan", self._plan)
        graph.add_node("act", self._act)
        graph.add_node("verify", self._verify)
        graph.add_edge(START, "observe")
        graph.add_edge("observe", "plan")
        graph.add_edge("plan", "act")
        graph.add_edge("act", "verify")
        graph.add_edge("verify", END)
        self._graph = graph.compile(
            checkpointer=checkpointer if checkpointer is not None else False,
            name=f"child-{profile.name}-{profile.graph_version}",
        )

    def thread_id(self, context: ChildTaskContext) -> str:
        """Return an exact scope/task/run/assignment checkpoint namespace."""

        execution_sha256 = canonical_sha256(
            {
                "profile_sha256": self._profile_sha256,
                "task_id": context.parent_task_id,
                "run_id": context.run_id,
                "assignment_id": context.assignment_id,
            }
        )
        return f"{context.scope.tenant_id}/{context.scope.project_id}/{execution_sha256}"

    def _validate_context(self, context: ChildTaskContext) -> None:
        if (
            context.agent_type != self._profile.name
            or context.kind is not self._profile.kind
            or context.model_version != self._profile.model_name
            or context.prompt_version != self._profile.prompt_version
            or context.skill_version != self._profile.skill_version
            or tuple(sorted(context.allowed_tools)) != self._profile.allowed_tools
        ):
            raise ChildExecutorError(
                "CHILD_AGENT_CONFIGURATION_MISMATCH",
                "Rebuild the child context from the current immutable agent configuration.",
            )

    def _observe(self, state: _ChildRuntimeState) -> _ChildRuntimeState:
        context = ChildTaskContext.model_validate(state["context"])
        self._validate_context(context)
        return {"phase": "OBSERVE"}

    def _plan(self, state: _ChildRuntimeState) -> _ChildRuntimeState:
        if state.get("phase") != "OBSERVE":
            raise ChildExecutorError(
                "CHILD_GRAPH_STATE_INVALID",
                "Restart the child from a validated pre-execution state.",
            )
        return {"phase": "PLAN"}

    async def _act(self, state: _ChildRuntimeState) -> _ChildRuntimeState:
        context = ChildTaskContext.model_validate(state["context"])
        try:
            payload = await asyncio.wait_for(
                self._delegate.execute(context, self._instruction),
                timeout=self._profile.timeout_ms / 1000,
            )
        except TimeoutError:
            raise ChildExecutorError(
                "CHILD_EXECUTION_TIMEOUT",
                "Inspect preserved child evidence and retry only under an authorized time budget.",
            ) from None
        return {"phase": "ACT", "payload": dict(payload)}

    def _verify(self, state: _ChildRuntimeState) -> _ChildRuntimeState:
        context = ChildTaskContext.model_validate(state["context"])
        try:
            result = AgentResult.model_validate(state["payload"])
        except (KeyError, ValidationError):
            raise ChildExecutorError(
                "CHILD_RESULT_INVALID",
                "Correct the child output to match the strict AgentResult contract.",
            ) from None
        if result.task_id != context.parent_task_id or result.run_id != context.run_id:
            raise ChildExecutorError(
                "CHILD_RESULT_INVALID",
                "Return a result bound to the exact parent task and run.",
            )
        if any(
            artifact.scope.tenant_id != context.scope.tenant_id
            or artifact.scope.project_id != context.scope.project_id
            for artifact in result.artifacts
        ):
            raise ChildExecutorError(
                "CHILD_RESULT_SCOPE_DENIED",
                "Remove cross-scope artifacts and rerun within the authorized tenant and project.",
            )
        return {"phase": "VERIFY", "payload": result.model_dump(mode="json")}

    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]:
        self._validate_context(context)
        initial: _ChildRuntimeState = {
            "context": context.model_dump(mode="json"),
            "phase": "PREPARED",
        }
        output = await self._graph.ainvoke(
            initial,
            config={
                "recursion_limit": 8,
                "configurable": {"thread_id": self.thread_id(context)},
            },
        )
        payload = cast(object, output.get("payload"))
        if not isinstance(payload, dict):
            raise ChildExecutorError(
                "CHILD_RESULT_INVALID",
                "Return one strict AgentResult object from the child graph.",
            )
        return cast(dict[str, Any], payload)
