"""Restart-safe local Workbench repository contract tests."""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from ndt_agents.client import (
    SQLITE_WORKBENCH_SCHEMA_VERSION,
    ClientTaskClass,
    InMemoryTaskRepository,
    SqliteTaskRepository,
    TaskCreateRequest,
    TaskEvent,
    TaskEventKind,
    TaskState,
    WorkbenchError,
    WorkbenchPersistenceError,
    WorkbenchRuntime,
    WorkbenchTask,
)
from ndt_agents.client.service import TaskRepository, WorkbenchTaskExecutor
from ndt_agents.contracts.v1 import TenantScope

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("PROJECT_OPERATOR",),
    permission_version="permissions-1",
)
NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)


def request(*, goal: str = "Run one durable synthetic Web task.") -> TaskCreateRequest:
    return TaskCreateRequest(
        task_class=ClientTaskClass.GENERAL,
        goal=goal,
        success_criteria=("Persist exact scope", "Replay without duplicate execution"),
        idempotency_key="web-durability-general-0001",
    )


def event(task_id: UUID, sequence: int, state: TaskState) -> TaskEvent:
    return TaskEvent(
        event_id=UUID(f"00000000-0000-4000-8000-{sequence:012d}"),
        task_id=task_id,
        scope=SCOPE,
        sequence=sequence,
        kind=TaskEventKind.RESULT if state is TaskState.SUCCEEDED else TaskEventKind.STATUS,
        state=state,
        message="Synthetic durable task event.",
        progress_percent=100 if state is TaskState.SUCCEEDED else 10,
        created_at=NOW,
    )


class CountingExecutor(WorkbenchTaskExecutor):
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        task: WorkbenchTask,
        repository: TaskRepository,
    ) -> WorkbenchTask:
        self.calls += 1
        running = repository.append(
            SCOPE,
            event(task.task_id, task.last_sequence + 1, TaskState.RUNNING),
        )
        return repository.append(
            SCOPE,
            event(running.task_id, running.last_sequence + 1, TaskState.SUCCEEDED),
        )


def test_reopen_preserves_task_events_terminal_replay_and_idempotency(tmp_path: Path) -> None:
    async def scenario() -> tuple[
        Path,
        WorkbenchTask,
        WorkbenchTask,
        tuple[TaskEvent, ...],
        int,
        int,
    ]:
        database = tmp_path / "workbench.sqlite3"
        first_executor = CountingExecutor()
        first = WorkbenchRuntime(SqliteTaskRepository(database), executor=first_executor)
        await first.start()
        try:
            accepted = await first.create_and_schedule(SCOPE, request())
            async for batch in first.stream_events(SCOPE, accepted.task_id, 0):
                if batch.terminal:
                    break
            completed = first.get(SCOPE, accepted.task_id)
        finally:
            await first.stop()

        second_executor = CountingExecutor()
        reopened = WorkbenchRuntime(SqliteTaskRepository(database), executor=second_executor)
        await reopened.start()
        try:
            replay = await reopened.create_and_schedule(SCOPE, request())
            events = reopened.events(SCOPE, completed.task_id, 0).events
        finally:
            await reopened.stop()
        return (
            database,
            completed,
            replay,
            events,
            first_executor.calls,
            second_executor.calls,
        )

    database, completed, replay, events, first_calls, second_calls = asyncio.run(scenario())

    assert completed.state is TaskState.SUCCEEDED
    assert replay == completed
    assert first_calls == 1
    assert second_calls == 0
    assert [item.sequence for item in events] == [1, 2, 3]
    with pytest.raises(WorkbenchError) as conflict:
        SqliteTaskRepository(database).create(SCOPE, request(goal="Changed durable input."))
    assert conflict.value.code == "CLIENT_IDEMPOTENCY_CONFLICT"

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM workbench_task").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM workbench_event").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM workbench_idempotency").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM workbench_execution").fetchone() == (1,)


@pytest.mark.parametrize(
    "scope",
    [
        SCOPE.model_copy(update={"tenant_id": UUID("00000000-0000-4000-8000-000000000201")}),
        SCOPE.model_copy(update={"project_id": UUID("00000000-0000-4000-8000-000000000202")}),
        SCOPE.model_copy(update={"user_id": UUID("00000000-0000-4000-8000-000000000203")}),
        SCOPE.model_copy(update={"role_codes": ("PROJECT_REVIEWER",)}),
        SCOPE.model_copy(update={"permission_version": "permissions-2"}),
    ],
)
def test_reopen_denies_every_cross_scope_dimension(tmp_path: Path, scope: TenantScope) -> None:
    repository = SqliteTaskRepository(tmp_path / "workbench.sqlite3")
    created = repository.create(SCOPE, request())

    with pytest.raises(WorkbenchError) as hidden:
        SqliteTaskRepository(tmp_path / "workbench.sqlite3").get(scope, created.task_id)
    assert hidden.value.code == "CLIENT_TASK_NOT_FOUND"
    with pytest.raises(WorkbenchError) as hidden_claim:
        repository.claim_execution(
            scope,
            created.task_id,
            owner_id="wrong-scope-runtime",
            now=NOW,
            lease_expires_at=NOW + timedelta(seconds=300),
        )
    assert hidden_claim.value.code == "CLIENT_TASK_NOT_FOUND"


