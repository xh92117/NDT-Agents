"""S5-08 deterministic six-method reference simulators."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID, uuid4, uuid5

from pydantic import Field, ValidationError, model_validator

from ndt_agents.contracts.v1 import (
    ArtifactRef,
    DataClassification,
    StrictModel,
    TenantScope,
    ToolResult,
    ToolStatus,
)
from ndt_agents.inspection_data import (
    CANONICAL_INSPECTION_DATA_VERSION,
    CanonicalDataValidationResult,
    CanonicalInspectionDataError,
    CanonicalInspectionDataset,
    build_canonical_inspection_dataset,
    dump_canonical_inspection_data,
    load_canonical_inspection_data,
    validate_canonical_inspection_dataset,
)
from ndt_agents.observability.audit import (
    AuditKind,
    AuditOutcome,
    AuditRecord,
    AuditService,
)
from ndt_agents.orchestration.budget import BudgetGuard
from ndt_agents.professional.methods import (
    METHOD_CODES,
    MethodSkillDefinition,
    default_method_definitions,
)
from ndt_agents.professional.processing import DataOrigin
from ndt_agents.tools.adapter_sdk import (
    AdapterCapabilityFamily,
    AdapterExecutionRequest,
    AdapterOrigin,
    AdapterOutputEnvelope,
    AdapterProvider,
    AdapterProviderReply,
    AdapterProviderStatus,
    AdapterRegistration,
    AdapterTransportBinding,
    RegisteredAdapter,
    adapter_registration_sha256,
    adapter_tool_definition,
    adapter_transport_binding_sha256,
)
from ndt_agents.tools.registry import (
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolDataDestination,
    ToolDataScope,
    ToolInvocationContext,
    ToolRecoveryPolicy,
    ToolRegistry,
    ToolTransport,
    canonical_sha256,
)

REFERENCE_ADAPTER_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
REFERENCE_ADAPTER_METHODS = METHOD_CODES
_REFERENCE_NAMESPACE = UUID("63ef4eac-92b7-4f3f-b7a6-9d0ab4edddc8")
_ACQUIRED_AT = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
_ZERO_SHA256 = "0" * 64

_METHOD_SETTINGS: dict[str, dict[str, bool | int | str]] = {
    "AE": {
        "preamplifier_gain_db": 40,
        "sensor_layout_ref": "reference-ae-layout-v1",
        "threshold_db": 45,
    },
    "GPR": {
        "antenna_frequency_mhz": "400",
        "scan_spacing_mm": "25",
        "time_window_ns": "100",
    },
    "IE": {
        "impactor_id": "reference-impactor-v1",
        "sampling_frequency_hz": "50000",
        "sensor_spacing_mm": "50",
    },
    "MV": {
        "camera_distance_mm": "1000",
        "image_plane_ref": "reference-image-plane-v1",
        "lighting_ref": "reference-lighting-v1",
        "pixel_scale_mm_per_pixel": "0.10",
    },
    "RT": {
        "impact_direction": "HORIZONTAL",
        "surface_condition": "DRY_SMOOTH",
        "test_grid_ref": "reference-rt-grid-v1",
    },
    "UT": {
        "couplant_ref": "reference-couplant-v1",
        "gain_db": 20,
        "probe_frequency_mhz": "2.5",
        "scan_layout_ref": "reference-ut-layout-v1",
    },
}


class ReferenceAdapterStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ReferenceAdapterProfile(StrictModel):
    schema_version: Literal["1.0.0"] = REFERENCE_ADAPTER_CONTRACT_VERSION
    profile_id: str = Field(pattern=r"^reference-(ae|gpr|ie|mv|rt|ut)$")
    profile_version: Literal["1.0.0"] = REFERENCE_ADAPTER_CONTRACT_VERSION
    method_code: str = Field(pattern=r"^(AE|GPR|IE|MV|RT|UT)$")
    method_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_contract_version: Literal["1.0.0"] = CANONICAL_INSPECTION_DATA_VERSION
    fixture_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    fixture_version: Literal["1.0.0"] = REFERENCE_ADAPTER_CONTRACT_VERSION
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signal_dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    signal_unit: str = Field(min_length=1, max_length=32)
    calibration_kind: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    acquisition_setting_names: tuple[str, ...] = Field(min_length=1, max_length=128)
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    parser_version: Literal["1.0.0"] = REFERENCE_ADAPTER_CONTRACT_VERSION
    instrument_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    device_identity: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    calibration_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    registration: AdapterRegistration
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        definition = _method_definitions()[self.method_code]
        if self.profile_id != f"reference-{self.method_code.lower()}":
            raise ValueError("reference profile identity does not match its method")
        if (
            self.fixture_id != f"reference-{self.method_code.lower()}-baseline"
            or self.parser_id != f"reference-{self.method_code.lower()}-parser"
            or self.instrument_id != f"reference-{self.method_code.lower()}-device"
            or self.device_identity != self.instrument_id
            or self.calibration_id != f"reference-{self.method_code.lower()}-calibration"
        ):
            raise ValueError("reference profile provenance identities do not match its method")
        if self.method_definition_sha256 != definition.definition_sha256:
            raise ValueError("reference profile method-definition hash is stale")
        if self.acquisition_setting_names != definition.required_acquisition_settings:
            raise ValueError("reference profile acquisition settings do not match the method")
        if self.calibration_kind not in definition.required_calibration_kinds:
            raise ValueError("reference profile calibration is not registered for the method")
        if not any(
            item.dimension == self.signal_dimension and self.signal_unit in item.units
            for item in definition.input_signals
        ):
            raise ValueError("reference profile signal is not registered for the method")
        _validate_registration_profile(self)
        if self.profile_sha256 != reference_adapter_profile_sha256(self):
            raise ValueError("reference adapter profile hash is invalid")
        return self


class ReferenceAdapterRegistry:
    """Immutable exact six-method reference-profile registry."""

    def __init__(self, profiles: Sequence[ReferenceAdapterProfile] | None = None) -> None:
        supplied = default_reference_adapter_profiles() if profiles is None else profiles
        selected = tuple(
            ReferenceAdapterProfile.model_validate(item.model_dump(mode="python"))
            for item in supplied
        )
        if tuple(item.method_code for item in selected) != REFERENCE_ADAPTER_METHODS:
            raise ReferenceAdapterError(
                "REFERENCE_REGISTRY_INVALID",
                "The reference registry must contain the six ordered V1 methods.",
                next_action="Publish exactly AE, GPR, IE, MV, RT, and UT reference profiles.",
            )
        if len({item.profile_id for item in selected}) != len(selected):
            raise ReferenceAdapterError(
                "REFERENCE_PROFILE_DUPLICATE",
                "The reference registry contains a duplicate profile.",
                next_action="Publish one immutable reference profile per method.",
            )
        self._profiles = {item.method_code: item for item in selected}
        self._version = canonical_sha256([item.model_dump(mode="json") for item in selected])

    @property
    def version(self) -> str:
        return self._version

    @property
    def profiles(self) -> tuple[ReferenceAdapterProfile, ...]:
        return tuple(self._profiles[method] for method in REFERENCE_ADAPTER_METHODS)

    def resolve(
        self,
        *,
        method_code: str,
        expected_registry_version: str,
        expected_profile_sha256: str,
        fixture_id: str,
        expected_fixture_sha256: str,
    ) -> ReferenceAdapterProfile:
        if expected_registry_version != self.version:
            raise ReferenceAdapterError(
                "REFERENCE_REGISTRY_STALE",
                "The requested reference registry snapshot is stale.",
                next_action="Refresh the exact current reference registry version.",
            )
        profile = self._profiles.get(method_code)
        if profile is None:
            raise ReferenceAdapterError(
                "REFERENCE_PROFILE_NOT_FOUND",
                "The requested method has no reference profile.",
                next_action="Select one of AE, GPR, IE, MV, RT, or UT.",
            )
        if expected_profile_sha256 != profile.profile_sha256:
            raise ReferenceAdapterError(
                "REFERENCE_PROFILE_STALE",
                "The requested reference profile hash is stale.",
                next_action="Use the exact current reference profile hash.",
            )
        if fixture_id != profile.fixture_id or expected_fixture_sha256 != profile.fixture_sha256:
            raise ReferenceAdapterError(
                "REFERENCE_FIXTURE_STALE",
                "The requested deterministic fixture identity is stale or unknown.",
                next_action="Use the exact fixture identity and hash from the current profile.",
            )
        return profile


class ReferenceSimulatorOutput(StrictModel):
    schema_version: Literal["1.0.0"] = REFERENCE_ADAPTER_CONTRACT_VERSION
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_payload: str = Field(min_length=1, max_length=2_000_000)


class ReferenceAdapterExecutionResult(StrictModel):
    schema_version: Literal["1.0.0"] = REFERENCE_ADAPTER_CONTRACT_VERSION
    status: ReferenceAdapterStatus
    scope: TenantScope
    task_id: UUID
    run_id: UUID
    call_id: UUID
    reference_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_id: str
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_id: str
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_code: str
    tool_result: ToolResult
    tool_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_data: CanonicalInspectionDataset | None
    canonical_validation: CanonicalDataValidationResult | None
    failure_code: str | None
    failure_impact: str | None
    next_action: str | None
    physical_tool_calls: Literal[1] = 1
    physical_llm_calls: Literal[0] = 0
    network_calls: Literal[0] = 0
    secret_resolutions: Literal[0] = 0
    real_device_actions: Literal[0] = 0
    approval_calls: Literal[0] = 0
    publication_calls: Literal[0] = 0
    retries: Literal[0] = 0
    trust: Literal["UNTRUSTED"] = "UNTRUSTED"
    review_required: Literal[True] = True
    formal_use_eligible: Literal[False] = False
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.scope != self.tool_result.scope:
            raise ValueError("reference result scope does not match its ToolResult")
        if self.task_id != self.tool_result.task_id or self.run_id != self.tool_result.run_id:
            raise ValueError("reference result task identity does not match its ToolResult")
        if self.call_id != self.tool_result.call_id:
            raise ValueError("reference result call identity does not match its ToolResult")
        if self.tool_result_sha256 != canonical_sha256(self.tool_result.model_dump(mode="json")):
            raise ValueError("reference ToolResult hash is invalid")
        if self.status is ReferenceAdapterStatus.SUCCESS:
            if (
                self.failure_code is not None
                or self.canonical_data is None
                or self.canonical_validation is None
                or self.tool_result.status is not ToolStatus.SUCCESS
                or not self.canonical_validation.processing_eligible
                or self.canonical_validation.formal_use_eligible
            ):
                raise ValueError("successful reference result is inconsistent")
            if (
                self.canonical_data.scope != self.scope
                or self.canonical_data.method_code != self.method_code
                or self.canonical_data.origin is not DataOrigin.SIMULATED
                or self.canonical_validation.scope != self.scope
                or self.canonical_validation.dataset_id != self.canonical_data.dataset_id
                or self.canonical_validation.manifest_sha256 != self.canonical_data.manifest_sha256
            ):
                raise ValueError("successful reference canonical identity is inconsistent")
        elif (
            not self.failure_code
            or not self.failure_impact
            or not self.next_action
            or self.canonical_data is not None
            or self.canonical_validation is not None
        ):
            raise ValueError("failed reference result requires typed failure details")
        if self.result_sha256 != reference_adapter_result_sha256(self):
            raise ValueError("reference adapter result hash is invalid")
        return self


class ReferenceAdapterError(RuntimeError):
    def __init__(self, code: str, message: str, *, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class DeterministicReferenceSimulatorProvider:
    """In-process fixture provider counted as one physical tool call."""

    def __init__(self, profile: ReferenceAdapterProfile) -> None:
        self.profile = profile
        self.calls = 0

    async def execute(self, request: AdapterExecutionRequest) -> AdapterProviderReply:
        self.calls += 1
        dataset = _build_reference_dataset(self.profile, request.scope)
        payload = dump_canonical_inspection_data(dataset)
        output = ReferenceSimulatorOutput(
            profile_sha256=self.profile.profile_sha256,
            fixture_sha256=self.profile.fixture_sha256,
            registration_sha256=self.profile.registration.registration_sha256,
            manifest_sha256=dataset.manifest_sha256,
            canonical_payload=payload.decode("utf-8"),
        )
        return AdapterProviderReply(
            adapter_id=self.profile.registration.adapter_id,
            adapter_version=self.profile.registration.adapter_version,
            registration_sha256=self.profile.registration.registration_sha256,
            request_sha256=request.request_sha256,
            status=AdapterProviderStatus.SUCCESS,
            output=output.model_dump(mode="json"),
            error_code=None,
            retryable=False,
            artifacts=(),
            provider_operation_id=(
                f"reference-{self.profile.method_code.lower()}-{self.profile.fixture_version}"
            ),
            device_identity=self.profile.device_identity,
            calibration_ids=(self.profile.calibration_id,),
            model_identity=None,
            bytes_read=0,
            bytes_written=len(payload),
        )


class ReferenceAdapterRuntime:
    """Build the shared Tool Registry and validate canonical simulator output."""

    def __init__(
        self,
        reference_registry: ReferenceAdapterRegistry,
        audit: AuditService,
        *,
        providers: Mapping[str, AdapterProvider] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        event_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        supplied = dict(providers or {})
        unknown = set(supplied) - set(REFERENCE_ADAPTER_METHODS)
        if unknown:
            raise ReferenceAdapterError(
                "REFERENCE_PROVIDER_UNKNOWN",
                "A provider override targets an unknown reference method.",
                next_action="Override only AE, GPR, IE, MV, RT, or UT.",
            )
        self.reference_registry = reference_registry
        self._audit = audit
        self._clock = clock
        self._event_id_factory = event_id_factory
        self.providers: dict[str, AdapterProvider] = {}
        definitions = []
        adapters: dict[str, RegisteredAdapter] = {}
        for profile in reference_registry.profiles:
            provider = supplied.get(profile.method_code) or DeterministicReferenceSimulatorProvider(
                profile
            )
            definition = adapter_tool_definition(profile.registration)
            self.providers[profile.method_code] = provider
            definitions.append(definition)
            adapters[definition.key] = RegisteredAdapter(
                profile.registration,
                provider,
                clock=clock,
            )
        self.tool_registry = ToolRegistry(definitions, adapters, audit=audit, clock=clock)

    async def acquire(
        self,
        *,
        method_code: str,
        fixture_id: str,
        expected_reference_registry_version: str,
        expected_profile_sha256: str,
        expected_fixture_sha256: str,
        context: ToolInvocationContext,
        budget: BudgetGuard,
        observation_sha256: str,
    ) -> ReferenceAdapterExecutionResult:
        input_sha256 = canonical_sha256(
            {
                "method_code": method_code,
                "fixture_id": fixture_id,
                "expected_reference_registry_version": expected_reference_registry_version,
                "expected_profile_sha256": expected_profile_sha256,
                "expected_fixture_sha256": expected_fixture_sha256,
                "tool_registry_version": context.expected_registry_version,
            }
        )
        try:
            profile = self.reference_registry.resolve(
                method_code=method_code,
                expected_registry_version=expected_reference_registry_version,
                expected_profile_sha256=expected_profile_sha256,
                fixture_id=fixture_id,
                expected_fixture_sha256=expected_fixture_sha256,
            )
        except ReferenceAdapterError as error:
            self._record_validation(
                context,
                method_code,
                decision=error.code,
                outcome=AuditOutcome.DENIED,
                input_sha256=input_sha256,
                output_sha256=canonical_sha256({"error_code": error.code}),
            )
            raise
        definition = adapter_tool_definition(profile.registration)
        tool_result = await self.tool_registry.invoke(
            name=definition.name,
            version=definition.version,
            arguments={"fixture_id": fixture_id},
            context=context,
            budget=budget,
            observation_sha256=observation_sha256,
        )
        if tool_result.status is not ToolStatus.SUCCESS:
            result = _reference_result(
                self,
                profile,
                tool_result,
                status=ReferenceAdapterStatus.FAILED,
                canonical_data=None,
                validation=None,
                failure_code=tool_result.error_code or "REFERENCE_PROVIDER_FAILED",
                failure_impact=(
                    "The reference provider did not return a validated canonical result."
                ),
                next_action="Inspect the preserved ToolResult before a new authorized call.",
            )
            self._record_validation_result(context, result, input_sha256)
            return result
        try:
            canonical_data, validation = _validated_reference_output(profile, tool_result)
        except (CanonicalInspectionDataError, ValidationError, ValueError):
            result = _reference_result(
                self,
                profile,
                tool_result,
                status=ReferenceAdapterStatus.FAILED,
                canonical_data=None,
                validation=None,
                failure_code="REFERENCE_OUTPUT_INVALID",
                failure_impact=(
                    "Reference output failed canonical identity or provenance validation."
                ),
                next_action="Repair the exact fixture provider and publish a new profile snapshot.",
            )
            self._record_validation_result(context, result, input_sha256)
            return result
        result = _reference_result(
            self,
            profile,
            tool_result,
            status=ReferenceAdapterStatus.SUCCESS,
            canonical_data=canonical_data,
            validation=validation,
            failure_code=None,
            failure_impact=None,
            next_action=None,
        )
        self._record_validation_result(context, result, input_sha256)
        return result

    def _record_validation_result(
        self,
        context: ToolInvocationContext,
        result: ReferenceAdapterExecutionResult,
        input_sha256: str,
    ) -> None:
        self._record_validation(
            context,
            result.method_code,
            decision=(
                "AUTHORIZED"
                if result.status is ReferenceAdapterStatus.SUCCESS
                else result.failure_code or "REFERENCE_VALIDATION_FAILED"
            ),
            outcome=(
                AuditOutcome.SUCCESS
                if result.status is ReferenceAdapterStatus.SUCCESS
                else AuditOutcome.FAILED
            ),
            input_sha256=input_sha256,
            output_sha256=result.result_sha256,
        )

    def _record_validation(
        self,
        context: ToolInvocationContext,
        method_code: str,
        *,
        decision: str,
        outcome: AuditOutcome,
        input_sha256: str,
        output_sha256: str,
    ) -> None:
        self._audit.record(
            AuditRecord(
                event_id=self._event_id_factory(),
                scope=context.scope,
                kind=AuditKind.TOOL,
                action="reference.adapter.validate",
                target_type="reference.adapter",
                target_id=method_code,
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


def reference_adapter_profile_sha256(profile: ReferenceAdapterProfile) -> str:
    return canonical_sha256(profile.model_dump(mode="json", exclude={"profile_sha256"}))


def reference_adapter_result_sha256(result: ReferenceAdapterExecutionResult) -> str:
    return canonical_sha256(result.model_dump(mode="json", exclude={"result_sha256"}))


def default_reference_adapter_profiles() -> tuple[ReferenceAdapterProfile, ...]:
    definitions = _method_definitions()
    return tuple(_build_reference_profile(definitions[method]) for method in METHOD_CODES)


def build_reference_fixture_dataset(
    scope: TenantScope,
    *,
    method_code: str = "UT",
) -> CanonicalInspectionDataset:
    """Build one deterministic same-scope SIMULATED dataset without invoking a tool."""

    profiles = {profile.method_code: profile for profile in default_reference_adapter_profiles()}
    try:
        profile = profiles[method_code]
    except KeyError:
        raise ValueError("reference fixture method is not registered") from None
    return _build_reference_dataset(profile, scope)


def _build_reference_profile(definition: MethodSkillDefinition) -> ReferenceAdapterProfile:
    method = definition.method_code
    signal = definition.input_signals[0]
    fixture_id = f"reference-{method.lower()}-baseline"
    fixture_content = {
        "schema_version": REFERENCE_ADAPTER_CONTRACT_VERSION,
        "method_code": method,
        "method_definition_sha256": definition.definition_sha256,
        "fixture_id": fixture_id,
        "fixture_version": REFERENCE_ADAPTER_CONTRACT_VERSION,
        "settings": _METHOD_SETTINGS[method],
        "acquired_at": _ACQUIRED_AT.isoformat().replace("+00:00", "Z"),
    }
    fixture_sha256 = canonical_sha256(fixture_content)
    binding = _simulator_binding(method, fixture_sha256)
    registration = _simulator_registration(method, fixture_id, binding)
    values: dict[str, Any] = {
        "schema_version": REFERENCE_ADAPTER_CONTRACT_VERSION,
        "profile_id": f"reference-{method.lower()}",
        "profile_version": REFERENCE_ADAPTER_CONTRACT_VERSION,
        "method_code": method,
        "method_definition_sha256": definition.definition_sha256,
        "canonical_contract_version": CANONICAL_INSPECTION_DATA_VERSION,
        "fixture_id": fixture_id,
        "fixture_version": REFERENCE_ADAPTER_CONTRACT_VERSION,
        "fixture_sha256": fixture_sha256,
        "signal_dimension": signal.dimension,
        "signal_unit": signal.units[0],
        "calibration_kind": definition.required_calibration_kinds[0],
        "acquisition_setting_names": definition.required_acquisition_settings,
        "parser_id": f"reference-{method.lower()}-parser",
        "parser_version": REFERENCE_ADAPTER_CONTRACT_VERSION,
        "instrument_id": f"reference-{method.lower()}-device",
        "device_identity": f"reference-{method.lower()}-device",
        "calibration_id": f"reference-{method.lower()}-calibration",
        "registration": registration,
    }
    draft = ReferenceAdapterProfile.model_construct(**values, profile_sha256=_ZERO_SHA256)
    values["profile_sha256"] = reference_adapter_profile_sha256(draft)
    return ReferenceAdapterProfile.model_validate(values)


def _simulator_binding(method: str, fixture_sha256: str) -> AdapterTransportBinding:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "transport": ToolTransport.SIMULATOR,
        "simulator_id": f"ndt.reference.{method.lower()}",
        "simulator_version": REFERENCE_ADAPTER_CONTRACT_VERSION,
        "simulator_fixture_sha256": fixture_sha256,
    }
    draft = AdapterTransportBinding.model_construct(**values, binding_sha256=_ZERO_SHA256)
    values["binding_sha256"] = adapter_transport_binding_sha256(draft)
    return AdapterTransportBinding.model_validate(values)


def _simulator_registration(
    method: str,
    fixture_id: str,
    binding: AdapterTransportBinding,
) -> AdapterRegistration:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "adapter_id": f"reference.{method.lower()}",
        "adapter_version": REFERENCE_ADAPTER_CONTRACT_VERSION,
        "capability_family": AdapterCapabilityFamily.INSTRUMENT,
        "origin": AdapterOrigin.SIMULATED,
        "purpose": f"Acquire the application-owned {method} deterministic reference fixture.",
        "operation": "acquire",
        "binding": binding,
        "data_scope": ToolDataScope.TASK,
        "data_destination": ToolDataDestination.LOCAL,
        "side_effect": SideEffectClass.READ_ONLY,
        "input_schema": _reference_input_schema(fixture_id),
        "output_schema": _reference_output_schema(),
        "required_permissions": frozenset({f"reference.{method.lower()}.acquire"}),
        "secret_purposes": frozenset(),
        "network": NetworkPolicy.NONE,
        "approval_required": False,
        "idempotency": IdempotencyPolicy.NONE,
        "timeout_ms": 1_000,
        "max_attempts": 1,
        "max_concurrency": 1,
        "max_input_bytes": 1_024,
        "max_output_bytes": 2_100_000,
        "max_tokens": 0,
        "recovery_policy": ToolRecoveryPolicy.NO_RETRY,
        "requires_device_identity": True,
        "requires_calibration": True,
        "requires_model_identity": False,
        "declared_error_codes": frozenset(
            {"REFERENCE_FIXTURE_FAILED", "REFERENCE_FIXTURE_NOT_FOUND"}
        ),
        "audit_owner": "reference-adapter-runtime",
        "test_owner": "reference-adapter-runtime",
    }
    draft = AdapterRegistration.model_construct(**values, registration_sha256=_ZERO_SHA256)
    values["registration_sha256"] = adapter_registration_sha256(draft)
    return AdapterRegistration.model_validate(values)


def _reference_input_schema(fixture_id: str) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"fixture_id": {"type": "string", "enum": [fixture_id]}},
        "required": ["fixture_id"],
        "additionalProperties": False,
    }


def _reference_output_schema() -> dict[str, object]:
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string", "const": "1.0.0"},
            "profile_sha256": sha,
            "fixture_sha256": sha,
            "registration_sha256": sha,
            "manifest_sha256": sha,
            "canonical_payload": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2_000_000,
            },
        },
        "required": [
            "schema_version",
            "profile_sha256",
            "fixture_sha256",
            "registration_sha256",
            "manifest_sha256",
            "canonical_payload",
        ],
        "additionalProperties": False,
    }


def _validate_registration_profile(profile: ReferenceAdapterProfile) -> None:
    registration = profile.registration
    if (
        registration.adapter_id != f"reference.{profile.method_code.lower()}"
        or registration.adapter_version != profile.profile_version
        or registration.binding.transport is not ToolTransport.SIMULATOR
        or registration.binding.simulator_id != f"ndt.reference.{profile.method_code.lower()}"
        or registration.binding.simulator_version != profile.fixture_version
        or registration.binding.simulator_fixture_sha256 != profile.fixture_sha256
        or registration.origin is not AdapterOrigin.SIMULATED
        or registration.network is not NetworkPolicy.NONE
        or registration.secret_purposes
        or registration.side_effect is not SideEffectClass.READ_ONLY
        or registration.data_scope is not ToolDataScope.TASK
        or registration.data_destination is not ToolDataDestination.LOCAL
        or registration.operation != "acquire"
        or registration.required_permissions
        != frozenset({f"reference.{profile.method_code.lower()}.acquire"})
        or registration.approval_required
        or registration.idempotency is not IdempotencyPolicy.NONE
        or registration.max_attempts != 1
        or registration.max_concurrency != 1
        or registration.max_tokens != 0
        or registration.recovery_policy is not ToolRecoveryPolicy.NO_RETRY
        or not registration.requires_device_identity
        or not registration.requires_calibration
        or registration.requires_model_identity
        or registration.input_schema != _reference_input_schema(profile.fixture_id)
        or registration.output_schema != _reference_output_schema()
    ):
        raise ValueError("reference adapter registration does not match its simulator profile")


def _method_definitions() -> dict[str, MethodSkillDefinition]:
    return {item.method_code: item for item in default_method_definitions()}


def _build_reference_dataset(
    profile: ReferenceAdapterProfile,
    scope: TenantScope,
) -> CanonicalInspectionDataset:
    method = profile.method_code
    source_artifact = _artifact(profile, scope, "source", 8_192, "application/x-ndt-fixture")
    channel_artifact = _artifact(
        profile,
        scope,
        "channels",
        4_096,
        "application/octet-stream",
    )
    calibration_artifact = _artifact(
        profile,
        scope,
        "calibration",
        1_024,
        "application/pdf",
    )
    settings: dict[str, bool | int | str] = {
        "calibration_kind": profile.calibration_kind,
        "material_class": "REINFORCED_CONCRETE",
        "structure_class": "BRIDGE",
        **_METHOD_SETTINGS[method],
    }
    setting_payload = tuple(
        {
            "name": name,
            "value": value,
            **(
                {"dimension": "AMPLITUDE", "unit": "dB"}
                if name in {"gain_db", "preamplifier_gain_db", "threshold_db"}
                else {}
            ),
        }
        for name, value in sorted(settings.items())
    )
    payload: dict[str, Any] = {
        "dataset_id": _scoped_uuid(profile, scope, "dataset"),
        "scope": scope,
        "origin": DataOrigin.SIMULATED,
        "method_code": method,
        "topology": {
            "structure_id": _scoped_uuid(profile, scope, "structure"),
            "structure_class": "BRIDGE",
            "component_id": _scoped_uuid(profile, scope, "component"),
            "component_class": "GIRDER",
            "area_id": "reference-area-west",
            "point_id": "reference-point-01",
            "location_id": _scoped_uuid(profile, scope, "location"),
            "material_class": "REINFORCED_CONCRETE",
            "coordinates": {
                "reference": "reference-bridge-grid-v1",
                "values": (
                    {"axis": "x", "value": "12.50", "dimension": "LENGTH", "unit": "m"},
                    {"axis": "y", "value": "3.25", "dimension": "LENGTH", "unit": "m"},
                    {"axis": "z", "value": "0.00", "dimension": "LENGTH", "unit": "m"},
                ),
            },
        },
        "source": {
            "source_name": f"-参考 桥梁\n{method} 模拟数据.ndt",
            "artifact": source_artifact,
            "media_type": source_artifact.media_type,
            "source_sha256": source_artifact.sha256,
            "parser_id": profile.parser_id,
            "parser_version": profile.parser_version,
            "parser_configuration_sha256": canonical_sha256(
                {"profile_sha256": profile.profile_sha256, "parser": profile.parser_id}
            ),
            "detected_encoding": "UTF-8",
            "normalized_encoding": "UTF-8",
            "encoding_confidence": "1.00",
            "lossless": True,
        },
        "channels": tuple(
            {
                "channel_index": index,
                "channel_id": f"reference-channel-{index:02d}",
                "point_id": "reference-point-01",
                "name": "主通道" if index == 0 else "参考通道",
                "sample_count": 1_000,
                "sample_rate_hz": "1000000.00",
                "first_sample_at": _ACQUIRED_AT,
                "dimension": profile.signal_dimension,
                "unit": profile.signal_unit,
                "sample_encoding": "little-endian-int16",
                "data_artifact": channel_artifact,
                "byte_offset": index * 2_000,
                "byte_length": 2_000,
                "data_sha256": canonical_sha256(
                    {"fixture": profile.fixture_sha256, "channel": index}
                ),
            }
            for index in range(2)
        ),
        "acquired_at": _ACQUIRED_AT,
        "acquisition_settings": setting_payload,
        "instrument": {
            "instrument_id": profile.instrument_id,
            "manufacturer": "NDT Reference Fixtures",
            "model": f"{method}-REFERENCE-1",
            "serial_number": f"SIM-{method}-0001",
            "instrument_version": "1.0.0",
            "firmware_version": "1.0.0",
            "adapter_id": profile.registration.adapter_id,
            "adapter_version": profile.registration.adapter_version,
            "adapter_registration_sha256": profile.registration.registration_sha256,
        },
        "calibrations": (
            {
                "calibration_id": profile.calibration_id,
                "calibration_version": "1.0.0",
                "calibration_kind": profile.calibration_kind,
                "status": "ACTIVE",
                "instrument_id": profile.instrument_id,
                "performed_at": _ACQUIRED_AT - timedelta(days=2),
                "valid_from": _ACQUIRED_AT - timedelta(days=1),
                "valid_until": _ACQUIRED_AT + timedelta(days=30),
                "evidence_artifact": calibration_artifact,
                "evidence_sha256": calibration_artifact.sha256,
            },
        ),
        "primary_calibration_id": profile.calibration_id,
        "operator": {
            "operator_id": scope.user_id,
            "identity_version": "reference-identity-1.0.0",
            "display_name": "参考模拟操作员",
            "organization": "NDT Reference Fixtures",
            "qualifications": (f"NDT-{method}-SIMULATOR",),
        },
    }
    return build_canonical_inspection_dataset(payload)


def _artifact(
    profile: ReferenceAdapterProfile,
    scope: TenantScope,
    kind: str,
    size_bytes: int,
    media_type: str,
) -> ArtifactRef:
    artifact_id = _scoped_uuid(profile, scope, f"artifact:{kind}")
    return ArtifactRef(
        artifact_id=artifact_id,
        scope=scope,
        artifact_version="1",
        uri=f"artifact://reference-adapter/{profile.method_code.lower()}/{artifact_id}",
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=canonical_sha256({"fixture_sha256": profile.fixture_sha256, "artifact_kind": kind}),
        classification=DataClassification.INTERNAL,
        immutable=True,
    )


def _scoped_uuid(profile: ReferenceAdapterProfile, scope: TenantScope, kind: str) -> UUID:
    return uuid5(
        _REFERENCE_NAMESPACE,
        ":".join(
            (
                str(scope.tenant_id),
                str(scope.project_id),
                str(scope.user_id),
                profile.fixture_sha256,
                kind,
            )
        ),
    )


def _validated_reference_output(
    profile: ReferenceAdapterProfile,
    tool_result: ToolResult,
) -> tuple[CanonicalInspectionDataset, CanonicalDataValidationResult]:
    envelope = AdapterOutputEnvelope.model_validate(tool_result.output)
    output = ReferenceSimulatorOutput.model_validate(envelope.output)
    if (
        output.profile_sha256 != profile.profile_sha256
        or output.fixture_sha256 != profile.fixture_sha256
        or output.registration_sha256 != profile.registration.registration_sha256
        or envelope.evidence.registration_sha256 != profile.registration.registration_sha256
        or envelope.evidence.device_identity != profile.device_identity
        or envelope.evidence.calibration_ids != (profile.calibration_id,)
        or envelope.evidence.origin is not AdapterOrigin.SIMULATED
        or envelope.evidence.transport is not ToolTransport.SIMULATOR
    ):
        raise ValueError("reference provider evidence does not match the exact profile")
    encoded = output.canonical_payload.encode("utf-8")
    dataset = load_canonical_inspection_data(encoded)
    if dump_canonical_inspection_data(dataset) != encoded:
        raise ValueError("reference canonical payload is not in canonical UTF-8 form")
    if (
        dataset.scope != tool_result.scope
        or dataset.method_code != profile.method_code
        or dataset.origin is not DataOrigin.SIMULATED
        or dataset.manifest_sha256 != output.manifest_sha256
        or dataset.instrument.instrument_id != profile.instrument_id
        or dataset.instrument.adapter_id != profile.registration.adapter_id
        or dataset.instrument.adapter_version != profile.registration.adapter_version
        or dataset.instrument.adapter_registration_sha256
        != profile.registration.registration_sha256
        or dataset.primary_calibration_id != profile.calibration_id
        or dataset.calibrations[0].calibration_kind != profile.calibration_kind
        or dataset.source.parser_id != profile.parser_id
        or dataset.source.parser_version != profile.parser_version
        or dataset.channels[0].dimension != profile.signal_dimension
        or dataset.channels[0].unit != profile.signal_unit
        or tuple(item.name for item in dataset.acquisition_settings)
        != profile.acquisition_setting_names
    ):
        raise ValueError("reference canonical data does not match the exact profile")
    validation = validate_canonical_inspection_dataset(dataset)
    if not validation.processing_eligible or validation.formal_use_eligible:
        raise ValueError("reference canonical eligibility boundary is invalid")
    return dataset, validation


def _reference_result(
    runtime: ReferenceAdapterRuntime,
    profile: ReferenceAdapterProfile,
    tool_result: ToolResult,
    *,
    status: ReferenceAdapterStatus,
    canonical_data: CanonicalInspectionDataset | None,
    validation: CanonicalDataValidationResult | None,
    failure_code: str | None,
    failure_impact: str | None,
    next_action: str | None,
) -> ReferenceAdapterExecutionResult:
    payload: dict[str, Any] = {
        "schema_version": REFERENCE_ADAPTER_CONTRACT_VERSION,
        "status": status,
        "scope": tool_result.scope,
        "task_id": tool_result.task_id,
        "run_id": tool_result.run_id,
        "call_id": tool_result.call_id,
        "reference_registry_version": runtime.reference_registry.version,
        "tool_registry_version": runtime.tool_registry.version,
        "profile_id": profile.profile_id,
        "profile_sha256": profile.profile_sha256,
        "fixture_id": profile.fixture_id,
        "fixture_sha256": profile.fixture_sha256,
        "method_code": profile.method_code,
        "tool_result": tool_result,
        "tool_result_sha256": canonical_sha256(tool_result.model_dump(mode="json")),
        "canonical_data": canonical_data,
        "canonical_validation": validation,
        "failure_code": failure_code,
        "failure_impact": failure_impact,
        "next_action": next_action,
        "physical_tool_calls": 1,
        "physical_llm_calls": 0,
        "network_calls": 0,
        "secret_resolutions": 0,
        "real_device_actions": 0,
        "approval_calls": 0,
        "publication_calls": 0,
        "retries": 0,
        "trust": "UNTRUSTED",
        "review_required": True,
        "formal_use_eligible": False,
    }
    draft = ReferenceAdapterExecutionResult.model_construct(**payload, result_sha256=_ZERO_SHA256)
    payload["result_sha256"] = reference_adapter_result_sha256(draft)
    return ReferenceAdapterExecutionResult.model_validate(payload)
