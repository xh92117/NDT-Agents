"""Bounded synthetic Technical QA and independent Review Agent model delegates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any, Final, cast
from uuid import UUID, uuid5

from ndt_agents.contracts.v1 import AgentResult, ReviewResult
from ndt_agents.models.config import ConfiguredModelRuntime
from ndt_agents.models.inference import (
    CanonicalPromptMode,
    ModelInferenceError,
    ModelInferenceGateway,
    ModelInferenceProvider,
    ModelInferenceResult,
    ModelInferenceStatus,
    ModelReasoningMode,
    build_model_inference_request,
)
from ndt_agents.models.instructions import ApplicationInstruction
from ndt_agents.models.profiles import (
    InspectionModelProfile,
    InspectionModelProfileRegistry,
    build_inspection_model_profile,
    canonical_inspection_input_schema_sha256,
)
from ndt_agents.models.registry import ModelCapability, ModelDataClass, canonical_sha256
from ndt_agents.observability import AuditService, TraceService
from ndt_agents.orchestration.agent_config import ConfiguredAgentRuntime
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.orchestration.child_models import ChildAgentKind, ChildTaskContext
from ndt_agents.orchestration.configured_review_runtime import ConfiguredReviewBindings
from ndt_agents.orchestration.general_model_delegate import (
    DeniedModelDelegate,
    GeneralModelDelegate,
)
from ndt_agents.orchestration.langgraph_runtime import ConfiguredChildDelegate
from ndt_agents.orchestration.review import CorrectionContext, ReviewContext, ReviewerDefinition
from ndt_agents.security.models import SecurityEnvironment
from ndt_agents.tools.reference_adapters import build_reference_fixture_dataset

TECHNICAL_QA_MAXIMUM_INPUT_TOKENS: Final = 3_600
TECHNICAL_QA_MAXIMUM_OUTPUT_TOKENS: Final = 2_400
REVIEW_MAXIMUM_INPUT_TOKENS: Final = 3_000
REVIEW_MAXIMUM_OUTPUT_TOKENS: Final = 1_000
REVIEWER_VERSION: Final = "review-model-1.0.0"
_TECHNICAL_NAMESPACE = UUID("be88a34b-2b40-455e-9a45-199f84d7d06a")
_REVIEW_NAMESPACE = UUID("f10c63d4-69f3-4bea-a1d1-c65b52340ff3")
_DECLARED_ERRORS = tuple(
    sorted(
        {
            "MODEL_INCOMPLETE",
            "MODEL_PROVIDER_AUTHENTICATION_FAILED",
            "MODEL_PROVIDER_BALANCE_EXHAUSTED",
            "MODEL_PROVIDER_FAILED",
            "MODEL_PROVIDER_NETWORK_FAILED",
            "MODEL_PROVIDER_REQUEST_INVALID",
            "MODEL_PROVIDER_RESPONSE_INVALID",
            "MODEL_PROVIDER_TIMEOUT",
            "MODEL_PROVIDER_UNAVAILABLE",
            "MODEL_RATE_LIMITED",
            "MODEL_REFUSED",
        }
    )
)
_RETRYABLE_ERRORS = tuple(
    sorted(
        {
            "MODEL_PROVIDER_NETWORK_FAILED",
            "MODEL_PROVIDER_TIMEOUT",
            "MODEL_PROVIDER_UNAVAILABLE",
            "MODEL_RATE_LIMITED",
        }
    )
)


def technical_qa_agent_result_schema(context: ChildTaskContext) -> dict[str, Any]:
    """Return the strict non-formal Technical QA AgentResult schema."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": "1.0.0"},
            "task_id": {"const": str(context.parent_task_id)},
            "run_id": {"const": str(context.run_id)},
            "status": {"const": "SUCCESS"},
            "summary": {"type": "string", "minLength": 1, "maxLength": 600},
            "structured_data": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "answer_scope": {"const": "SYNTHETIC_LIMITATIONS_ONLY"},
                    "observations": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {"type": "string", "maxLength": 300},
                    },
                    "limitations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 3,
                        "items": {"type": "string", "maxLength": 300},
                    },
                    "next_action": {"type": "string", "minLength": 1, "maxLength": 300},
                },
                "required": ["answer_scope", "observations", "limitations", "next_action"],
            },
            "artifacts": {"type": "array", "maxItems": 0},
            "evidence": {"type": "array", "maxItems": 0},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "issues": {"type": "array", "maxItems": 0},
            "retryable": {"const": False},
            "failure_code": {"type": "null"},
            "completed_at": {"type": "string", "format": "date-time"},
        },
        "required": [
            "schema_version",
            "task_id",
            "run_id",
            "status",
            "summary",
            "structured_data",
            "artifacts",
            "evidence",
            "confidence",
            "issues",
            "retryable",
            "failure_code",
            "completed_at",
        ],
    }


