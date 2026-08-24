"""Immutable runtime configuration loaded from a narrow environment allowlist."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ndt_agents import __version__

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class RuntimeEnvironment(StrEnum):
    """Supported deployment environment names."""

    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class ConfigurationError(RuntimeError):
    """Stable, non-disclosing startup configuration failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class AppSettings(BaseModel):
    """Validated service settings without provider or storage configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service_name: str = Field(default="ndt-agents", min_length=1, max_length=64)
    service_version: str = Field(default=__version__, min_length=1, max_length=64)
    environment: RuntimeEnvironment = RuntimeEnvironment.LOCAL
    log_level: LogLevel = "INFO"
    host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    port: int = Field(default=8000, ge=1, le=65535)
    expose_api_docs: bool = False

    @model_validator(mode="after")
    def validate_production_docs(self) -> Self:
        if self.environment is RuntimeEnvironment.PRODUCTION and self.expose_api_docs:
            raise ValueError("API documentation cannot be exposed in production")
        return self

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> AppSettings:
        """Load recognized NDT_ keys and reject typos without echoing their values."""

        source = os.environ if environ is None else environ
        environment_keys = {
            "NDT_SERVICE_NAME": "service_name",
            "NDT_ENVIRONMENT": "environment",
            "NDT_LOG_LEVEL": "log_level",
            "NDT_HOST": "host",
            "NDT_PORT": "port",
            "NDT_EXPOSE_API_DOCS": "expose_api_docs",
        }
        unknown = sorted(
            key for key in source if key.startswith("NDT_") and key not in environment_keys
        )
        if unknown:
            raise ConfigurationError(
                "CONFIG_UNKNOWN_ENVIRONMENT_KEY",
                "An unsupported NDT_ environment setting was provided.",
            )

        values = {
            field_name: source[environment_key]
            for environment_key, field_name in environment_keys.items()
            if environment_key in source
        }
        if values.get("environment") == RuntimeEnvironment.PRODUCTION.value and str(
            values.get("expose_api_docs", "false")
        ).lower() in {"1", "true", "yes", "on"}:
            raise ConfigurationError(
                "CONFIG_UNSAFE",
                "The selected runtime configuration violates a safety constraint.",
            )
        try:
            return cls.model_validate(values)
        except ValidationError:
            raise ConfigurationError(
                "CONFIG_VALIDATION_FAILED",
                "One or more runtime settings are invalid.",
            ) from None
