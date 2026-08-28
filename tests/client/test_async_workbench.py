"""S6-02-WEB-ASYNC execution ownership and notification-driven SSE tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ndt_agents.client import (
    ClientTaskClass,
    InMemoryTaskRepository,
    TaskCreateRequest,
    TaskEvent,
    TaskEventKind,
    TaskState,
    WorkbenchAsyncPolicy,
    WorkbenchRuntime,
    WorkbenchTask,
)
from ndt_agents.client.models import TaskEventBatch
from ndt_agents.client.service import TaskRepository, WorkbenchTaskExecutor
from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings
from tests.client.test_web_workbench import (
    SCOPE,
    create_request,
    headers,
    identity,
    signing_material,
    token,
)

NOW = datetime(2026, 8, 28, 4, 0, tzinfo=UTC)


def task_event(
    task: WorkbenchTask,
    sequence: int,
    state: TaskState,
    *,
    kind: TaskEventKind = TaskEventKind.STATUS,
    error_code: str | None = None,
    next_action: str | None = None,
) -> TaskEvent:
    return TaskEvent(
        event_id=uuid4(),
        task_id=task.task_id,
        scope=task.scope,
        sequence=sequence,
        kind=kind,
        state=state,
        message=f"Deterministic {state.value.lower()} event.",
        progress_percent=100 if state is TaskState.SUCCEEDED else 10,
        error_code=error_code,
        next_action=next_action,
        created_at=NOW + timedelta(seconds=sequence),
    )


class GateExecutor(WorkbenchTaskExecutor):
    def __init__(self) -> None:
        self.calls = 0
        self.started = Event()
        self.release = Event()

    async def execute(
        self,
        task: WorkbenchTask,
        repository: TaskRepository,
    ) -> WorkbenchTask:
        self.calls += 1
        running = repository.append(task.scope, task_event(task, 2, TaskState.RUNNING))
        self.started.set()
        released = await asyncio.to_thread(self.release.wait, 2)
        assert released
        return repository.append(
            task.scope,
            task_event(running, 3, TaskState.SUCCEEDED, kind=TaskEventKind.RESULT),
        )


class TerminalExecutor(WorkbenchTaskExecutor):
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        task: WorkbenchTask,
        repository: TaskRepository,
    ) -> WorkbenchTask:
        self.calls += 1
        running = repository.append(task.scope, task_event(task, 2, TaskState.RUNNING))
        return repository.append(
            task.scope,
            task_event(running, 3, TaskState.SUCCEEDED, kind=TaskEventKind.RESULT),
        )


class CountingRepository(InMemoryTaskRepository):
    def __init__(self) -> None:
        super().__init__()
        self.event_reads = 0

    def events(
        self,
        scope: TenantScope,
        task_id: UUID,
        after_sequence: int,
    ) -> TaskEventBatch:
        self.event_reads += 1
        return super().events(scope, task_id, after_sequence)


def policy(**updates: object) -> WorkbenchAsyncPolicy:
    values: dict[str, object] = {
        "lease_seconds": 300.0,
        "stream_wait_seconds": 0.2,
        "stream_max_seconds": 1.0,
        "stream_max_batches": 8,
        "recovery_batch_size": 8,
        "recovery_max_sweeps": 4,
        "max_active_tasks": 1,
    }
    values.update(updates)
    return WorkbenchAsyncPolicy(**values)  # type: ignore[arg-type]


def general_request() -> TaskCreateRequest:
    return create_request(task_class=ClientTaskClass.GENERAL)


def test_create_returns_accepted_before_executor_finishes_and_duplicate_is_not_scheduled() -> None:
    private_key, jwks = signing_material()
    executor = GateExecutor()
    runtime = WorkbenchRuntime(executor=executor, async_policy=policy())
    app = create_app(
        AppSettings(), configure_logs=False, identity=identity(jwks), workbench=runtime
    )
    request = general_request().model_dump(mode="json")

    with TestClient(app) as client:
        created = client.post(
            "/v1/workbench/tasks", headers=headers(token(private_key)), json=request
        )
        assert created.status_code == 202
        assert created.json()["state"] == "ACCEPTED"
        assert executor.started.wait(1)

        replay = client.post(
            "/v1/workbench/tasks", headers=headers(token(private_key)), json=request
        )
        assert replay.json()["task_id"] == created.json()["task_id"]
        assert executor.calls == 1

        executor.release.set()
        stream = client.get(
            "/v1/workbench/events",
            params={"task_id": created.json()["task_id"], "after_sequence": 0},
            headers=headers(token(private_key)),
        )
        completed = client.get(
            "/v1/workbench/task",
            params={"task_id": created.json()["task_id"]},
            headers=headers(token(private_key)),
        )

    assert stream.text.count("event: task-event") == 3
    assert '"terminal":true' in stream.text
    assert completed.json()["state"] == "SUCCEEDED"
    assert executor.calls == 1


def test_notification_stream_waits_without_repository_polling_and_closes_at_bound() -> None:
    async def scenario() -> None:
        repository = CountingRepository()
        runtime = WorkbenchRuntime(
            repository,
            executor=TerminalExecutor(),
            async_policy=policy(stream_wait_seconds=0.05),
        )
        try:
            task = runtime.create(SCOPE, general_request())
            stream = runtime.stream_events(SCOPE, task.task_id, 0)
            first = await anext(stream)
            assert [item.sequence for item in first.events] == [1]
            assert repository.event_reads == 1

            waiting: asyncio.Future[TaskEventBatch] = asyncio.ensure_future(anext(stream))
            await asyncio.sleep(0.01)
            assert waiting.done() is False
            assert repository.event_reads == 1

            runtime.repository.append(SCOPE, task_event(task, 2, TaskState.RUNNING))
            second = await asyncio.wait_for(waiting, timeout=0.2)
            assert [item.sequence for item in second.events] == [2]
            assert repository.event_reads == 2

            try:
                await anext(stream)
            except StopAsyncIteration:
                pass
            else:
                raise AssertionError("bounded stream did not close after its notification wait")
            assert repository.event_reads == 2
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_notification_stream_closes_at_batch_bound_without_an_extra_read() -> None:
    async def scenario() -> None:
        repository = CountingRepository()
        runtime = WorkbenchRuntime(
            repository,
            executor=TerminalExecutor(),
            async_policy=policy(stream_max_batches=1),
        )
        try:
            task = runtime.create(SCOPE, general_request())
            stream = runtime.stream_events(SCOPE, task.task_id, 0)
            first = await anext(stream)
            assert first.last_sequence == 1
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
            assert repository.event_reads == 1
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_notification_stream_closes_at_total_duration_bound() -> None:
    async def scenario() -> None:
        repository = CountingRepository()
        runtime = WorkbenchRuntime(
            repository,
            executor=TerminalExecutor(),
            async_policy=policy(
                stream_wait_seconds=0.2,
                stream_max_seconds=0.25,
            ),
        )
        try:
            task = runtime.create(SCOPE, general_request())
            stream = runtime.stream_events(SCOPE, task.task_id, 0)
            first = await anext(stream)
            assert first.last_sequence == 1

            async def publish_running() -> None:
                await asyncio.sleep(0.1)
                runtime.repository.append(SCOPE, task_event(task, 2, TaskState.RUNNING))

            publisher = asyncio.create_task(publish_running())
            second = await anext(stream)
            assert second.last_sequence == 2
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(stream), timeout=0.4)
            await publisher
            assert repository.event_reads == 2
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_expired_accepted_claim_is_recovered_once() -> None:
    async def scenario() -> None:
        repository = InMemoryTaskRepository()
        task = repository.create(SCOPE, general_request(), now=NOW)
        assert repository.claim_execution(
            SCOPE,
            task.task_id,
            owner_id="old-runtime",
            now=NOW,
            lease_expires_at=NOW + timedelta(seconds=1),
        )
        executor = TerminalExecutor()
        runtime = WorkbenchRuntime(
            repository,
            executor=executor,
            owner_id="new-runtime",
            clock=lambda: NOW + timedelta(seconds=2),
            async_policy=policy(),
        )
        await runtime.start()
        try:
            async for batch in runtime.stream_events(SCOPE, task.task_id, 0):
                if batch.terminal:
                    break
            assert runtime.get(SCOPE, task.task_id).state is TaskState.SUCCEEDED
            assert executor.calls == 1
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_expired_started_claim_blocks_without_executor_call() -> None:
    async def scenario() -> None:
        repository = InMemoryTaskRepository()
        task = repository.create(SCOPE, general_request(), now=NOW)
        assert repository.claim_execution(
            SCOPE,
            task.task_id,
            owner_id="old-runtime",
            now=NOW,
            lease_expires_at=NOW + timedelta(seconds=1),
        )
        repository.append(SCOPE, task_event(task, 2, TaskState.RUNNING))
        executor = TerminalExecutor()
        runtime = WorkbenchRuntime(
            repository,
            executor=executor,
            owner_id="new-runtime",
            clock=lambda: NOW + timedelta(seconds=2),
            async_policy=policy(),
        )
        await runtime.start()
        try:
            blocked = runtime.get(SCOPE, task.task_id)
            events = runtime.events(SCOPE, task.task_id, 0).events
            assert blocked.state is TaskState.BLOCKED
            assert events[-1].error_code == "CLIENT_EXECUTION_RECOVERY_REQUIRED"
            assert executor.calls == 0
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_shutdown_cancels_owned_task_without_fabricating_terminal_state() -> None:
    class CancelledExecutor(WorkbenchTaskExecutor):
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def execute(
            self,
            task: WorkbenchTask,
            repository: TaskRepository,
        ) -> WorkbenchTask:
            running = repository.append(SCOPE, task_event(task, 2, TaskState.RUNNING))
            self.started.set()
            await asyncio.Event().wait()
            return running

    async def scenario() -> None:
        executor = CancelledExecutor()
        runtime = WorkbenchRuntime(executor=executor, async_policy=policy())
        await runtime.start()
        task = await runtime.create_and_schedule(SCOPE, general_request())
        await asyncio.wait_for(executor.started.wait(), timeout=0.2)
        await runtime.stop()
        assert runtime.get(SCOPE, task.task_id).state is TaskState.RUNNING
        assert runtime.events(SCOPE, task.task_id, 0).events[-1].state is TaskState.RUNNING

    asyncio.run(scenario())


def test_coordinator_enforces_active_task_capacity() -> None:
    class CapacityExecutor(WorkbenchTaskExecutor):
        def __init__(self) -> None:
            self.calls = 0
            self.first_started = asyncio.Event()
            self.second_started = asyncio.Event()
            self.release_first = asyncio.Event()

        async def execute(
            self,
            task: WorkbenchTask,
            repository: TaskRepository,
        ) -> WorkbenchTask:
            self.calls += 1
            call_number = self.calls
            running = repository.append(task.scope, task_event(task, 2, TaskState.RUNNING))
            if call_number == 1:
                self.first_started.set()
                await self.release_first.wait()
            else:
                self.second_started.set()
            return repository.append(
                task.scope,
                task_event(running, 3, TaskState.SUCCEEDED, kind=TaskEventKind.RESULT),
            )

    async def scenario() -> None:
        executor = CapacityExecutor()
        runtime = WorkbenchRuntime(
            executor=executor,
            async_policy=policy(max_active_tasks=1),
        )
        await runtime.start()
        try:
            first = await runtime.create_and_schedule(SCOPE, general_request())
            await asyncio.wait_for(executor.first_started.wait(), timeout=0.2)
            second_request = general_request().model_copy(
                update={"idempotency_key": "async-capacity-second"}
            )
            second = await runtime.create_and_schedule(SCOPE, second_request)
            await asyncio.sleep(0)
            assert executor.calls == 1
            assert runtime.get(SCOPE, first.task_id).state is TaskState.RUNNING
            assert runtime.get(SCOPE, second.task_id).state is TaskState.ACCEPTED

            executor.release_first.set()
            await asyncio.wait_for(executor.second_started.wait(), timeout=0.2)
            for _attempt in range(10):
                if runtime.get(SCOPE, second.task_id).state.terminal:
                    break
                await asyncio.sleep(0)
            assert runtime.get(SCOPE, second.task_id).state is TaskState.SUCCEEDED
            assert executor.calls == 2
        finally:
            await runtime.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"schema_version": "2.0.0"}, "unsupported Workbench async policy version"),
        ({"lease_seconds": 0.5}, "lease_seconds is outside"),
        ({"stream_wait_seconds": 0.0}, "stream_wait_seconds is outside"),
        ({"stream_max_seconds": 0.1}, "stream_max_seconds must contain"),
        ({"stream_max_batches": 257}, "stream_max_batches is outside"),
        ({"recovery_batch_size": 257}, "recovery_batch_size is outside"),
        ({"recovery_max_sweeps": 257}, "recovery_max_sweeps is outside"),
        ({"max_active_tasks": 17}, "max_active_tasks is outside"),
    ],
)
def test_async_policy_rejects_unbounded_values(
    update: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        policy(**update)
