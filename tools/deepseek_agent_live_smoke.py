"""One-call Main-to-General DeepSeek smoke with fixed synthetic input."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from ndt_agents.contracts.v1 import (  # noqa: E402
    AgentResult,
    BudgetPolicy,
    RiskLevel,
    TaskContext,
)
from ndt_agents.models.config import (  # noqa: E402
    ConfiguredModelRuntime,
    ModelConfigurationError,
    load_model_runtime_configuration,
)
from ndt_agents.models.deepseek import build_deepseek_provider  # noqa: E402
from ndt_agents.models.inference import (  # noqa: E402
    ModelInferenceError,
    ModelInferenceGateway,
    ModelInferenceProvider,
    ModelInferenceResult,
    ModelInferenceStatus,
    build_model_inference_request,
)
from ndt_agents.models.instructions import ApplicationInstruction  # noqa: E402
from ndt_agents.models.profiles import (  # noqa: E402
    InspectionModelProfile,
    InspectionModelProfileRegistry,
    build_inspection_model_profile,
)
from ndt_agents.models.registry import (  # noqa: E402
    ModelCapability,
    ModelDataClass,
    canonical_sha256,
)
from ndt_agents.observability import (  # noqa: E402
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.agent_config import (  # noqa: E402
    ConfiguredAgentRuntime,
    load_agent_runtime_configuration,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy  # noqa: E402
from ndt_agents.orchestration.child_models import ChildTaskContext  # noqa: E402
from ndt_agents.orchestration.configured_runtime import (  # noqa: E402
    ConfiguredExecutorFactory,
    ConfiguredOrchestrationRuntime,
    ConfiguredRunStatus,
)
from ndt_agents.orchestration.models import RouteSignals  # noqa: E402
from ndt_agents.orchestration.prompt_registry import load_prompt_registry  # noqa: E402
from ndt_agents.orchestration.review import MainAggregationGate  # noqa: E402
from ndt_agents.orchestration.scheduler import ScheduleResult  # noqa: E402
from ndt_agents.professional.processing import DataOrigin  # noqa: E402
from ndt_agents.security.models import SecurityEnvironment  # noqa: E402
from tests.models.test_model_api_registry import SCOPE  # noqa: E402
from tests.models.test_model_inference import dataset, profile_payload  # noqa: E402

ACKNOWLEDGEMENT = "I_ACKNOWLEDGE_UNVERIFIED_DEEPSEEK_PROVIDER_POLICY"
TASK_ID = UUID("00000000-0000-4000-8000-000000000451")
CALL_NAMESPACE = UUID("00000000-0000-4000-8000-000000000452")
COMPLETED_AT = datetime(2026, 8, 27, tzinfo=UTC)


def _agent_result_schema(context: ChildTaskContext) -> dict[str, Any]:
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


def _profile(context: ChildTaskContext) -> InspectionModelProfile:
    output_schema = _agent_result_schema(context)
    payload = profile_payload()
    payload.update(
        {
            "profile_id": "deepseek-live-general-agent",
            "output_schema_id": "agent-result-live-smoke@1.0.0",
            "output_schema": output_schema,
            "output_schema_sha256": canonical_sha256(output_schema),
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
            "declared_error_codes": (
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
            ),
            "retryable_error_codes": (
                "MODEL_PROVIDER_NETWORK_FAILED",
                "MODEL_PROVIDER_TIMEOUT",
                "MODEL_PROVIDER_UNAVAILABLE",
                "MODEL_RATE_LIMITED",
            ),
        }
    )
    return build_inspection_model_profile(payload)


class LiveGeneralDelegate:
    """Bind one configured General context to the existing inspection inference gateway."""

    def __init__(
        self,
        configured_models: ConfiguredModelRuntime,
        provider: ModelInferenceProvider,
        audit: AuditService,
    ) -> None:
        self._configured_models = configured_models
        self._provider = provider
        self._audit = audit
        self.calls = 0
        self.last_inference: ModelInferenceResult | None = None
        self.last_error_code: str | None = None

    async def execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        self.calls += 1
        try:
            return await self._execute(context, instruction)
        except ModelInferenceError as error:
            self.last_error_code = error.code
            raise
        except Exception as error:
            self.last_error_code = type(error).__name__
            raise

    async def _execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        canonical = dataset(origin=DataOrigin.SIMULATED)
        if canonical.scope != context.scope:
            raise ModelInferenceError(
                "MODEL_SCOPE_DENIED",
                "The fixed synthetic dataset is outside the child scope.",
                retryable=False,
                next_action="Use the application-owned local smoke scope.",
            )
        registry = self._configured_models.build_registry(self._audit)
        profile = _profile(context)
        profiles = InspectionModelProfileRegistry(registry, (profile,))
        request = build_model_inference_request(
            {
                "task_id": context.parent_task_id,
                "run_id": context.run_id,
                "call_id": uuid5(CALL_NAMESPACE, f"{context.parent_task_id}:{context.run_id}"),
                "request_id": f"live-agent:{context.assignment_id}",
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
                "maximum_input_tokens": 3_400,
                "maximum_output_tokens": 2_048,
                "formal_use_requested": False,
            }
        )
        gateway = ModelInferenceGateway(
            profiles,
            (instruction,),
            self._provider,
            BudgetGuard(context.budget),
            self._audit,
        )
        result = await gateway.infer(request)
        self.last_inference = result
        if result.status is not ModelInferenceStatus.SUCCESS:
            raise ModelInferenceError(
                result.failure_code or "MODEL_PROVIDER_FAILED",
                result.failure_impact or "The live model did not return a trusted result.",
                retryable=result.retryable,
                next_action=result.next_action or "Inspect sanitized model evidence.",
            )
        parsed = AgentResult.model_validate(result.output)
        return dict(parsed.model_dump(mode="json"))


class DeniedDelegate:
    async def execute(
        self,
        _context: ChildTaskContext,
        _instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        raise RuntimeError("A non-General delegate cannot run in the bounded live smoke.")


def _task() -> TaskContext:
    source = TaskContext.model_validate_json(
        (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
    )
    return source.model_copy(
        update={
            "task_id": TASK_ID,
            "scope": SCOPE,
            "task_class": "G0",
            "goal": (
                "Confirm the fixed synthetic agent integration run and summarize its "
                "non-production limitations without interpreting inspection measurements."
            ),
            "success_criteria": (
                "Return one strict AgentResult bound to this task and run.",
                "State that the input is synthetic and not eligible for formal use.",
                "Use zero tools and provide no professional inspection conclusion.",
            ),
            "risk_level": RiskLevel.LOW,
            "artifacts": (),
            "allowed_tools": (),
            "budget": _live_smoke_budget(),
        }
    )


def _live_smoke_budget() -> BudgetPolicy:
    base = default_budget_policy("G0")
    return base.model_copy(
        update={
            "policy_id": "budget-g0-live-smoke-v1",
            "total_tokens": base.total_tokens.model_copy(update={"active": 6_000}),
        }
    )


def _agent_runtime(configured_models: ConfiguredModelRuntime) -> ConfiguredAgentRuntime:
    return load_agent_runtime_configuration(
        ROOT / "config/runtime/agent-runtime.local.yaml",
        model_runtime=configured_models,
        prompt_registry=load_prompt_registry(ROOT / "prompts/professional/catalog.v1.yaml"),
    )


async def run_with_provider(provider: ModelInferenceProvider) -> tuple[dict[str, object], bool]:
    configured_models = load_model_runtime_configuration(
        ROOT / "config/runtime/model-bindings.local.yaml",
        env_file_path=ROOT / ".env",
        expected_environment=SecurityEnvironment.LOCAL,
    )
    exporter = InMemorySpanExporter()
    traces = TraceService(
        service_name="deepseek-live-agent-smoke",
        service_version="1.0.0",
        exporter=exporter,
    )
    repository = InMemoryAuditRepository()
    audit = AuditService(repository, traces)
    try:
        agent_runtime = _agent_runtime(configured_models)
        live_delegate = LiveGeneralDelegate(configured_models, provider, audit)
        delegates = {
            profile.name: live_delegate if profile.name == "general" else DeniedDelegate()
            for profile in agent_runtime.profiles
        }
        runtime = ConfiguredOrchestrationRuntime(
            ConfiguredExecutorFactory(agent_runtime, delegates)
        )
        task = _task()
        with traces.start_span("agent.execution.deepseek-live-smoke"):
            execution = await runtime.start(
                task,
                RouteSignals(task_id=task.task_id, general_eligible=True),
            )
        if (
            execution.status is not ConfiguredRunStatus.SCHEDULED
            or not isinstance(execution.schedule, ScheduleResult)
            or len(execution.contexts) != 1
        ):
            return _sanitized_failure("LIVE_AGENT_ORCHESTRATION_FAILED"), False
        assignment = execution.schedule.assignments[0]
        if assignment.outcome is None:
            return _sanitized_failure(
                live_delegate.last_error_code or assignment.error_code or "LIVE_AGENT_CHILD_FAILED"
            ), False
        if assignment.outcome.status != "COMPLETED":
            inference = live_delegate.last_inference
            if inference is not None:
                return {
                    "result": "FAILED",
                    "failure_code": inference.failure_code
                    or assignment.error_code
                    or assignment.outcome.error_code,
                    "physical_llm_calls": inference.evidence.physical_llm_calls,
                    "physical_tool_calls": inference.evidence.physical_tool_calls,
                    "physical_network_calls": inference.evidence.physical_network_calls,
                    "provider_id": inference.evidence.provider_id,
                    "model_id": inference.evidence.model_id,
                    "model_snapshot": inference.evidence.model_snapshot,
                    "input_tokens": inference.evidence.input_tokens,
                    "output_tokens": inference.evidence.output_tokens,
                    "finish_reason": inference.evidence.finish_reason,
                    "model_result_sha256": inference.result_sha256,
                    "secret_output": False,
                }, False
            return _sanitized_failure(
                live_delegate.last_error_code or assignment.error_code or "LIVE_AGENT_CHILD_FAILED"
            ), False
        aggregation = MainAggregationGate.general(execution.contexts[0], assignment.outcome)
        assert execution.main_result.decision is not None
        inference = live_delegate.last_inference
        if inference is None:
            return _sanitized_failure("LIVE_AGENT_INFERENCE_MISSING"), False
        result = aggregation.results[0]
        report: dict[str, object] = {
            "result": "SUCCESS",
            "route": execution.main_result.decision.route.value,
            "aggregation_source": aggregation.source.value,
            "task_id": str(result.task_id),
            "run_id": str(result.run_id),
            "agent_result_sha256": canonical_sha256(result.model_dump(mode="json")),
            "model_result_sha256": inference.result_sha256,
            "provider_id": inference.evidence.provider_id,
            "model_id": inference.evidence.model_id,
            "model_snapshot": inference.evidence.model_snapshot,
            "input_tokens": inference.evidence.input_tokens,
            "output_tokens": inference.evidence.output_tokens,
            "finish_reason": inference.evidence.finish_reason,
            "physical_llm_calls": inference.evidence.physical_llm_calls,
            "physical_tool_calls": inference.evidence.physical_tool_calls,
            "physical_network_calls": inference.evidence.physical_network_calls,
            "review_required": inference.review_required,
            "formal_use_candidate": inference.formal_use_candidate,
            "secret_output": False,
        }
        success = (
            live_delegate.calls == 1
            and inference.status is ModelInferenceStatus.SUCCESS
            and inference.evidence.physical_llm_calls == 1
            and inference.evidence.physical_tool_calls == 0
            and inference.evidence.physical_network_calls == 1
            and not inference.formal_use_candidate
        )
        return report, success
    finally:
        traces.shutdown()


def _sanitized_failure(code: str) -> dict[str, object]:
    return {
        "result": "FAILED",
        "failure_code": code,
        "physical_llm_calls": 0,
        "physical_tool_calls": 0,
        "physical_network_calls": 0,
        "secret_output": False,
    }


async def _run_live() -> tuple[dict[str, object], bool]:
    configured_models = load_model_runtime_configuration(
        ROOT / "config/runtime/model-bindings.local.yaml",
        env_file_path=ROOT / ".env",
        expected_environment=SecurityEnvironment.LOCAL,
    )
    return await run_with_provider(build_deepseek_provider(configured_models, timeout_seconds=30))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acknowledgement")
    args = parser.parse_args()
    if args.acknowledgement != ACKNOWLEDGEMENT:
        print(json.dumps(_sanitized_failure("DEEPSEEK_POLICY_ACKNOWLEDGEMENT_REQUIRED")))
        return 2
    try:
        report, success = asyncio.run(_run_live())
    except (ModelConfigurationError, ModelInferenceError) as error:
        print(json.dumps(_sanitized_failure(error.code), sort_keys=True))
        return 1
    except Exception:
        print(json.dumps(_sanitized_failure("LIVE_AGENT_INTERNAL_FAILURE"), sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
