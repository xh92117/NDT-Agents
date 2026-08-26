"""S5-07 inspection-model profile, metering, provider, and evidence tests."""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import ArtifactRef, Limit
from ndt_agents.inspection_data import (
    CanonicalInspectionDataset,
    build_canonical_inspection_dataset,
)
from ndt_agents.models.inference import (
    ApplicationInstruction,
    ModelInferenceError,
    ModelInferenceGateway,
    ModelInferenceRequest,
    ModelInferenceResult,
    ModelInferenceStatus,
    ModelProviderError,
    ModelProviderReply,
    ModelProviderRequest,
    ModelProviderStatus,
    build_application_instruction,
    build_model_inference_request,
    model_inference_evidence_sha256,
    model_inference_request_sha256,
    model_inference_result_sha256,
)
from ndt_agents.models.profiles import (
    InspectionModelProfile,
    InspectionModelProfileError,
    InspectionModelProfileRegistry,
    ModelReportEligibility,
    build_inspection_model_profile,
    canonical_inspection_input_schema_sha256,
    inspection_model_profile_sha256,
)
from ndt_agents.models.registry import (
    CatalogOrigin,
    ModelCapability,
    ModelDataClass,
    ProviderBinding,
    canonical_sha256,
)
from ndt_agents.observability import AuditKind, AuditService
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.professional.processing import DataOrigin
from tests.contracts.test_canonical_inspection_data import (
    artifact_payload,
    manifest_payload,
)
from tests.models.test_model_api_registry import (
    OTHER_SCOPE,
    RUN_ID,
    SCOPE,
    TASK_ID,
    Runtime,
    binding,
)

CALL_ID = UUID("00000000-0000-4000-8000-000000000401")
NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "classification": {"type": "string", "enum": ["NO_INDICATION", "INDICATION"]},
        "summary": {"type": "string", "maxLength": 512},
    },
    "required": ["classification", "summary"],
}


def evidence_scope_payload(scope_id: str, *, origin: str = "SYNTHETIC") -> dict[str, object]:
    return {
        "scope_id": scope_id,
        "version": "1.0.0",
        "origin": origin,
        "method_codes": ("UT",),
        "structure_classes": ("BRIDGE",),
        "material_classes": ("REINFORCED_CONCRETE",),
        "record_count": 120,
        "evidence_sha256": canonical_sha256({"scope": scope_id}),
        "rights_verified": True,
        "deidentified": True,
        "evaluated_on": date(2026, 8, 25),
    }


def profile_payload(
    *,
    report_eligibility: ModelReportEligibility = ModelReportEligibility.PRELIMINARY_REVIEW,
) -> dict[str, object]:
    return {
        "profile_id": "ut-indication-profile",
        "profile_version": "1.0.0",
        "provider_id": "deepseek",
        "model_id": "deepseek-v4-pro",
        "model_snapshot": "DeepSeek-V4-Pro-0813",
        "method_codes": ("UT",),
        "structure_classes": ("BRIDGE",),
        "material_classes": ("REINFORCED_CONCRETE",),
        "input_schema_sha256": canonical_inspection_input_schema_sha256(),
        "output_schema_id": "ut-model-output@1.0.0",
        "output_schema": OUTPUT_SCHEMA,
        "output_schema_sha256": canonical_sha256(OUTPUT_SCHEMA),
        "training_scope": evidence_scope_payload("ut-training-v1"),
        "validation_scope": evidence_scope_payload(
            "ut-validation-v1",
            origin=(
                "PRODUCTION"
                if report_eligibility is ModelReportEligibility.FORMAL_HUMAN_REQUIRED
                else "SYNTHETIC"
            ),
        ),
        "thresholds": ({"metric": "quality_score", "direction": "MINIMUM", "value": "0.90"},),
        "runtime": {
            "kind": "DETERMINISTIC_FIXTURE",
            "runtime_id": "deterministic-ut-fixture",
            "runtime_version": "1.0.0",
            "artifact_sha256": canonical_sha256({"fixture": "ut"}),
            "precision": "decimal",
            "deterministic": True,
            "network_required": False,
        },
        "resources": {
            "cpu_cores": 1,
            "memory_mb": 256,
            "accelerator": None,
            "accelerator_memory_mb": 0,
            "max_concurrency": 1,
            "max_output_bytes": 10_000,
        },
        "declared_error_codes": (
            "MODEL_INCOMPLETE",
            "MODEL_RATE_LIMITED",
            "MODEL_REFUSED",
        ),
        "retryable_error_codes": ("MODEL_RATE_LIMITED",),
        "report_eligibility": report_eligibility,
        "independently_validated": (
            report_eligibility is ModelReportEligibility.FORMAL_HUMAN_REQUIRED
        ),
    }


