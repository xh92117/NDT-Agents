"""S1-14 LangGraph adapter boundary, topology, timeout, and persistence tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from ndt_agents.contracts.v1 import AgentResult, TaskContext
from ndt_agents.models.config import load_model_runtime_configuration
from ndt_agents.models.instructions import ApplicationInstruction
from ndt_agents.orchestration.agent_config import (
    ConfiguredAgentRuntime,
    ResolvedAgentProfile,
    load_agent_runtime_configuration,
)
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import ChildTaskContext
from ndt_agents.orchestration.langgraph_runtime import LangGraphChildExecutor
from ndt_agents.orchestration.models import DispatchPlan, RouteKind
from ndt_agents.orchestration.prompt_registry import load_prompt_registry
from ndt_agents.orchestration.subgraph import ChildSubgraph

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


def agent_runtime() -> ConfiguredAgentRuntime:
    models = load_model_runtime_configuration(
        ROOT / "config/runtime/model-bindings.example.yaml", environ={}
    )
    return load_agent_runtime_configuration(
        ROOT / "config/runtime/agent-runtime.example.yaml",
        model_runtime=models,
        prompt_registry=load_prompt_registry(PROMPT_CONFIG),
    )


def profile() -> ResolvedAgentProfile:
    return agent_runtime().profile("general")


def instruction() -> ApplicationInstruction:
    return agent_runtime().prompt_instruction("general")


def context() -> ChildTaskContext:
    registry = agent_runtime().build_agent_registry()
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


class RecordingExecutor:
    def __init__(self, *, delay: float = 0, mutation: str | None = None) -> None:
        self.calls = 0
        self.instructions: list[ApplicationInstruction] = []
        self.delay = delay
        self.mutation = mutation

    async def execute(
        self,
        child: ChildTaskContext,
        prompt: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        self.calls += 1
        self.instructions.append(prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        payload = RESULT.model_copy(
            update={"task_id": child.parent_task_id, "run_id": child.run_id}
        ).model_dump(mode="json")
        if self.mutation == "extra":
            payload["untrusted"] = True
        return payload


def test_langgraph_adapter_preserves_child_contract_and_calls_delegate_once() -> None:
    delegate = RecordingExecutor()
    adapter = LangGraphChildExecutor(profile(), instruction(), delegate)

    outcome = run(ChildSubgraph().run(context(), adapter))

    assert delegate.calls == 1
    assert delegate.instructions == [instruction()]
    assert outcome.status == "COMPLETED"
    assert outcome.aggregation_ready is True
    assert outcome.review_required is False
    assert outcome.user_delivery_allowed is False


def test_stale_agent_profile_is_denied_before_delegate_execution() -> None:
    delegate = RecordingExecutor()
    adapter = LangGraphChildExecutor(profile(), instruction(), delegate)
    stale = context().model_copy(update={"prompt_version": "stale-prompt"})

    outcome = run(ChildSubgraph().run(stale, adapter))

    assert delegate.calls == 0
    assert outcome.status == "FAILED"
    assert outcome.error_code == "CHILD_AGENT_CONFIGURATION_MISMATCH"


def test_langgraph_verification_rejects_extra_result_fields_without_retry() -> None:
    delegate = RecordingExecutor(mutation="extra")
    adapter = LangGraphChildExecutor(profile(), instruction(), delegate)

    outcome = run(ChildSubgraph().run(context(), adapter))

    assert delegate.calls == 1
    assert outcome.status == "FAILED"
    assert outcome.error_code == "CHILD_RESULT_INVALID"


def test_langgraph_timeout_is_typed_and_has_no_hidden_retry() -> None:
    delegate = RecordingExecutor(delay=0.05)
    short_profile = profile().model_copy(update={"timeout_ms": 1})
    adapter = LangGraphChildExecutor(short_profile, instruction(), delegate)

    outcome = run(ChildSubgraph().run(context(), adapter))

    assert delegate.calls == 1
    assert outcome.status == "FAILED"
    assert outcome.error_code == "CHILD_EXECUTION_TIMEOUT"


def test_injected_checkpointer_uses_isolated_thread_identity() -> None:
    delegate = RecordingExecutor()
    checkpointer = InMemorySaver()
    adapter = LangGraphChildExecutor(
        profile(),
        instruction(),
        delegate,
        checkpointer=checkpointer,
    )
    child = context()

    outcome = run(ChildSubgraph().run(child, adapter))
    checkpoint = checkpointer.get(
        {
            "configurable": {
                "thread_id": adapter.thread_id(child),
            }
        }
    )

    assert outcome.status == "COMPLETED"
    assert delegate.calls == 1
    assert checkpoint is not None
    assert instruction().text not in repr(checkpoint)
    assert str(child.scope.tenant_id) in adapter.thread_id(child)
    assert str(child.scope.project_id) in adapter.thread_id(child)


def test_checkpoint_namespace_changes_with_graph_profile_version() -> None:
    child = context()
    current = LangGraphChildExecutor(profile(), instruction(), RecordingExecutor())
    changed_profile = profile().model_copy(update={"graph_version": "child-react-1.1.0"})
    changed = LangGraphChildExecutor(changed_profile, instruction(), RecordingExecutor())

    assert current.thread_id(child) != changed.thread_id(child)
