"""Versioned default-deny role and route authorization policies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ndt_agents.identity.models import Principal


class Permission(StrEnum):
    RUNTIME_SCOPE_READ = "runtime:scope:read"
    KNOWLEDGE_IMPORT_START = "knowledge:import:start"


@dataclass(frozen=True, slots=True)
class RbacPolicy:
    policy_version: str
    grants: Mapping[str, frozenset[Permission]]

    def __post_init__(self) -> None:
        if not self.policy_version or len(self.policy_version) > 128:
            raise ValueError("RBAC policy version is invalid")
        frozen = {
            role: frozenset(permissions)
            for role, permissions in self.grants.items()
            if role and len(role) <= 128
        }
        if len(frozen) != len(self.grants):
            raise ValueError("RBAC role code is invalid")
        object.__setattr__(self, "grants", MappingProxyType(frozen))

    def allows(self, principal: Principal, permission: Permission) -> bool:
        return any(permission in self.grants.get(role, frozenset()) for role in principal.roles)


@dataclass(frozen=True, slots=True)
class RoutePermissionPolicy:
    policy_version: str
    permissions: Mapping[tuple[str, str], Permission]

    def __post_init__(self) -> None:
        if not self.policy_version or len(self.policy_version) > 128:
            raise ValueError("route policy version is invalid")
        normalized = {
            (method.upper(), path): permission
            for (method, path), permission in self.permissions.items()
            if method and path.startswith("/v1/")
        }
        if len(normalized) != len(self.permissions):
            raise ValueError("route permission entry is invalid")
        object.__setattr__(self, "permissions", MappingProxyType(normalized))

    def required_permission(self, method: str, path: str) -> Permission | None:
        return self.permissions.get((method.upper(), path))
