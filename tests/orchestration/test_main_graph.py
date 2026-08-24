"""S1-04 UNIT-CORE, INT-ORCH route, and Main budget checks."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from uuid import UUID

from ndt_agents.contracts.v1 import TaskContext
from ndt_agents.orchestration.main_graph import MainGraph
from ndt_agents.orchestration.models import (
    ProfessionalAssignment,
    RouteKind,
    RouteSignals,
)

ROOT = Path(__file__).resolve().parents[2]
TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)


def signals_for(route: RouteKind) -> RouteSignals:
    if route is RouteKind.GENERAL_SYNC:
        return RouteSignals(task_id=TASK.task_id, general_eligible=True)
    first = ProfessionalAssignment(assignment_id="qa", agent_type="technical_qa")
    if route is RouteKind.ONE_PROFESSIONAL_SYNC_REVIEW:
        return RouteSignals(
            task_id=TASK.task_id,
            general_eligible=False,
            professional_assignments=(first,),
        )
    if route is RouteKind.ONE_PROFESSIONAL_ASYNC_REVIEW:
        return RouteSignals(
            task_id=TASK.task_id,
            general_eligible=False,
            professional_assignments=(first,),
            asynchronous_required=True,
        )
    if route is RouteKind.HUMAN_REQUIRED:
        return RouteSignals(
            task_id=TASK.task_id,
            general_eligible=False,
            professional_assignments=(first,),
            human_required=True,
        )
    second = ProfessionalAssignment(
        assignment_id="report",
        agent_type="report",
        depends_on=("qa",) if route is RouteKind.MULTIPLE_DEPENDENT_ASYNC_REVIEW else (),
    )
    return RouteSignals(
        task_id=TASK.task_id,
        general_eligible=False,
        professional_assignments=(first, second),
    )


def test_rules_only_main_graph_covers_all_declared_topologies() -> None:
    graph = MainGraph()
    for route in RouteKind:
        result = graph.run(TASK, signals_for(route))
        assert result.status == "DISPATCH_READY"
        assert result.decision is not None
        assert result.dispatch is not None
        assert result.decision.route is route
        assert result.dispatch.main_allowed_tools == ()
        assert result.dispatch.main_llm_calls == 0
        assert [transition.target.value for transition in result.transitions] == [
            "OBSERVE",
            "PLAN",
            "ACT",
            "VERIFY",
            "DISPATCH_READY",
        ]
        if route is RouteKind.GENERAL_SYNC:
            assert result.dispatch.general_agent is True
            assert result.dispatch.review_required is False
        else:
            assert result.dispatch.general_agent is False
            assert result.dispatch.review_required is True
        assert result.dispatch.asynchronous is (
            route
            in {
                RouteKind.ONE_PROFESSIONAL_ASYNC_REVIEW,
                RouteKind.MULTIPLE_INDEPENDENT_ASYNC_REVIEW,
                RouteKind.MULTIPLE_DEPENDENT_ASYNC_REVIEW,
            }
        )


def test_dependency_cycle_returns_typed_blocked_state() -> None:
    cyclic = RouteSignals(
        task_id=TASK.task_id,
        general_eligible=False,
        professional_assignments=(
            ProfessionalAssignment(assignment_id="one", agent_type="qa", depends_on=("two",)),
            ProfessionalAssignment(assignment_id="two", agent_type="report", depends_on=("one",)),
        ),
    )

    result = MainGraph().run(TASK, cyclic)

    assert result.status == "BLOCKED"
    assert result.error_code == "ROUTE_DEPENDENCY_CYCLE"
    assert result.dispatch is None


def test_task_identity_mismatch_returns_typed_failure() -> None:
    signals = RouteSignals(
        task_id=UUID("00000000-0000-4000-8000-000000000999"),
        general_eligible=True,
    )

    result = MainGraph().run(TASK, signals)

    assert result.status == "FAILED"
    assert result.error_code == "ROUTE_TASK_MISMATCH"
    assert result.phase.value == "FAILED"


def test_untrusted_missing_route_signals_return_typed_blocked_state() -> None:
    result = MainGraph().run_payload(TASK, {"task_id": str(TASK.task_id)})

    assert result.status == "BLOCKED"
    assert result.error_code == "ROUTE_SIGNALS_INVALID"
    assert result.next_action is not None


def test_frozen_routing_macro_f1_meets_gate_without_case_id_features() -> None:
    expected: list[str] = []
    actual: list[str] = []
    path = ROOT / "benchmarks/v1/routing.jsonl"
    for line in path.read_text("utf-8").splitlines():
        case = json.loads(line)
        signals = RouteSignals(
            task_id=TASK.task_id,
            general_eligible=case["route_signals"]["general_eligible"],
            professional_assignments=tuple(
                ProfessionalAssignment.model_validate(assignment)
                for assignment in case["route_signals"]["professional_assignments"]
            ),
            human_required=case["route_signals"]["human_required"],
        )
        result = MainGraph().run(TASK, signals)
        assert result.decision is not None
        expected.append(case["expected"]["route"])
        actual.append(result.decision.route.value)

    labels = set(expected)
    f1_scores: list[float] = []
    pairs = Counter(zip(expected, actual, strict=True))
    for label in labels:
        true_positive = pairs[(label, label)]
        false_positive = sum(pairs[(other, label)] for other in labels if other != label)
        false_negative = sum(pairs[(label, other)] for other in labels if other != label)
        precision = true_positive / (true_positive + false_positive)
        recall = true_positive / (true_positive + false_negative)
        f1_scores.append(2 * precision * recall / (precision + recall))

    assert len(expected) == 1000
    assert sum(f1_scores) / len(f1_scores) >= 0.97
