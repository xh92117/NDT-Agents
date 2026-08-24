"""Immutable child-agent definition registry."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ndt_agents.orchestration.child_models import AgentDefinition, ChildAgentKind


class AgentRegistryError(RuntimeError):
    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class AgentRegistry:
    """Resolve only explicitly registered General or professional child definitions."""

    def __init__(self, definitions: tuple[AgentDefinition, ...]) -> None:
        mapped = {definition.agent_type: definition for definition in definitions}
        if len(mapped) != len(definitions):
            raise ValueError("agent definitions must have unique types")
        general = [item for item in definitions if item.kind is ChildAgentKind.GENERAL]
        if len(general) != 1 or general[0].agent_type != "general":
            raise ValueError("registry requires exactly one general child definition")
        self._definitions: Mapping[str, AgentDefinition] = MappingProxyType(mapped)

    def require(self, agent_type: str, kind: ChildAgentKind) -> AgentDefinition:
        definition = self._definitions.get(agent_type)
        if definition is None:
            raise AgentRegistryError(
                code="AGENT_NOT_REGISTERED",
                message="The requested child agent is not registered.",
                next_action="Register an authorized versioned child definition.",
            )
        if definition.kind is not kind:
            raise AgentRegistryError(
                code="AGENT_KIND_MISMATCH",
                message="The registered child agent kind does not match the dispatch.",
                next_action="Correct the route or the registered child definition.",
            )
        return definition