def dataset(
    *,
    origin: DataOrigin = DataOrigin.PRODUCTION,
    method: str = "UT",
    lossless: bool = True,
) -> CanonicalInspectionDataset:
    payload = cast(dict[str, Any], manifest_payload(method, origin=origin))
    payload["source"]["lossless"] = lossless
    scope = SCOPE.model_dump()
    payload["scope"] = scope
    payload["source"]["artifact"]["scope"] = scope
    for channel in payload["channels"]:
        channel["data_artifact"]["scope"] = scope
    for calibration in payload["calibrations"]:
        calibration["evidence_artifact"]["scope"] = scope
    payload["operator"]["operator_id"] = SCOPE.user_id
    return build_canonical_inspection_dataset(payload)


def instruction() -> ApplicationInstruction:
    return build_application_instruction(
        instruction_id="ut-indication-classifier",
        instruction_version="1.0.0",
        text="Classify the supplied canonical synthetic UT evidence as structured JSON.",
    )


def request_payload(
    api_runtime: Runtime,
    profiles: InspectionModelProfileRegistry,
    selected_profile: InspectionModelProfile,
    **updates: object,
) -> dict[str, object]:
    selected_instruction = instruction()
    canonical = dataset()
    values: dict[str, object] = {
        "task_id": TASK_ID,
        "run_id": RUN_ID,
        "call_id": CALL_ID,
        "request_id": "model-inference-request-1",
        "scope": SCOPE,
        "environment": "local",
        "policy_version": "model-policy-1",
        "api_registry_version": api_runtime.registry.version,
        "profile_registry_version": profiles.version,
        "binding_id": "personal-deepseek",
        "profile_id": selected_profile.profile_id,
        "profile_sha256": selected_profile.profile_sha256,
        "requested_model_id": selected_profile.model_id,
        "required_capabilities": frozenset(
            {ModelCapability.JSON_OUTPUT, ModelCapability.TEXT_OUTPUT}
        ),
        "data_class": ModelDataClass.SYNTHETIC,
        "granted_permissions": frozenset({"model.invoke.deepseek"}),
        "allow_network": True,
        "allow_fallback": False,
        "canonical_data": canonical,
        "canonical_manifest_sha256": canonical.manifest_sha256,
        "instruction_id": selected_instruction.instruction_id,
        "instruction_version": selected_instruction.instruction_version,
        "instruction_sha256": selected_instruction.instruction_sha256,
        "parameters": {"temperature": "0", "top_p": "1"},
        "maximum_input_tokens": 100,
        "maximum_output_tokens": 100,
        "formal_use_requested": False,
    }
    values.update(updates)
    return values


