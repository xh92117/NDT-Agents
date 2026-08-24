"""Strict reference-only models for secrets, keys, encryption, and policy context."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from ndt_agents.contracts.v1 import TenantScope

_PURPOSE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class SecurityEnvironment(StrEnum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class KeyState(StrEnum):
    ACTIVE = "ACTIVE"
    DECRYPT_ONLY = "DECRYPT_ONLY"
    REVOKED = "REVOKED"


class SecurityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SecurityContext(SecurityModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    scope: TenantScope
    environment: SecurityEnvironment
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    task_id: UUID | None = None
    policy_version: str = Field(min_length=1, max_length=128)
    allowed_secret_purposes: frozenset[str] = frozenset()
    allowed_key_purposes: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def validate_purposes(self) -> Self:
        if any(_PURPOSE.fullmatch(value) is None for value in self.allowed_secret_purposes):
            raise ValueError("allowed secret purpose is invalid")
        if any(_PURPOSE.fullmatch(value) is None for value in self.allowed_key_purposes):
            raise ValueError("allowed key purpose is invalid")
        return self


class SecretSelector(SecurityModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    secret_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,127}$")
    environment: SecurityEnvironment
    tenant_id: UUID
    project_id: UUID
    purpose: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")


class SecretRef(SecretSelector):
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

    @property
    def selector(self) -> SecretSelector:
        return SecretSelector.model_validate(self.model_dump(exclude={"version"}))


class SecretLease(SecurityModel):
    ref: SecretRef
    accessor_user_id: UUID
    permission_version: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    issued_at: datetime
    expires_at: datetime
    value: SecretStr = Field(exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        for value in (self.issued_at, self.expires_at):
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                raise ValueError("secret lease times must use UTC")
        if self.expires_at <= self.issued_at:
            raise ValueError("secret lease expiry must follow issue time")
        return self


class KeySelector(SecurityModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    key_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,127}$")
    environment: SecurityEnvironment
    tenant_id: UUID
    project_id: UUID
    purpose: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")


class KeyRef(KeySelector):
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    algorithm: Literal["AES-256-GCM"] = "AES-256-GCM"

    @property
    def selector(self) -> KeySelector:
        return KeySelector.model_validate(self.model_dump(exclude={"version", "algorithm"}))


class EncryptedEnvelope(SecurityModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    algorithm: Literal["AES-256-GCM"] = "AES-256-GCM"
    key_ref: KeyRef
    nonce_b64u: str = Field(pattern=r"^[A-Za-z0-9_-]{16}$")
    ciphertext_b64u: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    aad_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SecurityError(RuntimeError):
    """Stable non-disclosing platform-security failure."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        next_action: str,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.next_action = next_action
        super().__init__(message)