def review_agent_result_schema(context: ReviewContext) -> dict[str, Any]:
    """Return a strict bound review schema with no correction decision."""

    finding = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "code": {"type": "string", "minLength": 1, "maxLength": 128},
            "severity": {"enum": ["INFO", "WARNING", "ERROR", "CRITICAL"]},
            "message": {"type": "string", "minLength": 1, "maxLength": 500},
            "affected_path": {"type": ["string", "null"], "maxLength": 256},
            "next_action": {"type": ["string", "null"], "maxLength": 300},
        },
        "required": ["code", "severity", "message", "affected_path", "next_action"],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": "1.0.0"},
            "review_id": {"type": "string", "format": "uuid"},
            "task_id": {"const": str(context.task_id)},
            "target_run_id": {"const": str(context.review_target_run_id)},
            "target_sha256": {"const": context.review_target_sha256},
            "reviewer_version": {"const": context.reviewer_version},
            "decision": {"enum": ["PASS", "CONFLICT", "HUMAN_REQUIRED", "FAILED"]},
            "findings": {"type": "array", "maxItems": 3, "items": finding},
            "correction_count": {"const": context.correction_count},
            "completed_at": {"type": "string", "format": "date-time"},
        },
        "required": [
            "schema_version",
            "review_id",
            "task_id",
            "target_run_id",
            "target_sha256",
            "reviewer_version",
            "decision",
            "findings",
            "correction_count",
            "completed_at",
        ],
        "allOf": [
            {
                "if": {"properties": {"decision": {"const": "PASS"}}},
                "then": {"properties": {"findings": {"maxItems": 0}}},
                "else": {"properties": {"findings": {"minItems": 1}}},
            }
        ],
    }


def _exact_json(value: Any) -> Any:
    """Convert model floating values to exact Decimal payload values."""

    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _exact_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_exact_json(item) for item in value]
    return value


def _review_model_context(context: ReviewContext) -> dict[str, Any]:
    """Return the minimum hash-bound context required by the read-only reviewer."""

    return cast(
        dict[str, Any],
        _exact_json(
            {
                "task_id": str(context.task_id),
                "scope": context.scope.model_dump(mode="json"),
                "review_target_run_id": str(context.review_target_run_id),
                "review_target_sha256": context.review_target_sha256,
                "targets": [target.model_dump(mode="json") for target in context.targets],
                "review_checklist": list(context.review_checklist),
                "reviewer_version": context.reviewer_version,
                "correction_count": context.correction_count,
                "context_manifest_sha256": context.context_manifest_sha256,
                "read_only": context.read_only,
                "user_delivery_allowed": context.user_delivery_allowed,
            }
        ),
    )


