"""Application-owned synthetic General child delegate for configured model inference."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Final
from uuid import UUID, uuid5

from ndt_agents.contracts.v1 import AgentResult
from ndt_agents.models.config import ConfiguredModelRuntime
from ndt_agents.models.inference import (
    ModelInferenceError,
    ModelInferenceGateway,
    ModelInferenceProvider,
    ModelInferenceResult,
    ModelInferenceStatus,
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
from ndt_agents.orchestration.budget import BudgetGuard
from ndt_agents.orchestration.child_models import ChildTaskContext
from ndt_agents.orchestration.langgraph_runtime import ConfiguredChildDelegate
from ndt_agents.security.models import SecurityEnvironment
from ndt_agents.tools.reference_adapters import build_reference_fixture_dataset

DEEPSEEK_POLICY_ACKNOWLEDGEMENT: Final = "I_ACKNOWLEDGE_UNVERIFIED_DEEPSEEK_PROVIDER_POLICY"
_CALL_NAMESPACE = UUID("f51c7236-1092-4a5e-8f10-ddf89ae0cc9c")
_DECLARED_ERRORS = (
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
)
_RETRYABLE_ERRORS = (
    "MODEL_PROVIDER_NETWORK_FAILED",
    "MODEL_PROVIDER_TIMEOUT",
    "MODEL_PROVIDER_UNAVAILABLE",
    "MODEL_RATE_LIMITED",
)


def general_agent_result_schema(context: ChildTaskContext) -> dict[str, Any]:
    """Return the strict task- and run-bound General AgentResult JSON schema."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": "1.0.0"},
            "task_id": {"const": str(context.parent_task_id)},
            "run_id": {"const": str(context.run_id)},
            "status": {"const": "SUCCESS"},
            "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
            "structured_data": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "completed_work": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {"type": "string", "maxLength": 500},
                    },
                    "limitations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string", "maxLength": 500},
                    },
                    "next_action": {"type": "string", "minLength": 1, "maxLength": 500},
                },
                "required": ["completed_work", "limitations", "next_action"],
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


def build_general_model_profile(context: ChildTaskContext) -> InspectionModelProfile:
    """Build the immutable hosted profile for one exact General result contract."""

    output_schema = general_agent_result_schema(context)
    evidence_scope = {
        "scope_id": "general-agent-synthetic",
        "version": "1.0.0",
        "origin": "SYNTHETIC",
        "method_codes": ("UT",),
        "structure_classes": ("BRIDGE",),
        "material_classes": ("REINFORCED_CONCRETE",),
        "record_count": 1,
        "evidence_sha256": canonical_sha256({"profile": "general-agent-synthetic-v1"}),
        "rights_verified": True,
        "deidentified": True,
        "evaluated_on": date(2026, 8, 27),
    }
    return build_inspection_model_profile(
        {
            "profile_id": "general-agent-synthetic",
            "profile_version": "1.0.0",
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "model_snapshot": "DeepSeek-V4-Pro-0813",
            "method_codes": ("UT",),
            "structure_classes": ("BRIDGE",),
            "material_classes": ("REINFORCED_CONCRETE",),
            "input_schema_sha256": canonical_inspection_input_schema_sha256(),
            "output_schema_id": "general-agent-result@1.0.0",
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


class GeneralModelDelegate:
    """Execute one no-tool General child through the existing inference gateway."""

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
        if context.agent_type != "general" or context.allowed_tools:
            raise ModelInferenceError(
                "MODEL_GENERAL_CONTEXT_DENIED",
                "The configured model delegate accepts only the no-tool General child.",
                retryable=False,
                next_action="Route the task through the exact configured General profile.",
            )
        self.calls += 1
        try:
            if self._trace_service is None:
                return await self._infer(context, instruction)
            with self._trace_service.start_span(
                "agent.execution.general-model",
                attributes={
                    "tenant.id": str(context.scope.tenant_id),
                    "project.id": str(context.scope.project_id),
                    "task.id": str(context.parent_task_id),
                    "agent.type": "general",
                    "operation.type": "model_inference",
                },
            ):
                return await self._infer(context, instruction)
        except ModelInferenceError as error:
            self.last_error_code = error.code
            raise
        except Exception as error:
            self.last_error_code = type(error).__name__
            raise

    async def _infer(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        canonical = build_reference_fixture_dataset(context.scope)
        registry = self._configured_models.build_registry(self._audit)
        profile = build_general_model_profile(context)
        profiles = InspectionModelProfileRegistry(registry, (profile,))
        request = build_model_inference_request(
            {
                "task_id": context.parent_task_id,
                "run_id": context.run_id,
                "call_id": uuid5(
                    _CALL_NAMESPACE,
                    f"{context.parent_task_id}:{context.run_id}:{context.assignment_id}",
                ),
                "request_id": f"general-agent:{context.assignment_id}",
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
                "maximum_input_tokens": 3_600,
                "maximum_output_tokens": 2_400,
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
                result.failure_impact or "The model did not return a valid General result.",
                retryable=result.retryable,
                next_action=result.next_action or "Inspect sanitized model evidence.",
            )
        parsed = AgentResult.model_validate(result.output)
        return dict(parsed.model_dump(mode="json"))


class DeniedModelDelegate:
    """Fail closed for every configured profile outside the local General slice."""

    async def execute(
        self,
        _context: ChildTaskContext,
        _instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        raise ModelInferenceError(
            "MODEL_AGENT_PROFILE_DISABLED",
            "This application slice enables only the General model delegate.",
            retryable=False,
            next_action="Use a G0 synthetic task or configure a separately reviewed profile.",
        )


def build_general_delegate_catalog(
    agent_runtime: ConfiguredAgentRuntime,
    delegate: GeneralModelDelegate,
) -> Mapping[str, ConfiguredChildDelegate]:
    """Return an exact configured catalog with every non-General profile denied."""

    return {
        profile.name: delegate if profile.name == "general" else DeniedModelDelegate()
        for profile in agent_runtime.profiles
    }