def test_idempotency_isolated_by_role_scope_for_both_adapters(tmp_path: Path) -> None:
    changed_role = SCOPE.model_copy(update={"role_codes": ("PROJECT_REVIEWER",)})
    repositories: tuple[TaskRepository, ...] = (
        InMemoryTaskRepository(),
        SqliteTaskRepository(tmp_path / "workbench.sqlite3"),
    )

    for repository in repositories:
        original = repository.create(SCOPE, request())
        separate = repository.create(changed_role, request())
        assert separate.task_id != original.task_id


def test_two_repository_instances_commit_one_same_sequence_event(tmp_path: Path) -> None:
    database = tmp_path / "workbench.sqlite3"
    first = SqliteTaskRepository(database)
    second = SqliteTaskRepository(database)
    task = first.create(SCOPE, request())

    def append(repository: SqliteTaskRepository, index: int) -> str:
        try:
            repository.append(
                SCOPE,
                event(task.task_id, 2, TaskState.RUNNING).model_copy(
                    update={
                        "event_id": UUID(f"00000000-0000-4000-8000-{index:012d}"),
                    }
                ),
            )
        except WorkbenchError as error:
            return error.code
        return "COMMITTED"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda item: append(*item), ((first, 11), (second, 12))))

    assert sorted(outcomes) == ["CLIENT_EVENT_SEQUENCE_INVALID", "COMMITTED"]
    assert [item.sequence for item in first.events(SCOPE, task.task_id, 0).events] == [1, 2]


def test_unknown_schema_corrupt_payload_lock_and_unavailable_path_fail_closed(
    tmp_path: Path,
) -> None:
    unsupported = tmp_path / "unsupported.sqlite3"
    with sqlite3.connect(unsupported) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(WorkbenchPersistenceError) as schema_error:
        SqliteTaskRepository(unsupported)
    assert schema_error.value.code == "CLIENT_PERSISTENCE_SCHEMA_UNSUPPORTED"

    corrupt = tmp_path / "corrupt.sqlite3"
    repository = SqliteTaskRepository(corrupt)
    created = repository.create(SCOPE, request())
    with sqlite3.connect(corrupt) as connection:
        connection.execute(
            "UPDATE workbench_task SET task_json = ? WHERE task_id = ?",
            ("{not-json", str(created.task_id)),
        )
    with pytest.raises(WorkbenchPersistenceError) as corrupt_error:
        repository.get(SCOPE, created.task_id)
    assert corrupt_error.value.code == "CLIENT_PERSISTENCE_CORRUPT"

    inconsistent_event = tmp_path / "inconsistent-event.sqlite3"
    repository = SqliteTaskRepository(inconsistent_event)
    created = repository.create(SCOPE, request())
    with sqlite3.connect(inconsistent_event) as connection:
        connection.execute(
            "UPDATE workbench_event SET sequence = 2 WHERE task_id = ?",
            (str(created.task_id),),
        )
    with pytest.raises(WorkbenchPersistenceError) as event_error:
        repository.events(SCOPE, created.task_id, 0)
    assert event_error.value.code == "CLIENT_PERSISTENCE_CORRUPT"

    locked = tmp_path / "locked.sqlite3"
    locked_repository = SqliteTaskRepository(locked, busy_timeout_ms=1)
    with sqlite3.connect(locked, isolation_level=None) as connection:
        connection.execute("BEGIN EXCLUSIVE")
        with pytest.raises(WorkbenchPersistenceError) as lock_error:
            locked_repository.create(SCOPE, request())
        connection.execute("ROLLBACK")
    assert lock_error.value.code == "CLIENT_PERSISTENCE_BUSY"

    with pytest.raises(WorkbenchPersistenceError) as unavailable:
        SqliteTaskRepository(tmp_path / "missing" / "workbench.sqlite3")
    assert unavailable.value.code == "CLIENT_PERSISTENCE_UNAVAILABLE"


def test_version_one_database_migrates_execution_records_atomically(tmp_path: Path) -> None:
    database = tmp_path / "migrate.sqlite3"
    repository = SqliteTaskRepository(database)
    created = repository.create(SCOPE, request())
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE workbench_execution")
        connection.execute("PRAGMA user_version = 1")

    migrated = SqliteTaskRepository(database)
    pending = migrated.pending_executions(owner_id="new-runtime", now=NOW, limit=8)
    with sqlite3.connect(database) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert SQLITE_WORKBENCH_SCHEMA_VERSION == 2
    assert version == 2
    assert [item.task_id for item in pending] == [created.task_id]
