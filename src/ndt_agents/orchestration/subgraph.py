"""One-call bounded child subgraph with strict result verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from ndt_agents.contracts.v1 import AgentResult
from ndt_agents.orchestration.budget import BudgetExceeded, BudgetGuard
from ndt_agents.orchestration.child_models import (
    ChildAgentKind,
    ChildPhase,
    ChildRunOutcome,
    ChildTaskContext,
    ChildTransition,
)


class ChildExecutor(Protocol):
    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]: ...


class ChildExecutorError(RuntimeError):
    """Typed executor failure that may safely cross the child boundary."""

    def __init__(self, code: str, next_action: str) -> None:
        super().__init__(code)
        self.code = code
        self.next_action = next_action


class ChildSubgraph:
    """Execute and verify one isolated child without any user-delivery capability."""

    async def run(
        self,
        context: ChildTaskContext,
        executor: ChildExecutor,
        *,
        budget_guard: BudgetGuard | None = None,
    ) -> ChildRunOutcome:
        transitions: list[ChildTransition] = []
        current_phase = ChildPhase.PREPARED
        execution_calls: Literal[0, 1] = 0

        def move(source: ChildPhase, target: ChildPhase, event: str) -> None:
            nonlocal current_phase
            if budget_guard is not None:
                if target in {ChildPhase.COMPLETED, ChildPhase.FAILED}:
                    budget_guard.record_terminal_transition()
                else:
                    budget_guard.record_graph_step()
            transitions.append(
                ChildTransition(
                    sequence=len(transitions) + 1,
                    source=source,
                    target=target,
                    event=event,
                )
            )
            current_phase = target

        try:
            move(ChildPhase.PREPARED, ChildPhase.OBSERVE, "context_observed")
            move(ChildPhase.OBSERVE, ChildPhase.PLAN, "bounded_plan_created")
            move(ChildPhase.PLAN, ChildPhase.ACT, "executor_called")
            execution_calls = 1
            try:
                payload = await executor.execute(context)
            except BudgetExceeded as error:
                move(ChildPhase.ACT, ChildPhase.FAILED, "executor_budget_stopped")
                return self._failure(
                    context,
                    transitions,
                    error.code,
                    execution_calls=execution_calls,
                    next_action=error.next_action,
                )
            except ChildExecutorError as error:
                move(ChildPhase.ACT, ChildPhase.FAILED, "executor_typed_failure")
                return self._failure(
                    context,
                    transitions,
                    error.code,
                    execution_calls=execution_calls,
                    next_action=error.next_action,
                )
            except Exception:
                move(ChildPhase.ACT, ChildPhase.FAILED, "executor_failed")
                return self._failure(
                    context,
                    transitions,
                    "CHILD_EXECUTION_FAILED",
                    execution_calls=execution_calls,
                )
            move(ChildPhase.ACT, ChildPhase.VERIFY, "result_verification_started")
            try:
                result = AgentResult.model_validate(payload)
            except ValidationError:
                move(ChildPhase.VERIFY, ChildPhase.FAILED, "result_schema_invalid")
                return self._failure(
                    context,
                    transitions,
                    "CHILD_RESULT_INVALID",
                    execution_calls=execution_calls,
                )
            if result.task_id != context.parent_task_id or result.run_id != context.run_id:
                move(ChildPhase.VERIFY, ChildPhase.FAILED, "result_identity_invalid")
                return self._failure(
                    context,
                    transitions,
                    "CHILD_RESULT_INVALID",
                    execution_calls=execution_calls,
                )
            if any(
                artifact.scope.tenant_id != context.scope.tenant_id
                or artifact.scope.project_id != context.scope.project_id
                for artifact in result.artifacts
            ):
                move(ChildPhase.VERIFY, ChildPhase.FAILED, "result_scope_invalid")
                return self._failure(
                    context,
                    transitions,
                    "CHILD_RESULT_SCOPE_DENIED",
                    execution_calls=execution_calls,
                )
            move(ChildPhase.VERIFY, ChildPhase.COMPLETED, "typed_result_ready")
            professional = context.kind is ChildAgentKind.PROFESSIONAL
            return ChildRunOutcome(
                parent_task_id=context.parent_task_id,
                run_id=context.run_id,
                assignment_id=context.assignment_id,
                status="COMPLETED",
                phase=ChildPhase.COMPLETED,
                result=result,
                transitions=tuple(transitions),
                execution_calls=execution_calls,
                review_required=professional,
                aggregation_ready=not professional,
                error_code=None,
                next_action=None,
            )
        except BudgetExceeded as error:
            assert budget_guard is not None
            budget_guard.record_terminal_transition(budget_stop=True)
            transitions.append(
                ChildTransition(
                    sequence=len(transitions) + 1,
                    source=current_phase,
                    target=ChildPhase.FAILED,
                    event="graph_budget_stopped",
                )
            )
            return self._failure(
                context,
                transitions,
                error.code,
                execution_calls=execution_calls,
                next_action=error.next_action,
            )

    @staticmethod
    def _failure(
        context: ChildTaskContext,
        transitions: list[ChildTransition],
        error_code: str,
        *,
        execution_calls: Literal[0, 1] = 1,
        next_action: str = "Inspect the child evidence and retry with a corrected bounded input.",
    ) -> ChildRunOutcome:
        return ChildRunOutcome(
            parent_task_id=context.parent_task_id,
            run_id=context.run_id,
            assignment_id=context.assignment_id,
            status="FAILED",
            phase=ChildPhase.FAILED,
            result=None,
            transitions=tuple(transitions),
            execution_calls=execution_calls,
            review_required=context.kind is ChildAgentKind.PROFESSIONAL,
            aggregation_ready=False,
            error_code=error_code,
            next_action=next_action,
        )
