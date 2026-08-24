"""Deterministic explicit-intent and UI entry graph for Knowledge imports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from ndt_agents.approval.service import ApprovalKind, ApprovalState
from ndt_agents.contracts.v1 import TaskContext, TenantScope
from ndt_agents.orchestration.budget import default_budget_policy
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import ChildInput, ChildSideEffectClass
from ndt_agents.orchestration.main_graph import MainGraph
from ndt_agents.orchestration.models import ProfessionalAssignment, RouteSignals
from ndt_agents.orchestration.registry import AgentRegistry, AgentRegistryError

from .models import (
    KnowledgeEntryPhase,
    KnowledgeEntryResponse,
    KnowledgeEntryResult,
    KnowledgeEntryTransition,
    KnowledgeEntryTrigger,
    KnowledgeIntent,
    KnowledgeStartRequest,
    KnowledgeUiStartRequest,
)

KNOWLEDGE_ASSIGNMENT_ID = "knowledge_import"
KNOWLEDGE_AGENT_TYPE = "knowledge"
KNOWLEDGE_IMPORT_ACTION = "knowledge.import.start"
KNOWLEDGE_IMPORT_TARGET = "knowledge_import_request"


class KnowledgeEntryError(RuntimeError):
    def __init__(self, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class KnowledgeTaskRepository(Protocol):
    def get(self, *, scope: TenantScope, task_id: UUID) -> TaskContext: ...


class InMemoryKnowledgeTaskRepository:
    """Exact-scope deterministic task lookup for local tests and development."""

    def __init__(self, tasks: Iterable[TaskContext]) -> None:
        tasks_tuple = tuple(tasks)
        mapped = {task.task_id: task for task in tasks_tuple}
        if len(mapped) != len(tasks_tuple):
            raise ValueError("knowledge task IDs must be unique")
        self._tasks = mapped
        self.read_count = 0

    def get(self, *, scope: TenantScope, task_id: UUID) -> TaskContext:
        self.read_count += 1
        task = self._tasks.get(task_id)
        if task is None or task.scope != scope:
            raise KnowledgeEntryError(
                "KNOWLEDGE_TASK_SCOPE_DENIED",
                "The Knowledge task is unavailable in the active scope.",
                (
                    "Use an authorized K1 task in the active tenant, project, user, "
                    "and permission scope."
                ),
            )
        return task


def knowledge_entry_candidate_sha256(
    *,
    scope: TenantScope,
    request_id: str,
    task_id: UUID,
    trigger: KnowledgeEntryTrigger,
    intent: KnowledgeIntent,
    source_artifact_ids: tuple[UUID, ...],
) -> str:
    payload = {
        "schema_version": "1.0.0",
        "scope": scope.model_dump(mode="json"),
        "request_id": request_id,
        "task_id": str(task_id),
        "trigger": trigger.value,
        "intent": intent.value,
        "source_artifact_ids": sorted(str(item) for item in source_artifact_ids),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class KnowledgeEntryGraph:
    """Prepare one isolated Knowledge child without executing or publishing it."""

    def __init__(
        self,
        repository: KnowledgeTaskRepository,
        registry: AgentRegistry,
        *,
        main_graph: MainGraph | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._main_graph = main_graph or MainGraph()
        self._clock = clock

    def start_ui(
        self, *, scope: TenantScope, request: KnowledgeUiStartRequest
    ) -> KnowledgeEntryResult:
        return self.start(
            scope=scope,
            request=KnowledgeStartRequest(
                request_id=request.request_id,
                task_id=request.task_id,
                trigger=KnowledgeEntryTrigger.UI_ACTION,
                intent=KnowledgeIntent.IMPORT,
                source_artifact_ids=request.source_artifact_ids,
            ),
        )

    def start(self, *, scope: TenantScope, request: KnowledgeStartRequest) -> KnowledgeEntryResult:
        candidate_sha256 = knowledge_entry_candidate_sha256(
            scope=scope,
            request_id=request.request_id,
            task_id=request.task_id,
            trigger=request.trigger,
            intent=request.intent,
            source_artifact_ids=request.source_artifact_ids,
        )
        entry_id = uuid5(NAMESPACE_URL, candidate_sha256)
        transitions: list[KnowledgeEntryTransition] = []

        def move(source: KnowledgeEntryPhase, target: KnowledgeEntryPhase, event: str) -> None:
            transitions.append(
                KnowledgeEntryTransition(
                    sequence=len(transitions) + 1,
                    source=source,
                    target=target,
                    event=event,
                )
            )

        move(KnowledgeEntryPhase.RECEIVED, KnowledgeEntryPhase.OBSERVE, "entry_observed")
        if request.intent is KnowledgeIntent.READ_ONLY_QUERY:
            move(
                KnowledgeEntryPhase.OBSERVE,
                KnowledgeEntryPhase.NOT_APPLICABLE,
                "read_only_query_retained",
            )
            return self._non_ready(
                entry_id=entry_id,
                task_id=request.task_id,
                status="NOT_APPLICABLE",
                phase=KnowledgeEntryPhase.NOT_APPLICABLE,
                transitions=transitions,
                code="KNOWLEDGE_ENTRY_NOT_EXPLICIT",
                next_action="Continue through the read-only retrieval or General Agent path.",
            )

        move(KnowledgeEntryPhase.OBSERVE, KnowledgeEntryPhase.VALIDATE, "entry_validation_started")
        try:
            if request.trigger is KnowledgeEntryTrigger.ADMIN_JOB:
                self._validate_admin_approval(scope, request, candidate_sha256)
            task = self._repository.get(scope=scope, task_id=request.task_id)
            self._validate_task(task, request)
        except KnowledgeEntryError as error:
            move(KnowledgeEntryPhase.VALIDATE, KnowledgeEntryPhase.BLOCKED, "entry_denied")
            return self._non_ready(
                entry_id=entry_id,
                task_id=request.task_id,
                status="BLOCKED",
                phase=KnowledgeEntryPhase.BLOCKED,
                transitions=transitions,
                code=error.code,
                next_action=error.next_action,
            )

        move(KnowledgeEntryPhase.VALIDATE, KnowledgeEntryPhase.PLAN, "main_route_started")
        main_result = self._main_graph.run(
            task,
            RouteSignals(
                task_id=task.task_id,
                general_eligible=False,
                professional_assignments=(
                    ProfessionalAssignment(
                        assignment_id=KNOWLEDGE_ASSIGNMENT_ID,
                        agent_type=KNOWLEDGE_AGENT_TYPE,
                    ),
                ),
                asynchronous_required=True,
            ),
        )
        if main_result.status != "DISPATCH_READY" or main_result.dispatch is None:
            move(KnowledgeEntryPhase.PLAN, KnowledgeEntryPhase.FAILED, "main_route_failed")
            return self._non_ready(
                entry_id=entry_id,
                task_id=request.task_id,
                status="FAILED",
                phase=KnowledgeEntryPhase.FAILED,
                transitions=transitions,
                code=main_result.error_code or "KNOWLEDGE_MAIN_ROUTE_FAILED",
                next_action=main_result.next_action or "Repair the verified Main Graph route.",
            )

        child_input = ChildInput(
            assignment_id=KNOWLEDGE_ASSIGNMENT_ID,
            goal=task.goal,
            success_criteria=task.success_criteria,
            artifact_ids=request.source_artifact_ids,
            requested_tools=tuple(sorted(task.allowed_tools)),
            side_effect_class=ChildSideEffectClass.MUTATING,
        )
        try:
            contexts = ChildContextFactory(self._registry).prepare(
                task,
                main_result.dispatch,
                professional_inputs=(child_input,),
            )
        except AgentRegistryError as error:
            move(KnowledgeEntryPhase.PLAN, KnowledgeEntryPhase.BLOCKED, "child_context_denied")
            return self._non_ready(
                entry_id=entry_id,
                task_id=request.task_id,
                status="BLOCKED",
                phase=KnowledgeEntryPhase.BLOCKED,
                transitions=transitions,
                code=error.code,
                next_action=error.next_action,
            )

        move(KnowledgeEntryPhase.PLAN, KnowledgeEntryPhase.VERIFY, "topology_verification_started")
        child = contexts[0]
        dispatch = main_result.dispatch
        if (
            len(contexts) != 1
            or not dispatch.asynchronous
            or not dispatch.review_required
            or dispatch.main_llm_calls != 0
            or dispatch.main_allowed_tools != ()
            or child.user_delivery_allowed
        ):
            move(KnowledgeEntryPhase.VERIFY, KnowledgeEntryPhase.FAILED, "topology_invalid")
            return self._non_ready(
                entry_id=entry_id,
                task_id=request.task_id,
                status="FAILED",
                phase=KnowledgeEntryPhase.FAILED,
                transitions=transitions,
                code="KNOWLEDGE_TOPOLOGY_INVALID",
                next_action="Rebuild the Knowledge dispatch through the verified Main Graph.",
            )
        move(KnowledgeEntryPhase.VERIFY, KnowledgeEntryPhase.DISPATCH_READY, "dispatch_verified")
        return KnowledgeEntryResult(
            entry_id=entry_id,
            task_id=request.task_id,
            status="DISPATCH_READY",
            phase=KnowledgeEntryPhase.DISPATCH_READY,
            main_result=main_result,
            child_context=child,
            transitions=tuple(transitions),
        )

    def response(self, result: KnowledgeEntryResult) -> KnowledgeEntryResponse:
        dispatch = result.main_result.dispatch if result.main_result is not None else None
        return KnowledgeEntryResponse(
            entry_id=result.entry_id,
            task_id=result.task_id,
            status=result.status,
            asynchronous=bool(dispatch and dispatch.asynchronous),
            review_required=bool(dispatch and dispatch.review_required),
            code=result.code,
            next_action=result.next_action,
        )

    def _validate_admin_approval(
        self,
        scope: TenantScope,
        request: KnowledgeStartRequest,
        candidate_sha256: str,
    ) -> None:
        status = request.approval_status
        if status is None or status.state is not ApprovalState.APPROVED or status.grant is None:
            raise KnowledgeEntryError(
                "KNOWLEDGE_ADMIN_APPROVAL_REQUIRED",
                "The administrator job does not have a completed approval grant.",
                "Approve the exact Knowledge import candidate before scheduling the job.",
            )
        candidate = status.candidate
        grant = status.grant
        if (
            candidate.kind is not ApprovalKind.KNOWLEDGE
            or candidate.action != KNOWLEDGE_IMPORT_ACTION
            or candidate.target_type != KNOWLEDGE_IMPORT_TARGET
            or candidate.target_id != request.task_id
            or candidate.scope != scope
            or candidate.task_id != request.task_id
            or candidate.candidate_sha256 != candidate_sha256
            or candidate.expires_at <= self._clock()
            or grant.approval_id != candidate.approval_id
            or grant.scope != scope
            or grant.task_id != request.task_id
            or grant.candidate_sha256 != candidate_sha256
            or grant.policy_version != candidate.policy_version
        ):
            raise KnowledgeEntryError(
                "KNOWLEDGE_ADMIN_APPROVAL_INVALID",
                "The administrator approval is stale or bound to different work.",
                "Create and approve a current candidate for this exact scoped import request.",
            )

    @staticmethod
    def _validate_task(task: TaskContext, request: KnowledgeStartRequest) -> None:
        if task.task_class != "K1" or task.budget.task_class != "K1":
            raise KnowledgeEntryError(
                "KNOWLEDGE_TASK_CLASS_INVALID",
                "Knowledge import requires a K1 task and budget.",
                "Rebuild the task with the versioned K1 budget policy.",
            )
        if "context_bundle" not in task.dependency_data:
            raise KnowledgeEntryError(
                "KNOWLEDGE_CONTEXT_REQUIRED",
                "Knowledge import requires a verified S2 TaskContext bundle.",
                "Assemble the K1 TaskContext through the versioned S2 context boundary.",
            )
        expected = default_budget_policy("K1", file_count=len(request.source_artifact_ids))
        for name in (
            "graph_steps",
            "llm_calls",
            "tool_calls",
            "total_tokens",
            "wall_time_ms",
            "professional_concurrency",
            "review_rounds",
            "correction_rounds",
        ):
            actual_limit = getattr(task.budget, name)
            expected_limit = getattr(expected, name)
            if (
                actual_limit.default != expected_limit.default
                or actual_limit.hard != expected_limit.hard
            ):
                raise KnowledgeEntryError(
                    "KNOWLEDGE_BUDGET_INVALID",
                    "The K1 budget is not bound to the selected file count.",
                    "Rebuild the task budget from the central K1 policy and exact file count.",
                )
        available = {artifact.artifact_id: artifact for artifact in task.artifacts}
        selected = [available.get(artifact_id) for artifact_id in request.source_artifact_ids]
        if any(artifact is None for artifact in selected):
            raise KnowledgeEntryError(
                "KNOWLEDGE_SOURCE_DENIED",
                "A requested source artifact is not in the authorized TaskContext.",
                "Use only immutable source artifacts from the active TaskContext.",
            )
        if any(
            not artifact.immutable
            or artifact.scope.tenant_id != task.scope.tenant_id
            or artifact.scope.project_id != task.scope.project_id
            for artifact in selected
            if artifact is not None
        ):
            raise KnowledgeEntryError(
                "KNOWLEDGE_SOURCE_INVALID",
                "Knowledge sources must be immutable and inside the active scope.",
                "Register immutable source artifacts in the active tenant and project.",
            )

    @staticmethod
    def _non_ready(
        *,
        entry_id: UUID,
        task_id: UUID,
        status: Literal["NOT_APPLICABLE", "BLOCKED", "FAILED"],
        phase: KnowledgeEntryPhase,
        transitions: list[KnowledgeEntryTransition],
        code: str,
        next_action: str,
    ) -> KnowledgeEntryResult:
        return KnowledgeEntryResult(
            entry_id=entry_id,
            task_id=task_id,
            status=status,
            phase=phase,
            main_result=None,
            child_context=None,
            transitions=tuple(transitions),
            code=code,
            next_action=next_action,
        )
