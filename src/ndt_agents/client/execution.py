"""Authenticated Web workbench adapter for the configured General orchestration path."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from ndt_agents.client.models import TaskEvent, TaskEventKind, TaskState, WorkbenchTask
from ndt_agents.client.service import InMemoryTaskRepository, WorkbenchTaskExecutor
from ndt_agents.contracts.v1 import BudgetPolicy, RiskLevel, TaskContext
from ndt_agents.models.registry import canonical_sha256
from ndt_agents.orchestration.budget import default_budget_policy
from ndt_agents.orchestration.configured_runtime import (
    ConfiguredOrchestrationRuntime,
    ConfiguredRunStatus,
)
from ndt_agents.orchestration.models import RouteSignals
from ndt_agents.orchestration.review import MainAggregationGate
from ndt_agents.orchestration.scheduler import AssignmentStatus, ScheduleResult


def _general_budget() -> BudgetPolicy:
    base = default_budget_policy("G0")
    return base.model_copy(
        update={
            "policy_id": "budget-g0-general-model-local-v1",
            "total_tokens": base.total_tokens.model_copy(update={"active": 6_000}),
        }
    )


class GeneralWorkbenchExecutor(WorkbenchTaskExecutor):
    """Run one G0 task synchronously and publish only Main-aggregated events."""

    def __init__(
        self,
        runtime: ConfiguredOrchestrationRuntime,
        *,
        failure_code: Callable[[], str | None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._failure_code = failure_code or (lambda: None)

    async def execute(
        self,
        task: WorkbenchTask,
        repository: InMemoryTaskRepository,
    ) -> WorkbenchTask:
        if task.task_class.value != "G0":
            return self._failure(
                repository,
                task,
                code="CLIENT_GENERAL_MODEL_TASK_CLASS_DENIED",
                next_action=(
                    "Submit a G0 synthetic task or configure reviewed professional execution."
                ),
            )
        running = self._append(
            repository,
            task,
            kind=TaskEventKind.STATUS,
            state=TaskState.RUNNING,
            message="Main Agent selected the configured General synthetic execution path.",
            progress=10,
        )
        try:
            context = self._task_context(running)
            execution = await self._runtime.start(
                context,
                RouteSignals(task_id=context.task_id, general_eligible=True),
            )
            if (
                execution.status is not ConfiguredRunStatus.SCHEDULED
                or not isinstance(execution.schedule, ScheduleResult)
                or len(execution.contexts) != 1
                or len(execution.schedule.assignments) != 1
            ):
                return self._failure(
                    repository,
                    running,
                    code="CLIENT_GENERAL_ORCHESTRATION_FAILED",
                    next_action="Inspect the configured Main and General runtime state.",
                )
            assignment = execution.schedule.assignments[0]
            if assignment.status is not AssignmentStatus.COMPLETED or assignment.outcome is None:
                return self._failure(
                    repository,
                    running,
                    code=(
                        self._failure_code()
                        or assignment.error_code
                        or "CLIENT_GENERAL_CHILD_FAILED"
                    ),
                    next_action=assignment.next_action or "Inspect sanitized child evidence.",
                )
            aggregation = MainAggregationGate.general(
                execution.contexts[0],
                assignment.outcome,
            )
            result = aggregation.results[0]
            return self._append(
                repository,
                running,
                kind=TaskEventKind.RESULT,
                state=TaskState.SUCCEEDED,
                message=(
                    f"{result.summary} Synthetic local model evidence remains review-required "
                    "and is not eligible for formal use."
                ),
                progress=100,
            )
        except Exception as error:
            code = getattr(error, "code", "CLIENT_GENERAL_EXECUTION_FAILED")
            next_action = getattr(
                error,
                "next_action",
                "Inspect sanitized application evidence before another explicit execution.",
            )
            return self._failure(
                repository,
                running,
                code=str(code),
                next_action=str(next_action),
            )

    def _task_context(self, task: WorkbenchTask) -> TaskContext:
        profile = self._runtime.agent_runtime.profile("general")
        manifest = {
            "task_id": str(task.task_id),
            "scope": task.scope.model_dump(mode="json"),
            "goal": task.goal,
            "success_criteria": task.success_criteria,
            "agent_configuration_sha256": self._runtime.agent_runtime.configuration_sha256,
            "data_class": "SYNTHETIC",
            "formal_use": False,
        }
        return TaskContext(
            task_id=task.task_id,
            scope=task.scope,
            task_class="G0",
            goal=task.goal,
            success_criteria=task.success_criteria,
            risk_level=RiskLevel.LOW,
            dependency_data={"data_class": "SYNTHETIC", "formal_use": False},
            context_manifest_sha256=canonical_sha256(manifest),
            artifacts=(),
            skill_versions={"general": profile.skill_version},
            prompt_versions={"general": profile.prompt_version},
            model_versions={"general": profile.model_name},
            knowledge_versions=(),
            allowed_tools=(),
            budget=_general_budget(),
            output_schema_id="general-agent-result@1.0.0",
            review_checklist=("Verify synthetic and non-formal limitations remain explicit.",),
            created_at=task.created_at,
        )

    @staticmethod
    def _append(
        repository: InMemoryTaskRepository,
        task: WorkbenchTask,
        *,
        kind: TaskEventKind,
        state: TaskState,
        message: str,
        progress: int,
        error_code: str | None = None,
        next_action: str | None = None,
    ) -> WorkbenchTask:
        bounded_message = message[:4000] or "The General execution returned no displayable summary."
        return repository.append(
            task.scope,
            TaskEvent(
                event_id=uuid4(),
                task_id=task.task_id,
                scope=task.scope,
                sequence=task.last_sequence + 1,
                kind=kind,
                state=state,
                message=bounded_message,
                progress_percent=progress,
                retryable=False,
                error_code=error_code,
                next_action=next_action,
                created_at=datetime.now(UTC),
            ),
        )

    def _failure(
        self,
        repository: InMemoryTaskRepository,
        task: WorkbenchTask,
        *,
        code: str,
        next_action: str,
    ) -> WorkbenchTask:
        return self._append(
            repository,
            task,
            kind=TaskEventKind.ISSUE,
            state=TaskState.FAILED,
            message="The configured General execution stopped without a user-facing result.",
            progress=100,
            error_code=code[:128],
            next_action=next_action[:2000],
        )