class DeterministicProvider:
    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.calls = 0
        self.last_request: ModelProviderRequest | None = None

    async def infer(self, request: ModelProviderRequest) -> object:
        self.calls += 1
        self.last_request = request
        if self.mode == "timeout":
            await asyncio.sleep(0.05)
        if self.mode == "cancelled_exception":
            raise asyncio.CancelledError
        if self.mode == "generic_exception":
            raise RuntimeError("provider diagnostic containing forbidden-secret")
        if self.mode == "typed_exception":
            raise ModelProviderError(
                "MODEL_RATE_LIMITED",
                "rate limited",
                retryable=True,
                next_action="Wait for an approved new call window.",
            )
        if self.mode == "malformed":
            return {"unknown": "provider-secret-value"}

        status = ModelProviderStatus.SUCCESS
        error_code: str | None = None
        retryable = False
        if self.mode in {
            "refused",
            "incomplete",
            "rate_limited",
            "undeclared",
            "retry_mismatch",
            "cancelled_reply",
            "provider_text_secret",
        }:
            status = {
                "refused": ModelProviderStatus.REFUSED,
                "incomplete": ModelProviderStatus.INCOMPLETE,
                "rate_limited": ModelProviderStatus.RATE_LIMITED,
                "undeclared": ModelProviderStatus.FAILED,
                "retry_mismatch": ModelProviderStatus.RATE_LIMITED,
                "cancelled_reply": ModelProviderStatus.CANCELLED,
                "provider_text_secret": ModelProviderStatus.RATE_LIMITED,
            }[self.mode]
            error_code = {
                "refused": "MODEL_REFUSED",
                "incomplete": "MODEL_INCOMPLETE",
                "rate_limited": "MODEL_RATE_LIMITED",
                "undeclared": "UNKNOWN_PROVIDER_FAILURE",
                "retry_mismatch": "MODEL_RATE_LIMITED",
                "cancelled_reply": "MODEL_INCOMPLETE",
                "provider_text_secret": "MODEL_RATE_LIMITED",
            }[self.mode]
            retryable = self.mode in {"rate_limited", "provider_text_secret"}

        output: dict[str, object] = {
            "classification": "NO_INDICATION",
            "summary": "Synthetic deterministic result.",
        }
        if status is not ModelProviderStatus.SUCCESS:
            output = {}
        if self.mode == "schema_invalid":
            output = {"classification": "UNKNOWN"}

        reply: dict[str, object] = {
            "call_id": request.call_id,
            "provider_request_sha256": request.provider_request_sha256,
            "provider_id": request.provider_id,
            "provider_version": request.provider_version,
            "endpoint_id": request.endpoint_id,
            "model_id": request.model_id,
            "model_snapshot": request.model_snapshot,
            "provider_request_id": "provider-request-1",
            "status": status,
            "output": output,
            "artifacts": (),
            "input_tokens": 60,
            "output_tokens": 40,
            "confidence": "0.97" if status is ModelProviderStatus.SUCCESS else None,
            "metrics": (
                {
                    "metric": "quality_score",
                    "value": "0.80" if self.mode == "low_quality" else "0.96",
                },
            ),
            "finish_reason": "stop" if status is ModelProviderStatus.SUCCESS else self.mode,
            "physical_network_calls": 0,
            "error_code": error_code,
            "error_impact": (
                "No complete model output is available." if error_code is not None else None
            ),
            "next_action": (
                "Review provider evidence before a new call." if error_code is not None else None
            ),
            "retryable": retryable,
        }
        if self.mode == "identity_mismatch":
            reply["model_snapshot"] = "changed-snapshot"
        if self.mode == "usage_overrun":
            reply["input_tokens"] = 150
            reply["output_tokens"] = 100
        if self.mode == "artifact_invalid":
            reply["artifacts"] = (
                ArtifactRef.model_validate(
                    artifact_payload(
                        "50000000-0000-4000-8000-000000000099",
                        owner=OTHER_SCOPE.model_dump(),
                    )
                ),
            )
        if self.mode == "provider_text_secret":
            reply["error_impact"] = "forbidden-provider-secret"
            reply["next_action"] = "Reuse forbidden-provider-secret"
        return ModelProviderReply.model_validate(reply)


class InferenceRuntime:
    def __init__(
        self,
        *,
        provider: DeterministicProvider | None = None,
        selected_binding: ProviderBinding | None = None,
        selected_profile: InspectionModelProfile | None = None,
        budget: BudgetGuard | None = None,
    ) -> None:
        self.api = Runtime(route=selected_binding)
        self.profile = selected_profile or build_inspection_model_profile(profile_payload())
        self.profiles = InspectionModelProfileRegistry(self.api.registry, (self.profile,))
        self.provider = provider or DeterministicProvider()
        self.budget = budget or BudgetGuard(default_budget_policy("P1"))
        self.audit = AuditService(self.api.repository, self.api.traces)
        event_ids = iter(UUID(int=value) for value in range(2_000, 4_000))
        self.gateway = ModelInferenceGateway(
            self.profiles,
            (instruction(),),
            self.provider,
            self.budget,
            self.audit,
            utc_clock=lambda: NOW,
            monotonic_clock=lambda: 10.0,
            event_id_factory=event_ids.__next__,
        )

    def request(self, **updates: object) -> ModelInferenceRequest:
        return build_model_inference_request(
            request_payload(self.api, self.profiles, self.profile, **updates)
        )

    def run(self, request: ModelInferenceRequest | None = None) -> ModelInferenceResult:
        with self.api.traces.start_span("model.inference"):
            return asyncio.run(self.gateway.infer(request or self.request()))

    def close(self) -> None:
        self.api.close()


