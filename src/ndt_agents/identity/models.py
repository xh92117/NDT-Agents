"""Strict models for OIDC configuration, principals, and request scope output."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OidcSettings(IdentityModel):
    issuer: str = Field(min_length=8, max_length=2048)
    audience: str = Field(min_length=1, max_length=256)
    allowed_algorithms: tuple[Literal["RS256", "ES256"], ...] = ("RS256",)
    clock_skew_seconds: int = Field(default=30, ge=0, le=120)

    @model_validator(mode="after")
    def validate_issuer_and_algorithms(self) -> Self:
        if not self.issuer.startswith("https://"):
            raise ValueError("OIDC issuer must use HTTPS")
        if not self.allowed_algorithms or len(set(self.allowed_algorithms)) != len(
            self.allowed_algorithms
        ):
            raise ValueError("OIDC algorithms must be non-empty and unique")
        return self


class Principal(IdentityModel):
    subject: str = Field(min_length=1, max_length=512)
    user_id: UUID
    tenant_id: UUID
    project_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    roles: tuple[str, ...] = Field(min_length=1, max_length=32)
    permission_version: str = Field(min_length=1, max_length=128)
    token_id: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_collections(self) -> Self:
        if len(set(self.project_ids)) != len(self.project_ids):
            raise ValueError("project IDs must be unique")
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("roles must be unique")
        if any(not role or len(role) > 128 for role in self.roles):
            raise ValueError("role code is invalid")
        return self


class ScopeResponse(IdentityModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    tenant_id: UUID
    project_id: UUID
    user_id: UUID
    role_codes: tuple[str, ...]
    permission_version: str
    rbac_policy_version: str
    route_policy_version: str


class IdentityError(RuntimeError):
    """Stable authentication or authorization denial."""

    def __init__(self, *, code: str, status_code: int, message: str, next_action: str) -> None:
        self.code = code
        self.status_code = status_code
        self.next_action = next_action
        super().__init__(message)
