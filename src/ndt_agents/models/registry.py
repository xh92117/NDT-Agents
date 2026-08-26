"""Immutable model API catalogs and scope-bound provider bindings."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal, NoReturn, Protocol, Self
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel, TenantScope
from ndt_agents.observability.audit import AuditKind, AuditOutcome, AuditRecord
from ndt_agents.security.models import SecretSelector, SecurityEnvironment

MODEL_API_REGISTRY_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class CatalogOrigin(StrEnum):
    APPLICATION = "APPLICATION"
    UNTRUSTED = "UNTRUSTED"


class ApiProtocol(StrEnum):
    OPENAI_CHAT_COMPLETIONS = "OPENAI_CHAT_COMPLETIONS"
    OPENAI_RESPONSES = "OPENAI_RESPONSES"
    ANTHROPIC_MESSAGES = "ANTHROPIC_MESSAGES"


class CredentialScheme(StrEnum):
    BEARER = "BEARER"
    API_KEY_HEADER = "API_KEY_HEADER"


class PolicyVerification(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ModelDataClass(StrEnum):
    PUBLIC = "PUBLIC"
    SYNTHETIC = "SYNTHETIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class ModelCapability(StrEnum):
    TEXT_INPUT = "TEXT_INPUT"
    TEXT_OUTPUT = "TEXT_OUTPUT"
    VISION_INPUT = "VISION_INPUT"
    TOOL_CALLING = "TOOL_CALLING"
    JSON_OUTPUT = "JSON_OUTPUT"
    REASONING = "REASONING"
    STREAMING = "STREAMING"


class ModelLifecycle(StrEnum):
    STABLE = "STABLE"
    EXPERIMENTAL = "EXPERIMENTAL"


class BindingState(StrEnum):
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"


class SelectionSource(StrEnum):
    REQUESTED = "REQUESTED"
    DEFAULT = "DEFAULT"
    FALLBACK = "FALLBACK"


class ProviderEndpoint(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_API_REGISTRY_CONTRACT_VERSION
    endpoint_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    protocol: ApiProtocol
    base_url: str = Field(min_length=1, max_length=2048)
    request_path: str = Field(pattern=r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
    models_path: str | None = Field(default=None, pattern=r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")

    @model_validator(mode="after")
    def validate_url(self) -> Self:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "provider base_url must be a credential-free HTTPS origin or base path"
            )
        return self

    @property
    def request_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.request_path}"


class ProviderDefinition(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_API_REGISTRY_CONTRACT_VERSION
    origin: CatalogOrigin = CatalogOrigin.APPLICATION
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    display_name: str = Field(min_length=1, max_length=128)
    endpoints: tuple[ProviderEndpoint, ...] = Field(min_length=1)
    credential_scheme: CredentialScheme
    credential_header: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9-]{0,127}$")
    credential_purpose: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    allowed_data_classes: frozenset[ModelDataClass] = Field(min_length=1)
    processing_regions: tuple[str, ...] = ()
    processing_region_state: PolicyVerification
    retention_state: PolicyVerification
    training_use_state: PolicyVerification
    commercial_terms_state: PolicyVerification
    production_eligible: bool = False
    metadata_checked_on: date
    official_sources: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if self.origin is not CatalogOrigin.APPLICATION:
            raise ValueError("only application-owned provider definitions are publishable")
        if len({endpoint.endpoint_id for endpoint in self.endpoints}) != len(self.endpoints):
            raise ValueError("provider endpoint IDs must be unique")
        if self.credential_scheme is CredentialScheme.BEARER:
            if self.credential_header is not None:
                raise ValueError("bearer credentials cannot override the authorization header")
        elif self.credential_header is None:
            raise ValueError("API-key header credentials require an exact header name")
        _validate_source_urls(self.official_sources)
        verification = (
            self.processing_region_state,
            self.retention_state,
            self.training_use_state,
            self.commercial_terms_state,
        )
        if self.production_eligible and any(
            state is not PolicyVerification.VERIFIED for state in verification
        ):
            raise ValueError("production eligibility requires verified provider policy metadata")
        return self

    def endpoint(self, endpoint_id: str) -> ProviderEndpoint:
        for endpoint in self.endpoints:
            if endpoint.endpoint_id == endpoint_id:
                return endpoint
        raise ModelRegistryError(
            "MODEL_ENDPOINT_NOT_FOUND",
            "The provider endpoint is not in the published catalog.",
            retryable=False,
            next_action="Use an endpoint from the current provider catalog.",
        )


class ModelDefinition(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_API_REGISTRY_CONTRACT_VERSION
    origin: CatalogOrigin = CatalogOrigin.APPLICATION
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    provider_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    model_snapshot: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    lifecycle: ModelLifecycle
    protocols: frozenset[ApiProtocol] = Field(min_length=1)
    capabilities: frozenset[ModelCapability] = Field(min_length=1)
    context_window_tokens: int = Field(ge=1, le=10_000_000)
    max_output_tokens: int = Field(ge=1, le=1_000_000)
    metadata_checked_on: date
    official_sources: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if self.origin is not CatalogOrigin.APPLICATION:
            raise ValueError("only application-owned model definitions are publishable")
        if ModelCapability.TEXT_OUTPUT not in self.capabilities:
            raise ValueError("a chat model must declare text output capability")
        if self.max_output_tokens > self.context_window_tokens:
            raise ValueError("model output limit cannot exceed its context window")
        _validate_source_urls(self.official_sources)
        return self

    @property
    def key(self) -> str:
        return f"{self.provider_id}:{self.model_id}"


class ModelCatalogManifest(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_API_REGISTRY_CONTRACT_VERSION
    catalog_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    catalog_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    checked_on: date
    providers: tuple[ProviderDefinition, ...] = Field(min_length=1)
    models: tuple[ModelDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        provider_map = {provider.provider_id: provider for provider in self.providers}
        if len(provider_map) != len(self.providers):
            raise ValueError("provider IDs must be unique within a catalog")
        if len({model.key for model in self.models}) != len(self.models):
            raise ValueError("provider and model ID pairs must be unique within a catalog")
        for model in self.models:
            provider = provider_map.get(model.provider_id)
            if provider is None or provider.version != model.provider_version:
                raise ValueError("every model must reference the exact published provider version")
            endpoint_protocols = frozenset(endpoint.protocol for endpoint in provider.endpoints)
            if model.protocols.isdisjoint(endpoint_protocols):
                raise ValueError("every model requires a compatible provider endpoint")
        return self


class ProviderBinding(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_API_REGISTRY_CONTRACT_VERSION
    origin: CatalogOrigin = CatalogOrigin.APPLICATION
    binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    provider_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    environment: SecurityEnvironment
    tenant_id: UUID
    project_id: UUID
    permission_version: str = Field(min_length=1, max_length=128)
    endpoint_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    secret_selector: SecretSelector
    state: BindingState = BindingState.DISABLED
    allowed_model_ids: tuple[str, ...] = Field(min_length=1)
    default_model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    fallback_model_ids: tuple[str, ...] = ()
    allowed_data_classes: frozenset[ModelDataClass] = Field(min_length=1)
    required_permission: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,127}$")
    budget_policy_version: str = Field(min_length=1, max_length=128)
    timeout_ms: int = Field(ge=1, le=3_600_000)
    max_attempts: int = Field(ge=1, le=3)
    max_concurrency: int = Field(ge=1, le=16)
    max_input_tokens: int = Field(ge=1, le=1_000_000)
    max_output_tokens: int = Field(ge=1, le=1_000_000)

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.origin is not CatalogOrigin.APPLICATION:
            raise ValueError("only application-owned provider bindings are publishable")
        if len(set(self.allowed_model_ids)) != len(self.allowed_model_ids):
            raise ValueError("allowed model IDs must be unique")
        if len(set(self.fallback_model_ids)) != len(self.fallback_model_ids):
            raise ValueError("fallback model IDs must be unique")
        if self.default_model_id not in self.allowed_model_ids:
            raise ValueError("default model must be allowed by the binding")
        if self.default_model_id in self.fallback_model_ids or not set(
            self.fallback_model_ids
        ).issubset(self.allowed_model_ids):
            raise ValueError("fallback models must be distinct allowed models")
        selector = self.secret_selector
        if (
            selector.environment is not self.environment
            or selector.tenant_id != self.tenant_id
            or selector.project_id != self.project_id
        ):
            raise ValueError("secret selector must match binding environment, tenant, and project")
        return self

    @property
    def key(self) -> str:
        return f"{self.binding_id}@{self.version}"


class ModelResolutionContext(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_API_REGISTRY_CONTRACT_VERSION
    task_id: UUID
    run_id: UUID
    scope: TenantScope
    environment: SecurityEnvironment
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    policy_version: str = Field(min_length=1, max_length=128)
    expected_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    granted_permissions: frozenset[str] = frozenset()
    allow_network: bool = False


class ModelSelectionRequest(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_API_REGISTRY_CONTRACT_VERSION
    requested_model_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    required_capabilities: frozenset[ModelCapability] = Field(min_length=1)
    data_class: ModelDataClass
    input_tokens: int = Field(ge=1, le=1_000_000)
    output_tokens: int = Field(ge=1, le=1_000_000)
    allow_fallback: bool = True


class ResolvedModelRoute(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_API_REGISTRY_CONTRACT_VERSION
    registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_id: str
    binding_version: str
    provider_id: str
    provider_version: str
    model_id: str
    model_snapshot: str
    endpoint_id: str
    endpoint_url: str
    protocol: ApiProtocol
    credential_scheme: CredentialScheme
    credential_header: str | None = None
    selection_source: SelectionSource
    capabilities: frozenset[ModelCapability]
    secret_selector: SecretSelector
    budget_policy_version: str
    permission_version: str
    timeout_ms: int
    max_attempts: int
    max_concurrency: int
    max_input_tokens: int
    max_output_tokens: int


class ModelRegistryError(RuntimeError):
    """Stable model-registry failure with an operator recovery action."""

    def __init__(self, code: str, message: str, *, retryable: bool, next_action: str) -> None:
        self.code = code
        self.retryable = retryable
        self.next_action = next_action
        super().__init__(message)


class ModelAuditSink(Protocol):
    def record(self, record: AuditRecord) -> object: ...


def canonical_sha256(value: object) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ModelRegistryError(
            "MODEL_PAYLOAD_INVALID",
            "The model-registry payload is not canonical JSON.",
            retryable=False,
            next_action="Provide a strict JSON-compatible registry payload.",
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _validate_source_urls(urls: tuple[str, ...]) -> None:
    for url in urls:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("official source URLs must be credential-free HTTPS URLs")


class ModelApiRegistry:
    """Publish immutable catalogs and authorize reference-only model routes."""

    def __init__(
        self,
        catalog: ModelCatalogManifest,
        bindings: Sequence[ProviderBinding],
        *,
        audit: ModelAuditSink,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        event_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._providers = {provider.provider_id: provider for provider in catalog.providers}
        self._models = {model.key: model for model in catalog.models}
        by_id: dict[str, ProviderBinding] = {}
        for binding in bindings:
            if binding.binding_id in by_id:
                raise ModelRegistryError(
                    "MODEL_BINDING_REJECTED",
                    "The provider binding ID is duplicated.",
                    retryable=False,
                    next_action="Publish one immutable binding version per binding ID.",
                )
            self._validate_binding(binding)
            by_id[binding.binding_id] = binding
        snapshot = {
            "catalog": catalog.model_dump(mode="json"),
            "bindings": [by_id[key].model_dump(mode="json") for key in sorted(by_id)],
        }
        self._catalog = catalog
        self._bindings = by_id
        self._version = canonical_sha256(snapshot)
        self._audit = audit
        self._clock = clock
        self._event_id_factory = event_id_factory

    @property
    def version(self) -> str:
        return self._version

    @property
    def catalog(self) -> ModelCatalogManifest:
        return self._catalog

    @property
    def bindings(self) -> tuple[ProviderBinding, ...]:
        return tuple(self._bindings[key] for key in sorted(self._bindings))

    def resolve(
        self,
        *,
        binding_id: str,
        context: ModelResolutionContext,
        selection: ModelSelectionRequest,
    ) -> ResolvedModelRoute:
        input_sha256 = canonical_sha256(
            {
                "binding_id": binding_id,
                "context": context.model_dump(mode="json"),
                "selection": selection.model_dump(mode="json"),
            }
        )
        target_id = binding_id if _IDENTIFIER.fullmatch(binding_id) else "unresolved"
        try:
            route = self._resolve(binding_id, context, selection)
        except ModelRegistryError as error:
            self._record(
                context=context,
                target_id=target_id,
                decision="DENY",
                outcome=AuditOutcome.DENIED,
                input_sha256=input_sha256,
                output_sha256=canonical_sha256({"error_code": error.code}),
            )
            raise
        self._record(
            context=context,
            target_id=route.binding_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=canonical_sha256(
                {
                    "registry_version": route.registry_version,
                    "provider_id": route.provider_id,
                    "model_id": route.model_id,
                    "model_snapshot": route.model_snapshot,
                }
            ),
        )
        return route

    def _resolve(
        self,
        binding_id: str,
        context: ModelResolutionContext,
        selection: ModelSelectionRequest,
    ) -> ResolvedModelRoute:
        if context.expected_registry_version != self.version:
            self._deny(
                "MODEL_REGISTRY_STALE",
                "The caller model-registry snapshot is stale.",
                "Refresh the published registry snapshot before retrying.",
            )
        binding = self._bindings.get(binding_id)
        if binding is None:
            self._deny(
                "MODEL_BINDING_NOT_FOUND",
                "The provider binding is not published.",
                "Use a binding from the current model-registry snapshot.",
            )
        assert binding is not None
        if binding.state is not BindingState.ENABLED:
            self._deny(
                "MODEL_BINDING_DISABLED",
                "The provider binding is disabled.",
                "Provision its secret reference and explicitly enable an approved binding.",
            )
        scope = context.scope
        if (
            context.environment is not binding.environment
            or scope.tenant_id != binding.tenant_id
            or scope.project_id != binding.project_id
            or scope.permission_version != binding.permission_version
        ):
            self._deny(
                "MODEL_SCOPE_MISMATCH",
                "The model route is outside the authorized environment or scope.",
                "Use the exact environment, tenant, project, and permission version.",
            )
        if not context.allow_network:
            self._deny(
                "MODEL_NETWORK_DENIED",
                "The task does not permit a hosted model call.",
                "Use an offline route or obtain task policy permission for network access.",
            )
        if binding.required_permission not in context.granted_permissions:
            self._deny(
                "MODEL_PERMISSION_DENIED",
                "The task lacks the provider binding permission.",
                "Grant the exact versioned model permission through RBAC.",
            )
        if selection.data_class not in binding.allowed_data_classes:
            self._deny(
                "MODEL_DATA_CLASS_DENIED",
                "The provider binding does not permit this data class.",
                "Use an eligible data class or an independently approved provider route.",
            )
        if (
            selection.input_tokens > binding.max_input_tokens
            or selection.output_tokens > binding.max_output_tokens
        ):
            self._deny(
                "MODEL_TOKEN_LIMIT_EXCEEDED",
                "The requested model input or output exceeds the binding limit.",
                "Reduce the request or use an approved higher bounded policy.",
            )
        model, source = self._select_model(binding, selection)
        provider = self._providers[binding.provider_id]
        endpoint = provider.endpoint(binding.endpoint_id)
        return ResolvedModelRoute(
            registry_version=self.version,
            binding_id=binding.binding_id,
            binding_version=binding.version,
            provider_id=provider.provider_id,
            provider_version=provider.version,
            model_id=model.model_id,
            model_snapshot=model.model_snapshot,
            endpoint_id=endpoint.endpoint_id,
            endpoint_url=endpoint.request_url,
            protocol=endpoint.protocol,
            credential_scheme=provider.credential_scheme,
            credential_header=provider.credential_header,
            selection_source=source,
            capabilities=model.capabilities,
            secret_selector=binding.secret_selector,
            budget_policy_version=binding.budget_policy_version,
            permission_version=binding.permission_version,
            timeout_ms=binding.timeout_ms,
            max_attempts=binding.max_attempts,
            max_concurrency=binding.max_concurrency,
            max_input_tokens=binding.max_input_tokens,
            max_output_tokens=binding.max_output_tokens,
        )

    def _select_model(
        self, binding: ProviderBinding, selection: ModelSelectionRequest
    ) -> tuple[ModelDefinition, SelectionSource]:
        if selection.requested_model_id is not None:
            if selection.requested_model_id not in binding.allowed_model_ids:
                self._deny(
                    "MODEL_SELECTION_DENIED",
                    "The requested model is not allowed by the provider binding.",
                    "Use an allowed model ID from the current binding.",
                )
            candidates: tuple[tuple[str, SelectionSource], ...] = (
                (selection.requested_model_id, SelectionSource.REQUESTED),
            )
        else:
            candidates = ((binding.default_model_id, SelectionSource.DEFAULT),)
            if selection.allow_fallback:
                candidates += tuple(
                    (model_id, SelectionSource.FALLBACK) for model_id in binding.fallback_model_ids
                )
        for model_id, source in candidates:
            model = self._models[f"{binding.provider_id}:{model_id}"]
            if selection.required_capabilities.issubset(model.capabilities):
                return model, source
        self._deny(
            "MODEL_CAPABILITY_UNAVAILABLE",
            "No allowed model satisfies the requested capabilities.",
            "Change the capability request or publish an approved compatible model binding.",
        )

    def _validate_binding(self, binding: ProviderBinding) -> None:
        if binding.origin is not CatalogOrigin.APPLICATION:
            raise ModelRegistryError(
                "MODEL_BINDING_REJECTED",
                "The provider binding is not application-owned.",
                retryable=False,
                next_action="Publish only validated application-owned bindings.",
            )
        provider = self._providers.get(binding.provider_id)
        if provider is None or provider.version != binding.provider_version:
            raise ModelRegistryError(
                "MODEL_BINDING_REJECTED",
                "The binding references an unknown provider version.",
                retryable=False,
                next_action="Bind the exact provider version from the current catalog.",
            )
        endpoint = provider.endpoint(binding.endpoint_id)
        if binding.secret_selector.purpose != provider.credential_purpose:
            raise ModelRegistryError(
                "MODEL_BINDING_REJECTED",
                "The secret selector purpose does not match the provider contract.",
                retryable=False,
                next_action="Use the provider's exact scoped credential purpose.",
            )
        if not binding.allowed_data_classes.issubset(provider.allowed_data_classes):
            raise ModelRegistryError(
                "MODEL_BINDING_REJECTED",
                "The binding expands the provider data-class policy.",
                retryable=False,
                next_action="Restrict the binding to provider-approved data classes.",
            )
        if (
            binding.state is BindingState.ENABLED
            and binding.environment is SecurityEnvironment.PRODUCTION
            and not provider.production_eligible
        ):
            raise ModelRegistryError(
                "MODEL_PROVIDER_PRODUCTION_INELIGIBLE",
                "The provider metadata is not eligible for production.",
                retryable=False,
                next_action="Verify regional, retention, training, commercial, and security terms.",
            )
        for model_id in binding.allowed_model_ids:
            model = self._models.get(f"{binding.provider_id}:{model_id}")
            if model is None or model.provider_version != binding.provider_version:
                raise ModelRegistryError(
                    "MODEL_BINDING_REJECTED",
                    "The binding references an unknown model version.",
                    retryable=False,
                    next_action="Use exact model IDs from the current provider catalog.",
                )
            if endpoint.protocol not in model.protocols:
                raise ModelRegistryError(
                    "MODEL_BINDING_REJECTED",
                    "The model does not support the selected endpoint protocol.",
                    retryable=False,
                    next_action="Select a compatible endpoint or model.",
                )
            if (
                binding.max_input_tokens > model.context_window_tokens
                or binding.max_output_tokens > model.max_output_tokens
            ):
                raise ModelRegistryError(
                    "MODEL_BINDING_REJECTED",
                    "The binding token limits exceed a selected model limit.",
                    retryable=False,
                    next_action="Lower binding token limits to every allowed model's bounds.",
                )

    def _record(
        self,
        *,
        context: ModelResolutionContext,
        target_id: str,
        decision: str,
        outcome: AuditOutcome,
        input_sha256: str,
        output_sha256: str,
    ) -> None:
        self._audit.record(
            AuditRecord(
                event_id=self._event_id_factory(),
                scope=context.scope,
                kind=AuditKind.MODEL,
                action="model.route.resolve",
                target_type="model.binding",
                target_id=target_id,
                task_id=context.task_id,
                policy_version=context.policy_version,
                decision=decision,
                outcome=outcome,
                input_sha256=input_sha256,
                output_sha256=output_sha256,
                request_id=context.request_id,
                occurred_at=self._clock(),
            )
        )

    @staticmethod
    def _deny(code: str, message: str, next_action: str) -> NoReturn:
        raise ModelRegistryError(code, message, retryable=False, next_action=next_action)
