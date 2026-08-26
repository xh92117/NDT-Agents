"""S5-07 separately metered provider-neutral model inference gateway."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol, Self
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, ValidationError, model_validator

from ndt_agents.contracts.v1 import ArtifactRef, StrictModel, TenantScope
from ndt_agents.inspection_data import (
    CanonicalInspectionDataset,
    validate_canonical_inspection_dataset,
)
from ndt_agents.models.profiles import (
    InspectionModelProfile,
    InspectionModelProfileError,
    InspectionModelProfileRegistry,
    MetricThresholdDirection,
    ModelReportEligibility,
)
from ndt_agents.models.registry import (
    ApiProtocol,
    CatalogOrigin,
    ModelCapability,
    ModelDataClass,
    ModelRegistryError,
    ModelResolutionContext,
    ModelSelectionRequest,
    ResolvedModelRoute,
    SelectionSource,
    canonical_sha256,
)
from ndt_agents.observability.audit import AuditKind, AuditOutcome, AuditRecord
from ndt_agents.orchestration.budget import (
    BudgetActionClass,
    BudgetContractError,
    BudgetExceeded,
    BudgetGuard,
)
from ndt_agents.security.models import SecretSelector, SecurityEnvironment

MODEL_INFERENCE_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"


class ModelProviderStatus(StrEnum):
    SUCCESS = "SUCCESS"
    REFUSED = "REFUSED"
    INCOMPLETE = "INCOMPLETE"
    RATE_LIMITED = "RATE_LIMITED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ModelInferenceStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class ApplicationInstruction(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_INFERENCE_CONTRACT_VERSION
    origin: Literal[CatalogOrigin.APPLICATION] = CatalogOrigin.APPLICATION
    instruction_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    instruction_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    text: str = Field(min_length=1, max_length=100_000)
    instruction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.instruction_sha256 != hashlib.sha256(self.text.encode("utf-8")).hexdigest():
            raise ValueError("application instruction hash is invalid")
        return self


class _ModelInferenceRequestContent(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_INFERENCE_CONTRACT_VERSION
    task_id: UUID
    run_id: UUID
    call_id: UUID
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    scope: TenantScope
    environment: SecurityEnvironment
    policy_version: str = Field(min_length=1, max_length=128)
    api_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_model_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    required_capabilities: frozenset[ModelCapability] = Field(min_length=1)
    data_class: ModelDataClass
    granted_permissions: frozenset[str]
    allow_network: bool
    allow_fallback: bool = False
    canonical_data: CanonicalInspectionDataset
    canonical_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    instruction_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    instruction_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    instruction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters: dict[str, Any] = Field(max_length=64)
    maximum_input_tokens: int = Field(ge=1, le=1_000_000)
    maximum_output_tokens: int = Field(ge=1, le=1_000_000)
    formal_use_requested: bool = False

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if self.canonical_data.scope != self.scope:
            raise ValueError("model inference canonical data must use the exact request scope")
        if self.canonical_manifest_sha256 != self.canonical_data.manifest_sha256:
            raise ValueError("model inference canonical manifest hash is invalid")
        if ModelCapability.JSON_OUTPUT not in self.required_capabilities:
            raise ValueError("inspection-model inference requires JSON output capability")
        _validate_parameters(self.parameters)
        return self


class ModelInferenceRequest(_ModelInferenceRequestContent):
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_request_hash(self) -> Self:
        if self.request_sha256 != model_inference_request_sha256(self):
            raise ValueError("model inference request hash is invalid")
        return self


class ModelMetric(StrictModel):
    metric: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    value: Decimal


class ModelProviderRequest(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_INFERENCE_CONTRACT_VERSION
    call_id: UUID
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: str
    provider_version: str
    endpoint_id: str
    endpoint_url: str
    protocol: ApiProtocol
    model_id: str
    model_snapshot: str
    secret_selector: SecretSelector
    canonical_data: CanonicalInspectionDataset
    instruction_id: str
    instruction_version: str
    instruction_text: str = Field(min_length=1, max_length=100_000)
    parameters: dict[str, Any]
    maximum_input_tokens: int
    maximum_output_tokens: int
    provider_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.provider_request_sha256 != model_provider_request_sha256(self):
            raise ValueError("model provider request hash is invalid")
        return self


class ModelProviderReply(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_INFERENCE_CONTRACT_VERSION
    call_id: UUID
    provider_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: str
    provider_version: str
    endpoint_id: str
    model_id: str
    model_snapshot: str
    provider_request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
    status: ModelProviderStatus
    output: dict[str, Any]
    artifacts: tuple[ArtifactRef, ...] = Field(max_length=256)
    input_tokens: int = Field(ge=0, le=10_000_000)
    output_tokens: int = Field(ge=0, le=10_000_000)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    metrics: tuple[ModelMetric, ...] = Field(max_length=64)
    finish_reason: str = Field(min_length=1, max_length=256)
    physical_network_calls: int = Field(ge=0, le=1)
    error_code: str | None = Field(default=None, max_length=128)
    error_impact: str | None = Field(default=None, max_length=2_000)
    next_action: str | None = Field(default=None, max_length=2_000)
    retryable: bool = False

    @model_validator(mode="after")
    def validate_reply(self) -> Self:
        metrics = tuple(item.metric for item in self.metrics)
        if metrics != tuple(sorted(set(metrics))):
            raise ValueError("provider metrics must be sorted and unique")
        artifact_ids = tuple(str(item.artifact_id) for item in self.artifacts)
        if artifact_ids != tuple(sorted(set(artifact_ids))):
            raise ValueError("provider artifacts must be sorted and unique")
        if self.status is ModelProviderStatus.SUCCESS:
            if self.error_code is not None or self.confidence is None:
                raise ValueError("successful model reply requires confidence and no error")
        elif not self.error_code or not self.error_impact or not self.next_action:
            raise ValueError("non-successful model reply requires typed failure details")
        return self


class ModelInferenceEvidence(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_INFERENCE_CONTRACT_VERSION
    scope: TenantScope
    task_id: UUID
    run_id: UUID
    call_id: UUID
    request_id: str
    api_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_id: str
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_id: str
    binding_version: str
    provider_id: str
    provider_version: str
    endpoint_id: str
    protocol: ApiProtocol
    model_id: str
    model_snapshot: str
    selection_source: SelectionSource
    canonical_dataset_id: UUID
    canonical_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    instruction_id: str
    instruction_version: str
    instruction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_request_id: str | None
    status: ModelInferenceStatus
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: tuple[ArtifactRef, ...]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    budget_policy_version: str
    confidence: Decimal | None
    metrics: tuple[ModelMetric, ...]
    finish_reason: str
    error_code: str | None
    retryable: bool
    provider_calls: Literal[1] = 1
    physical_llm_calls: Literal[1] = 1
    physical_tool_calls: Literal[0] = 0
    physical_network_calls: int = Field(ge=0, le=1)
    duration_ms: int = Field(ge=0)
    trust: Literal["UNTRUSTED"] = "UNTRUSTED"
    review_required: Literal[True] = True
    formal_human_confirmation_required: bool
    completed_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        _require_utc(self.completed_at)
        if self.evidence_sha256 != model_inference_evidence_sha256(self):
            raise ValueError("model inference evidence hash is invalid")
        return self


class ModelInferenceResult(StrictModel):
    schema_version: Literal["1.0.0"] = MODEL_INFERENCE_CONTRACT_VERSION
    status: ModelInferenceStatus
    output: dict[str, Any]
    artifacts: tuple[ArtifactRef, ...]
    confidence: Decimal | None
    evidence: ModelInferenceEvidence
    failure_code: str | None
    failure_impact: str | None
    next_action: str | None
    retryable: bool
    formal_use_candidate: bool
    trust: Literal["UNTRUSTED"] = "UNTRUSTED"
    review_required: Literal[True] = True
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status is ModelInferenceStatus.SUCCESS:
            if self.failure_code is not None:
                raise ValueError("successful inference cannot carry failure details")
        elif not self.failure_code or not self.failure_impact or not self.next_action:
            raise ValueError("non-successful inference requires typed failure details")
        if self.formal_use_candidate and not self.evidence.formal_human_confirmation_required:
            raise ValueError("formal-use candidate requires qualified human confirmation")
        if self.result_sha256 != model_inference_result_sha256(self):
            raise ValueError("model inference result hash is invalid")
        return self


class ModelInferenceProvider(Protocol):
    async def infer(self, request: ModelProviderRequest) -> object: ...


class ModelInferenceAuditSink(Protocol):
    def record(self, record: AuditRecord) -> object: ...


class ModelProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        next_action: str,
        physical_network_calls: int = 0,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.next_action = next_action
        self.physical_network_calls = physical_network_calls
        super().__init__(message)


class ModelInferenceError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool, next_action: str) -> None:
        self.code = code
        self.retryable = retryable
        self.next_action = next_action
        super().__init__(message)


class ModelInferenceGateway:
    """Authorize one route, reserve one LLM call, and validate one provider reply."""

    def __init__(
        self,
        profile_registry: InspectionModelProfileRegistry,
        instructions: Sequence[ApplicationInstruction],
        provider: ModelInferenceProvider,
        budget: BudgetGuard,
        audit: ModelInferenceAuditSink,
        *,
        utc_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic_clock: Callable[[], float] = time.monotonic,
        event_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        by_key: dict[tuple[str, str], ApplicationInstruction] = {}
        for instruction in instructions:
            key = (instruction.instruction_id, instruction.instruction_version)
            if key in by_key:
                raise ModelInferenceError(
                    "MODEL_INSTRUCTION_DUPLICATE",
                    "The application instruction identity is duplicated.",
                    retryable=False,
                    next_action="Publish one immutable instruction per ID and version.",
                )
            by_key[key] = instruction
        self._profiles = profile_registry
        self._instructions = by_key
        self._provider = provider
        self._budget = budget
        self._audit = audit
        self._utc_clock = utc_clock
        self._monotonic_clock = monotonic_clock
        self._event_id_factory = event_id_factory

    async def infer(self, request: ModelInferenceRequest) -> ModelInferenceResult:
        route = self._resolve_route(request)
        try:
            profile = self._profiles.resolve(
                profile_id=request.profile_id,
                expected_registry_version=request.profile_registry_version,
                expected_profile_sha256=request.profile_sha256,
                route=route,
                dataset=request.canonical_data,
            )
            instruction = self._resolve_instruction(request)
            self._validate_canonical_and_formal_use(request, profile)
            if profile.resources.max_concurrency > route.max_concurrency:
                self._deny("MODEL_RESOURCE_LIMIT_INVALID", "Profile concurrency exceeds the route.")
            reservation = self._budget.begin_llm_call(
                maximum_total_tokens=(request.maximum_input_tokens + request.maximum_output_tokens),
                action_class=BudgetActionClass.STANDARD,
            )
        except (InspectionModelProfileError, BudgetExceeded, BudgetContractError) as error:
            converted = _preflight_error(error)
            self._record_audit(
                request,
                route.model_id,
                "DENY",
                AuditOutcome.DENIED,
                canonical_sha256({"error_code": converted.code}),
            )
            raise converted from error
        except ModelInferenceError as error:
            self._record_audit(
                request,
                route.model_id,
                "DENY",
                AuditOutcome.DENIED,
                canonical_sha256({"error_code": error.code}),
            )
            raise

        provider_request = _provider_request(request, route, profile, instruction)
        started = self._monotonic_clock()
        try:
            raw_reply = await asyncio.wait_for(
                self._provider.infer(provider_request),
                timeout=route.timeout_ms / 1_000,
            )
        except TimeoutError:
            self._complete_failed_reservation(reservation)
            return self._failure_result(
                request,
                route,
                profile,
                provider_request,
                status=ModelInferenceStatus.TIMEOUT,
                code="MODEL_INFERENCE_TIMEOUT",
                impact="No model output is available.",
                next_action="Return preserved evidence and retry only as a new authorized call.",
                retryable=True,
                duration_ms=self._duration_ms(started),
                physical_network_calls=int(profile.runtime.network_required),
            )
        except asyncio.CancelledError:
            self._complete_failed_reservation(reservation)
            return self._failure_result(
                request,
                route,
                profile,
                provider_request,
                status=ModelInferenceStatus.CANCELLED,
                code="MODEL_INFERENCE_CANCELLED",
                impact="The model attempt was cancelled before a validated result.",
                next_action="Resume only from preserved task state with a new authorization.",
                retryable=False,
                duration_ms=self._duration_ms(started),
                physical_network_calls=int(profile.runtime.network_required),
            )
        except ModelProviderError as error:
            self._complete_failed_reservation(reservation)
            code, retryable = _validated_provider_error(profile, error.code, error.retryable)
            return self._failure_result(
                request,
                route,
                profile,
                provider_request,
                status=ModelInferenceStatus.FAILED,
                code=code,
                impact="The provider did not return a validated inference result.",
                next_action="Review provider diagnostics outside model context before a new call.",
                retryable=retryable,
                duration_ms=self._duration_ms(started),
                physical_network_calls=error.physical_network_calls,
            )
        except Exception:
            self._complete_failed_reservation(reservation)
            return self._failure_result(
                request,
                route,
                profile,
                provider_request,
                status=ModelInferenceStatus.FAILED,
                code="MODEL_PROVIDER_FAILED",
                impact="The provider attempt failed without a trusted typed response.",
                next_action="Inspect provider diagnostics outside model context before a new call.",
                retryable=False,
                duration_ms=self._duration_ms(started),
                physical_network_calls=int(profile.runtime.network_required),
            )

        try:
            reply = ModelProviderReply.model_validate(raw_reply)
        except (ValidationError, ValueError):
            self._complete_failed_reservation(reservation)
            return self._failure_result(
                request,
                route,
                profile,
                provider_request,
                status=ModelInferenceStatus.FAILED,
                code="MODEL_PROVIDER_RESPONSE_INVALID",
                impact="The provider response could not enter model context.",
                next_action="Repair the provider adapter response contract.",
                retryable=False,
                duration_ms=self._duration_ms(started),
                physical_network_calls=int(profile.runtime.network_required),
            )

        budget_error = self._complete_reply_reservation(reservation, reply)
        if budget_error is not None:
            return self._failure_result(
                request,
                route,
                profile,
                provider_request,
                status=ModelInferenceStatus.FAILED,
                code=budget_error.code,
                impact="Provider usage exceeded the reserved model budget.",
                next_action=budget_error.next_action,
                retryable=False,
                duration_ms=self._duration_ms(started),
                input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens,
                provider_request_id=reply.provider_request_id,
                physical_network_calls=reply.physical_network_calls,
            )

        validation_error = _validate_reply(request, route, profile, provider_request, reply)
        if validation_error is not None:
            return self._failure_result(
                request,
                route,
                profile,
                provider_request,
                status=validation_error.status,
                code=validation_error.code,
                impact=validation_error.impact,
                next_action=validation_error.next_action,
                retryable=validation_error.retryable,
                duration_ms=self._duration_ms(started),
                input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens,
                provider_request_id=reply.provider_request_id,
                physical_network_calls=reply.physical_network_calls,
                finish_reason=reply.finish_reason,
                metrics=reply.metrics,
                confidence=reply.confidence,
            )

        threshold_failure = _threshold_failure(profile, reply)
        if threshold_failure is not None:
            return self._result(
                request,
                route,
                profile,
                provider_request,
                status=ModelInferenceStatus.PARTIAL_SUCCESS,
                output=reply.output,
                artifacts=reply.artifacts,
                confidence=reply.confidence,
                metrics=reply.metrics,
                finish_reason=reply.finish_reason,
                input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens,
                provider_request_id=reply.provider_request_id,
                physical_network_calls=reply.physical_network_calls,
                duration_ms=self._duration_ms(started),
                failure_code="MODEL_QUALITY_THRESHOLD_FAILED",
                failure_impact="Model output failed one or more registered quality thresholds.",
                next_action=(
                    "Preserve output for review and use qualified disposition or reprocess."
                ),
                retryable=False,
                formal_use_candidate=False,
            )

        formal_candidate = (
            request.formal_use_requested
            and profile.report_eligibility is ModelReportEligibility.FORMAL_HUMAN_REQUIRED
        )
        return self._result(
            request,
            route,
            profile,
            provider_request,
            status=ModelInferenceStatus.SUCCESS,
            output=reply.output,
            artifacts=reply.artifacts,
            confidence=reply.confidence,
            metrics=reply.metrics,
            finish_reason=reply.finish_reason,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            provider_request_id=reply.provider_request_id,
            physical_network_calls=reply.physical_network_calls,
            duration_ms=self._duration_ms(started),
            failure_code=None,
            failure_impact=None,
            next_action=None,
            retryable=False,
            formal_use_candidate=formal_candidate,
        )

    def _resolve_route(self, request: ModelInferenceRequest) -> ResolvedModelRoute:
        try:
            return self._profiles.api_registry.resolve(
                binding_id=request.binding_id,
                context=ModelResolutionContext(
                    task_id=request.task_id,
                    run_id=request.run_id,
                    scope=request.scope,
                    environment=request.environment,
                    request_id=request.request_id,
                    policy_version=request.policy_version,
                    expected_registry_version=request.api_registry_version,
                    granted_permissions=request.granted_permissions,
                    allow_network=request.allow_network,
                ),
                selection=ModelSelectionRequest(
                    requested_model_id=request.requested_model_id,
                    required_capabilities=request.required_capabilities,
                    data_class=request.data_class,
                    input_tokens=request.maximum_input_tokens,
                    output_tokens=request.maximum_output_tokens,
                    allow_fallback=request.allow_fallback,
                ),
            )
        except ModelRegistryError as error:
            raise ModelInferenceError(
                error.code,
                "Model route authorization failed.",
                retryable=error.retryable,
                next_action=error.next_action,
            ) from error

    def _resolve_instruction(self, request: ModelInferenceRequest) -> ApplicationInstruction:
        instruction = self._instructions.get((request.instruction_id, request.instruction_version))
        if instruction is None or instruction.instruction_sha256 != request.instruction_sha256:
            self._deny("MODEL_INSTRUCTION_STALE", "Application instruction identity is stale.")
        assert instruction is not None
        return instruction

    @staticmethod
    def _validate_canonical_and_formal_use(
        request: ModelInferenceRequest,
        profile: InspectionModelProfile,
    ) -> None:
        validation = validate_canonical_inspection_dataset(request.canonical_data)
        if not validation.processing_eligible:
            raise ModelInferenceError(
                "MODEL_CANONICAL_INPUT_INELIGIBLE",
                "Canonical inspection data is not processing eligible.",
                retryable=False,
                next_action="Resolve canonical source validation issues before inference.",
            )
        if request.formal_use_requested and (
            not validation.formal_use_eligible
            or profile.report_eligibility is not ModelReportEligibility.FORMAL_HUMAN_REQUIRED
        ):
            raise ModelInferenceError(
                "MODEL_FORMAL_USE_DENIED",
                "Canonical data or model profile is not eligible for formal-use review.",
                retryable=False,
                next_action="Use valid production evidence and a qualified formal profile.",
            )

    def _complete_failed_reservation(self, reservation: UUID) -> None:
        try:
            self._budget.complete_llm_call(
                reservation,
                input_tokens=0,
                output_tokens=0,
                success=False,
            )
        except (BudgetExceeded, BudgetContractError):
            return

    def _complete_reply_reservation(
        self,
        reservation: UUID,
        reply: ModelProviderReply,
    ) -> ModelInferenceError | None:
        try:
            self._budget.complete_llm_call(
                reservation,
                input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens,
                success=reply.status is ModelProviderStatus.SUCCESS,
            )
        except BudgetExceeded as error:
            return ModelInferenceError(
                error.code,
                "Provider usage exceeded the reserved model budget.",
                retryable=False,
                next_action=error.next_action,
            )
        except BudgetContractError as error:
            return ModelInferenceError(
                error.code,
                "Model token telemetry violated the budget contract.",
                retryable=False,
                next_action="Stop model execution and reconcile budget telemetry.",
            )
        return None

    def _failure_result(
        self,
        request: ModelInferenceRequest,
        route: ResolvedModelRoute,
        profile: InspectionModelProfile,
        provider_request: ModelProviderRequest,
        *,
        status: ModelInferenceStatus,
        code: str,
        impact: str,
        next_action: str,
        retryable: bool,
        duration_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        provider_request_id: str | None = None,
        physical_network_calls: int = 0,
        finish_reason: str = "failed",
        metrics: tuple[ModelMetric, ...] = (),
        confidence: Decimal | None = None,
    ) -> ModelInferenceResult:
        return self._result(
            request,
            route,
            profile,
            provider_request,
            status=status,
            output={},
            artifacts=(),
            confidence=confidence,
            metrics=metrics,
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_request_id=provider_request_id,
            physical_network_calls=physical_network_calls,
            duration_ms=duration_ms,
            failure_code=code,
            failure_impact=impact,
            next_action=next_action,
            retryable=retryable,
            formal_use_candidate=False,
        )

    def _result(
        self,
        request: ModelInferenceRequest,
        route: ResolvedModelRoute,
        profile: InspectionModelProfile,
        provider_request: ModelProviderRequest,
        *,
        status: ModelInferenceStatus,
        output: dict[str, Any],
        artifacts: tuple[ArtifactRef, ...],
        confidence: Decimal | None,
        metrics: tuple[ModelMetric, ...],
        finish_reason: str,
        input_tokens: int,
        output_tokens: int,
        provider_request_id: str | None,
        physical_network_calls: int,
        duration_ms: int,
        failure_code: str | None,
        failure_impact: str | None,
        next_action: str | None,
        retryable: bool,
        formal_use_candidate: bool,
    ) -> ModelInferenceResult:
        completed_at = self._utc_clock()
        evidence_payload: dict[str, object] = {
            "schema_version": MODEL_INFERENCE_CONTRACT_VERSION,
            "scope": request.scope,
            "task_id": request.task_id,
            "run_id": request.run_id,
            "call_id": request.call_id,
            "request_id": request.request_id,
            "api_registry_version": route.registry_version,
            "profile_registry_version": self._profiles.version,
            "profile_id": profile.profile_id,
            "profile_sha256": profile.profile_sha256,
            "binding_id": route.binding_id,
            "binding_version": route.binding_version,
            "provider_id": route.provider_id,
            "provider_version": route.provider_version,
            "endpoint_id": route.endpoint_id,
            "protocol": route.protocol,
            "model_id": route.model_id,
            "model_snapshot": route.model_snapshot,
            "selection_source": route.selection_source,
            "canonical_dataset_id": request.canonical_data.dataset_id,
            "canonical_manifest_sha256": request.canonical_manifest_sha256,
            "instruction_id": request.instruction_id,
            "instruction_version": request.instruction_version,
            "instruction_sha256": request.instruction_sha256,
            "parameters_sha256": canonical_sha256(request.parameters),
            "request_sha256": request.request_sha256,
            "provider_request_sha256": provider_request.provider_request_sha256,
            "provider_request_id": provider_request_id,
            "status": status,
            "output_sha256": canonical_sha256(
                output if failure_code is None else {"error": failure_code}
            ),
            "artifacts": artifacts,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "budget_policy_version": route.budget_policy_version,
            "confidence": confidence,
            "metrics": metrics,
            "finish_reason": finish_reason,
            "error_code": failure_code,
            "retryable": retryable,
            "provider_calls": 1,
            "physical_llm_calls": 1,
            "physical_tool_calls": 0,
            "physical_network_calls": physical_network_calls,
            "duration_ms": duration_ms,
            "trust": "UNTRUSTED",
            "review_required": True,
            "formal_human_confirmation_required": formal_use_candidate,
            "completed_at": completed_at,
        }
        evidence = ModelInferenceEvidence.model_validate(
            {
                **evidence_payload,
                "evidence_sha256": canonical_sha256(_jsonable(evidence_payload)),
            }
        )
        result_payload: dict[str, object] = {
            "schema_version": MODEL_INFERENCE_CONTRACT_VERSION,
            "status": status,
            "output": output,
            "artifacts": artifacts,
            "confidence": confidence,
            "evidence": evidence,
            "failure_code": failure_code,
            "failure_impact": failure_impact,
            "next_action": next_action,
            "retryable": retryable,
            "formal_use_candidate": formal_use_candidate,
            "trust": "UNTRUSTED",
            "review_required": True,
        }
        result = ModelInferenceResult.model_validate(
            {
                **result_payload,
                "result_sha256": canonical_sha256(_jsonable(result_payload)),
            }
        )
        self._record_audit(
            request,
            route.model_id,
            "ALLOW",
            AuditOutcome.SUCCESS if status is ModelInferenceStatus.SUCCESS else AuditOutcome.FAILED,
            result.result_sha256,
        )
        return result

    def _record_audit(
        self,
        request: ModelInferenceRequest,
        target_id: str,
        decision: str,
        outcome: AuditOutcome,
        output_sha256: str,
    ) -> None:
        self._audit.record(
            AuditRecord(
                event_id=self._event_id_factory(),
                scope=request.scope,
                kind=AuditKind.MODEL,
                action="model.inference.execute",
                target_type="model.inference",
                target_id=target_id,
                task_id=request.task_id,
                policy_version=request.policy_version,
                decision=decision,
                outcome=outcome,
                input_sha256=request.request_sha256,
                output_sha256=output_sha256,
                request_id=request.request_id,
                occurred_at=self._utc_clock(),
            )
        )

    def _duration_ms(self, started: float) -> int:
        return max(0, int((self._monotonic_clock() - started) * 1_000))

    @staticmethod
    def _deny(code: str, message: str) -> None:
        raise ModelInferenceError(
            code,
            message,
            retryable=False,
            next_action="Refresh and validate the exact registered model input.",
        )


class _ReplyValidationError(StrictModel):
    status: ModelInferenceStatus
    code: str
    impact: str
    next_action: str
    retryable: bool


def build_application_instruction(
    *,
    instruction_id: str,
    instruction_version: str,
    text: str,
) -> ApplicationInstruction:
    return ApplicationInstruction(
        instruction_id=instruction_id,
        instruction_version=instruction_version,
        text=text,
        instruction_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def build_model_inference_request(
    payload: Mapping[str, object],
) -> ModelInferenceRequest:
    content = dict(payload)
    content.pop("request_sha256", None)
    content.setdefault("schema_version", MODEL_INFERENCE_CONTRACT_VERSION)
    normalized = _ModelInferenceRequestContent.model_validate(content).model_dump(mode="json")
    return ModelInferenceRequest.model_validate(
        {
            **normalized,
            "request_sha256": canonical_sha256(normalized),
        }
    )


def model_inference_request_sha256(request: ModelInferenceRequest) -> str:
    return canonical_sha256(request.model_dump(mode="json", exclude={"request_sha256"}))


def model_provider_request_sha256(request: ModelProviderRequest) -> str:
    return canonical_sha256(request.model_dump(mode="json", exclude={"provider_request_sha256"}))


def model_inference_evidence_sha256(evidence: ModelInferenceEvidence) -> str:
    return canonical_sha256(evidence.model_dump(mode="json", exclude={"evidence_sha256"}))


def model_inference_result_sha256(result: ModelInferenceResult) -> str:
    return canonical_sha256(result.model_dump(mode="json", exclude={"result_sha256"}))


def _provider_request(
    request: ModelInferenceRequest,
    route: ResolvedModelRoute,
    profile: InspectionModelProfile,
    instruction: ApplicationInstruction,
) -> ModelProviderRequest:
    payload: dict[str, object] = {
        "schema_version": MODEL_INFERENCE_CONTRACT_VERSION,
        "call_id": request.call_id,
        "request_sha256": request.request_sha256,
        "profile_sha256": profile.profile_sha256,
        "provider_id": route.provider_id,
        "provider_version": route.provider_version,
        "endpoint_id": route.endpoint_id,
        "endpoint_url": route.endpoint_url,
        "protocol": route.protocol,
        "model_id": route.model_id,
        "model_snapshot": route.model_snapshot,
        "secret_selector": route.secret_selector,
        "canonical_data": request.canonical_data,
        "instruction_id": instruction.instruction_id,
        "instruction_version": instruction.instruction_version,
        "instruction_text": instruction.text,
        "parameters": request.parameters,
        "maximum_input_tokens": request.maximum_input_tokens,
        "maximum_output_tokens": request.maximum_output_tokens,
    }
    return ModelProviderRequest.model_validate(
        {
            **payload,
            "provider_request_sha256": canonical_sha256(_jsonable(payload)),
        }
    )


def _validate_reply(
    request: ModelInferenceRequest,
    route: ResolvedModelRoute,
    profile: InspectionModelProfile,
    provider_request: ModelProviderRequest,
    reply: ModelProviderReply,
) -> _ReplyValidationError | None:
    if (
        reply.call_id != request.call_id
        or reply.provider_request_sha256 != provider_request.provider_request_sha256
        or reply.provider_id != route.provider_id
        or reply.provider_version != route.provider_version
        or reply.endpoint_id != route.endpoint_id
        or reply.model_id != route.model_id
        or reply.model_snapshot != route.model_snapshot
    ):
        return _reply_error(
            "MODEL_PROVIDER_IDENTITY_INVALID",
            "Provider response identity is not bound to the authorized route.",
        )
    if (
        reply.input_tokens > request.maximum_input_tokens
        or reply.output_tokens > request.maximum_output_tokens
    ):
        return _reply_error(
            "MODEL_USAGE_LIMIT_EXCEEDED",
            "Provider usage exceeds the per-direction request limit.",
        )
    for artifact in reply.artifacts:
        if artifact.scope != request.scope or not artifact.immutable:
            return _reply_error(
                "MODEL_ARTIFACT_INVALID",
                "Provider artifact is mutable or outside the exact request scope.",
            )
    if reply.status is not ModelProviderStatus.SUCCESS:
        assert reply.error_code is not None
        code, retryable = _validated_provider_error(profile, reply.error_code, reply.retryable)
        status = (
            ModelInferenceStatus.PARTIAL_SUCCESS
            if reply.status is ModelProviderStatus.INCOMPLETE
            else ModelInferenceStatus.CANCELLED
            if reply.status is ModelProviderStatus.CANCELLED
            else ModelInferenceStatus.FAILED
        )
        return _ReplyValidationError(
            status=status,
            code=code,
            impact="The provider did not return a complete validated result.",
            next_action="Review provider diagnostics outside model context before a new call.",
            retryable=retryable,
        )
    try:
        _validate_plain_json(reply.output)
        output_bytes = len(_canonical_json(reply.output).encode("utf-8"))
        if output_bytes > profile.resources.max_output_bytes:
            raise ValueError("model output exceeds its byte limit")
        Draft202012Validator(profile.output_schema).validate(reply.output)
    except Exception:
        return _reply_error(
            "MODEL_OUTPUT_SCHEMA_INVALID",
            "Provider output failed the strict registered output schema.",
        )
    return None


def _threshold_failure(
    profile: InspectionModelProfile,
    reply: ModelProviderReply,
) -> bool | None:
    values = {item.metric: item.value for item in reply.metrics}
    for threshold in profile.thresholds:
        actual = values.get(threshold.metric)
        if actual is None:
            return True
        if threshold.direction is MetricThresholdDirection.MINIMUM:
            if actual < threshold.value:
                return True
        elif actual > threshold.value:
            return True
    return None


def _validated_provider_error(
    profile: InspectionModelProfile,
    code: str,
    retryable: bool,
) -> tuple[str, bool]:
    if code not in profile.declared_error_codes:
        return "MODEL_PROVIDER_ERROR_UNDECLARED", False
    expected_retryable = code in profile.retryable_error_codes
    if retryable != expected_retryable:
        return "MODEL_PROVIDER_RETRYABILITY_INVALID", False
    return code, retryable


def _reply_error(code: str, impact: str) -> _ReplyValidationError:
    return _ReplyValidationError(
        status=ModelInferenceStatus.FAILED,
        code=code,
        impact=impact,
        next_action="Repair and revalidate the provider adapter before a new call.",
        retryable=False,
    )


def _preflight_error(
    error: InspectionModelProfileError | BudgetExceeded | BudgetContractError,
) -> ModelInferenceError:
    if isinstance(error, InspectionModelProfileError):
        return ModelInferenceError(
            error.code,
            "Inspection-model profile authorization failed.",
            retryable=False,
            next_action=error.next_action,
        )
    if isinstance(error, BudgetExceeded):
        return ModelInferenceError(
            error.code,
            "Model budget authorization failed.",
            retryable=False,
            next_action=error.next_action,
        )
    return ModelInferenceError(
        error.code,
        "Model budget contract is invalid.",
        retryable=False,
        next_action="Repair the versioned budget request before inference.",
    )


def _validate_parameters(parameters: Mapping[str, object]) -> None:
    forbidden = {"api_key", "authorization", "credential", "password", "secret"}
    if any(key.lower() in forbidden for key in parameters):
        raise ValueError("model inference parameters cannot contain credential fields")
    _validate_plain_json(parameters)


def _validate_plain_json(value: object) -> None:
    if value is None or isinstance(value, (bool, int, str, Decimal)):
        return
    if isinstance(value, float):
        raise ValueError("floating model payload values must use exact Decimal text")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("model payload object keys must be strings")
            _validate_plain_json(item)
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            _validate_plain_json(item)
        return
    raise ValueError("model payload must contain strict JSON-compatible values")


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (StrEnum, UUID, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("model inference evidence time must use UTC")
