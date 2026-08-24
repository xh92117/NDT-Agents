"""Rules-only routing from explicit typed task signals."""

from __future__ import annotations

from ndt_agents.orchestration.models import (
    ProfessionalAssignment,
    RouteDecision,
    RouteKind,
    RouteSignals,
)


class RoutingError(RuntimeError):
    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class RulesFirstRouter:
    """Select the minimum declared child topology without an LLM call."""

    def route(self, signals: RouteSignals) -> RouteDecision:
        assignments = signals.professional_assignments
        self._validate_acyclic(assignments)
        if signals.general_eligible:
            return RouteDecision(
                task_id=signals.task_id,
                route=RouteKind.GENERAL_SYNC,
                rule_id="route.general.explicit.v1",
                target_agents=("general",),
                asynchronous=False,
                review_required=False,
                human_required=False,
            )
        targets = tuple(assignment.agent_type for assignment in assignments)
        if signals.human_required:
            return RouteDecision(
                task_id=signals.task_id,
                route=RouteKind.HUMAN_REQUIRED,
                rule_id="route.human.explicit.v1",
                target_agents=targets,
                asynchronous=False,
                review_required=True,
                human_required=True,
            )
        if len(assignments) == 1:
            return RouteDecision(
                task_id=signals.task_id,
                route=(
                    RouteKind.ONE_PROFESSIONAL_ASYNC_REVIEW
                    if signals.asynchronous_required
                    else RouteKind.ONE_PROFESSIONAL_SYNC_REVIEW
                ),
                rule_id=(
                    "route.professional.single-async.v1"
                    if signals.asynchronous_required
                    else "route.professional.single.v1"
                ),
                target_agents=targets,
                asynchronous=signals.asynchronous_required,
                review_required=True,
                human_required=False,
            )
        dependent = any(assignment.depends_on for assignment in assignments)
        return RouteDecision(
            task_id=signals.task_id,
            route=(
                RouteKind.MULTIPLE_DEPENDENT_ASYNC_REVIEW
                if dependent
                else RouteKind.MULTIPLE_INDEPENDENT_ASYNC_REVIEW
            ),
            rule_id=(
                "route.professional.multiple-dependent.v1"
                if dependent
                else "route.professional.multiple-independent.v1"
            ),
            target_agents=targets,
            asynchronous=True,
            review_required=True,
            human_required=False,
        )

    @staticmethod
    def _validate_acyclic(assignments: tuple[ProfessionalAssignment, ...]) -> None:
        dependencies = {
            assignment.assignment_id: set(assignment.depends_on) for assignment in assignments
        }
        remaining = dict(dependencies)
        while remaining:
            ready = {name for name, needs in remaining.items() if not needs & remaining.keys()}
            if not ready:
                raise RoutingError(
                    code="ROUTE_DEPENDENCY_CYCLE",
                    message="Professional assignment dependencies contain a cycle.",
                    next_action="Remove the cycle and submit explicit task dependencies again.",
                )
            for name in ready:
                del remaining[name]
