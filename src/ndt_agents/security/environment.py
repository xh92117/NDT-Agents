"""Read-only local and CI secret provider backed by explicit environment variables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import Field, SecretStr, model_validator

from ndt_agents.security.models import (
    SecretRef,
    SecretSelector,
    SecurityEnvironment,
    SecurityError,
    SecurityModel,
)


class EnvironmentSecretBinding(SecurityModel):
    selector: SecretSelector
    variable_name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

    @model_validator(mode="after")
    def reject_managed_environments(self) -> EnvironmentSecretBinding:
        if self.selector.environment in {
            SecurityEnvironment.STAGING,
            SecurityEnvironment.PRODUCTION,
        }:
            raise ValueError("environment secrets are limited to local and CI use")
        return self

    @property
    def ref(self) -> SecretRef:
        return SecretRef(**self.selector.model_dump(), version=self.version)


class EnvironmentSecretProvider:
    """Resolve allowlisted environment values without supporting mutation or fallback."""

    def __init__(
        self,
        bindings: Sequence[EnvironmentSecretBinding],
        values: Mapping[str, str],
    ) -> None:
        by_selector: dict[SecretSelector, tuple[SecretRef, SecretStr]] = {}
        variables: set[str] = set()
        for binding in bindings:
            if binding.selector in by_selector or binding.variable_name in variables:
                raise SecurityError(
                    code="SECRET_BINDING_DUPLICATE",
                    message="An environment secret binding is duplicated.",
                    retryable=False,
                    next_action="Use one exact selector and variable per local secret binding.",
                )
            raw_value = values.get(binding.variable_name)
            if raw_value is None or not 1 <= len(raw_value) <= 16_384:
                raise SecurityError(
                    code="SECRET_VALUE_INVALID",
                    message="A configured environment secret is missing or invalid.",
                    retryable=False,
                    next_action="Set a non-empty bounded value in the approved local environment.",
                )
            by_selector[binding.selector] = (binding.ref, SecretStr(raw_value))
            variables.add(binding.variable_name)
        self._values = by_selector

    def current_ref(self, selector: SecretSelector) -> SecretRef:
        value = self._values.get(selector)
        if value is None:
            raise SecurityError(
                code="SECRET_NOT_FOUND",
                message="The requested environment secret reference does not exist.",
                retryable=False,
                next_action="Provision the exact approved local secret reference before retrying.",
            )
        return value[0]

    def reveal(self, ref: SecretRef) -> SecretStr:
        value = self._values.get(ref.selector)
        if value is None:
            raise SecurityError(
                code="SECRET_NOT_FOUND",
                message="The requested environment secret reference does not exist.",
                retryable=False,
                next_action="Provision the exact approved local secret reference before retrying.",
            )
        if value[0] != ref:
            raise SecurityError(
                code="SECRET_VERSION_STALE",
                message="The requested environment secret version is stale.",
                retryable=False,
                next_action="Resolve the current configured local secret version.",
            )
        return value[1]

    def rotate(self, selector: SecretSelector, version: str, value: SecretStr) -> SecretRef:
        del selector, version, value
        raise self._read_only_error()

    def revoke(self, ref: SecretRef) -> None:
        del ref
        raise self._read_only_error()

    @staticmethod
    def _read_only_error() -> SecurityError:
        return SecurityError(
            code="SECRET_PROVIDER_READ_ONLY",
            message="The local environment secret provider is read-only.",
            retryable=False,
            next_action=(
                "Update the environment outside the process and restart with a new version."
            ),
        )
