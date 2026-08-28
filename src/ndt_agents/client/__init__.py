"""Versioned Web and desktop client contracts and runtimes."""

from ndt_agents.client.desktop import (
    DesktopBridgeError,
    DesktopBridgeRequest,
    DesktopBridgeResult,
    DesktopBridgeService,
    DesktopSessionGrant,
    InMemoryDesktopSessionAuthority,
)
from ndt_agents.client.models import (
    ClientTaskClass,
    TaskCreateRequest,
    TaskEvent,
    TaskEventKind,
    TaskState,
    WorkbenchCapabilities,
    WorkbenchExecutionMode,
    WorkbenchTask,
)
from ndt_agents.client.service import (
    InMemoryTaskRepository,
    TaskRepository,
    WorkbenchAsyncPolicy,
    WorkbenchError,
    WorkbenchRuntime,
)
from ndt_agents.client.sqlite_repository import (
    SQLITE_WORKBENCH_SCHEMA_VERSION,
    SqliteTaskRepository,
    WorkbenchPersistenceError,
)

__all__ = [
    "ClientTaskClass",
    "DesktopBridgeError",
    "DesktopBridgeRequest",
    "DesktopBridgeResult",
    "DesktopBridgeService",
    "DesktopSessionGrant",
    "InMemoryTaskRepository",
    "InMemoryDesktopSessionAuthority",
    "SQLITE_WORKBENCH_SCHEMA_VERSION",
    "SqliteTaskRepository",
    "TaskRepository",
    "TaskCreateRequest",
    "TaskEvent",
    "TaskEventKind",
    "TaskState",
    "WorkbenchError",
    "WorkbenchAsyncPolicy",
    "WorkbenchPersistenceError",
    "WorkbenchCapabilities",
    "WorkbenchExecutionMode",
    "WorkbenchRuntime",
    "WorkbenchTask",
]
