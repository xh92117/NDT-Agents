"""S5-08 six-method reference simulator integration tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import Limit, TenantScope, ToolStatus
from ndt_agents.inspection_data import (
    build_canonical_inspection_dataset,
    dump_canonical_inspection_data,
    load_canonical_inspection_data,
)
from ndt_agents.observability import (
    AuditKind,
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.professional.methods import METHOD_CODES, default_method_definitions
from ndt_agents.professional.processing import DataOrigin
from ndt_agents.tools import ToolInvocationContext, ToolRegistryError
from ndt_agents.tools.adapter_sdk import (
    AdapterExecutionRequest,
    AdapterOrigin,
    AdapterProviderError,
    AdapterProviderReply,
    AdapterRegistration,
    adapter_registration_sha256,
)
from ndt_agents.tools.reference_adapters import (
    DeterministicReferenceSimulatorProvider,
    ReferenceAdapterError,
    ReferenceAdapterExecutionResult,
    ReferenceAdapterProfile,
    ReferenceAdapterRegistry,
    ReferenceAdapterRuntime,
    ReferenceAdapterStatus,
    ReferenceSimulatorOutput,
    default_reference_adapter_profiles,
    reference_adapter_profile_sha256,
    reference_adapter_result_sha256,
)
from ndt_agents.tools.registry import (
    NetworkPolicy,
    SideEffectClass,
    ToolDataDestination,
    ToolDataScope,
    ToolRecoveryPolicy,
    ToolTransport,
)

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000901"),
    project_id=UUID("00000000-0000-4000-8000-000000000902"),
    user_id=UUID("00000000-0000-4000-8000-000000000903"),
    role_codes=("REFERENCE_USER",),
    permission_version="permissions-1",
)
OTHER_SCOPE = SCOPE.model_copy(update={"project_id": UUID("00000000-0000-4000-8000-000000000999")})
TASK_ID = UUID("00000000-0000-4000-8000-000000000911")
RUN_ID = UUID("00000000-0000-4000-8000-000000000912")
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
OBSERVATION = "9" * 64


class Harness:
    def __init__(
        self,
        *,
        profiles: tuple[ReferenceAdapterProfile, ...] | None = None,
        providers: dict[str, Any] | None = None,
    ) -> None:
        self.reference_registry = ReferenceAdapterRegistry(profiles)
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="reference-adapter-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.repository = InMemoryAuditRepository()
        self.runtime = ReferenceAdapterRuntime(
            self.reference_registry,
            AuditService(self.repository, self.traces),
            providers=providers,
            clock=lambda: NOW,
        )

    def profile(self, method: str) -> ReferenceAdapterProfile:
        return next(item for item in self.reference_registry.profiles if item.method_code == method)

    def context(
        self,
        method: str,
        *,
        scope: TenantScope = SCOPE,
        **updates: Any,
    ) -> ToolInvocationContext:
        profile = self.profile(method)
        definition = next(
            item
            for item in self.runtime.tool_registry.definitions
            if item.name == f"adapter.{profile.registration.adapter_id}.acquire"
        )
        values: dict[str, Any] = {
            "task_id": TASK_ID,
            "run_id": RUN_ID,
            "scope": scope,
            "request_id": f"reference-{method.lower()}-request",
            "policy_version": "reference-policy-1",
            "expected_registry_version": self.runtime.tool_registry.version,
            "allowed_tools": frozenset({definition.key}),
            "granted_permissions": profile.registration.required_permissions,
            "allowed_secret_purposes": frozenset(),
            "allowed_data_destinations": frozenset({ToolDataDestination.LOCAL}),
            "allow_network": False,
        }
        values.update(updates)
        return ToolInvocationContext.model_validate(values)

    def acquire(
        self,
        method: str,
        *,
        context: ToolInvocationContext | None = None,
        budget: BudgetGuard | None = None,
        **updates: Any,
    ) -> ReferenceAdapterExecutionResult:
        profile = self.profile(method)
        values: dict[str, Any] = {
            "method_code": method,
            "fixture_id": profile.fixture_id,
            "expected_reference_registry_version": self.reference_registry.version,
            "expected_profile_sha256": profile.profile_sha256,
            "expected_fixture_sha256": profile.fixture_sha256,
            "context": context or self.context(method),
            "budget": budget or BudgetGuard(default_budget_policy("P1")),
            "observation_sha256": OBSERVATION,
        }
        values.update(updates)
        with self.traces.start_span("reference.acquire"):
            return asyncio.run(self.runtime.acquire(**values))

    def close(self) -> None:
        self.traces.shutdown()


class MutatingProvider:
    def __init__(self, profile: ReferenceAdapterProfile, mode: str) -> None:
        self.profile = profile
        self.mode = mode
        self.inner = DeterministicReferenceSimulatorProvider(profile)

    @property
    def calls(self) -> int:
        return self.inner.calls

    async def execute(self, request: AdapterExecutionRequest) -> object:
        if self.mode == "error":
            self.inner.calls += 1
            raise AdapterProviderError("REFERENCE_FIXTURE_FAILED")
        if self.mode == "generic":
            self.inner.calls += 1
            raise RuntimeError("provider internals and forbidden-secret")
        if self.mode == "slow":
            self.inner.calls += 1
            await asyncio.sleep(0.05)
        if self.mode == "cross_scope":
            modified = request.model_copy(update={"scope": OTHER_SCOPE})
            changed_reply = await DeterministicReferenceSimulatorProvider(self.profile).execute(
                modified
            )
            self.inner.calls += 1
            return changed_reply.model_copy(update={"request_sha256": request.request_sha256})
        reply = await self.inner.execute(request)
        output = ReferenceSimulatorOutput.model_validate(reply.output)
        if self.mode == "identity":
            return reply.model_copy(update={"adapter_id": "reference.invalid"})
        if self.mode == "profile_hash":
            return reply.model_copy(
                update={
                    "output": {
                        **output.model_dump(mode="json"),
                        "profile_sha256": "f" * 64,
                    }
                }
            )
        if self.mode == "noncanonical":
            parsed = json.loads(output.canonical_payload)
            return _reply_with_payload(
                reply, output, json.dumps(parsed, ensure_ascii=False, indent=2)
            )
        if self.mode == "tamper":
            parsed = json.loads(output.canonical_payload)
            parsed["source"]["source_name"] = "changed"
            return _reply_with_payload(
                reply,
                output,
                json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
        if self.mode == "production_origin":
            dataset = load_canonical_inspection_data(output.canonical_payload.encode("utf-8"))
            content = dataset.model_dump(mode="python", exclude={"manifest_sha256"})
            content["origin"] = DataOrigin.PRODUCTION
            changed = build_canonical_inspection_dataset(content)
            changed_payload = dump_canonical_inspection_data(changed).decode("utf-8")
            return _reply_with_payload(
                reply,
                output,
                changed_payload,
                manifest_sha256=changed.manifest_sha256,
            )
        if self.mode == "oversized":
            return reply.model_copy(
                update={
                    "output": {
                        **output.model_dump(mode="json"),
                        "canonical_payload": "x" * 2_000_001,
                    }
                }
            )
        return reply


def _reply_with_payload(
    reply: AdapterProviderReply,
    output: ReferenceSimulatorOutput,
    payload: str,
    *,
    manifest_sha256: str | None = None,
) -> AdapterProviderReply:
    changed = {
        **output.model_dump(mode="json"),
        "canonical_payload": payload,
        "manifest_sha256": manifest_sha256 or output.manifest_sha256,
    }
    return reply.model_copy(update={"output": changed, "bytes_written": len(payload.encode())})


def _rehashed_profile(
    profile: ReferenceAdapterProfile,
    **updates: Any,
) -> ReferenceAdapterProfile:
    values = profile.model_dump(mode="python")
    values.pop("profile_sha256", None)
    values["registration"] = profile.registration
    values.update(updates)
    draft = ReferenceAdapterProfile.model_construct(**values, profile_sha256="0" * 64)
    values["profile_sha256"] = reference_adapter_profile_sha256(draft)
    return ReferenceAdapterProfile.model_validate(values)


def _timeout_profile(profile: ReferenceAdapterProfile) -> ReferenceAdapterProfile:
    registration_values = profile.registration.model_dump(mode="python")
    registration_values.pop("registration_sha256", None)
    registration_values["binding"] = profile.registration.binding
    registration_values["timeout_ms"] = 10
    draft = AdapterRegistration.model_construct(
        **registration_values,
        registration_sha256="0" * 64,
    )
    registration_values["registration_sha256"] = adapter_registration_sha256(draft)
    registration = AdapterRegistration.model_validate(registration_values)
    return _rehashed_profile(profile, registration=registration)


def test_reference_registry_is_exact_hash_stable_and_policy_bounded() -> None:
    first = ReferenceAdapterRegistry()
    second = ReferenceAdapterRegistry(default_reference_adapter_profiles())
    definitions = {item.method_code: item for item in default_method_definitions()}

    assert tuple(item.method_code for item in first.profiles) == METHOD_CODES
    assert first.version == second.version
    assert len({item.profile_sha256 for item in first.profiles}) == 6
    for profile in first.profiles:
        registration = profile.registration
        assert profile.profile_sha256 == reference_adapter_profile_sha256(profile)
        assert (
            profile.method_definition_sha256 == definitions[profile.method_code].definition_sha256
        )
        assert (
            profile.acquisition_setting_names
            == definitions[profile.method_code].required_acquisition_settings
        )
        assert registration.binding.transport is ToolTransport.SIMULATOR
        assert registration.binding.simulator_fixture_sha256 == profile.fixture_sha256
        assert registration.origin is AdapterOrigin.SIMULATED
        assert registration.data_scope is ToolDataScope.TASK
        assert registration.data_destination is ToolDataDestination.LOCAL
        assert registration.side_effect is SideEffectClass.READ_ONLY
        assert registration.network is NetworkPolicy.NONE
        assert registration.secret_purposes == frozenset()
        assert registration.max_attempts == 1
        assert registration.recovery_policy is ToolRecoveryPolicy.NO_RETRY


@pytest.mark.parametrize(
    "mutation",
    ("method_hash", "signal", "calibration", "fixture_hash", "registration"),
)
def test_profile_rejects_stale_cross_method_or_changed_contract(mutation: str) -> None:
    profile = default_reference_adapter_profiles()[0]
    values = profile.model_dump(mode="python")
    values["registration"] = profile.registration
    if mutation == "method_hash":
        values["method_definition_sha256"] = "f" * 64
    elif mutation == "signal":
        values["signal_dimension"] = "INDEX"
        values["signal_unit"] = "index"
    elif mutation == "calibration":
        values["calibration_kind"] = "UNKNOWN"
    elif mutation == "fixture_hash":
        values["fixture_sha256"] = "f" * 64
    else:
        registration = AdapterRegistration.model_validate(values["registration"])
        values["registration"] = registration.model_copy(update={"adapter_id": "reference.invalid"})
    values.pop("profile_sha256", None)
    draft = ReferenceAdapterProfile.model_construct(**values, profile_sha256="0" * 64)
    values["profile_sha256"] = reference_adapter_profile_sha256(draft)

    with pytest.raises(ValidationError):
        ReferenceAdapterProfile.model_validate(values)


def test_registry_rejects_empty_duplicate_and_wrong_order() -> None:
    profiles = default_reference_adapter_profiles()
    with pytest.raises(ReferenceAdapterError) as empty:
        ReferenceAdapterRegistry(())
    assert empty.value.code == "REFERENCE_REGISTRY_INVALID"
    with pytest.raises(ReferenceAdapterError) as duplicate:
        ReferenceAdapterRegistry((profiles[0],) * 6)
    assert duplicate.value.code == "REFERENCE_REGISTRY_INVALID"
    with pytest.raises(ReferenceAdapterError) as reordered:
        ReferenceAdapterRegistry(tuple(reversed(profiles)))
    assert reordered.value.code == "REFERENCE_REGISTRY_INVALID"


@pytest.mark.parametrize("method", METHOD_CODES)
def test_each_method_runs_once_and_returns_exact_simulated_canonical_data(method: str) -> None:
    harness = Harness()
    budget = BudgetGuard(default_budget_policy("P1"))
    try:
        result = harness.acquire(method, budget=budget)
        profile = harness.profile(method)
        provider = cast(
            DeterministicReferenceSimulatorProvider,
            harness.runtime.providers[method],
        )
        counters = budget.telemetry().counters
        audits = harness.repository.list(SCOPE)

        assert result.status is ReferenceAdapterStatus.SUCCESS
        assert result.result_sha256 == reference_adapter_result_sha256(result)
        assert result.canonical_data is not None
        assert result.canonical_validation is not None
        assert result.canonical_data.scope == SCOPE
        assert result.canonical_data.method_code == method
        assert result.canonical_data.origin is DataOrigin.SIMULATED
        assert result.canonical_data.manifest_sha256 == result.canonical_validation.manifest_sha256
        assert result.canonical_data.instrument.adapter_id == profile.registration.adapter_id
        assert (
            result.canonical_data.instrument.adapter_registration_sha256
            == profile.registration.registration_sha256
        )
        assert result.canonical_data.primary_calibration_id == profile.calibration_id
        assert result.canonical_data.source.parser_id == profile.parser_id
        assert result.canonical_data.source.source_name.startswith("-参考 桥梁\n")
        assert result.canonical_validation.processing_eligible
        assert not result.canonical_validation.formal_use_eligible
        assert result.trust == "UNTRUSTED" and result.review_required
        assert not result.formal_use_eligible
        assert result.physical_tool_calls == 1 and result.physical_llm_calls == 0
        assert result.network_calls == 0 and result.real_device_actions == 0
        assert provider.calls == 1
        assert counters.physical_tool_calls == 1
        assert counters.physical_llm_calls == 0
        assert len(audits) == 2
        assert all(item.kind is AuditKind.TOOL for item in audits)
        assert [item.action for item in audits] == [
            "tool.execute",
            "reference.adapter.validate",
        ]
        assert "canonical_payload" not in audits[0].model_dump_json()
    finally:
        harness.close()


@pytest.mark.parametrize("method", METHOD_CODES)
def test_fixture_payload_is_byte_deterministic_and_matches_method_skeleton(method: str) -> None:
    first = Harness()
    second = Harness()
    try:
        first_result = first.acquire(method)
        second_result = second.acquire(method)
        first_data = first_result.canonical_data
        second_data = second_result.canonical_data
        definition = next(
            item for item in default_method_definitions() if item.method_code == method
        )

        assert first_data is not None and second_data is not None
        assert dump_canonical_inspection_data(first_data) == dump_canonical_inspection_data(
            second_data
        )
        assert tuple(item.name for item in first_data.acquisition_settings) == (
            definition.required_acquisition_settings
        )
        assert first_data.calibrations[0].calibration_kind in (
            definition.required_calibration_kinds
        )
        assert any(
            signal.dimension == first_data.channels[0].dimension
            and first_data.channels[0].unit in signal.units
            for signal in definition.input_signals
        )
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize(
    ("update", "code"),
    (
        ({"expected_reference_registry_version": "f" * 64}, "REFERENCE_REGISTRY_STALE"),
        ({"expected_profile_sha256": "f" * 64}, "REFERENCE_PROFILE_STALE"),
        ({"fixture_id": "unknown-fixture"}, "REFERENCE_FIXTURE_STALE"),
        ({"expected_fixture_sha256": "f" * 64}, "REFERENCE_FIXTURE_STALE"),
        ({"method_code": "UNKNOWN"}, "REFERENCE_PROFILE_NOT_FOUND"),
    ),
)
def test_reference_preflight_denials_make_zero_provider_calls(
    update: dict[str, str],
    code: str,
) -> None:
    harness = Harness()
    provider = cast(
        DeterministicReferenceSimulatorProvider,
        harness.runtime.providers["UT"],
    )
    budget = BudgetGuard(default_budget_policy("P1"))
    try:
        with pytest.raises(ReferenceAdapterError) as caught:
            harness.acquire("UT", budget=budget, **cast(dict[str, Any], update))

        assert caught.value.code == code
        assert provider.calls == 0
        assert budget.telemetry().counters.physical_tool_calls == 0
        audits = harness.repository.list(SCOPE)
        assert len(audits) == 1
        assert audits[0].action == "reference.adapter.validate"
        assert audits[0].decision == code
    finally:
        harness.close()


@pytest.mark.parametrize(
    "context_update",
    (
        {"granted_permissions": frozenset()},
        {"expected_registry_version": "f" * 64},
        {"allowed_tools": frozenset({"adapter.reference.gpr.acquire@1.0.0"})},
        {"allowed_data_destinations": frozenset({ToolDataDestination.APPROVED_EXTERNAL})},
    ),
)
def test_shared_tool_registry_denies_unauthorized_context_before_provider(
    context_update: dict[str, object],
) -> None:
    harness = Harness()
    provider = cast(
        DeterministicReferenceSimulatorProvider,
        harness.runtime.providers["UT"],
    )
    budget = BudgetGuard(default_budget_policy("P1"))
    try:
        context = harness.context("UT", **cast(dict[str, Any], context_update))
        with pytest.raises(ToolRegistryError):
            harness.acquire("UT", context=context, budget=budget)

        assert provider.calls == 0
        assert budget.telemetry().counters.physical_tool_calls == 0
    finally:
        harness.close()


def test_budget_denial_and_unknown_argument_make_zero_provider_calls() -> None:
    policy = default_budget_policy("P1").model_copy(
        update={"tool_calls": Limit(default=0, active=0, hard=0)}
    )
    harness = Harness()
    provider = cast(
        DeterministicReferenceSimulatorProvider,
        harness.runtime.providers["UT"],
    )
    try:
        with pytest.raises(ToolRegistryError) as denied:
            harness.acquire("UT", budget=BudgetGuard(policy))
        assert denied.value.code == "BUDGET_HARD_LIMIT_EXCEEDED"
        assert provider.calls == 0

        profile = harness.profile("UT")
        definition = next(
            item
            for item in harness.runtime.tool_registry.definitions
            if item.name == f"adapter.{profile.registration.adapter_id}.acquire"
        )
        with harness.traces.start_span("reference.invalid-input"):
            with pytest.raises(ToolRegistryError) as invalid:
                asyncio.run(
                    harness.runtime.tool_registry.invoke(
                        name=definition.name,
                        version=definition.version,
                        arguments={"fixture_id": profile.fixture_id, "method": "GPR"},
                        context=harness.context("UT"),
                        budget=BudgetGuard(default_budget_policy("P1")),
                        observation_sha256=OBSERVATION,
                    )
                )
        assert invalid.value.code == "TOOL_SCHEMA_INVALID"
        assert provider.calls == 0
    finally:
        harness.close()


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    (
        ("identity", "ADAPTER_RESPONSE_INVALID"),
        ("profile_hash", "REFERENCE_OUTPUT_INVALID"),
        ("noncanonical", "REFERENCE_OUTPUT_INVALID"),
        ("tamper", "REFERENCE_OUTPUT_INVALID"),
        ("production_origin", "REFERENCE_OUTPUT_INVALID"),
        ("cross_scope", "REFERENCE_OUTPUT_INVALID"),
        ("oversized", "ADAPTER_OUTPUT_INVALID"),
        ("error", "REFERENCE_FIXTURE_FAILED"),
        ("generic", "ADAPTER_PROVIDER_FAILED"),
    ),
)
def test_post_call_provider_and_canonical_failures_are_typed(
    mode: str,
    expected_code: str,
) -> None:
    profile = default_reference_adapter_profiles()[-1]
    provider = MutatingProvider(profile, mode)
    harness = Harness(providers={"UT": provider})
    budget = BudgetGuard(default_budget_policy("P1"))
    try:
        result = harness.acquire("UT", budget=budget)

        assert result.status is ReferenceAdapterStatus.FAILED
        assert result.failure_code == expected_code
        assert result.canonical_data is None
        assert result.canonical_validation is None
        assert result.tool_result.status is not ToolStatus.SUCCESS or mode in {
            "profile_hash",
            "noncanonical",
            "tamper",
            "production_origin",
            "cross_scope",
        }
        assert provider.calls >= 1
        assert budget.telemetry().counters.physical_tool_calls == 1
        serialized = result.model_dump_json()
        assert "forbidden-secret" not in serialized
    finally:
        harness.close()


def test_timeout_is_typed_one_call_without_retry() -> None:
    profiles = list(default_reference_adapter_profiles())
    profiles[-1] = _timeout_profile(profiles[-1])
    provider = MutatingProvider(profiles[-1], "slow")
    harness = Harness(profiles=tuple(profiles), providers={"UT": provider})
    budget = BudgetGuard(default_budget_policy("P1"))
    try:
        result = harness.acquire("UT", budget=budget)

        assert result.status is ReferenceAdapterStatus.FAILED
        assert result.failure_code == "TOOL_TIMEOUT"
        assert result.tool_result.status is ToolStatus.TIMEOUT
        assert provider.calls == 1
        assert budget.telemetry().counters.physical_tool_calls == 1
        assert result.retries == 0
    finally:
        harness.close()


def test_all_six_tools_expose_as_one_authorized_local_surface() -> None:
    harness = Harness()
    try:
        allowed = frozenset(item.key for item in harness.runtime.tool_registry.definitions)
        permissions = frozenset(
            permission
            for profile in harness.reference_registry.profiles
            for permission in profile.registration.required_permissions
        )
        context = harness.context(
            "UT",
            allowed_tools=allowed,
            granted_permissions=permissions,
        )
        with harness.traces.start_span("reference.expose"):
            manifest = harness.runtime.tool_registry.expose(context)

        assert len(manifest.tools) == 6
        assert {item.name for item in manifest.tools} == {
            f"adapter.reference.{method.lower()}.acquire" for method in METHOD_CODES
        }
        assert all(item.side_effect is SideEffectClass.READ_ONLY for item in manifest.tools)
    finally:
        harness.close()


def test_result_and_profile_hash_tamper_are_rejected() -> None:
    harness = Harness()
    try:
        result = harness.acquire("UT")
        with pytest.raises(ValidationError):
            ReferenceAdapterExecutionResult.model_validate(
                {**result.model_dump(mode="python"), "result_sha256": "f" * 64}
            )
        profile = harness.profile("UT")
        with pytest.raises(ValidationError):
            ReferenceAdapterProfile.model_validate(
                {**profile.model_dump(mode="python"), "profile_sha256": "f" * 64}
            )
    finally:
        harness.close()


def test_provider_override_and_contracts_never_serialize_credentials() -> None:
    harness = Harness()
    try:
        serialized = " ".join(
            profile.model_dump_json() for profile in harness.reference_registry.profiles
        )
        assert "api_key" not in serialized
        assert "password" not in serialized
        assert '"secret_purposes":[]' in serialized
        assert all(
            profile.registration.binding.transport is ToolTransport.SIMULATOR
            for profile in harness.reference_registry.profiles
        )
    finally:
        harness.close()
