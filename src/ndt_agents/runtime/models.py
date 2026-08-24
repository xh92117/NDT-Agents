"""Versioned API boundary models for runtime status and failures."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RUNTIME_API_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"


class RuntimeApiModel(BaseModel):
    """Strict immutable base for runtime API payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class HealthCheck(RuntimeApiModel):
    name: str = Field(min_length=1, max_length=64)
    status: Literal["PASS", "FAIL"]
    error_code: str | None = Field(default=None, max_length=128)


class HealthResponse(RuntimeApiModel):
    schema_version: Literal["1.0.0"] = RUNTIME_API_SCHEMA_VERSION
    service: str = Field(min_length=1, max_length=64)
    service_version: str = Field(min_length=1, max_length=64)
    status: Literal["PASS", "FAIL"]
    checks: tuple[HealthCheck, ...] = Field(min_length=1)


class ProblemDetail(RuntimeApiModel):
    schema_version: Literal["1.0.0"] = RUNTIME_API_SCHEMA_VERSION
    error_code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1000)
    request_id: str = Field(min_length=1, max_length=128)
    retryable: bool
    next_action: str = Field(min_length=1, max_length=1000)
