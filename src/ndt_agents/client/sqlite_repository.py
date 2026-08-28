"""Versioned restart-safe SQLite adapter for the local Web workbench."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ndt_agents.client.models import (
    TaskCreateRequest,
    TaskEvent,
    TaskEventBatch,
    TaskState,
    WorkbenchTask,
)
from ndt_agents.client.service import (
    WorkbenchError,
    _initial_task_records,
    _request_hash,
    _validate_execution_arguments,
    _validate_execution_query,
    _validated_appended_task,
)
from ndt_agents.contracts.v1 import TenantScope

SQLITE_WORKBENCH_SCHEMA_VERSION = 2
_V1_REQUIRED_TABLES = frozenset({"workbench_task", "workbench_event", "workbench_idempotency"})
_REQUIRED_TABLES = frozenset({*_V1_REQUIRED_TABLES, "workbench_execution"})

_EXECUTION_SCHEMA_STATEMENT = """
CREATE TABLE workbench_execution (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'CLAIMED', 'COMPLETED')),
    owner_id TEXT,
    lease_expires_at TEXT,
    CHECK (
        (status = 'CLAIMED' AND owner_id IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status != 'CLAIMED' AND owner_id IS NULL AND lease_expires_at IS NULL)
    ),
    FOREIGN KEY (task_id) REFERENCES workbench_task (task_id) ON DELETE RESTRICT
) STRICT
"""

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE workbench_task (
        task_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role_codes_json TEXT NOT NULL,
        permission_version TEXT NOT NULL,
        state TEXT NOT NULL,
        last_sequence INTEGER NOT NULL CHECK (last_sequence >= 1),
        task_json TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE INDEX workbench_task_scope_idx
    ON workbench_task (
        tenant_id, project_id, user_id, role_codes_json, permission_version, task_id
    )
    """,
    """
    CREATE TABLE workbench_event (
        event_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role_codes_json TEXT NOT NULL,
        permission_version TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        event_json TEXT NOT NULL,
        UNIQUE (task_id, sequence),
        FOREIGN KEY (task_id) REFERENCES workbench_task (task_id) ON DELETE RESTRICT
    ) STRICT
    """,
    """
    CREATE INDEX workbench_event_scope_idx
    ON workbench_event (
        tenant_id, project_id, user_id, role_codes_json, permission_version, task_id, sequence
    )
    """,
    """
    CREATE TABLE workbench_idempotency (
        tenant_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role_codes_json TEXT NOT NULL,
        permission_version TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_sha256 TEXT NOT NULL CHECK (length(request_sha256) = 64),
        task_id TEXT NOT NULL,
        PRIMARY KEY (
            tenant_id, project_id, user_id, role_codes_json,
            permission_version, idempotency_key
        ),
        FOREIGN KEY (task_id) REFERENCES workbench_task (task_id) ON DELETE RESTRICT
    ) STRICT
    """,
    _EXECUTION_SCHEMA_STATEMENT,
)

_REQUIRED_COLUMNS = {
    "workbench_task": frozenset(
        {
            "task_id",
            "tenant_id",
            "project_id",
            "user_id",
            "role_codes_json",
            "permission_version",
            "state",
            "last_sequence",
            "task_json",
        }
    ),
    "workbench_event": frozenset(
        {
            "event_id",
            "task_id",
            "tenant_id",
            "project_id",
            "user_id",
            "role_codes_json",
            "permission_version",
            "sequence",
            "event_json",
        }
    ),
    "workbench_idempotency": frozenset(
        {
            "tenant_id",
            "project_id",
            "user_id",
            "role_codes_json",
            "permission_version",
            "idempotency_key",
            "request_sha256",
            "task_id",
        }
    ),
    "workbench_execution": frozenset({"task_id", "status", "owner_id", "lease_expires_at"}),
}


class WorkbenchPersistenceError(WorkbenchError):
    """Stable local persistence failure without backend or path disclosure."""

    def __init__(self, *, code: str, next_action: str) -> None:
        super().__init__(code=code, status_code=503, next_action=next_action)