def _model_profile(
    *,
    profile_id: str,
    output_schema_id: str,
    output_schema: dict[str, Any],
) -> InspectionModelProfile:
    evidence_scope = {
        "scope_id": "professional-agent-synthetic",
        "version": "1.0.0",
        "origin": "SYNTHETIC",
        "method_codes": ("UT",),
        "structure_classes": ("BRIDGE",),
        "material_classes": ("REINFORCED_CONCRETE",),
        "record_count": 1,
        "evidence_sha256": canonical_sha256({"profile": "professional-agent-synthetic-v1"}),
        "rights_verified": True,
        "deidentified": True,
        "evaluated_on": date(2026, 8, 27),
    }
    return build_inspection_model_profile(
        {
            "profile_id": profile_id,
            "profile_version": "1.0.0",
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "model_snapshot": "DeepSeek-V4-Pro-0813",
            "method_codes": ("UT",),
            "structure_classes": ("BRIDGE",),
            "material_classes": ("REINFORCED_CONCRETE",),
            "input_schema_sha256": canonical_inspection_input_schema_sha256(),
            "output_schema_id": output_schema_id,
            "output_schema": output_schema,
            "output_schema_sha256": canonical_sha256(output_schema),
            "training_scope": evidence_scope,
            "validation_scope": evidence_scope,
            "thresholds": ({"metric": "quality_score", "direction": "MINIMUM", "value": "0"},),
            "runtime": {
                "kind": "HOSTED_API",
                "runtime_id": "deepseek-chat-completions",
                "runtime_version": "1.0.0",
                "artifact_sha256": None,
                "precision": "decimal",
                "deterministic": False,
                "network_required": True,
            },
            "resources": {
                "cpu_cores": 1,
                "memory_mb": 256,
                "accelerator": None,
                "accelerator_memory_mb": 0,
                "max_concurrency": 1,
                "max_output_bytes": 12_000,
            },
            "declared_error_codes": _DECLARED_ERRORS,
            "retryable_error_codes": _RETRYABLE_ERRORS,
            "report_eligibility": "NOT_ELIGIBLE",
            "independently_validated": False,
        }
    )


