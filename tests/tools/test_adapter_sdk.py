"""S5-05 adapter transport, registry, result, and evidence contract tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from ndt_agents.contracts.v1 import (
    ArtifactRef,
    DataClassification,
    TenantScope,
    ToolStatus,
)
from ndt_agents.observability import (
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.tools import (
    AdapterCapabilityFamily,
    AdapterEvidence,
    AdapterOrigin,
    AdapterOutputEnvelope,
    AdapterProviderError,
    AdapterProviderReply,
    AdapterProviderStatus,
    AdapterRegistration,
    AdapterTransportBinding,
    IdempotencyPolicy,
    NetworkPolicy,
    RegisteredAdapter,
    SideEffectClass,
    ToolDataDestination,
    ToolDataScope,
    ToolInvocationContext,
    ToolKind,
    ToolRecoveryPolicy,
    ToolRegistry,
    ToolRegistryError,
    ToolTransport,
    adapter_evidence_sha256,
    adapter_registration_sha256,
    adapter_tool_definition,
    adapter_transport_binding_sha256,
    tool_approval_binding_sha256,
)
from ndt_agents.tools.adapter_sdk import _canonicalize_adapter_registration_sets
from ndt_agents.tools.registry import canonical_sha256

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000801"),
    project_id=UUID("00000000-0000-4000-8000-000000000802"),
    user_id=UUID("00000000-0000-4000-8000-000000000803"),
    role_codes=("ADAPTER_USER",),
    permission_version="permissions-1",
)
TASK_ID = UUID("00000000-0000-4000-8000-000000000811")
RUN_ID = UUID("00000000-0000-4000-8000-000000000812")
NOW = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"measurement": {"type": "number"}},
    "required": ["measurement"],
    "additionalProperties": False,
}


_BINDING_FIELDS: dict[ToolTransport, dict[str, Any]] = {
    ToolTransport.BASH: {
        "command_id": "instrument.read",
        "executable_sha256": "1" * 64,
    },
    ToolTransport.HTTP_API: {"base_url": "https://instrument.example.test/v1"},
    ToolTransport.SDK: {
        "package_name": "fixture.sdk",
        "package_version": "1.2.3",
        "package_sha256": "2" * 64,
        "entry_point": "fixture.sdk:execute",
    },
    ToolTransport.DLL: {
        "library_id": "fixture.dll",
        "library_version": "2.0.0",
        "library_sha256": "3" * 64,
        "entry_point": "FixtureExecute",
    },
    ToolTransport.FILE_EXCHANGE: {
        "exchange_root_id": "instrument.exchange",
        "exchange_media_type": "application/json",
    },
    ToolTransport.MCP: {
        "mcp_server_registration_sha256": "4" * 64,
        "mcp_namespace": "fixture.instrument",
    },
    ToolTransport.SIMULATOR: {
        "simulator_id": "fixture.simulator",
        "simulator_version": "1.0.0",
        "simulator_fixture_sha256": "5" * 64,
    },
}


def binding(transport: ToolTransport = ToolTransport.HTTP_API, **updates: Any) -> Any:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "transport": transport,
        **_BINDING_FIELDS[transport],
    }
    values.update(updates)
    draft = AdapterTransportBinding.model_construct(**values, binding_sha256="0" * 64)
    values["binding_sha256"] = adapter_transport_binding_sha256(draft)
    return AdapterTransportBinding.model_validate(values)


def registration(
    *,
    selected_binding: AdapterTransportBinding | None = None,
    family: AdapterCapabilityFamily = AdapterCapabilityFamily.INSTRUMENT,
    **updates: Any,
) -> Any:
    transport_binding = selected_binding or binding()
    local = transport_binding.transport in {
        ToolTransport.BASH,
        ToolTransport.DLL,
        ToolTransport.FILE_EXCHANGE,
        ToolTransport.SIMULATOR,
    }
    simulated = transport_binding.transport is ToolTransport.SIMULATOR
    model = family is AdapterCapabilityFamily.AI_MODEL
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "adapter_id": "fixture.adapter",
        "adapter_version": "1.0.0",
        "capability_family": family,
        "origin": AdapterOrigin.SIMULATED if simulated else AdapterOrigin.LABORATORY,
        "purpose": "Read one deterministic fixture measurement.",
        "operation": "measure",
        "binding": transport_binding,
        "data_scope": ToolDataScope.TASK,
        "data_destination": (
            ToolDataDestination.LOCAL
            if local
            else ToolDataDestination.APPROVED_EXTERNAL
            if transport_binding.transport is ToolTransport.HTTP_API
            else ToolDataDestination.LOCAL
        ),
        "side_effect": SideEffectClass.READ_ONLY,
        "input_schema": INPUT_SCHEMA,
        "output_schema": OUTPUT_SCHEMA,
        "required_permissions": frozenset({"adapter.measure"}),
        "secret_purposes": (
            frozenset({"adapter.fixture"})
            if transport_binding.transport is ToolTransport.HTTP_API
            else frozenset()
        ),
        "network": (
            NetworkPolicy.RESTRICTED
            if transport_binding.transport is ToolTransport.HTTP_API
            else NetworkPolicy.NONE
        ),
        "approval_required": False,
        "idempotency": IdempotencyPolicy.NONE,
        "timeout_ms": 100,
        "max_attempts": 2,
        "max_concurrency": 3,
        "max_input_bytes": 10_000,
        "max_output_bytes": 10_000,
        "max_tokens": 1_000 if model else 0,
        "recovery_policy": ToolRecoveryPolicy.RETRY_READ_ONLY,
        "requires_device_identity": not model,
        "requires_calibration": False,
        "requires_model_identity": model,
        "declared_error_codes": frozenset({"FIXTURE_FAILURE", "FIXTURE_PARTIAL"}),
        "audit_owner": "adapter-runtime",
        "test_owner": "adapter-runtime",
    }
    values.update(updates)
    draft = AdapterRegistration.model_construct(**values, registration_sha256="0" * 64)
    values["registration_sha256"] = adapter_registration_sha256(draft)
    return AdapterRegistration.model_validate(values)


def result_artifact(
    *,
    scope: TenantScope = SCOPE,
    immutable: bool = True,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=UUID("00000000-0000-4000-8000-000000000890"),
        scope=scope,
        artifact_version="1",
        uri="artifact://adapter/result-1",
        media_type="application/json",
        size_bytes=128,
        sha256="a" * 64,
        classification=DataClassification.INTERNAL,
        immutable=immutable,
    )


class FakeProvider:
    def __init__(
        self,
        selected_registration: AdapterRegistration,
        *,
        reply_updates: dict[str, Any] | None = None,
        error: AdapterProviderError | None = None,
        generic_failure: bool = False,
        delay: float = 0,
    ) -> None:
        self.registration = selected_registration
        self.reply_updates = reply_updates or {}
        self.error = error
        self.generic_failure = generic_failure
        self.delay = delay
        self.calls: list[Any] = []

    async def execute(self, request: Any) -> Any:
        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        if self.generic_failure:
            raise RuntimeError("provider internals must not cross the adapter boundary")
        status = self.reply_updates.get("status", AdapterProviderStatus.SUCCESS)
        values: dict[str, Any] = {
            "adapter_id": self.registration.adapter_id,
            "adapter_version": self.registration.adapter_version,
            "registration_sha256": self.registration.registration_sha256,
            "request_sha256": request.request_sha256,
            "status": status,
            "output": (
                {"measurement": 12.5}
                if status in {AdapterProviderStatus.SUCCESS, AdapterProviderStatus.PARTIAL_SUCCESS}
                else {}
            ),
            "error_code": (
                None
                if status is AdapterProviderStatus.SUCCESS
                else "FIXTURE_PARTIAL"
                if status is AdapterProviderStatus.PARTIAL_SUCCESS
                else "FIXTURE_FAILURE"
            ),
            "retryable": False,
            "artifacts": (),
            "provider_operation_id": "provider-operation-1",
            "device_identity": (
                "device-fixture-1" if self.registration.requires_device_identity else None
            ),
            "calibration_ids": (
                ("calibration-fixture-1",) if self.registration.requires_calibration else ()
            ),
            "model_identity": (
                "model-fixture@1.0.0" if self.registration.requires_model_identity else None
            ),
            "bytes_read": 128,
            "bytes_written": 64,
        }
        values.update(self.reply_updates)
        return AdapterProviderReply(**values)


class Runtime:
    def __init__(
        self,
        selected_registration: AdapterRegistration,
        provider: FakeProvider | None = None,
    ) -> None:
        self.registration = selected_registration
        self.provider = provider or FakeProvider(selected_registration)
        self.definition = adapter_tool_definition(selected_registration)
        self.adapter = RegisteredAdapter(
            selected_registration,
            self.provider,
            clock=lambda: NOW,
        )
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="adapter-sdk-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.repository = InMemoryAuditRepository()
        self.registry = ToolRegistry(
            (self.definition,),
            {self.definition.key: self.adapter},
            audit=AuditService(self.repository, self.traces),
            clock=lambda: NOW,
        )

    def context(self, **updates: Any) -> ToolInvocationContext:
        values: dict[str, Any] = {
            "task_id": TASK_ID,
            "run_id": RUN_ID,
            "scope": SCOPE,
            "request_id": "adapter-request-1",
            "policy_version": "adapter-policy-1",
            "expected_registry_version": self.registry.version,
            "allowed_tools": frozenset({self.definition.key}),
            "granted_permissions": self.registration.required_permissions,
            "allowed_secret_purposes": self.registration.secret_purposes,
            "allowed_data_destinations": frozenset({self.registration.data_destination}),
            "allow_network": self.registration.network is NetworkPolicy.RESTRICTED,
        }
        values.update(updates)
        return ToolInvocationContext(**values)

    async def invoke(
        self,
        arguments: dict[str, Any],
        *,
        context: ToolInvocationContext | None = None,
        budget: BudgetGuard | None = None,
        observation: str = "1" * 64,
        idempotency_key: str | None = None,
    ) -> tuple[Any, AdapterOutputEnvelope | None, BudgetGuard]:
        selected_budget = budget or BudgetGuard(default_budget_policy("P1"))
        with self.traces.start_span("adapter.invoke"):
            result = await self.registry.invoke(
                name=self.definition.name,
                version=self.definition.version,
                arguments=arguments,
                context=context or self.context(),
                budget=selected_budget,
                observation_sha256=observation,
                idempotency_key=idempotency_key,
            )
        envelope = (
            None
            if result.status is ToolStatus.TIMEOUT
            else AdapterOutputEnvelope.model_validate(result.output)
        )
        return result, envelope, selected_budget

    def close(self) -> None:
        self.traces.shutdown()


@pytest.mark.parametrize("transport", sorted(_BINDING_FIELDS, key=str))
def test_all_seven_transport_bindings_are_exact_and_hash_valid(
    transport: ToolTransport,
) -> None:
    selected = binding(transport)
    assert selected.transport is transport
    assert selected.binding_sha256 == adapter_transport_binding_sha256(selected)
    serialized = selected.model_dump_json()
    assert "password" not in serialized and "token" not in serialized


@pytest.mark.parametrize("transport", sorted(_BINDING_FIELDS, key=str))
def test_all_seven_transport_registrations_generate_shared_tool_definitions(
    transport: ToolTransport,
) -> None:
    selected = registration(selected_binding=binding(transport))
    definition = adapter_tool_definition(selected)
    assert definition.transport is transport
    assert definition.kind is ToolKind.INSTRUMENT
    assert selected.registration_sha256 in definition.output_schema["$comment"]
    assert definition.namespace == (
        "fixture.instrument" if transport is ToolTransport.MCP else None
    )
    if transport is ToolTransport.BASH:
        assert "SEC-BASH" in definition.test_groups


def test_registration_hash_canonicalizes_set_order_and_detects_member_changes() -> None:
    selected = registration()
    payload = selected.model_dump(mode="json", exclude={"registration_sha256"})
    forward = dict(payload)
    reverse = dict(payload)
    for field_name in ("required_permissions", "secret_purposes", "declared_error_codes"):
        forward[field_name] = sorted(payload[field_name])
        reverse[field_name] = sorted(payload[field_name], reverse=True)

    assert canonical_sha256(_canonicalize_adapter_registration_sets(forward)) == (
        selected.registration_sha256
    )
    assert canonical_sha256(_canonicalize_adapter_registration_sets(reverse)) == (
        selected.registration_sha256
    )
    changed = dict(forward)
    changed["declared_error_codes"] = [*forward["declared_error_codes"], "FIXTURE_TIMEOUT"]
    assert canonical_sha256(_canonicalize_adapter_registration_sets(changed)) != (
        selected.registration_sha256
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://instrument.example.test/v1",
        "https://user:pass@instrument.example.test/v1",
        "https://127.0.0.1/v1",
        "https://localhost/v1",
        "https://instrument.example.test:8443/v1",
        "https://instrument.example.test/v1?token=x",
    ],
)
def test_http_binding_rejects_unsafe_endpoints(url: str) -> None:
    with pytest.raises((PydanticValidationError, ValueError)):
        binding(ToolTransport.HTTP_API, base_url=url)


def test_binding_rejects_unused_fields_unpinned_identity_and_tamper() -> None:
    with pytest.raises(PydanticValidationError, match="transport fields"):
        binding(ToolTransport.HTTP_API, command_id="unexpected.command")
    with pytest.raises(PydanticValidationError):
        binding(ToolTransport.SDK, package_sha256=None)
    selected = binding()
    with pytest.raises(PydanticValidationError, match="binding hash"):
        AdapterTransportBinding.model_validate(
            {**selected.model_dump(), "base_url": "https://changed.example.test/v1"}
        )


def test_registration_rejects_plaintext_secrets_and_tamper() -> None:
    secret_schema = {
        "type": "object",
        "properties": {"api_key": {"type": "string"}},
        "required": ["api_key"],
        "additionalProperties": False,
    }
    with pytest.raises(PydanticValidationError, match="credential"):
        registration(input_schema=secret_schema)
    selected = registration()
    with pytest.raises(PydanticValidationError, match="registration hash"):
        AdapterRegistration.model_validate({**selected.model_dump(), "adapter_version": "1.0.1"})


def test_registration_rejects_transport_and_provenance_policy_mismatch() -> None:
    simulator = binding(ToolTransport.SIMULATOR)
    with pytest.raises(PydanticValidationError, match="simulator"):
        registration(
            selected_binding=simulator,
            origin=AdapterOrigin.LABORATORY,
        )
    bash = binding(ToolTransport.BASH)
    with pytest.raises(PydanticValidationError, match="network-free"):
        registration(
            selected_binding=bash,
            network=NetworkPolicy.RESTRICTED,
        )
    with pytest.raises(PydanticValidationError, match="device identity"):
        registration(requires_device_identity=False)
    with pytest.raises(PydanticValidationError, match="idempotency"):
        registration(
            side_effect=SideEffectClass.REVERSIBLE,
            max_attempts=1,
            recovery_policy=ToolRecoveryPolicy.RECONCILE,
        )
    with pytest.raises(PydanticValidationError, match="unsupported"):
        registration(
            selected_binding=binding(ToolTransport.DLL),
            family=AdapterCapabilityFamily.AI_MODEL,
            requires_device_identity=False,
            requires_model_identity=True,
            max_tokens=1_000,
        )


def test_generated_definition_binds_registration_and_model_gate() -> None:
    instrument = registration()
    instrument_definition = adapter_tool_definition(instrument)
    assert instrument_definition.kind is ToolKind.INSTRUMENT
    assert instrument.registration_sha256 in instrument_definition.output_schema["$comment"]

    model_registration = registration(
        selected_binding=binding(ToolTransport.HTTP_API),
        family=AdapterCapabilityFamily.AI_MODEL,
    )
    model_provider = FakeProvider(model_registration)
    runtime = Runtime(model_registration, model_provider)
    try:
        assert runtime.definition.kind is ToolKind.AI_MODEL
        budget = BudgetGuard(default_budget_policy("P1"))
        with pytest.raises(ToolRegistryError) as captured:
            asyncio.run(runtime.invoke({"value": "model-input"}, budget=budget))
        assert captured.value.code == "TOOL_MODEL_GATEWAY_REQUIRED"
        assert not model_provider.calls
        assert budget.telemetry().counters.physical_tool_calls == 0
        assert budget.telemetry().counters.physical_llm_calls == 0
    finally:
        runtime.close()


def test_registry_version_changes_with_transport_or_registration() -> None:
    first = Runtime(registration())
    moved = Runtime(
        registration(
            selected_binding=binding(
                ToolTransport.HTTP_API,
                base_url="https://instrument-alt.example.test/v1",
            )
        )
    )
    changed = Runtime(registration(adapter_version="1.0.1"))
    try:
        assert first.registry.version != moved.registry.version
        assert first.registry.version != changed.registry.version
    finally:
        first.close()
        moved.close()
        changed.close()


def test_success_returns_exact_untrusted_evidence_after_one_provider_call() -> None:
    selected = registration(requires_calibration=True)
    provider = FakeProvider(
        selected,
        reply_updates={"artifacts": (result_artifact(),)},
    )
    runtime = Runtime(selected, provider)
    try:
        result, envelope, budget = asyncio.run(runtime.invoke({"value": "sample"}))
        assert result.status is ToolStatus.SUCCESS
        assert envelope is not None
        assert envelope.trust == "UNTRUSTED" and envelope.review_required
        assert envelope.output == {"measurement": 12.5}
        evidence = envelope.evidence
        assert evidence.scope == SCOPE
        assert evidence.task_id == str(TASK_ID) and evidence.run_id == str(RUN_ID)
        assert evidence.registration_sha256 == selected.registration_sha256
        assert evidence.transport_binding_sha256 == selected.binding.binding_sha256
        assert evidence.device_identity == "device-fixture-1"
        assert evidence.calibration_ids == ("calibration-fixture-1",)
        assert evidence.provider_calls == 1 and len(provider.calls) == 1
        assert evidence.output_sha256 == canonical_sha256(envelope.output)
        assert evidence.artifact_bindings and result.artifacts == (result_artifact(),)
        assert budget.telemetry().counters.physical_tool_calls == 1
        assert runtime.repository.list(SCOPE)[0].decision == "SUCCESS"
        request_json = provider.calls[0].model_dump_json()
        assert "adapter.fixture" not in request_json
        assert "instrument.example.test" not in request_json
        assert provider.calls[0].transport_binding_sha256 == selected.binding.binding_sha256
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "context_updates",
    [
        {"granted_permissions": frozenset({"unrelated"})},
        {"allowed_secret_purposes": frozenset()},
        {"allow_network": False},
        {"allowed_data_destinations": frozenset({ToolDataDestination.LOCAL})},
    ],
)
def test_registry_preflight_denials_are_zero_provider_call(
    context_updates: dict[str, Any],
) -> None:
    selected = registration()
    provider = FakeProvider(selected)
    runtime = Runtime(selected, provider)
    try:
        with pytest.raises(ToolRegistryError):
            asyncio.run(
                runtime.invoke(
                    {"value": "sample"},
                    context=runtime.context(**context_updates),
                )
            )
        assert not provider.calls
    finally:
        runtime.close()


def test_invalid_input_is_rejected_before_provider_and_budget_count() -> None:
    selected = registration()
    provider = FakeProvider(selected)
    runtime = Runtime(selected, provider)
    budget = BudgetGuard(default_budget_policy("P1"))
    try:
        with pytest.raises(ToolRegistryError) as captured:
            asyncio.run(runtime.invoke({"wrong": "field"}, budget=budget))
        assert captured.value.code == "TOOL_SCHEMA_INVALID"
        assert not provider.calls
        assert budget.telemetry().counters.physical_tool_calls == 0
    finally:
        runtime.close()


def test_side_effect_requires_approval_idempotency_and_replays_once() -> None:
    selected = registration(
        side_effect=SideEffectClass.IRREVERSIBLE,
        approval_required=True,
        idempotency=IdempotencyPolicy.REQUIRED,
        max_attempts=1,
        max_concurrency=1,
        recovery_policy=ToolRecoveryPolicy.HUMAN_REVIEW,
    )
    provider = FakeProvider(selected)
    runtime = Runtime(selected, provider)
    arguments = {"value": "action"}
    try:
        with pytest.raises(ToolRegistryError) as missing:
            asyncio.run(runtime.invoke(arguments, idempotency_key="action-1"))
        assert missing.value.code == "TOOL_APPROVAL_REQUIRED" and not provider.calls
        base_context = runtime.context()
        approval = tool_approval_binding_sha256(
            base_context,
            runtime.definition,
            canonical_sha256(arguments),
        )
        context = base_context.model_copy(update={"approved_call_sha256s": frozenset({approval})})
        first, _, _ = asyncio.run(
            runtime.invoke(
                arguments,
                context=context,
                idempotency_key="action-1",
                observation="2" * 64,
            )
        )
        second, _, _ = asyncio.run(
            runtime.invoke(
                arguments,
                context=context,
                idempotency_key="action-1",
                observation="3" * 64,
            )
        )
        assert first == second and len(provider.calls) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("reply_updates", "expected_code"),
    [
        ({"adapter_id": "wrong.adapter"}, "ADAPTER_RESPONSE_INVALID"),
        ({"registration_sha256": "f" * 64}, "ADAPTER_RESPONSE_INVALID"),
        ({"request_sha256": "e" * 64}, "ADAPTER_RESPONSE_INVALID"),
        ({"output": {"wrong": 1}}, "ADAPTER_OUTPUT_INVALID"),
        (
            {
                "error_code": "UNDECLARED_ERROR",
                "status": AdapterProviderStatus.FAILED,
            },
            "ADAPTER_RESPONSE_INVALID",
        ),
    ],
)
def test_invalid_provider_identity_schema_or_error_is_typed(
    reply_updates: dict[str, Any],
    expected_code: str,
) -> None:
    selected = registration()
    provider = FakeProvider(selected, reply_updates=reply_updates)
    runtime = Runtime(selected, provider)
    try:
        result, envelope, _ = asyncio.run(runtime.invoke({"value": "sample"}))
        assert result.status is ToolStatus.FAILED
        assert result.error_code == expected_code
        assert envelope is not None and envelope.output == {}
        assert len(provider.calls) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "reply_updates",
    [
        {"device_identity": None},
        {"calibration_ids": ()},
    ],
)
def test_missing_required_device_or_calibration_provenance_fails(
    reply_updates: dict[str, Any],
) -> None:
    selected = registration(requires_calibration=True)
    runtime = Runtime(selected, FakeProvider(selected, reply_updates=reply_updates))
    try:
        result, _, _ = asyncio.run(runtime.invoke({"value": "sample"}))
        assert result.error_code == "ADAPTER_PROVENANCE_INVALID"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "artifact",
    [
        result_artifact(immutable=False),
        result_artifact(
            scope=SCOPE.model_copy(
                update={"project_id": UUID("00000000-0000-4000-8000-000000000804")}
            )
        ),
    ],
)
def test_invalid_artifact_scope_or_immutability_fails(artifact: ArtifactRef) -> None:
    selected = registration()
    runtime = Runtime(
        selected,
        FakeProvider(selected, reply_updates={"artifacts": (artifact,)}),
    )
    try:
        result, _, _ = asyncio.run(runtime.invoke({"value": "sample"}))
        assert result.error_code == "ADAPTER_ARTIFACT_INVALID"
    finally:
        runtime.close()


def test_partial_success_preserves_output_and_declared_cause() -> None:
    selected = registration()
    runtime = Runtime(
        selected,
        FakeProvider(
            selected,
            reply_updates={"status": AdapterProviderStatus.PARTIAL_SUCCESS},
        ),
    )
    try:
        result, envelope, _ = asyncio.run(runtime.invoke({"value": "sample"}))
        assert result.status is ToolStatus.PARTIAL_SUCCESS
        assert result.error_code == "FIXTURE_PARTIAL"
        assert envelope is not None and envelope.output == {"measurement": 12.5}
        assert envelope.evidence.error_code == "FIXTURE_PARTIAL"
    finally:
        runtime.close()


def test_successful_retryable_provider_reply_is_rejected() -> None:
    selected = registration()
    runtime = Runtime(
        selected,
        FakeProvider(selected, reply_updates={"retryable": True}),
    )
    try:
        result, _, _ = asyncio.run(runtime.invoke({"value": "sample"}))
        assert result.error_code == "ADAPTER_RESPONSE_INVALID"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("provider", "code", "retryable"),
    [
        (
            lambda selected: FakeProvider(
                selected,
                error=AdapterProviderError("ADAPTER_PROVIDER_UNAVAILABLE", retryable=True),
            ),
            "ADAPTER_PROVIDER_UNAVAILABLE",
            True,
        ),
        (
            lambda selected: FakeProvider(selected, generic_failure=True),
            "ADAPTER_PROVIDER_FAILED",
            True,
        ),
        (
            lambda selected: FakeProvider(
                selected,
                error=AdapterProviderError("UNDECLARED", retryable=True),
            ),
            "ADAPTER_RESPONSE_INVALID",
            False,
        ),
    ],
)
def test_provider_failures_are_typed_non_disclosing_and_single_call(
    provider: Any,
    code: str,
    retryable: bool,
) -> None:
    selected = registration()
    fake = provider(selected)
    runtime = Runtime(selected, fake)
    try:
        result, _, _ = asyncio.run(runtime.invoke({"value": "sample"}))
        assert result.error_code == code
        assert result.retryable is retryable
        assert len(fake.calls) == 1
        assert "provider internals" not in result.model_dump_json()
    finally:
        runtime.close()


def test_output_byte_budget_failure_is_typed() -> None:
    large_schema = {
        "type": "object",
        "properties": {
            "measurement": {"type": "number"},
            "padding": {"type": "string"},
        },
        "required": ["measurement"],
        "additionalProperties": False,
    }
    selected = registration(max_output_bytes=100, output_schema=large_schema)
    provider = FakeProvider(
        selected,
        reply_updates={"output": {"measurement": 12.5, "padding": "x" * 200}},
    )
    runtime = Runtime(selected, provider)
    try:
        result, _, _ = asyncio.run(runtime.invoke({"value": "sample"}))
        assert result.error_code == "ADAPTER_OUTPUT_INVALID"
        assert len(provider.calls) == 1
    finally:
        runtime.close()


def test_registry_timeout_has_no_hidden_retry() -> None:
    selected = registration(timeout_ms=1)
    provider = FakeProvider(selected, delay=0.02)
    runtime = Runtime(selected, provider)
    try:
        result, envelope, budget = asyncio.run(runtime.invoke({"value": "sample"}))
        assert result.status is ToolStatus.TIMEOUT
        assert result.error_code == "TOOL_TIMEOUT" and envelope is None
        assert len(provider.calls) == 1
        assert budget.telemetry().counters.physical_tool_calls == 1
    finally:
        runtime.close()


def test_evidence_hash_rejects_tamper() -> None:
    selected = registration()
    runtime = Runtime(selected)
    try:
        _, envelope, _ = asyncio.run(runtime.invoke({"value": "sample"}))
        assert envelope is not None
        evidence = envelope.evidence
        assert evidence.evidence_sha256 == adapter_evidence_sha256(evidence)
        with pytest.raises(PydanticValidationError, match="evidence hash"):
            AdapterEvidence.model_validate(
                {**evidence.model_dump(), "bytes_read": evidence.bytes_read + 1}
            )
    finally:
        runtime.close()