def _scope_values(scope: TenantScope) -> tuple[str, str, str, str, str]:
    return (
        str(scope.tenant_id),
        str(scope.project_id),
        str(scope.user_id),
        json.dumps(scope.role_codes, ensure_ascii=True, separators=(",", ":")),
        scope.permission_version,
    )


class SqliteTaskRepository:
    """Local-only atomic repository; each operation owns one bounded transaction."""

    def __init__(self, database_path: str | Path, *, busy_timeout_ms: int = 1_000) -> None:
        path = Path(database_path)
        if (
            not path.is_absolute()
            or busy_timeout_ms < 1
            or busy_timeout_ms > 30_000
            or not path.parent.is_dir()
            or path.is_symlink()
            or (path.exists() and not path.is_file())
        ):
            raise self._unavailable()
        self._database_path = path.resolve(strict=False)
        self._busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def create(
        self,
        scope: TenantScope,
        request: TaskCreateRequest,
        *,
        task_id_factory: Callable[[], UUID] = uuid4,
        event_id_factory: Callable[[], UUID] = uuid4,
        now: datetime | None = None,
    ) -> WorkbenchTask:
        digest = _request_hash(request)
        scope_values = _scope_values(scope)
        with self._transaction(write=True) as connection:
            existing = connection.execute(
                """
                SELECT request_sha256, task_id
                FROM workbench_idempotency
                WHERE tenant_id = ? AND project_id = ? AND user_id = ?
                  AND role_codes_json = ? AND permission_version = ? AND idempotency_key = ?
                """,
                (*scope_values, request.idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    raise WorkbenchError(
                        code="CLIENT_IDEMPOTENCY_CONFLICT",
                        status_code=409,
                        next_action="Use a new idempotency key for changed task input.",
                    )
                return self._load_task(connection, scope, UUID(existing[1]))

            task, accepted = _initial_task_records(
                scope,
                request,
                task_id_factory=task_id_factory,
                event_id_factory=event_id_factory,
                timestamp=now or datetime.now(UTC),
            )
            connection.execute(
                """
                INSERT INTO workbench_task (
                    task_id, tenant_id, project_id, user_id, role_codes_json, permission_version,
                    state, last_sequence, task_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(task.task_id),
                    *scope_values,
                    task.state.value,
                    task.last_sequence,
                    task.model_dump_json(),
                ),
            )
            self._insert_event(connection, accepted)
            connection.execute(
                """
                INSERT INTO workbench_idempotency (
                    tenant_id, project_id, user_id, role_codes_json, permission_version,
                    idempotency_key, request_sha256, task_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*scope_values, request.idempotency_key, digest, str(task.task_id)),
            )
            connection.execute(
                """
                INSERT INTO workbench_execution (task_id, status, owner_id, lease_expires_at)
                VALUES (?, 'PENDING', NULL, NULL)
                """,
                (str(task.task_id),),
            )
            return task

    def get(self, scope: TenantScope, task_id: UUID) -> WorkbenchTask:
        with self._transaction(write=False) as connection:
            return self._load_task(connection, scope, task_id)

    def events(self, scope: TenantScope, task_id: UUID, after_sequence: int) -> TaskEventBatch:
        with self._transaction(write=False) as connection:
            task = self._load_task(connection, scope, task_id)
            if after_sequence < 0 or after_sequence > task.last_sequence:
                raise WorkbenchError(
                    code="CLIENT_EVENT_CURSOR_INVALID",
                    status_code=409,
                    next_action="Reconnect using the last sequence acknowledged by the server.",
                )
            rows = connection.execute(
                """
                SELECT sequence, event_json
                FROM workbench_event
                WHERE task_id = ? AND tenant_id = ? AND project_id = ? AND user_id = ?
                  AND role_codes_json = ? AND permission_version = ? AND sequence > ?
                ORDER BY sequence
                """,
                (str(task_id), *_scope_values(scope), after_sequence),
            ).fetchall()
            selected = tuple(self._parse_event(row[1]) for row in rows)
            expected_sequences = tuple(range(after_sequence + 1, task.last_sequence + 1))
            stored_sequences = tuple(int(row[0]) for row in rows)
            actual_sequences = tuple(item.sequence for item in selected)
            if (
                stored_sequences != expected_sequences
                or actual_sequences != expected_sequences
                or any(item.task_id != task_id or item.scope != scope for item in selected)
            ):
                raise self._corrupt()
            return TaskEventBatch(
                task_id=task_id,
                after_sequence=after_sequence,
                last_sequence=task.last_sequence,
                terminal=task.state.terminal,
                events=selected,
            )

    def append(self, scope: TenantScope, event: TaskEvent) -> WorkbenchTask:
        with self._transaction(write=True) as connection:
            task = self._load_task(connection, scope, event.task_id)
            updated = _validated_appended_task(task, scope, event)
            self._insert_event(connection, event)
            result = connection.execute(
                """
                UPDATE workbench_task
                SET state = ?, last_sequence = ?, task_json = ?
                WHERE task_id = ? AND tenant_id = ? AND project_id = ? AND user_id = ?
                  AND role_codes_json = ? AND permission_version = ? AND last_sequence = ?
                """,
                (
                    updated.state.value,
                    updated.last_sequence,
                    updated.model_dump_json(),
                    str(updated.task_id),
                    *_scope_values(scope),
                    task.last_sequence,
                ),
            )
            if result.rowcount != 1:
                raise WorkbenchError(
                    code="CLIENT_EVENT_SEQUENCE_INVALID",
                    status_code=409,
                    next_action="Append the next exact-scope event sequence.",
                )
            if updated.state.terminal:
                completed = connection.execute(
                    """
                    UPDATE workbench_execution
                    SET status = 'COMPLETED', owner_id = NULL, lease_expires_at = NULL
                    WHERE task_id = ? AND status != 'COMPLETED'
                    """,
                    (str(updated.task_id),),
                )
                if completed.rowcount != 1:
                    raise self._corrupt()
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
        with self._transaction(write=True) as connection:
            task = self._load_task(connection, scope, task_id)
            row = connection.execute(
                """
                SELECT status, owner_id, lease_expires_at
                FROM workbench_execution
                WHERE task_id = ?
                """,
                (str(task_id),),
            ).fetchone()
            if row is None:
                raise self._corrupt()
            expired_foreign = (
                row[0] == "CLAIMED"
                and row[1] != owner_id
                and row[2] is not None
                and self._parse_timestamp(row[2]) <= now.astimezone(UTC)
            )
            if task.state is not TaskState.ACCEPTED or not (row[0] == "PENDING" or expired_foreign):
                return False
            updated = connection.execute(
                """
                UPDATE workbench_execution
                SET status = 'CLAIMED', owner_id = ?, lease_expires_at = ?
                WHERE task_id = ?
                """,
                (owner_id, self._timestamp(lease_expires_at), str(task_id)),
            )
            if updated.rowcount != 1:
                raise self._corrupt()
            return True

    def pending_executions(
        self,
        *,
        owner_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[WorkbenchTask, ...]:
        _validate_execution_query(owner_id, now, limit)
        with self._transaction(write=False) as connection:
            rows = connection.execute(
                """
                SELECT t.state, t.last_sequence, t.task_json
                FROM workbench_task AS t
                JOIN workbench_execution AS e ON e.task_id = t.task_id
                WHERE t.state = 'ACCEPTED'
                  AND (
                      e.status = 'PENDING'
                      OR (
                          e.status = 'CLAIMED' AND e.owner_id != ?
                          AND e.lease_expires_at <= ?
                      )
                  )
                ORDER BY t.task_id
                LIMIT ?
                """,
                (owner_id, self._timestamp(now), limit),
            ).fetchall()
            return tuple(self._parse_scanned_task(row) for row in rows)

    def orphaned_executions(
        self,
        *,
        owner_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[WorkbenchTask, ...]:
        _validate_execution_query(owner_id, now, limit)
        terminal = tuple(state.value for state in TaskState if state.terminal)
        placeholders = ", ".join("?" for _item in terminal)
        with self._transaction(write=False) as connection:
            rows = connection.execute(
                f"""
                SELECT t.state, t.last_sequence, t.task_json
                FROM workbench_task AS t
                JOIN workbench_execution AS e ON e.task_id = t.task_id
                WHERE t.state != 'ACCEPTED' AND t.state NOT IN ({placeholders})
                  AND e.status = 'CLAIMED' AND e.owner_id != ?
                  AND e.lease_expires_at <= ?
                ORDER BY t.task_id
                LIMIT ?
                """,
                (*terminal, owner_id, self._timestamp(now), limit),
            ).fetchall()
            return tuple(self._parse_scanned_task(row) for row in rows)

    def next_foreign_lease_expiry(
        self,
        *,
        owner_id: str,
        now: datetime,
    ) -> datetime | None:
        _validate_execution_query(owner_id, now, 1)
        with self._transaction(write=False) as connection:
            row = connection.execute(
                """
                SELECT MIN(lease_expires_at)
                FROM workbench_execution
                WHERE status = 'CLAIMED' AND owner_id != ? AND lease_expires_at > ?
                """,
                (owner_id, self._timestamp(now)),
            ).fetchone()
            if row is None or row[0] is None:
                return None
            return self._parse_timestamp(row[0])

    def _initialize(self) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            version_row = connection.execute("PRAGMA user_version").fetchone()
            version = int(version_row[0]) if version_row is not None else -1
            if version not in {0, 1, SQLITE_WORKBENCH_SCHEMA_VERSION}:
                raise WorkbenchPersistenceError(
                    code="CLIENT_PERSISTENCE_SCHEMA_UNSUPPORTED",
                    next_action="Migrate or select a supported local workbench database.",
                )
            tables = frozenset(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            )
            if version == 0:
                if tables:
                    raise self._corrupt()
                connection.execute("BEGIN IMMEDIATE")
                for statement in _SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {SQLITE_WORKBENCH_SCHEMA_VERSION}")
                connection.execute("COMMIT")
            elif version == 1:
                if not _V1_REQUIRED_TABLES.issubset(tables) or "workbench_execution" in tables:
                    raise self._corrupt()
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(_EXECUTION_SCHEMA_STATEMENT)
                connection.execute(
                    """
                    INSERT INTO workbench_execution (
                        task_id, status, owner_id, lease_expires_at
                    )
                    SELECT
                        task_id,
                        CASE
                            WHEN state = 'ACCEPTED' THEN 'PENDING'
                            WHEN state IN (
                                'SUCCEEDED', 'PARTIAL', 'BLOCKED', 'FAILED', 'CANCELLED'
                            ) THEN 'COMPLETED'
                            ELSE 'CLAIMED'
                        END,
                        CASE
                            WHEN state IN (
                                'ACCEPTED', 'SUCCEEDED', 'PARTIAL',
                                'BLOCKED', 'FAILED', 'CANCELLED'
                            ) THEN NULL
                            ELSE 'schema-v1-unknown-owner'
                        END,
                        CASE
                            WHEN state IN (
                                'ACCEPTED', 'SUCCEEDED', 'PARTIAL',
                                'BLOCKED', 'FAILED', 'CANCELLED'
                            ) THEN NULL
                            ELSE '1970-01-01T00:00:00+00:00'
                        END
                    FROM workbench_task
                    """
                )
                connection.execute(f"PRAGMA user_version = {SQLITE_WORKBENCH_SCHEMA_VERSION}")
                connection.execute("COMMIT")
            connection.execute("PRAGMA journal_mode = WAL")
            tables = frozenset(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            )
            if not _REQUIRED_TABLES.issubset(tables):
                raise self._corrupt()
            for table, required_columns in _REQUIRED_COLUMNS.items():
                columns = frozenset(
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                )
                if not required_columns.issubset(columns):
                    raise self._corrupt()
            missing_execution = connection.execute(
                """
                SELECT COUNT(*)
                FROM workbench_task AS t
                LEFT JOIN workbench_execution AS e ON e.task_id = t.task_id
                WHERE e.task_id IS NULL
                """
            ).fetchone()
            if missing_execution is None or int(missing_execution[0]) != 0:
                raise self._corrupt()
        except WorkbenchError:
            self._rollback(connection)
            raise
        except sqlite3.Error as error:
            self._rollback(connection)
            raise self._translated(error) from None
        finally:
            if connection is not None:
                connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection

    @contextmanager
    def _transaction(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.execute("COMMIT")
        except WorkbenchError:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError:
            self._rollback(connection)
            raise WorkbenchPersistenceError(
                code="CLIENT_PERSISTENCE_CONFLICT",
                next_action="Reload the exact task state before another local write.",
            ) from None
        except sqlite3.Error as error:
            self._rollback(connection)
            raise self._translated(error) from None
        finally:
            if connection is not None:
                connection.close()

    def _load_task(
        self,
        connection: sqlite3.Connection,
        scope: TenantScope,
        task_id: UUID,
    ) -> WorkbenchTask:
        row = connection.execute(
            """
            SELECT state, last_sequence, task_json
            FROM workbench_task
            WHERE task_id = ? AND tenant_id = ? AND project_id = ? AND user_id = ?
              AND role_codes_json = ? AND permission_version = ?
            """,
            (str(task_id), *_scope_values(scope)),
        ).fetchone()
        if row is None:
            raise WorkbenchError(
                code="CLIENT_TASK_NOT_FOUND",
                status_code=404,
                next_action="Select an existing task in the active project.",
            )
        task = self._parse_task(row[2])
        if (
            task.task_id != task_id
            or task.scope != scope
            or task.state.value != row[0]
            or task.last_sequence != row[1]
        ):
            raise self._corrupt()
        return task

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, event: TaskEvent) -> None:
        connection.execute(
            """
            INSERT INTO workbench_event (
                event_id, task_id, tenant_id, project_id, user_id, role_codes_json,
                permission_version, sequence, event_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.event_id),
                str(event.task_id),
                *_scope_values(event.scope),
                event.sequence,
                event.model_dump_json(),
            ),
        )

    @staticmethod
    def _parse_task(payload: str) -> WorkbenchTask:
        try:
            return WorkbenchTask.model_validate_json(payload)
        except (TypeError, ValueError):
            raise SqliteTaskRepository._corrupt() from None

    @classmethod
    def _parse_scanned_task(cls, row: tuple[object, ...]) -> WorkbenchTask:
        if len(row) != 3 or not isinstance(row[2], str):
            raise cls._corrupt()
        task = cls._parse_task(row[2])
        if task.state.value != row[0] or task.last_sequence != row[1]:
            raise cls._corrupt()
        return task

    @staticmethod
    def _parse_event(payload: str) -> TaskEvent:
        try:
            return TaskEvent.model_validate_json(payload)
        except (TypeError, ValueError):
            raise SqliteTaskRepository._corrupt() from None

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("SQLite execution timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str):
            raise SqliteTaskRepository._corrupt()
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise SqliteTaskRepository._corrupt() from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SqliteTaskRepository._corrupt()
        return parsed.astimezone(UTC)

    @staticmethod
    def _rollback(connection: sqlite3.Connection | None) -> None:
        if connection is not None and connection.in_transaction:
            connection.execute("ROLLBACK")

    @staticmethod
    def _translated(error: sqlite3.Error) -> WorkbenchPersistenceError:
        detail = str(error).lower()
        if "locked" in detail or "busy" in detail:
            return WorkbenchPersistenceError(
                code="CLIENT_PERSISTENCE_BUSY",
                next_action="Stop the competing local process and retry the explicit action.",
            )
        if isinstance(error, sqlite3.DatabaseError) and not isinstance(
            error, sqlite3.OperationalError
        ):
            return SqliteTaskRepository._corrupt()
        return SqliteTaskRepository._unavailable()

    @staticmethod
    def _corrupt() -> WorkbenchPersistenceError:
        return WorkbenchPersistenceError(
            code="CLIENT_PERSISTENCE_CORRUPT",
            next_action="Preserve the local database and restore a verified compatible copy.",
        )

    @staticmethod
    def _unavailable() -> WorkbenchPersistenceError:
        return WorkbenchPersistenceError(
            code="CLIENT_PERSISTENCE_UNAVAILABLE",
            next_action="Configure an available absolute local state path and restart.",
        )
