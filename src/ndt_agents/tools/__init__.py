"""Shared tool registration and invocation boundary."""

from ndt_agents.tools.file_gateway import (
    ControlledFileGateway,
    ExecutableIdentity,
    ExecutionTemplate,
    FileGatewayError,
    FileRootPolicy,
)
from ndt_agents.tools.registry import (
    DefinitionOrigin,
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolAdapter,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationContext,
    ToolRegistry,
    ToolRegistryError,
)

__all__ = [
    "ControlledFileGateway",
    "DefinitionOrigin",
    "ExecutableIdentity",
    "ExecutionTemplate",
    "FileGatewayError",
    "FileRootPolicy",
    "IdempotencyPolicy",
    "NetworkPolicy",
    "SideEffectClass",
    "ToolAdapter",
    "ToolDefinition",
    "ToolInvocation",
    "ToolInvocationContext",
    "ToolRegistry",
    "ToolRegistryError",
]
