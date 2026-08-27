"""Immutable runtime configuration loaded from a narrow environment allowlist."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ndt_agents import __version__
from ndt_agents.orchestration.general_model_delegate import (
    DEEPSEEK_POLICY_ACKNOWLEDGEMENT,
)

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
    model_config_path: str | None = Field(default=None, min_length=1, max_length=4096)
    model_env_file: str | None = Field(default=None, min_length=1, max_length=4096)
    prompt_config_path: str | None = Field(default=None, min_length=1, max_length=4096)
    agent_config_path: str | None = Field(default=None, min_length=1, max_length=4096)
    general_model_delegate_enabled: bool = False
    deepseek_policy_acknowledgement: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_production_docs(self) -> Self:
        if self.environment is RuntimeEnvironment.PRODUCTION and self.expose_api_docs:
            raise ValueError("API documentation cannot be exposed in production")
        if self.model_env_file is not None and self.model_config_path is None:
            raise ValueError("a model environment file requires a model configuration")
        if self.agent_config_path is not None and self.model_config_path is None:
            raise ValueError("an agent configuration requires a model configuration")
        if self.agent_config_path is not None and self.prompt_config_path is None:
            raise ValueError("an agent configuration requires a prompt catalog")
        if self.prompt_config_path is not None and self.agent_config_path is None:
            raise ValueError("a prompt catalog requires an agent configuration")
        if self.environment is RuntimeEnvironment.PRODUCTION and self.model_env_file is not None:
            raise ValueError("a local model environment file is forbidden in production")
        if self.general_model_delegate_enabled:
            if self.environment is not RuntimeEnvironment.LOCAL:
                raise ValueError("the General model delegate is local-only")
            if (
                self.model_config_path is None
                or self.prompt_config_path is None
                or self.agent_config_path is None
            ):
                raise ValueError("the General model delegate requires complete model configuration")
            if self.deepseek_policy_acknowledgement != DEEPSEEK_POLICY_ACKNOWLEDGEMENT:
                raise ValueError("the General model delegate requires exact policy acknowledgement")
        elif self.deepseek_policy_acknowledgement is not None:
            raise ValueError("provider-policy acknowledgement requires the enabled local delegate")
        for path in (
            self.model_config_path,
            self.model_env_file,
            self.prompt_config_path,
            self.agent_config_path,
        ):
            if path is not None and ("\x00" in path or "\r" in path or "\n" in path):
                raise ValueError("model configuration paths contain forbidden characters")
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
            "NDT_MODEL_CONFIG": "model_config_path",
            "NDT_MODEL_ENV_FILE": "model_env_file",
            "NDT_PROMPT_CONFIG": "prompt_config_path",
            "NDT_AGENT_CONFIG": "agent_config_path",
            "NDT_GENERAL_MODEL_DELEGATE_ENABLED": "general_model_delegate_enabled",
            "NDT_DEEPSEEK_POLICY_ACKNOWLEDGEMENT": "deepseek_policy_acknowledgement",
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
        if (
            values.get("environment") == RuntimeEnvironment.PRODUCTION.value
            and "model_env_file" in values
        ):
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
