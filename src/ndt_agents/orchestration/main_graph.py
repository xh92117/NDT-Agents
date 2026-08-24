"""Deterministic Main Graph that stops at a verified typed dispatch plan."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ndt_agents.contracts.v1 import TaskContext
from ndt_agents.orchestration.models import (
    DispatchPlan,
    GraphTransition,
    MainGraphPhase,
    MainGraphResult,
    RouteSignals,
)
from ndt_agents.orchestration.routing import RoutingError, RulesFirstRouter


class MainGraph:
    """Run Observe -> Plan -> Act -> Verify without Main LLM or tool calls."""

    def __init__(self, router: RulesFirstRouter | None = None) -> None:
        self._router = router or RulesFirstRouter()

    def run_payload(self, task: TaskContext, payload: Mapping[str, Any]) -> MainGraphResult:
        """Validate untrusted route signals and return a typed boundary failure."""

        try:
            signals = RouteSignals.model_validate(payload)
        except ValidationError:
            return MainGraphResult(
                task_id=task.task_id,
                status="BLOCKED",
                phase=MainGraphPhase.BLOCKED,
                decision=None,
                dispatch=None,
                transitions=(
                    GraphTransition(
                        sequence=1,
                        source=MainGraphPhase.RECEIVED,
                        target=MainGraphPhase.OBSERVE,
                        event="task_observed",
                    ),
                    GraphTransition(
                        sequence=2,
                        source=MainGraphPhase.OBSERVE,
                        target=MainGraphPhase.BLOCKED,
                        event="route_signals_invalid",
                    ),
                ),
                error_code="ROUTE_SIGNALS_INVALID",
                next_action="Provide valid explicit route signals for the active task.",
            )
        return self.run(task, signals)

    def run(self, task: TaskContext, signals: RouteSignals) -> MainGraphResult:
        transitions: list[GraphTransition] = []

        def move(source: MainGraphPhase, target: MainGraphPhase, event: str) -> None:
            transitions.append(
                GraphTransition(
                    sequence=len(transitions) + 1,
                    source=source,
                    target=target,
                    event=event,
                )
            )

        move(MainGraphPhase.RECEIVED, MainGraphPhase.OBSERVE, "task_observed")
        if task.task_id != signals.task_id:
            move(MainGraphPhase.OBSERVE, MainGraphPhase.FAILED, "task_identity_mismatch")
            return MainGraphResult(
                task_id=task.task_id,
                status="FAILED",
                phase=MainGraphPhase.FAILED,
                decision=None,
                dispatch=None,
                transitions=tuple(transitions),
                error_code="ROUTE_TASK_MISMATCH",
                next_action="Rebuild route signals for the active task ID.",
            )
        move(MainGraphPhase.OBSERVE, MainGraphPhase.PLAN, "rules_route_started")
        try:
            decision = self._router.route(signals)
        except RoutingError as error:
            move(MainGraphPhase.PLAN, MainGraphPhase.BLOCKED, "rules_route_blocked")
            return MainGraphResult(
                task_id=task.task_id,
                status="BLOCKED",
                phase=MainGraphPhase.BLOCKED,
                decision=None,
                dispatch=None,
                transitions=tuple(transitions),
                error_code=error.code,
                next_action=error.next_action,
            )
        move(MainGraphPhase.PLAN, MainGraphPhase.ACT, "dispatch_plan_created")
        dispatch = DispatchPlan(
            task_id=task.task_id,
            route=decision.route,
            general_agent=decision.route.value == "GENERAL_SYNC",
            professional_assignments=signals.professional_assignments,
            asynchronous=decision.asynchronous,
            review_required=decision.review_required,
            human_required=decision.human_required,
        )
        move(MainGraphPhase.ACT, MainGraphPhase.VERIFY, "topology_verification_started")
        if dispatch.professional_assignments and not dispatch.review_required:
            move(MainGraphPhase.VERIFY, MainGraphPhase.FAILED, "review_invariant_failed")
            return MainGraphResult(
                task_id=task.task_id,
                status="FAILED",
                phase=MainGraphPhase.FAILED,
                decision=decision,
                dispatch=None,
                transitions=tuple(transitions),
                error_code="TOPOLOGY_REVIEW_REQUIRED",
                next_action="Require review for every professional dispatch.",
            )
        move(MainGraphPhase.VERIFY, MainGraphPhase.DISPATCH_READY, "dispatch_verified")
        return MainGraphResult(
            task_id=task.task_id,
            status="DISPATCH_READY",
            phase=MainGraphPhase.DISPATCH_READY,
            decision=decision,
            dispatch=dispatch,
            transitions=tuple(transitions),
            error_code=None,
            next_action=None,
        )