def test_profile_and_registry_hashes_are_stable_and_exact() -> None:
    runtime = Runtime()
    first = build_inspection_model_profile(profile_payload())
    second = build_inspection_model_profile(dict(reversed(tuple(profile_payload().items()))))
    try:
        first_registry = InspectionModelProfileRegistry(runtime.registry, (first,))
        second_registry = InspectionModelProfileRegistry(runtime.registry, (second,))
        assert first == second
        assert first.profile_sha256 == inspection_model_profile_sha256(first)
        assert first_registry.version == second_registry.version
        assert first.input_schema_sha256 == canonical_inspection_input_schema_sha256()
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "mutation",
    (
        "origin",
        "input_hash",
        "output_hash",
        "external_ref",
        "unsorted_method",
        "retry_subset",
        "formal_unvalidated",
        "runtime_unpinned",
        "resource_unbounded",
        "unresolved_ref",
    ),
)
def test_profile_contract_rejects_untrusted_or_incomplete_metadata(mutation: str) -> None:
    payload = profile_payload()
    if mutation == "origin":
        payload["origin"] = CatalogOrigin.UNTRUSTED
    elif mutation == "input_hash":
        payload["input_schema_sha256"] = "f" * 64
    elif mutation == "output_hash":
        payload["output_schema_sha256"] = "f" * 64
    elif mutation == "external_ref":
        schema = copy.deepcopy(OUTPUT_SCHEMA)
        schema["properties"]["summary"] = {"$ref": "https://example.com/schema"}
        payload["output_schema"] = schema
        payload["output_schema_sha256"] = canonical_sha256(schema)
    elif mutation == "unresolved_ref":
        schema = copy.deepcopy(OUTPUT_SCHEMA)
        schema["properties"]["summary"] = {"$ref": "#/$defs/missing"}
        payload["output_schema"] = schema
        payload["output_schema_sha256"] = canonical_sha256(schema)
    elif mutation == "unsorted_method":
        payload["method_codes"] = ("UT", "AE")
    elif mutation == "retry_subset":
        payload["retryable_error_codes"] = ("UNKNOWN",)
    elif mutation == "formal_unvalidated":
        payload["report_eligibility"] = ModelReportEligibility.FORMAL_HUMAN_REQUIRED
    elif mutation == "runtime_unpinned":
        runtime = cast(dict[str, object], payload["runtime"])
        payload["runtime"] = {**runtime, "artifact_sha256": None}
    else:
        resources = cast(dict[str, object], payload["resources"])
        payload["resources"] = {**resources, "max_concurrency": 65}

    with pytest.raises((ValidationError, ValueError)):
        build_inspection_model_profile(payload)


def test_profile_registry_rejects_duplicate_and_cross_catalog_snapshot() -> None:
    runtime = Runtime()
    profile = build_inspection_model_profile(profile_payload())
    try:
        with pytest.raises(InspectionModelProfileError) as duplicate:
            InspectionModelProfileRegistry(runtime.registry, (profile, profile))
        assert duplicate.value.code == "MODEL_PROFILE_DUPLICATE"

        changed = profile.model_copy(update={"model_snapshot": "unknown-snapshot"})
        with pytest.raises(InspectionModelProfileError) as mismatch:
            InspectionModelProfileRegistry(runtime.registry, (changed,))
        assert mismatch.value.code == "MODEL_PROFILE_CATALOG_MISMATCH"
    finally:
        runtime.close()