class TechnicalQaModelDelegate:
    """Execute one exact no-tool synthetic Technical QA child."""

    def __init__(
        self,
        configured_models: ConfiguredModelRuntime,
        provider: ModelInferenceProvider,
        audit: AuditService,
        *,
        trace_service: TraceService | None = None,
    ) -> None:
        self._configured_models = configured_models
        self._provider = provider
        self._audit = audit
        self._trace_service = trace_service
        self.calls = 0
        self.last_inference: ModelInferenceResult | None = None
        self.last_error_code: str | None = None

    async def execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        if (
            context.agent_type != "technical_qa"
            or context.kind is not ChildAgentKind.PROFESSIONAL
            or context.task_class != "P1"
            or context.allowed_tools
            or context.artifacts
        ):
            raise ModelInferenceError(
                "MODEL_PROFESSIONAL_CONTEXT_DENIED",
                "The professional delegate accepts only the no-tool Technical QA profile.",
                retryable=False,
                next_action="Route one P1 task through the configured Technical QA profile.",
            )
        self.calls += 1
        try:
            if self._trace_service is None:
                result = await self._infer(context, instruction)
            else:
                with self._trace_service.start_span(
                    "agent.execution.technical-qa-model",
                    attributes={
                        "tenant.id": str(context.scope.tenant_id),
                        "project.id": str(context.scope.project_id),
                        "task.id": str(context.parent_task_id),
                        "agent.type": "technical_qa",
                        "operation.type": "model_inference",
                    },
                ):
                    result = await self._infer(context, instruction)
        except ModelInferenceError as error:
            self.last_error_code = error.code
            raise
        except Exception as error:
            self.last_error_code = type(error).__name__
            raise
        self.last_error_code = None
        return result

    async def _infer(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        canonical = build_reference_fixture_dataset(context.scope)
        registry = self._configured_models.build_registry(self._audit)
        output_schema = technical_qa_agent_result_schema(context)
        profile = _model_profile(
            profile_id="technical-qa-agent-synthetic",
            output_schema_id="technical-qa-agent-result@1.0.0",
            output_schema=output_schema,
        )
        profiles = InspectionModelProfileRegistry(registry, (profile,))
        request = build_model_inference_request(
            {
                "task_id": context.parent_task_id,
                "run_id": context.run_id,
                "call_id": uuid5(
                    _TECHNICAL_NAMESPACE,
                    f"{context.parent_task_id}:{context.run_id}:{context.assignment_id}",
                ),
                "request_id": f"technical-qa-agent:{context.assignment_id}",
                "scope": context.scope,
                "environment": SecurityEnvironment.LOCAL,
                "policy_version": "model-policy-1",
                "api_registry_version": registry.version,
                "profile_registry_version": profiles.version,
                "binding_id": "personal-deepseek",
                "profile_id": profile.profile_id,
                "profile_sha256": profile.profile_sha256,
                "requested_model_id": "deepseek-v4-pro",
                "required_capabilities": frozenset(
                    {ModelCapability.JSON_OUTPUT, ModelCapability.TEXT_OUTPUT}
                ),
                "data_class": ModelDataClass.SYNTHETIC,
                "granted_permissions": frozenset({"model.invoke.deepseek"}),
                "allow_network": True,
                "allow_fallback": False,
                "canonical_data": canonical,
                "canonical_manifest_sha256": canonical.manifest_sha256,
                "instruction_id": instruction.instruction_id,
                "instruction_version": instruction.instruction_version,
                "instruction_sha256": instruction.instruction_sha256,
                "parameters": {
                    "child_context": {
                        "parent_task_id": str(context.parent_task_id),
                        "run_id": str(context.run_id),
                        "assignment_id": context.assignment_id,
                        "goal": context.goal,
                        "success_criteria": list(context.success_criteria),
                        "data_class": "SYNTHETIC",
                        "formal_use": False,
                        "tools_allowed": [],
                    }
                },
                "maximum_input_tokens": TECHNICAL_QA_MAXIMUM_INPUT_TOKENS,
                "maximum_output_tokens": TECHNICAL_QA_MAXIMUM_OUTPUT_TOKENS,
                "formal_use_requested": False,
            }
        )
        result = await ModelInferenceGateway(
            profiles,
            (instruction,),
            self._provider,
            BudgetGuard(context.budget),
            self._audit,
        ).infer(request)
        self.last_inference = result
        if result.status is not ModelInferenceStatus.SUCCESS:
            raise ModelInferenceError(
                result.failure_code or "MODEL_PROVIDER_FAILED",
                result.failure_impact or "The model did not return a valid Technical QA result.",
                retryable=False,
                next_action=result.next_action or "Inspect sanitized professional evidence.",
            )
        return dict(AgentResult.model_validate(result.output).model_dump(mode="json"))


class ReviewModelDelegate:
    """Execute one independent read-only review over the exact professional result."""

    def __init__(
        self,
        configured_models: ConfiguredModelRuntime,
        provider: ModelInferenceProvider,
        audit: AuditService,
        *,
        reviewer_version: str,
        model_version: str,
        trace_service: TraceService | None = None,
    ) -> None:
        self._configured_models = configured_models
        self._provider = provider
        self._audit = audit
        self._reviewer_version = reviewer_version
        self._model_version = model_version
        self._trace_service = trace_service
        self.calls = 0
        self.last_inference: ModelInferenceResult | None = None
        self.last_error_code: str | None = None

    async def review(
        self,
        context: ReviewContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        if (
            not context.read_only
            or context.allowed_tools
            or context.reviewer_version != self._reviewer_version
            or context.model_version != self._model_version
            or any(
                target.result.artifacts
                or target.result.evidence
                or target.result.structured_data.get("answer_scope") != "SYNTHETIC_LIMITATIONS_ONLY"
                for target in context.targets
            )
        ):
            raise ModelInferenceError(
                "MODEL_REVIEW_CONTEXT_DENIED",
                "The Review Agent context does not match the read-only model binding.",
                retryable=False,
                next_action="Rebuild the exact configured independent review context.",
            )
        self.calls += 1
        try:
            if self._trace_service is None:
                result = await self._infer(context, instruction)
            else:
                with self._trace_service.start_span(
                    "agent.execution.review-model",
                    attributes={
                        "tenant.id": str(context.scope.tenant_id),
                        "project.id": str(context.scope.project_id),
                        "task.id": str(context.task_id),
                        "agent.type": "review",
                        "operation.type": "model_inference",
                    },
                ):
                    result = await self._infer(context, instruction)
        except ModelInferenceError as error:
            self.last_error_code = error.code
            raise
        except Exception as error:
            self.last_error_code = type(error).__name__
            raise
        self.last_error_code = None
        return result

    async def _infer(
        self,
        context: ReviewContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        canonical = build_reference_fixture_dataset(context.scope)
        registry = self._configured_models.build_registry(self._audit)
        output_schema = review_agent_result_schema(context)
        profile = _model_profile(
            profile_id="review-agent-synthetic",
            output_schema_id="review-agent-result@1.0.0",
            output_schema=output_schema,
        )
        profiles = InspectionModelProfileRegistry(registry, (profile,))
        request = build_model_inference_request(
            {
                "task_id": context.task_id,
                "run_id": context.review_target_run_id,
                "call_id": uuid5(
                    _REVIEW_NAMESPACE,
                    f"{context.task_id}:{context.review_target_run_id}:{context.review_target_sha256}",
                ),
                "request_id": f"review-agent:{context.review_target_sha256[:16]}",
                "scope": context.scope,
                "environment": SecurityEnvironment.LOCAL,
                "policy_version": "model-policy-1",
                "api_registry_version": registry.version,
                "profile_registry_version": profiles.version,
                "binding_id": "personal-deepseek",
                "profile_id": profile.profile_id,
                "profile_sha256": profile.profile_sha256,
                "requested_model_id": "deepseek-v4-pro",
                "required_capabilities": frozenset(
                    {ModelCapability.JSON_OUTPUT, ModelCapability.TEXT_OUTPUT}
                ),
                "data_class": ModelDataClass.SYNTHETIC,
                "granted_permissions": frozenset({"model.invoke.deepseek"}),
                "allow_network": True,
                "allow_fallback": False,
                "canonical_data": canonical,
                "canonical_prompt_mode": CanonicalPromptMode.IDENTITY_ONLY,
                "reasoning_mode": ModelReasoningMode.DISABLED,
                "canonical_manifest_sha256": canonical.manifest_sha256,
                "instruction_id": instruction.instruction_id,
                "instruction_version": instruction.instruction_version,
                "instruction_sha256": instruction.instruction_sha256,
                "parameters": {"review_context": _review_model_context(context)},
                "maximum_input_tokens": REVIEW_MAXIMUM_INPUT_TOKENS,
                "maximum_output_tokens": REVIEW_MAXIMUM_OUTPUT_TOKENS,
                "formal_use_requested": False,
            }
        )
        result = await ModelInferenceGateway(
            profiles,
            (instruction,),
            self._provider,
            BudgetGuard(default_budget_policy("P1")),
            self._audit,
        ).infer(request)
        self.last_inference = result
        if result.status is not ModelInferenceStatus.SUCCESS:
            raise ModelInferenceError(
                result.failure_code or "MODEL_PROVIDER_FAILED",
                result.failure_impact or "The model did not return a valid review result.",
                retryable=False,
                next_action=result.next_action or "Inspect sanitized review evidence.",
            )
        return dict(ReviewResult.model_validate(result.output).model_dump(mode="json"))


class DeniedCorrectionDelegate:
    """Keep all model-driven correction paths disabled in this slice."""

    async def correct(
        self,
        _context: CorrectionContext,
        _instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        raise ModelInferenceError(
            "MODEL_CORRECTION_DISABLED",
            "Model-driven professional correction is not enabled.",
            retryable=False,
            next_action="Preserve the reviewed result for a separately qualified correction path.",
        )


def build_professional_delegate_catalog(
    runtime: ConfiguredAgentRuntime,
    general: GeneralModelDelegate,
    technical_qa: TechnicalQaModelDelegate,
) -> Mapping[str, ConfiguredChildDelegate]:
    """Enable only General and Technical QA while denying every other profile."""

    return {
        profile.name: (
            general
            if profile.name == "general"
            else technical_qa
            if profile.name == "technical_qa"
            else DeniedModelDelegate()
        )
        for profile in runtime.profiles
    }


def build_professional_review_bindings(
    runtime: ConfiguredAgentRuntime,
    reviewer: ReviewModelDelegate,
) -> ConfiguredReviewBindings:
    """Bind one independent reviewer and default-deny all configured corrections."""

    technical_profile = runtime.profile("technical_qa")
    review_prompt = runtime.prompt_registry.resolve("review")
    professional_names = {
        profile.name for profile in runtime.profiles if profile.kind is ChildAgentKind.PROFESSIONAL
    }
    return ConfiguredReviewBindings(
        runtime,
        reviewer=reviewer,
        reviewer_definition=ReviewerDefinition(
            reviewer_version=REVIEWER_VERSION,
            prompt_version=review_prompt.version,
            model_version=technical_profile.model_id,
            review_timeout_ms=technical_profile.timeout_ms,
            correction_timeout_ms=30_000,
        ),
        correctors={name: DeniedCorrectionDelegate() for name in professional_names},
    )
