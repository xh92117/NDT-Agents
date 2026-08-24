"""S1-05 General and professional child-subgraph isolation tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ndt_agents.contracts.v1 import AgentResult, TaskContext
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import (
    AgentDefinition,
    ChildAgentKind,
    ChildInput,
    ChildTaskContext,
)
from ndt_agents.orchestration.models import DispatchPlan, ProfessionalAssignment, RouteKind
from ndt_agents.orchestration.registry import AgentRegistry, AgentRegistryError
from ndt_agents.orchestration.subgraph import ChildSubgraph

ROOT = Path(__file__).resolve().parents[2]
TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
RESULT_TEMPLATE = AgentResult.model_validate_json(
    (ROOT / "examples/contracts/v1/agent-result.valid.json").read_text("utf-8")
)


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def registry() -> AgentRegistry:
    return AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset({"artifact.read@1"}),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="reference",
            ),
            AgentDefinition(
                agent_type="technical_qa",
                kind=ChildAgentKind.PROFESSIONAL,
                allowed_tools=frozenset({"artifact.read@1", "web.search@1"}),
                skill_version="technical-qa-1",
                prompt_version="technical-qa-1",
                model_version="reference",
            ),
            AgentDefinition(
                agent_type="report",
                kind=ChildAgentKind.PROFESSIONAL,
                allowed_tools=frozenset({"artifact.read@1"}),
                skill_version="report-1",
                prompt_version="report-1",
                model_version="reference",
            ),
        )
    )


def general_dispatch() -> DispatchPlan:
    return DispatchPlan(
        task_id=TASK.task_id,
        route=RouteKind.GENERAL_SYNC,
        general_agent=True,
        professional_assignments=(),
        asynchronous=False,
        review_required=False,
        human_required=False,
    )


def professional_dispatch() -> DispatchPlan:
    return DispatchPlan(
        task_id=TASK.task_id,
        route=RouteKind.MULTIPLE_DEPENDENT_ASYNC_REVIEW,
        general_agent=False,
        professional_assignments=(
            ProfessionalAssignment(assignment_id="qa", agent_type="technical_qa"),
            ProfessionalAssignment(assignment_id="report", agent_type="report", depends_on=("qa",)),
        ),
        asynchronous=True,
        review_required=True,
        human_required=False,
    )


def test_general_agent_is_a_child_with_minimal_scope_and_no_parent_private_data() -> None:
    task = TASK.model_copy(update={"dependency_data": {"parent_private": "must-not-copy"}})
    contexts = ChildContextFactory(registry()).prepare(task, general_dispatch())

    assert len(contexts) == 1
    child = contexts[0]
    assert child.kind is ChildAgentKind.GENERAL
    assert child.agent_type == "general"
    assert child.scope == task.scope
    assert child.goal == task.goal
    assert child.allowed_tools == ("artifact.read@1",)
    assert child.scratch_namespace.startswith(
        f"scratch://{task.scope.tenant_id}/{task.scope.project_id}/{task.task_id}/"
    )
    serialized = child.model_dump_json()
    assert "parent_private" not in serialized
    assert "dependency_data" not in serialized
    assert "user_response" not in serialized


def test_professional_contexts_are_minimal_unique_and_dependency_explicit() -> None:
    artifact_id = TASK.artifacts[0].artifact_id
    inputs = (
        ChildInput(
            assignment_id="qa",
            goal="Assess the selected observation.",
            success_criteria=("Return a typed technical finding.",),
            artifact_ids=(artifact_id,),
            requested_tools=("artifact.read@1", "web.search@1"),
        ),
        ChildInput(
            assignment_id="report",
            goal="Draft a bounded report section from the reviewed finding.",
            success_criteria=("Return one typed section.",),
            artifact_ids=(),
            requested_tools=("artifact.read@1",),
        ),
    )

    contexts = ChildContextFactory(registry()).prepare(
        TASK, professional_dispatch(), professional_inputs=inputs
    )

    assert len(contexts) == 2
    qa, report = contexts
    assert qa.artifacts == TASK.artifacts
    assert report.artifacts == ()
    assert qa.allowed_tools == ("artifact.read@1",)
    assert report.dependency_assignment_ids == ("qa",)
    assert qa.scratch_namespace != report.scratch_namespace
    assert report.goal not in qa.model_dump_json()
    assert qa.goal not in report.model_dump_json()
    assert qa.context_manifest_sha256 != report.context_manifest_sha256
    assert all(context.scope == TASK.scope for context in contexts)


def test_unknown_professional_agent_is_rejected_before_context_creation() -> None:
    dispatch = professional_dispatch().model_copy(
        update={
            "professional_assignments": (
                ProfessionalAssignment(assignment_id="unknown", agent_type="unknown"),
            )
        }
    )
    inputs = (
        ChildInput(
            assignment_id="unknown",
            goal="Do unknown work.",
            success_criteria=("Never executes.",),
        ),
    )

    with pytest.raises(AgentRegistryError) as captured:
        ChildContextFactory(registry()).prepare(TASK, dispatch, professional_inputs=inputs)
    assert captured.value.code == "AGENT_NOT_REGISTERED"


class RecordingExecutor:
    def __init__(self, *, mutate: str | None = None) -> None:
        self.calls: list[ChildTaskContext] = []
        self._mutate = mutate

    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]:
        self.calls.append(context)
        payload = RESULT_TEMPLATE.model_copy(
            update={"task_id": context.parent_task_id, "run_id": context.run_id}
        ).model_dump(mode="json")
        if self._mutate == "task":
            payload["task_id"] = str(UUID("00000000-0000-4000-8000-000000000999"))
        elif self._mutate == "extra":
            payload["unexpected"] = True
        return payload


def test_general_result_returns_to_main_aggregation_after_one_bounded_call() -> None:
    context = ChildContextFactory(registry()).prepare(TASK, general_dispatch())[0]
    executor = RecordingExecutor()

    outcome = run(ChildSubgraph().run(context, executor))

    assert len(executor.calls) == 1
    assert outcome.status == "COMPLETED"
    assert outcome.result is not None
    assert outcome.review_required is False
    assert outcome.aggregation_ready is True
    assert outcome.execution_calls == 1
    assert [transition.target.value for transition in outcome.transitions] == [
        "OBSERVE",
        "PLAN",
        "ACT",
        "VERIFY",
        "COMPLETED",
    ]


def test_professional_result_is_review_pending_and_not_directly_aggregated() -> None:
    inputs = (
        ChildInput(
            assignment_id="qa",
            goal="Assess.",
            success_criteria=("Typed result.",),
            artifact_ids=(TASK.artifacts[0].artifact_id,),
        ),
        ChildInput(
            assignment_id="report",
            goal="Report.",
            success_criteria=("Typed section.",),
        ),
    )
    context = ChildContextFactory(registry()).prepare(
        TASK, professional_dispatch(), professional_inputs=inputs
    )[0]

    outcome = run(ChildSubgraph().run(context, RecordingExecutor()))

    assert outcome.status == "COMPLETED"
    assert outcome.review_required is True
    assert outcome.aggregation_ready is False
    assert outcome.user_delivery_allowed is False


@pytest.mark.parametrize("mutation", ["task", "extra"])
def test_invalid_executor_result_returns_typed_failure(mutation: str) -> None:
    context = ChildContextFactory(registry()).prepare(TASK, general_dispatch())[0]

    outcome = run(ChildSubgraph().run(context, RecordingExecutor(mutate=mutation)))

    assert outcome.status == "FAILED"
    assert outcome.result is None
    assert outcome.error_code == "CHILD_RESULT_INVALID"
    assert outcome.next_action is not None
    assert outcome.user_delivery_allowed is False