def test_success_is_separately_metered_untrusted_and_hash_bound() -> None:
    runtime = InferenceRuntime()
    try:
        request = runtime.request()
        result = runtime.run(request)
        telemetry = runtime.budget.telemetry().counters
        events = runtime.api.repository.list(SCOPE)

        assert result.status is ModelInferenceStatus.SUCCESS
        assert result.output["classification"] == "NO_INDICATION"
        assert result.trust == "UNTRUSTED"
        assert result.review_required
        assert not result.formal_use_candidate
        assert result.result_sha256 == model_inference_result_sha256(result)
        assert result.evidence.evidence_sha256 == model_inference_evidence_sha256(result.evidence)
        assert result.evidence.request_sha256 == request.request_sha256
        assert result.evidence.canonical_manifest_sha256 == request.canonical_manifest_sha256
        assert result.evidence.provider_calls == 1
        assert result.evidence.physical_llm_calls == 1
        assert result.evidence.physical_tool_calls == 0
        assert result.evidence.input_tokens == 60
        assert result.evidence.output_tokens == 40
        assert runtime.provider.calls == 1
        assert runtime.provider.last_request is not None
        assert runtime.provider.last_request.secret_selector.secret_id == "deepseek-api-key"
        assert "plaintext" not in runtime.provider.last_request.model_dump_json()
        assert telemetry.physical_llm_calls == 1
        assert telemetry.physical_tool_calls == 0
        assert telemetry.actual_total_tokens == 100
        assert telemetry.reserved_total_tokens == 0
        assert [event.kind for event in events] == [AuditKind.MODEL, AuditKind.MODEL]
        assert [event.action for event in events] == [
            "model.route.resolve",
            "model.inference.execute",
        ]
        assert "Synthetic deterministic result" not in " ".join(
            event.model_dump_json() for event in events
        )
    finally:
        runtime.close()


def test_request_hash_is_stable_across_unordered_input_insertion() -> None:
    runtime = InferenceRuntime()
    try:
        forward = runtime.request(
            required_capabilities=frozenset(
                (ModelCapability.JSON_OUTPUT, ModelCapability.TEXT_OUTPUT)
            ),
            granted_permissions=frozenset(("model.invoke.deepseek", "model.read.public")),
        )
        reverse = runtime.request(
            required_capabilities=frozenset(
                (ModelCapability.TEXT_OUTPUT, ModelCapability.JSON_OUTPUT)
            ),
            granted_permissions=frozenset(("model.read.public", "model.invoke.deepseek")),
        )

        assert forward.request_sha256 == reverse.request_sha256
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("mode", "status", "code", "retryable"),
    (
        ("refused", ModelInferenceStatus.FAILED, "MODEL_REFUSED", False),
        ("incomplete", ModelInferenceStatus.PARTIAL_SUCCESS, "MODEL_INCOMPLETE", False),
        ("rate_limited", ModelInferenceStatus.FAILED, "MODEL_RATE_LIMITED", True),
        ("undeclared", ModelInferenceStatus.FAILED, "MODEL_PROVIDER_ERROR_UNDECLARED", False),
        (
            "retry_mismatch",
            ModelInferenceStatus.FAILED,
            "MODEL_PROVIDER_RETRYABILITY_INVALID",
            False,
        ),
        ("cancelled_reply", ModelInferenceStatus.CANCELLED, "MODEL_INCOMPLETE", False),
    ),
)
def test_provider_terminal_states_are_typed_without_retry(
    mode: str,
    status: ModelInferenceStatus,
    code: str,
    retryable: bool,
) -> None:
    runtime = InferenceRuntime(provider=DeterministicProvider(mode))
    try:
        result = runtime.run()

        assert result.status is status
        assert result.failure_code == code
        assert result.retryable is retryable
        assert result.output == {}
        assert runtime.provider.calls == 1
        assert runtime.budget.telemetry().counters.physical_llm_calls == 1
    finally:
        runtime.close()


def test_provider_failure_text_does_not_enter_result_or_audit() -> None:
    runtime = InferenceRuntime(provider=DeterministicProvider("provider_text_secret"))
    try:
        result = runtime.run()
        serialized = result.model_dump_json()
        audits = " ".join(event.model_dump_json() for event in runtime.api.repository.list(SCOPE))

        assert result.failure_code == "MODEL_RATE_LIMITED"
        assert "forbidden-provider-secret" not in serialized
        assert "forbidden-provider-secret" not in audits
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("mode", "code"),
    (
        ("identity_mismatch", "MODEL_PROVIDER_IDENTITY_INVALID"),
        ("schema_invalid", "MODEL_OUTPUT_SCHEMA_INVALID"),
        ("artifact_invalid", "MODEL_ARTIFACT_INVALID"),
        ("malformed", "MODEL_PROVIDER_RESPONSE_INVALID"),
        ("generic_exception", "MODEL_PROVIDER_FAILED"),
        ("typed_exception", "MODEL_RATE_LIMITED"),
    ),
)
def test_provider_identity_schema_artifact_and_failures_fail_closed(
    mode: str,
    code: str,
) -> None:
    runtime = InferenceRuntime(provider=DeterministicProvider(mode))
    try:
        result = runtime.run()

        assert result.status is ModelInferenceStatus.FAILED
        assert result.failure_code == code
        assert result.output == {}
        assert result.artifacts == ()
        assert runtime.provider.calls == 1
        assert "forbidden-secret" not in result.model_dump_json()
    finally:
        runtime.close()


