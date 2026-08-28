"""Exact-scope task repository port and in-memory adapter for the Web boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
from asyncio import Lock
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol
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


class WorkbenchError(RuntimeError):
    def __init__(self, *, code: str, status_code: int, next_action: str) -> None:
        self.code = code
        self.status_code = status_code
        self.next_action = next_action
        super().__init__("The workbench request could not be completed.")


@dataclass(frozen=True)
class WorkbenchAsyncPolicy:
    """Versioned local coordinator and bounded SSE policy."""

    schema_version: str = "1.0.0"
    lease_seconds: float = 300.0
    stream_wait_seconds: float = 15.0
    stream_max_seconds: float = 60.0
    stream_max_batches: int = 64
    recovery_batch_size: int = 32
    recovery_max_sweeps: int = 64
    max_active_tasks: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("unsupported Workbench async policy version")
        if not 1.0 <= self.lease_seconds <= 3_600.0:
            raise ValueError("lease_seconds is outside the supported local range")
        if not 0.01 <= self.stream_wait_seconds <= 60.0:
            raise ValueError("stream_wait_seconds is outside the supported range")
        if not self.stream_wait_seconds <= self.stream_max_seconds <= 300.0:
            raise ValueError("stream_max_seconds must contain at least one wait interval")
        if not 1 <= self.stream_max_batches <= 256:
            raise ValueError("stream_max_batches is outside the supported range")
        if not 1 <= self.recovery_batch_size <= 256:
            raise ValueError("recovery_batch_size is outside the supported range")
        if not 1 <= self.recovery_max_sweeps <= 256:
            raise ValueError("recovery_max_sweeps is outside the supported range")
        if not 1 <= self.max_active_tasks <= 16:
            raise ValueError("max_active_tasks is outside the supported local range")


class TaskRepository(Protocol):
    """Exact-scope atomic persistence port for tasks, events, and idempotency."""

    def create(
        self,
        scope: TenantScope,
        request: TaskCreateRequest,
        *,
        task_id_factory: Callable[[], UUID] = uuid4,
        event_id_factory: Callable[[], UUID] = uuid4,
        now: datetime | None = None,
    ) -> WorkbenchTask: ...

    def get(self, scope: TenantScope, task_id: UUID) -> WorkbenchTask: ...

    def events(
        self,
        scope: TenantScope,
        task_id: UUID,
        after_sequence: int,
    ) -> TaskEventBatch: ...

    def append(self, scope: TenantScope, event: TaskEvent) -> WorkbenchTask: ...

    def claim_execution(
        self,
        scope: TenantScope,
        task_id: UUID,
        *,
        owner_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...

    def pending_executions(
        self,
        *,
        owner_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[WorkbenchTask, ...]: ...

    def orphaned_executions(
        self,
        *,
        owner_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[WorkbenchTask, ...]: ...

    def next_foreign_lease_expiry(
        self,
        *,
        owner_id: str,
        now: datetime,
    ) -> datetime | None: ...


class WorkbenchTaskExecutor:
    """Application-owned async executor port for a server-created workbench task."""

    async def execute(
        self,
        task: WorkbenchTask,
        repository: TaskRepository,
    ) -> WorkbenchTask:
        raise NotImplementedError


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


def _initial_task_records(
    scope: TenantScope,
    request: TaskCreateRequest,
    *,
    task_id_factory: Callable[[], UUID],
    event_id_factory: Callable[[], UUID],
    timestamp: datetime,
) -> tuple[WorkbenchTask, TaskEvent]:
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
    return task, event


def _validated_appended_task(
    task: WorkbenchTask,
    scope: TenantScope,
    event: TaskEvent,
) -> WorkbenchTask:
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
    return task.model_copy(
        update={
            "state": event.state,
            "last_sequence": event.sequence,
            "review_completed": review_completed,
            "approval_required": event.state is TaskState.HUMAN_REQUIRED,
            "updated_at": event.created_at,
        }
    )


def _validate_execution_query(owner_id: str, now: datetime, limit: int) -> None:
    if (
        not owner_id
        or len(owner_id) > 128
        or any(character in owner_id for character in "\x00\r\n")
    ):
        raise ValueError("execution owner_id is invalid")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("execution time must be timezone-aware")
    if not 1 <= limit <= 256:
        raise ValueError("execution query limit is outside the supported range")


def _validate_execution_arguments(
    owner_id: str,
    now: datetime,
    lease_expires_at: datetime,
) -> None:
    _validate_execution_query(owner_id, now, 1)
    if lease_expires_at.tzinfo is None or lease_expires_at.utcoffset() is None:
        raise ValueError("execution lease expiry must be timezone-aware")
    if lease_expires_at <= now:
        raise ValueError("execution lease expiry must be later than now")


@dataclass
class _ExecutionRecord:
    status: str = "PENDING"
    owner_id: str | None = None
    lease_expires_at: datetime | None = None


class InMemoryTaskRepository:
    """Thread-safe ephemeral adapter for deterministic tests and contract-only runtimes."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, WorkbenchTask] = {}
        self._events: dict[UUID, tuple[TaskEvent, ...]] = {}
        self._idempotency: dict[
            tuple[UUID, UUID, UUID, tuple[str, ...], str, str], tuple[str, UUID]
        ] = {}
        self._executions: dict[UUID, _ExecutionRecord] = {}
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
            scope.role_codes,
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
            task, event = _initial_task_records(
                scope,
                request,
                task_id_factory=task_id_factory,
                event_id_factory=event_id_factory,
                timestamp=timestamp,
            )
            self._tasks[task.task_id] = task
            self._events[task.task_id] = (event,)
            self._idempotency[identity] = (digest, task.task_id)
            self._executions[task.task_id] = _ExecutionRecord()
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
            updated = _validated_appended_task(task, scope, event)
            self._tasks[event.task_id] = updated
            self._events[event.task_id] = (*self._events[event.task_id], event)
            if updated.state.terminal:
                execution = self._executions.get(event.task_id)
                if execution is None:
                    raise WorkbenchError(
                        code="CLIENT_EXECUTION_STATE_CORRUPT",
                        status_code=503,
                        next_action="Restore a verified task execution record before continuing.",
                    )
                execution.status = "COMPLETED"
                execution.owner_id = None
                execution.lease_expires_at = None
            return updated

    def claim_execution(
        self,
        scope: TenantScope,
        task_id: UUID,
        *,
        owner_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        _validate_execution_arguments(owner_id, now, lease_expires_at)
        with self._lock:
            task = self._require_task_locked(scope, task_id)
            execution = self._require_execution_locked(task_id)
            expired_foreign_claim = (
                execution.status == "CLAIMED"
                and execution.owner_id != owner_id
                and execution.lease_expires_at is not None
                and execution.lease_expires_at <= now
            )
            if task.state is not TaskState.ACCEPTED or not (
                execution.status == "PENDING" or expired_foreign_claim
            ):
                return False
            execution.status = "CLAIMED"
            execution.owner_id = owner_id
            execution.lease_expires_at = lease_expires_at
            return True

    def pending_executions(
        self,
        *,
        owner_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[WorkbenchTask, ...]:
        _validate_execution_query(owner_id, now, limit)
        with self._lock:
            selected = [
                task
                for task in self._tasks.values()
                if task.state is TaskState.ACCEPTED
                and self._execution_is_pending(
                    self._require_execution_locked(task.task_id), owner_id, now
                )
            ]
            return tuple(
                sorted(selected, key=lambda item: (item.created_at, str(item.task_id)))[:limit]
            )

    def orphaned_executions(
        self,
        *,
        owner_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[WorkbenchTask, ...]:
        _validate_execution_query(owner_id, now, limit)
        with self._lock:
            selected = [
                task
                for task in self._tasks.values()
                if not task.state.terminal
                and task.state is not TaskState.ACCEPTED
                and self._execution_is_expired_foreign(
                    self._require_execution_locked(task.task_id), owner_id, now
                )
            ]
            return tuple(
                sorted(selected, key=lambda item: (item.updated_at, str(item.task_id)))[:limit]
            )

    def next_foreign_lease_expiry(
        self,
        *,
        owner_id: str,
        now: datetime,
    ) -> datetime | None:
        _validate_execution_query(owner_id, now, 1)
        with self._lock:
            expiries = [
                record.lease_expires_at
                for record in self._executions.values()
                if record.status == "CLAIMED"
                and record.owner_id != owner_id
                and record.lease_expires_at is not None
                and record.lease_expires_at > now
            ]
            return min(expiries) if expiries else None

    def _require_task_locked(self, scope: TenantScope, task_id: UUID) -> WorkbenchTask:
        task = self._tasks.get(task_id)
        if task is None or not _same_scope(task.scope, scope):
            raise WorkbenchError(
                code="CLIENT_TASK_NOT_FOUND",
                status_code=404,
                next_action="Select an existing task in the active project.",
            )
        return task

    def _require_execution_locked(self, task_id: UUID) -> _ExecutionRecord:
        execution = self._executions.get(task_id)
        if execution is None:
            raise WorkbenchError(
                code="CLIENT_EXECUTION_STATE_CORRUPT",
                status_code=503,
                next_action="Restore a verified task execution record before continuing.",
            )
        return execution

    @staticmethod
    def _execution_is_expired_foreign(
        execution: _ExecutionRecord,
        owner_id: str,
        now: datetime,
    ) -> bool:
        return (
            execution.status == "CLAIMED"
            and execution.owner_id != owner_id
            and execution.lease_expires_at is not None
            and execution.lease_expires_at <= now
        )

    @classmethod
    def _execution_is_pending(
        cls,
        execution: _ExecutionRecord,
        owner_id: str,
        now: datetime,
    ) -> bool:
        return execution.status == "PENDING" or cls._execution_is_expired_foreign(
            execution, owner_id, now
        )


class _TaskEventSignal:
    """Thread-safe commit notification bridge for async SSE waiters."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._versions: dict[UUID, int] = {}
        self._waiters: dict[
            UUID,
            set[tuple[asyncio.AbstractEventLoop, asyncio.Event]],
        ] = {}

    def generation(self, task_id: UUID) -> int:
        with self._lock:
            return self._versions.get(task_id, 0)

    def publish(self, task_id: UUID) -> None:
        with self._lock:
            self._versions[task_id] = self._versions.get(task_id, 0) + 1
            waiters = tuple(self._waiters.get(task_id, ()))
        for loop, event in waiters:
            loop.call_soon_threadsafe(event.set)

    async def wait(self, task_id: UUID, generation: int, timeout: float) -> bool:
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        waiter = (loop, event)
        with self._lock:
            if self._versions.get(task_id, 0) != generation:
                return True
            self._waiters.setdefault(task_id, set()).add(waiter)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False
        finally:
            with self._lock:
                task_waiters = self._waiters.get(task_id)
                if task_waiters is not None:
                    task_waiters.discard(waiter)
                    if not task_waiters:
                        self._waiters.pop(task_id, None)


class _NotifyingTaskRepository:
    """Publish only after the underlying repository commits an event change."""

    def __init__(self, repository: TaskRepository, signal: _TaskEventSignal) -> None:
        self._repository = repository
        self._signal = signal

    def create(
        self,
        scope: TenantScope,
        request: TaskCreateRequest,
        *,
        task_id_factory: Callable[[], UUID] = uuid4,
        event_id_factory: Callable[[], UUID] = uuid4,
        now: datetime | None = None,
    ) -> WorkbenchTask:
        task = self._repository.create(
            scope,
            request,
            task_id_factory=task_id_factory,
            event_id_factory=event_id_factory,
            now=now,
        )
        self._signal.publish(task.task_id)
        return task

    def get(self, scope: TenantScope, task_id: UUID) -> WorkbenchTask:
        return self._repository.get(scope, task_id)

    def events(self, scope: TenantScope, task_id: UUID, after_sequence: int) -> TaskEventBatch:
        return self._repository.events(scope, task_id, after_sequence)

    def append(self, scope: TenantScope, event: TaskEvent) -> WorkbenchTask:
        task = self._repository.append(scope, event)
        self._signal.publish(event.task_id)
        return task

    def claim_execution(
        self,
        scope: TenantScope,
        task_id: UUID,
        *,
        owner_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        return self._repository.claim_execution(
            scope,
            task_id,
            owner_id=owner_id,
            now=now,
            lease_expires_at=lease_expires_at,
        )

    def pending_executions(
        self,
        *,
        owner_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[WorkbenchTask, ...]:
        return self._repository.pending_executions(owner_id=owner_id, now=now, limit=limit)

    def orphaned_executions(
        self,
        *,
        owner_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[WorkbenchTask, ...]:
        return self._repository.orphaned_executions(owner_id=owner_id, now=now, limit=limit)

    def next_foreign_lease_expiry(
        self,
        *,
        owner_id: str,
        now: datetime,
    ) -> datetime | None:
        return self._repository.next_foreign_lease_expiry(owner_id=owner_id, now=now)


class WorkbenchRuntime:
    def __init__(
        self,
        repository: TaskRepository | None = None,
        *,
        executor: WorkbenchTaskExecutor | None = None,
        async_policy: WorkbenchAsyncPolicy | None = None,
        owner_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        base_repository = repository if repository is not None else InMemoryTaskRepository()
        self._signal = _TaskEventSignal()
        self.repository: TaskRepository = _NotifyingTaskRepository(base_repository, self._signal)
        self._executor = executor
        self._schedule_lock = Lock()
        self._policy = async_policy or WorkbenchAsyncPolicy()
        self._owner_id = owner_id or str(uuid4())
        self._clock = clock or (lambda: datetime.now(UTC))
        self._active: dict[UUID, asyncio.Task[None]] = {}
        self._recovery_task: asyncio.Task[None] | None = None
        self._started = False
        self._stopping = False

    def bind_executor(self, executor: WorkbenchTaskExecutor) -> None:
        if self._executor is not None:
            raise ValueError("workbench executor is already bound")
        self._executor = executor

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stopping = False
        if self._executor is None:
            return
        await self._reconcile_expired_executions()
        await self._fill_execution_capacity()
        self._recovery_task = asyncio.create_task(self._watch_foreign_leases())

    async def stop(self) -> None:
        if not self._started:
            return
        self._stopping = True
        tasks = tuple(self._active.values())
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            tasks = (*tasks, self._recovery_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active.clear()
        self._recovery_task = None
        self._started = False

    def create(self, scope: TenantScope, request: TaskCreateRequest) -> WorkbenchTask:
        return self.repository.create(scope, request)

    async def create_and_schedule(
        self,
        scope: TenantScope,
        request: TaskCreateRequest,
    ) -> WorkbenchTask:
        if not self._started:
            raise WorkbenchError(
                code="CLIENT_EXECUTION_COORDINATOR_UNAVAILABLE",
                status_code=503,
                next_action="Start the bounded Workbench execution coordinator and submit again.",
            )
        task = self.create(scope, request)
        if self._executor is not None:
            await self._fill_execution_capacity()
        return task

    def get(self, scope: TenantScope, task_id: UUID) -> WorkbenchTask:
        return self.repository.get(scope, task_id)

    def events(self, scope: TenantScope, task_id: UUID, after_sequence: int) -> TaskEventBatch:
        return self.repository.events(scope, task_id, after_sequence)

    async def stream_events(
        self,
        scope: TenantScope,
        task_id: UUID,
        after_sequence: int,
    ) -> AsyncIterator[TaskEventBatch]:
        cursor = after_sequence
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._policy.stream_max_seconds
        for _batch_index in range(self._policy.stream_max_batches):
            generation = self._signal.generation(task_id)
            batch = self.events(scope, task_id, cursor)
            yield batch
            cursor = batch.last_sequence
            if batch.terminal:
                return
            if self._executor is None:
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            changed = await self._signal.wait(
                task_id,
                generation,
                min(self._policy.stream_wait_seconds, remaining),
            )
            if not changed:
                return

    async def _fill_execution_capacity(self) -> None:
        if self._executor is None or self._stopping:
            return
        async with self._schedule_lock:
            while len(self._active) < self._policy.max_active_tasks and not self._stopping:
                now = self._clock()
                available = self._policy.max_active_tasks - len(self._active)
                candidates = self.repository.pending_executions(
                    owner_id=self._owner_id,
                    now=now,
                    limit=min(available, self._policy.recovery_batch_size),
                )
                if not candidates:
                    return
                claimed = 0
                for task in candidates:
                    if task.task_id in self._active:
                        continue
                    if not self.repository.claim_execution(
                        task.scope,
                        task.task_id,
                        owner_id=self._owner_id,
                        now=now,
                        lease_expires_at=now + timedelta(seconds=self._policy.lease_seconds),
                    ):
                        continue
                    execution = asyncio.create_task(self._execute_claimed(task))
                    self._active[task.task_id] = execution
                    claimed += 1
                if claimed == 0:
                    return

    async def _execute_claimed(self, task: WorkbenchTask) -> None:
        assert self._executor is not None
        try:
            result = await self._executor.execute(task, self.repository)
            if not result.state.terminal:
                self._append_execution_failure(
                    result,
                    code="CLIENT_EXECUTION_INCOMPLETE",
                    message="The background executor returned without a terminal task state.",
                    next_action="Inspect the executor contract before another explicit task.",
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            current = self.repository.get(task.scope, task.task_id)
            if not current.state.terminal:
                self._append_execution_failure(
                    current,
                    code="CLIENT_EXECUTION_FAILED",
                    message="The background executor stopped unexpectedly.",
                    next_action="Inspect sanitized runtime evidence before another explicit task.",
                )
        finally:
            async with self._schedule_lock:
                self._active.pop(task.task_id, None)
            if not self._stopping:
                await self._fill_execution_capacity()

    async def _reconcile_expired_executions(self) -> None:
        for _sweep in range(self._policy.recovery_max_sweeps):
            orphaned = self.repository.orphaned_executions(
                owner_id=self._owner_id,
                now=self._clock(),
                limit=self._policy.recovery_batch_size,
            )
            for task in orphaned:
                self._append_execution_failure(
                    task,
                    code="CLIENT_EXECUTION_RECOVERY_REQUIRED",
                    message="The prior process stopped after task execution had begun.",
                    next_action=(
                        "Review preserved events and create a new task only after human review."
                    ),
                    blocked=True,
                )
            if len(orphaned) < self._policy.recovery_batch_size:
                return
        if self.repository.orphaned_executions(
            owner_id=self._owner_id,
            now=self._clock(),
            limit=1,
        ):
            raise WorkbenchError(
                code="CLIENT_EXECUTION_RECOVERY_LIMIT_REACHED",
                status_code=503,
                next_action=(
                    "Increase the approved recovery batch policy or reconcile tasks manually."
                ),
            )

    async def _watch_foreign_leases(self) -> None:
        for _sweep in range(self._policy.recovery_max_sweeps):
            now = self._clock()
            expiry = self.repository.next_foreign_lease_expiry(
                owner_id=self._owner_id,
                now=now,
            )
            if expiry is None:
                return
            delay = max(0.0, (expiry - now).total_seconds())
            if delay:
                await asyncio.sleep(delay)
            await self._reconcile_expired_executions()
            await self._fill_execution_capacity()

    def _append_execution_failure(
        self,
        task: WorkbenchTask,
        *,
        code: str,
        message: str,
        next_action: str,
        blocked: bool = False,
    ) -> WorkbenchTask:
        current = self.repository.get(task.scope, task.task_id)
        if current.state.terminal:
            return current
        event = TaskEvent(
            event_id=uuid4(),
            task_id=current.task_id,
            scope=current.scope,
            sequence=current.last_sequence + 1,
            kind=TaskEventKind.ISSUE,
            state=TaskState.BLOCKED if blocked else TaskState.FAILED,
            message=message,
            error_code=code,
            next_action=next_action,
            created_at=self._clock(),
        )
        return self.repository.append(current.scope, event)
