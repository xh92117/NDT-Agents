"""Strict local YAML/environment bootstrap for model catalogs and provider bindings."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from pydantic import Field, ValidationError, model_validator
from yaml.tokens import AliasToken, AnchorToken

from ndt_agents.contracts.v1 import StrictModel
from ndt_agents.models.registry import (
    BindingState,
    ModelApiRegistry,
    ModelAuditSink,
    ModelCatalogManifest,
    ModelDataClass,
    ModelRegistryError,
    ProviderBinding,
    canonical_sha256,
)
from ndt_agents.observability.audit import AuditRecord
from ndt_agents.security.environment import EnvironmentSecretBinding, EnvironmentSecretProvider
from ndt_agents.security.models import SecretSelector, SecurityEnvironment, SecurityError

MODEL_RUNTIME_CONFIG_VERSION: Literal["1.0.0"] = "1.0.0"
_MAX_CONFIG_BYTES = 256 * 1024
_MAX_CATALOG_BYTES = 2 * 1024 * 1024
_MAX_ENV_BYTES = 64 * 1024
_ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class ModelConfigurationError(RuntimeError):
    """Stable non-disclosing configuration failure with an operator action."""

    def __init__(self, code: str, message: str, *, next_action: str) -> None:
        self.code = code
        self.retryable = False
        self.next_action = next_action
        super().__init__(message)


class EnvironmentSecretSource(StrictModel):
    source: Literal["ENVIRONMENT"] = "ENVIRONMENT"
    variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    secret_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,127}$")
    purpose: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")


class ModelBindingConfiguration(StrictModel):
    binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    provider_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    environment: SecurityEnvironment
    tenant_id: UUID
    project_id: UUID
    permission_version: str = Field(min_length=1, max_length=128)
    endpoint_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    state: BindingState = BindingState.DISABLED
    allowed_model_ids: tuple[str, ...] = Field(min_length=1)
    default_model_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    fallback_model_ids: tuple[str, ...] = ()
    allowed_data_classes: frozenset[ModelDataClass] = Field(min_length=1)
    required_permission: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,127}$")
    budget_policy_version: str = Field(min_length=1, max_length=128)
    timeout_ms: int = Field(ge=1, le=3_600_000)
    max_attempts: int = Field(ge=1, le=3)
    max_concurrency: int = Field(ge=1, le=16)
    max_input_tokens: int = Field(ge=1, le=1_000_000)
    max_output_tokens: int = Field(ge=1, le=1_000_000)
    secret: EnvironmentSecretSource

    def binding(self) -> ProviderBinding:
        values = self.model_dump(exclude={"secret"})
        return ProviderBinding(
            **values,
            secret_selector=SecretSelector(
                secret_id=self.secret.secret_id,
                environment=self.environment,
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                purpose=self.secret.purpose,
            ),
        )


class ModelRuntimeConfigurationDocument(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_RUNTIME_CONFIG_VERSION
    config_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    catalogs: tuple[str, ...] = Field(min_length=1, max_length=32)
    bindings: tuple[ModelBindingConfiguration, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_uniqueness(self) -> ModelRuntimeConfigurationDocument:
        if len(set(self.catalogs)) != len(self.catalogs):
            raise ValueError("catalog paths must be unique")
        binding_ids = [binding.binding_id for binding in self.bindings]
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError("binding IDs must be unique")
        variables = [binding.secret.variable for binding in self.bindings]
        if len(set(variables)) != len(variables):
            raise ValueError("secret environment variables must be unique")
        return self


class ModelRuntimeStatus(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_RUNTIME_CONFIG_VERSION
    state: Literal["CONFIGURED"] = "CONFIGURED"
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalogs: int = Field(ge=1)
    bindings: int = Field(ge=1)
    enabled_bindings: int = Field(ge=0)
    provisioned_secrets: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class ConfiguredModelRuntime:
    source_path: Path
    catalog: ModelCatalogManifest
    bindings: tuple[ProviderBinding, ...]
    configuration_sha256: str
    registry_version: str
    status: ModelRuntimeStatus
    secret_provider: EnvironmentSecretProvider = field(repr=False)

    def build_registry(self, audit: ModelAuditSink) -> ModelApiRegistry:
        return ModelApiRegistry(self.catalog, self.bindings, audit=audit)


class _ValidationAudit:
    def record(self, record: AuditRecord) -> object:
        del record
        raise AssertionError("registry publication validation emitted an audit event")


def _configuration_error(code: str, message: str, next_action: str) -> ModelConfigurationError:
    return ModelConfigurationError(code, message, next_action=next_action)


def _read_bounded_utf8(path: Path, *, limit: int, kind: str) -> tuple[bytes, str]:
    try:
        raw = path.read_bytes()
    except OSError:
        raise _configuration_error(
            f"{kind}_NOT_FOUND",
            "A required model configuration file could not be read.",
            "Verify the explicit path and local read permission.",
        ) from None
    if len(raw) > limit:
        raise _configuration_error(
            f"{kind}_TOO_LARGE",
            "A model configuration file exceeds its byte limit.",
            "Reduce the file to the documented bounded configuration size.",
        )
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _configuration_error(
            f"{kind}_ENCODING_INVALID",
            "A model configuration file uses a forbidden byte-order mark.",
            "Save the file as UTF-8 without BOM.",
        )
    try:
        return raw, raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _configuration_error(
            f"{kind}_ENCODING_INVALID",
            "A model configuration file is not valid UTF-8.",
            "Save the file as validated UTF-8 without lossy replacement.",
        ) from None


def _parse_document(path: Path) -> ModelRuntimeConfigurationDocument:
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise _configuration_error(
            "MODEL_CONFIG_EXTENSION_INVALID",
            "The model configuration must use a YAML filename.",
            "Select an explicit .yaml or .yml model configuration file.",
        )
    _raw, text = _read_bounded_utf8(path, limit=_MAX_CONFIG_BYTES, kind="MODEL_CONFIG")
    try:
        tokens = yaml.scan(text)
        if any(isinstance(token, (AliasToken, AnchorToken)) for token in tokens):
            raise ValueError("YAML aliases are not permitted")
        payload: Any = yaml.safe_load(text)
        return ModelRuntimeConfigurationDocument.model_validate(payload)
    except (ValueError, TypeError, yaml.YAMLError, ValidationError):
        raise _configuration_error(
            "MODEL_CONFIG_INVALID",
            "The model YAML configuration is malformed or violates its strict schema.",
            "Correct the non-secret YAML using the versioned example and retry.",
        ) from None


def _load_catalogs(
    document: ModelRuntimeConfigurationDocument,
    config_path: Path,
) -> tuple[ModelCatalogManifest, tuple[dict[str, str], ...]]:
    allowed_root = config_path.parent.parent.resolve()
    catalogs: list[ModelCatalogManifest] = []
    evidence: list[dict[str, str]] = []
    for relative in document.catalogs:
        path_value = Path(relative)
        if path_value.is_absolute():
            raise _configuration_error(
                "MODEL_CATALOG_PATH_DENIED",
                "An absolute model catalog path is not allowed.",
                "Use a relative catalog path inside the configuration root.",
            )
        candidate = (config_path.parent / path_value).resolve()
        if not candidate.is_relative_to(allowed_root):
            raise _configuration_error(
                "MODEL_CATALOG_PATH_DENIED",
                "A model catalog path leaves the configuration root.",
                "Keep catalog files inside the bounded configuration root.",
            )
        raw, text = _read_bounded_utf8(candidate, limit=_MAX_CATALOG_BYTES, kind="MODEL_CATALOG")
        try:
            catalog = ModelCatalogManifest.model_validate_json(text)
        except (ValueError, ValidationError):
            raise _configuration_error(
                "MODEL_CATALOG_INVALID",
                "A selected model catalog violates the strict catalog contract.",
                "Replace it with a validated application-owned catalog version.",
            ) from None
        catalogs.append(catalog)
        evidence.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if len(catalogs) == 1:
        return catalogs[0], tuple(evidence)
    combined = ModelCatalogManifest(
        catalog_id="runtime-composite",
        catalog_version=document.config_version,
        checked_on=max(catalog.checked_on for catalog in catalogs),
        providers=tuple(provider for catalog in catalogs for provider in catalog.providers),
        models=tuple(model for catalog in catalogs for model in catalog.models),
    )
    return combined, tuple(evidence)


def _parse_environment_file(path: Path, wanted: frozenset[str]) -> dict[str, str]:
    _raw, text = _read_bounded_utf8(path, limit=_MAX_ENV_BYTES, kind="MODEL_ENV")
    selected: dict[str, str] = {}
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export ") or "=" not in stripped:
            raise _configuration_error(
                "MODEL_ENV_INVALID",
                "The local environment file contains unsupported shell syntax.",
                "Use one literal NAME=VALUE assignment per line without shell expansion.",
            )
        name, raw_value = stripped.split("=", maxsplit=1)
        if _ENVIRONMENT_NAME.fullmatch(name) is None:
            raise _configuration_error(
                "MODEL_ENV_INVALID",
                "The local environment file contains an invalid variable name.",
                "Use uppercase ASCII environment variable names.",
            )
        if name in seen:
            raise _configuration_error(
                "MODEL_ENV_DUPLICATE",
                "The local environment file contains a duplicate variable.",
                "Keep one literal assignment for each environment variable.",
            )
        seen.add(name)
        value = raw_value.strip()
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise _configuration_error(
                    "MODEL_ENV_INVALID",
                    "The local environment file contains an invalid quoted value.",
                    "Use one matching pair of quotes without shell expansion.",
                )
            value = value[1:-1]
        if "\x00" in value or len(value) > 16_384:
            raise _configuration_error(
                "MODEL_ENV_INVALID",
                "The local environment file contains an invalid bounded value.",
                "Use a non-empty bounded literal secret value.",
            )
        if name in wanted:
            selected[name] = value
    return selected


def load_model_runtime_configuration(
    config_path: str | Path,
    *,
    env_file_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    expected_environment: SecurityEnvironment | None = None,
) -> ConfiguredModelRuntime:
    """Load strict non-secret config and retain only explicitly referenced local secret values."""

    source_path = Path(config_path).expanduser().resolve()
    document = _parse_document(source_path)
    catalog, catalog_evidence = _load_catalogs(document, source_path)
    binding_pairs = tuple((item, item.binding()) for item in document.bindings)
    bindings = tuple(sorted((pair[1] for pair in binding_pairs), key=lambda item: item.binding_id))
    for _item, binding in binding_pairs:
        if binding.environment in {
            SecurityEnvironment.STAGING,
            SecurityEnvironment.PRODUCTION,
        }:
            raise _configuration_error(
                "MODEL_ENV_SECRET_PRODUCTION_DENIED",
                "Environment-file model secrets are not allowed in managed environments.",
                "Use an approved managed secret provider for staging or production.",
            )
        if expected_environment is not None and binding.environment is not expected_environment:
            raise _configuration_error(
                "MODEL_CONFIG_ENVIRONMENT_MISMATCH",
                "A model binding environment differs from the application environment.",
                "Use bindings for the exact active application environment.",
            )
    try:
        published = ModelApiRegistry(catalog, bindings, audit=_ValidationAudit())
    except ModelRegistryError:
        raise _configuration_error(
            "MODEL_CONFIG_INVALID",
            "The model catalogs and bindings cannot form a valid registry snapshot.",
            "Correct provider, model, endpoint, scope, policy, and limit references.",
        ) from None

    wanted = frozenset(item.secret.variable for item in document.bindings)
    file_values: dict[str, str] = {}
    if env_file_path is not None:
        file_values = _parse_environment_file(Path(env_file_path).expanduser().resolve(), wanted)
    process_environment = os.environ if environ is None else environ
    selected_values = dict(file_values)
    for variable in wanted:
        if variable in process_environment:
            selected_values[variable] = process_environment[variable]

    secret_bindings: list[EnvironmentSecretBinding] = []
    for item, binding in binding_pairs:
        raw_value = selected_values.get(item.secret.variable)
        if binding.state is BindingState.ENABLED and not raw_value:
            raise _configuration_error(
                "MODEL_CONFIG_SECRET_MISSING",
                "An enabled model binding has no provisioned local secret.",
                "Set its referenced variable in the process environment or ignored local env file.",
            )
        if raw_value:
            secret_bindings.append(
                EnvironmentSecretBinding(
                    selector=binding.secret_selector,
                    variable_name=item.secret.variable,
                    version=item.secret.version,
                )
            )
    try:
        secret_provider = EnvironmentSecretProvider(secret_bindings, selected_values)
    except SecurityError as error:
        raise _configuration_error(
            "MODEL_CONFIG_SECRET_INVALID",
            "A referenced local model secret could not be provisioned safely.",
            error.next_action,
        ) from None

    configuration_sha256 = canonical_sha256(
        {
            "document": document.model_dump(mode="json"),
            "catalogs": catalog_evidence,
        }
    )
    status = ModelRuntimeStatus(
        configuration_sha256=configuration_sha256,
        registry_version=published.version,
        catalogs=len(document.catalogs),
        bindings=len(bindings),
        enabled_bindings=sum(binding.state is BindingState.ENABLED for binding in bindings),
        provisioned_secrets=len(secret_bindings),
    )
    return ConfiguredModelRuntime(
        source_path=source_path,
        catalog=catalog,
        bindings=bindings,
        configuration_sha256=configuration_sha256,
        registry_version=published.version,
        status=status,
        secret_provider=secret_provider,
    )