def test_quality_threshold_preserves_partial_output_for_review() -> None:
    runtime = InferenceRuntime(provider=DeterministicProvider("low_quality"))
    try:
        result = runtime.run()

        assert result.status is ModelInferenceStatus.PARTIAL_SUCCESS
        assert result.failure_code == "MODEL_QUALITY_THRESHOLD_FAILED"
        assert result.output["classification"] == "NO_INDICATION"
        assert result.review_required
        assert not result.formal_use_candidate
    finally:
        runtime.close()


def test_post_provider_usage_overrun_is_budget_failure_without_second_call() -> None:
    runtime = InferenceRuntime(provider=DeterministicProvider("usage_overrun"))
    try:
        result = runtime.run()
        telemetry = runtime.budget.telemetry().counters

        assert result.status is ModelInferenceStatus.FAILED
        assert result.failure_code == "BUDGET_TOKEN_RESERVATION_EXCEEDED"
        assert runtime.provider.calls == 1
        assert telemetry.physical_llm_calls == 1
        assert telemetry.actual_total_tokens == 250
        assert telemetry.physical_tool_calls == 0
    finally:
        runtime.close()


def test_timeout_and_cancellation_complete_one_failed_llm_attempt() -> None:
    fast_timeout = binding().model_copy(update={"timeout_ms": 1})
    timeout_runtime = InferenceRuntime(
        provider=DeterministicProvider("timeout"), selected_binding=fast_timeout
    )
    cancelled_runtime = InferenceRuntime(provider=DeterministicProvider("cancelled_exception"))
    try:
        timeout = timeout_runtime.run()
        cancelled = cancelled_runtime.run()

        assert timeout.status is ModelInferenceStatus.TIMEOUT
        assert timeout.failure_code == "MODEL_INFERENCE_TIMEOUT"
        assert cancelled.status is ModelInferenceStatus.CANCELLED
        assert cancelled.failure_code == "MODEL_INFERENCE_CANCELLED"
        assert timeout_runtime.provider.calls == 1
        assert cancelled_runtime.provider.calls == 1
        assert timeout_runtime.budget.telemetry().counters.llm_failures == 1
        assert cancelled_runtime.budget.telemetry().counters.llm_failures == 1
    finally:
        timeout_runtime.close()
        cancelled_runtime.close()


@pytest.mark.parametrize(
    ("update", "code"),
    (
        ({"profile_registry_version": "0" * 64}, "MODEL_PROFILE_REGISTRY_STALE"),
        ({"profile_sha256": "0" * 64}, "MODEL_PROFILE_STALE"),
        ({"instruction_sha256": "0" * 64}, "MODEL_INSTRUCTION_STALE"),
        ({"formal_use_requested": True}, "MODEL_FORMAL_USE_DENIED"),
    ),
)
def test_profile_instruction_and_formal_preflight_denials_make_zero_provider_calls(
    update: dict[str, object],
    code: str,
) -> None:
    runtime = InferenceRuntime()
    try:
        with pytest.raises(ModelInferenceError) as caught:
            runtime.run(runtime.request(**update))

        assert caught.value.code == code
        assert runtime.provider.calls == 0
        assert runtime.budget.telemetry().counters.physical_llm_calls == 0
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("update", "code"),
    (
        ({"allow_network": False}, "MODEL_NETWORK_DENIED"),
        ({"granted_permissions": frozenset()}, "MODEL_PERMISSION_DENIED"),
        ({"api_registry_version": "0" * 64}, "MODEL_REGISTRY_STALE"),
    ),
)
def test_route_denials_make_zero_provider_and_budget_calls(
    update: dict[str, object],
    code: str,
) -> None:
    runtime = InferenceRuntime()
    try:
        with pytest.raises(ModelInferenceError) as caught:
            runtime.run(runtime.request(**update))

        assert caught.value.code == code
        assert runtime.provider.calls == 0
        assert runtime.budget.telemetry().counters.physical_llm_calls == 0
        events = runtime.api.repository.list(SCOPE)
        assert len(events) == 1
        assert events[0].decision == "DENY"
    finally:
        runtime.close()


