"""S5-07 provider-neutral model API registry and DeepSeek catalog tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.models import (
    BindingState,
    ModelApiRegistry,
    ModelCapability,
    ModelCatalogManifest,
    ModelDataClass,
    ModelRegistryError,
    ModelResolutionContext,
    ModelSelectionRequest,
    ProviderBinding,
)
from ndt_agents.observability import (
    AuditKind,
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.security import SecretSelector, SecurityEnvironment

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "config" / "model-providers" / "deepseek-v4.v1.json"
SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("MODEL_USER",),
    permission_version="permissions-1",
)
OTHER_SCOPE = SCOPE.model_copy(update={"project_id": UUID("00000000-0000-4000-8000-000000000202")})
TASK_ID = UUID("00000000-0000-4000-8000-000000000301")
RUN_ID = UUID("00000000-0000-4000-8000-000000000302")


def load_catalog() -> ModelCatalogManifest:
    return ModelCatalogManifest.model_validate_json(CATALOG_PATH.read_text(encoding="utf-8"))


def binding(
    *,
    state: BindingState = BindingState.ENABLED,
    scope: TenantScope = SCOPE,
    environment: SecurityEnvironment = SecurityEnvironment.LOCAL,
    binding_id: str = "personal-deepseek",
    secret_id: str = "deepseek-api-key",
    default_model_id: str = "deepseek-v4-pro",
    fallback_model_ids: tuple[str, ...] = ("deepseek-v4-flash",),
) -> ProviderBinding:
    selector = SecretSelector(
        secret_id=secret_id,
        environment=environment,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        purpose="model.deepseek.credential",
    )
    return ProviderBinding(
        binding_id=binding_id,
        version="1.0.0",
        provider_id="deepseek",
        provider_version="1.0.0",
        environment=environment,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        permission_version=scope.permission_version,
        endpoint_id="openai-chat",
        secret_selector=selector,
        state=state,
        allowed_model_ids=("deepseek-v4-pro", "deepseek-v4-flash"),
        default_model_id=default_model_id,
        fallback_model_ids=fallback_model_ids,
        allowed_data_classes=frozenset({ModelDataClass.PUBLIC, ModelDataClass.SYNTHETIC}),
        required_permission="model.invoke.deepseek",
        budget_policy_version="budget-policy-1.0.0",
        timeout_ms=120_000,
        max_attempts=2,
        max_concurrency=1,
        max_input_tokens=120_000,
        max_output_tokens=60_000,
    )


class Runtime:
    def __init__(self, *, route: ProviderBinding | None = None) -> None:
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="model-registry-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.repository = InMemoryAuditRepository()
        event_ids = iter(UUID(int=value) for value in range(1, 1000))
        self.registry = ModelApiRegistry(
            load_catalog(),
            (route or binding(),),
            audit=AuditService(self.repository, self.traces),
            clock=lambda: datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
            event_id_factory=event_ids.__next__,
        )

    def context(self, **updates: Any) -> ModelResolutionContext:
        values: dict[str, Any] = {
            "task_id": TASK_ID,
            "run_id": RUN_ID,
            "scope": SCOPE,
            "environment": SecurityEnvironment.LOCAL,
            "request_id": "model-request-1",
            "policy_version": "model-policy-1",
            "expected_registry_version": self.registry.version,
            "granted_permissions": frozenset({"model.invoke.deepseek"}),
            "allow_network": True,
        }
        values.update(updates)
        return ModelResolutionContext(**values)

    def select(self, **updates: Any) -> ModelSelectionRequest:
        values: dict[str, Any] = {
            "data_class": ModelDataClass.SYNTHETIC,
            "required_capabilities": frozenset({ModelCapability.TEXT_OUTPUT}),
            "input_tokens": 10_000,
            "output_tokens": 4_000,
        }
        values.update(updates)
        return ModelSelectionRequest(**values)

    def close(self) -> None:
        self.traces.shutdown()


def test_deepseek_catalog_is_official_non_secret_and_strict() -> None:
    raw = CATALOG_PATH.read_text(encoding="utf-8")
    catalog = load_catalog()
    assert {model.model_id for model in catalog.models} == {
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
        "deepseek-v4-pro",
    }
    provider = catalog.providers[0]
    assert provider.endpoint("openai-chat").base_url == "https://api.deepseek.com"
    assert provider.production_eligible is False
    assert provider.allowed_data_classes == frozenset(
        {ModelDataClass.PUBLIC, ModelDataClass.SYNTHETIC}
    )
    lowered = raw.lower()
    assert 'api_key"' not in lowered
    assert "secret_value" not in lowered
    assert "sk-" not in lowered

    payload = catalog.model_dump(mode="json")
    payload["unknown"] = True
    with pytest.raises(ValidationError):
        ModelCatalogManifest.model_validate(payload)

    payload = catalog.model_dump(mode="json")
    payload["providers"][0]["official_sources"] = ("https://example.com/?token=forbidden",)
    with pytest.raises(ValidationError):
        ModelCatalogManifest.model_validate(payload)


def test_registry_publication_is_deterministic_and_rejects_duplicates() -> None:
    first = Runtime()
    second = Runtime()
    try:
        assert first.registry.version == second.registry.version
        with pytest.raises(ModelRegistryError) as captured:
            ModelApiRegistry(
                load_catalog(),
                (binding(), binding()),
                audit=AuditService(first.repository, first.traces),
            )
        assert captured.value.code == "MODEL_BINDING_REJECTED"
    finally:
        first.close()
        second.close()


def test_multiple_api_bindings_are_order_independent_and_resolve_separately() -> None:
    runtime = Runtime()
    primary = binding()
    secondary = binding(
        binding_id="backup-deepseek",
        secret_id="deepseek-backup-key",
        default_model_id="deepseek-v4-flash",
        fallback_model_ids=("deepseek-v4-pro",),
    )
    event_ids = iter(UUID(int=value) for value in range(1001, 2000))
    first = ModelApiRegistry(
        load_catalog(),
        (primary, secondary),
        audit=AuditService(runtime.repository, runtime.traces),
        clock=lambda: datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
        event_id_factory=event_ids.__next__,
    )
    second = ModelApiRegistry(
        load_catalog(),
        (secondary, primary),
        audit=AuditService(runtime.repository, runtime.traces),
    )
    try:
        assert first.version == second.version
        context = runtime.context(expected_registry_version=first.version)
        with runtime.traces.start_span("model.resolve"):
            route = first.resolve(
                binding_id="backup-deepseek",
                context=context,
                selection=runtime.select(),
            )
        assert route.model_id == "deepseek-v4-flash"
        assert route.secret_selector.secret_id == "deepseek-backup-key"
        assert route.credential_scheme.value == "BEARER"
        assert route.credential_header is None
    finally:
        runtime.close()


def test_binding_requires_exact_secret_reference_scope_and_purpose() -> None:
    payload = binding().model_dump()
    payload["secret_selector"] = {
        **payload["secret_selector"],
        "project_id": OTHER_SCOPE.project_id,
    }
    with pytest.raises(ValidationError):
        ProviderBinding.model_validate(payload)

    payload = binding().model_dump()
    payload["secret_selector"] = {**payload["secret_selector"], "value": "plaintext"}
    with pytest.raises(ValidationError):
        ProviderBinding.model_validate(payload)


def test_default_route_is_pro_with_reference_only_credentials_and_audit() -> None:
    runtime = Runtime()
    try:
        with runtime.traces.start_span("model.resolve"):
            route = runtime.registry.resolve(
                binding_id="personal-deepseek",
                context=runtime.context(),
                selection=runtime.select(),
            )
        assert route.model_id == "deepseek-v4-pro"
        assert route.endpoint_url == "https://api.deepseek.com/chat/completions"
        assert route.secret_selector.secret_id == "deepseek-api-key"
        serialized = route.model_dump_json()
        assert "secret_selector" in serialized
        assert "plaintext" not in serialized
        events = runtime.repository.list(SCOPE)
        assert len(events) == 1
        assert events[0].kind is AuditKind.MODEL
        assert events[0].decision == "ALLOW"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("context_updates", "selection_updates", "code"),
    [
        ({"expected_registry_version": "0" * 64}, {}, "MODEL_REGISTRY_STALE"),
        ({"scope": OTHER_SCOPE}, {}, "MODEL_SCOPE_MISMATCH"),
        ({"allow_network": False}, {}, "MODEL_NETWORK_DENIED"),
        ({"granted_permissions": frozenset()}, {}, "MODEL_PERMISSION_DENIED"),
        ({}, {"data_class": ModelDataClass.CONFIDENTIAL}, "MODEL_DATA_CLASS_DENIED"),
        ({}, {"output_tokens": 60_001}, "MODEL_TOKEN_LIMIT_EXCEEDED"),
    ],
)
def test_resolution_denies_unsafe_context_with_one_audit_event(
    context_updates: dict[str, Any], selection_updates: dict[str, Any], code: str
) -> None:
    runtime = Runtime()
    try:
        with runtime.traces.start_span("model.resolve"):
            with pytest.raises(ModelRegistryError) as captured:
                runtime.registry.resolve(
                    binding_id="personal-deepseek",
                    context=runtime.context(**context_updates),
                    selection=runtime.select(**selection_updates),
                )
        assert captured.value.code == code
        assert captured.value.next_action
        events = runtime.repository.list(context_updates.get("scope", SCOPE))
        assert len(events) == 1
        assert events[0].kind is AuditKind.MODEL
        assert events[0].decision == "DENY"
    finally:
        runtime.close()


def test_disabled_and_unknown_capability_routes_are_typed_failures() -> None:
    disabled = Runtime(route=binding(state=BindingState.DISABLED))
    unsupported = Runtime()
    try:
        with disabled.traces.start_span("model.resolve"):
            with pytest.raises(ModelRegistryError) as captured:
                disabled.registry.resolve(
                    binding_id="personal-deepseek",
                    context=disabled.context(),
                    selection=disabled.select(),
                )
        assert captured.value.code == "MODEL_BINDING_DISABLED"

        with unsupported.traces.start_span("model.resolve"):
            with pytest.raises(ModelRegistryError) as captured:
                unsupported.registry.resolve(
                    binding_id="personal-deepseek",
                    context=unsupported.context(),
                    selection=unsupported.select(
                        required_capabilities=frozenset({ModelCapability.VISION_INPUT})
                    ),
                )
        assert captured.value.code == "MODEL_CAPABILITY_UNAVAILABLE"
    finally:
        disabled.close()
        unsupported.close()


def test_unverified_provider_cannot_publish_enabled_production_binding() -> None:
    production = binding(environment=SecurityEnvironment.PRODUCTION)
    runtime = Runtime()
    try:
        with pytest.raises(ModelRegistryError) as captured:
            ModelApiRegistry(
                load_catalog(),
                (production,),
                audit=AuditService(runtime.repository, runtime.traces),
            )
        assert captured.value.code == "MODEL_PROVIDER_PRODUCTION_INELIGIBLE"
    finally:
        runtime.close()


def test_catalog_json_contains_no_credential_fields_recursively() -> None:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    forbidden = {"api_key", "authorization", "password", "secret", "token"}

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(key.lower() for key in value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
