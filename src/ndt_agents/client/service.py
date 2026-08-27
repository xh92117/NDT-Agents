"""Exact-scope in-memory task repository for the S6-01 client boundary."""

from __future__ import annotations

import hashlib
import json
from asyncio import Lock
from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from ndt_agents.client.models import (
    TaskCreateRequest,
    TaskEvent,
    TaskEventBatch,
    TaskEventKind,
    TaskState,
    WorkbenchTask,
)
from ndt_agents.contracts.v1 import TenantScope


class WorkbenchTaskExecutor:
    """Application-owned async executor port for a server-created workbench task."""

    async def execute(
        self,
        task: WorkbenchTask,
        repository: InMemoryTaskRepository,
    ) -> WorkbenchTask:
        raise NotImplementedError


class WorkbenchError(RuntimeError):
    def __init__(self, *, code: str, status_code: int, next_action: str) -> None:
        self.code = code
        self.status_code = status_code
        self.next_action = next_action
        super().__init__("The workbench request could not be completed.")


def _request_hash(request: TaskCreateRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _same_scope(left: TenantScope, right: TenantScope) -> bool:
    return left == right


_ALLOWED_STATE_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.ACCEPTED: frozenset(
        {TaskState.RUNNING, TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.RUNNING: frozenset(
        {
            TaskState.REVIEW_REQUIRED,
            TaskState.HUMAN_REQUIRED,
            TaskState.SUCCEEDED,
            TaskState.PARTIAL,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.REVIEW_REQUIRED: frozenset(
        {
            TaskState.RUNNING,
            TaskState.HUMAN_REQUIRED,
            TaskState.SUCCEEDED,
            TaskState.PARTIAL,
            TaskState.BLOCKED,
            TaskState.FAILED,
        }
    ),
    TaskState.HUMAN_REQUIRED: frozenset(
        {
            TaskState.RUNNING,
            TaskState.SUCCEEDED,
            TaskState.PARTIAL,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
}


class InMemoryTaskRepository:
    """Thread-safe deterministic repository; production persistence is a later S6 adapter."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, WorkbenchTask] = {}
        self._events: dict[UUID, tuple[TaskEvent, ...]] = {}
        self._idempotency: dict[tuple[UUID, UUID, UUID, str, str], tuple[str, UUID]] = {}
        self._lock = RLock()

    def create(
        self,
        scope: TenantScope,
        request: TaskCreateRequest,
        *,
        task_id_factory: Callable[[], UUID] = uuid4,
        event_id_factory: Callable[[], UUID] = uuid4,
        now: datetime | None = None,
    ) -> WorkbenchTask:
        timestamp = now or datetime.now(UTC)
        identity = (
            scope.tenant_id,
            scope.project_id,
            scope.user_id,
            scope.permission_version,
            request.idempotency_key,
        )
        digest = _request_hash(request)
        with self._lock:
            existing = self._idempotency.get(identity)
            if existing is not None:
                if existing[0] != digest:
                    raise WorkbenchError(
                        code="CLIENT_IDEMPOTENCY_CONFLICT",
                        status_code=409,
                        next_action="Use a new idempotency key for changed task input.",
                    )
                return self._tasks[existing[1]]
            task_id = task_id_factory()
            event = TaskEvent(
                event_id=event_id_factory(),
                task_id=task_id,
                scope=scope,
                sequence=1,
                kind=TaskEventKind.STATUS,
                state=TaskState.ACCEPTED,
                message="Task accepted for Main Agent routing.",
                progress_percent=0,
                created_at=timestamp,
            )
            task = WorkbenchTask(
                task_id=task_id,
                scope=scope,
                task_class=request.task_class,
                goal=request.goal,
                success_criteria=request.success_criteria,
                state=TaskState.ACCEPTED,
                last_sequence=1,
                review_required=request.task_class.value != "G0",
                review_completed=request.task_class.value == "G0",
                approval_required=False,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._tasks[task_id] = task
            self._events[task_id] = (event,)
            self._idempotency[identity] = (digest, task_id)
            return task

    def get(self, scope: TenantScope, task_id: UUID) -> WorkbenchTask:
        with self._lock:
            return self._require_task_locked(scope, task_id)

    def events(self, scope: TenantScope, task_id: UUID, after_sequence: int) -> TaskEventBatch:
        with self._lock:
            task = self._require_task_locked(scope, task_id)
            if after_sequence < 0 or after_sequence > task.last_sequence:
                raise WorkbenchError(
                    code="CLIENT_EVENT_CURSOR_INVALID",
                    status_code=409,
                    next_action="Reconnect using the last sequence acknowledged by the server.",
                )
            selected = tuple(
                event for event in self._events[task_id] if event.sequence > after_sequence
            )
            return TaskEventBatch(
                task_id=task_id,
                after_sequence=after_sequence,
                last_sequence=task.last_sequence,
                terminal=task.state.terminal,
                events=selected,
            )

    def append(self, scope: TenantScope, event: TaskEvent) -> WorkbenchTask:
        """Append a server-produced event; this method is never exposed as a client route."""
        with self._lock:
            task = self._require_task_locked(scope, event.task_id)
            if task.state.terminal:
                raise WorkbenchError(
                    code="CLIENT_TASK_TERMINAL",
                    status_code=409,
                    next_action="Create a new task instead of changing a terminal task.",
                )
            if not _same_scope(event.scope, scope) or event.sequence != task.last_sequence + 1:
                raise WorkbenchError(
                    code="CLIENT_EVENT_SEQUENCE_INVALID",
                    status_code=409,
                    next_action="Append the next exact-scope event sequence.",
                )
            if event.state not in _ALLOWED_STATE_TRANSITIONS.get(task.state, frozenset()):
                raise WorkbenchError(
                    code="CLIENT_STATE_TRANSITION_INVALID",
                    status_code=409,
                    next_action="Append an event allowed from the current task state.",
                )
            review_completed = task.review_completed or (
                task.state is TaskState.REVIEW_REQUIRED
                and event.kind is TaskEventKind.REVIEW
                and event.state is TaskState.RUNNING
            )
            if event.state is TaskState.SUCCEEDED and not review_completed:
                raise WorkbenchError(
                    code="CLIENT_REVIEW_REQUIRED",
                    status_code=409,
                    next_action="Complete the required review before a successful terminal event.",
                )
            updated = task.model_copy(
                update={
                    "state": event.state,
                    "last_sequence": event.sequence,
                    "review_completed": review_completed,
                    "approval_required": event.state is TaskState.HUMAN_REQUIRED,
                    "updated_at": event.created_at,
                }
            )
            self._tasks[event.task_id] = updated
            self._events[event.task_id] = (*self._events[event.task_id], event)
            return updated

    def _require_task_locked(self, scope: TenantScope, task_id: UUID) -> WorkbenchTask:
        task = self._tasks.get(task_id)
        if task is None or not _same_scope(task.scope, scope):
            raise WorkbenchError(
                code="CLIENT_TASK_NOT_FOUND",
                status_code=404,
                next_action="Select an existing task in the active project.",
            )
        return task


class WorkbenchRuntime:
    def __init__(
        self,
        repository: InMemoryTaskRepository | None = None,
        *,
        executor: WorkbenchTaskExecutor | None = None,
    ) -> None:
        self.repository = repository or InMemoryTaskRepository()
        self._executor = executor
        self._execution_lock = Lock()

    def bind_executor(self, executor: WorkbenchTaskExecutor) -> None:
        if self._executor is not None:
            raise ValueError("workbench executor is already bound")
        self._executor = executor

    def create(self, scope: TenantScope, request: TaskCreateRequest) -> WorkbenchTask:
        return self.repository.create(scope, request)

    async def create_and_execute(
        self,
        scope: TenantScope,
        request: TaskCreateRequest,
    ) -> WorkbenchTask:
        task = self.create(scope, request)
        if self._executor is None:
            return task
        async with self._execution_lock:
            current = self.repository.get(scope, task.task_id)
            if current.state is not TaskState.ACCEPTED:
                return current
            return await self._executor.execute(current, self.repository)

    def get(self, scope: TenantScope, task_id: UUID) -> WorkbenchTask:
        return self.repository.get(scope, task_id)

    def events(self, scope: TenantScope, task_id: UUID, after_sequence: int) -> TaskEventBatch:
        return self.repository.events(scope, task_id, after_sequence)
