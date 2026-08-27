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
from ndt_agents.client.service import InMemoryTaskRepository, WorkbenchError, WorkbenchRuntime

__all__ = [
    "ClientTaskClass",
    "DesktopBridgeError",
    "DesktopBridgeRequest",
    "DesktopBridgeResult",
    "DesktopBridgeService",
    "DesktopSessionGrant",
    "InMemoryTaskRepository",
    "InMemoryDesktopSessionAuthority",
    "TaskCreateRequest",
    "TaskEvent",
    "TaskEventKind",
    "TaskState",
    "WorkbenchError",
    "WorkbenchCapabilities",
    "WorkbenchExecutionMode",
    "WorkbenchRuntime",
    "WorkbenchTask",
]