def test_budget_denial_after_route_authorization_makes_zero_provider_calls() -> None:
    policy = default_budget_policy("P1").model_copy(
        update={"llm_calls": Limit(default=0, active=0, hard=0)}
    )
    runtime = InferenceRuntime(budget=BudgetGuard(policy))
    try:
        with pytest.raises(ModelInferenceError) as caught:
            runtime.run()

        assert caught.value.code == "BUDGET_HARD_LIMIT_EXCEEDED"
        assert runtime.provider.calls == 0
        assert runtime.budget.telemetry().counters.physical_llm_calls == 0
        assert len(runtime.api.repository.list(SCOPE)) == 2
    finally:
        runtime.close()


def test_request_contract_rejects_cross_scope_secret_fields_and_tamper() -> None:
    runtime = InferenceRuntime()
    try:
        payload = request_payload(runtime.api, runtime.profiles, runtime.profile)
        payload["scope"] = OTHER_SCOPE
        with pytest.raises(ValidationError):
            build_model_inference_request(payload)

        payload = request_payload(runtime.api, runtime.profiles, runtime.profile)
        payload["parameters"] = {"api_key": "forbidden-secret"}
        with pytest.raises(ValidationError):
            build_model_inference_request(payload)

        valid = runtime.request()
        assert valid.request_sha256 == model_inference_request_sha256(valid)
        with pytest.raises(ValidationError):
            ModelInferenceRequest.model_validate(
                {**valid.model_dump(mode="json"), "request_sha256": "f" * 64}
            )
    finally:
        runtime.close()


def test_profile_applicability_and_lossy_canonical_input_deny_before_provider() -> None:
    runtime = InferenceRuntime()
    try:
        gpr = dataset(method="GPR")
        with pytest.raises(ModelInferenceError) as applicability:
            runtime.run(
                runtime.request(
                    canonical_data=gpr,
                    canonical_manifest_sha256=gpr.manifest_sha256,
                )
            )
        assert applicability.value.code == "MODEL_PROFILE_NOT_APPLICABLE"
        assert runtime.provider.calls == 0

        lossy = dataset(lossless=False)
        with pytest.raises(ModelInferenceError) as ineligible:
            runtime.run(
                runtime.request(
                    canonical_data=lossy,
                    canonical_manifest_sha256=lossy.manifest_sha256,
                )
            )
        assert ineligible.value.code == "MODEL_CANONICAL_INPUT_INELIGIBLE"
        assert runtime.provider.calls == 0
    finally:
        runtime.close()


def test_formal_candidate_remains_human_confirmation_required() -> None:
    formal_profile = build_inspection_model_profile(
        profile_payload(report_eligibility=ModelReportEligibility.FORMAL_HUMAN_REQUIRED)
    )
    runtime = InferenceRuntime(selected_profile=formal_profile)
    try:
        result = runtime.run(runtime.request(formal_use_requested=True))

        assert result.status is ModelInferenceStatus.SUCCESS
        assert result.formal_use_candidate
        assert result.evidence.formal_human_confirmation_required
        assert result.review_required
    finally:
        runtime.close()


def test_profile_and_result_serialization_contains_no_secret_value() -> None:
    runtime = InferenceRuntime()
    try:
        result = runtime.run()
        serialized = " ".join(
            (
                runtime.profile.model_dump_json(),
                result.model_dump_json(),
                runtime.budget.telemetry().model_dump_json(),
            )
        )
        assert "forbidden-secret" not in serialized
        assert "provider-secret-value" not in serialized
        assert "deepseek-api-key" not in result.model_dump_json()
    finally:
        runtime.close()
