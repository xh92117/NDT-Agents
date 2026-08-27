"""One-call Main-to-General DeepSeek smoke with fixed synthetic input."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from ndt_agents.contracts.v1 import (  # noqa: E402
    BudgetPolicy,
    RiskLevel,
    TaskContext,
    TenantScope,
)
from ndt_agents.models.config import (  # noqa: E402
    ConfiguredModelRuntime,
    ModelConfigurationError,
    load_model_runtime_configuration,
)
from ndt_agents.models.deepseek import build_deepseek_provider  # noqa: E402
from ndt_agents.models.inference import (  # noqa: E402
    ModelInferenceError,
    ModelInferenceProvider,
    ModelInferenceResult,
    ModelInferenceStatus,
)
from ndt_agents.models.registry import canonical_sha256  # noqa: E402
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
from ndt_agents.orchestration.budget import default_budget_policy  # noqa: E402
from ndt_agents.orchestration.child_models import ChildTaskContext  # noqa: E402
from ndt_agents.orchestration.configured_runtime import (  # noqa: E402
    ConfiguredExecutorFactory,
    ConfiguredOrchestrationRuntime,
    ConfiguredRunStatus,
)
from ndt_agents.orchestration.general_model_delegate import (  # noqa: E402
    DEEPSEEK_POLICY_ACKNOWLEDGEMENT,
    GeneralModelDelegate,
    build_general_delegate_catalog,
    general_agent_result_schema,
)
from ndt_agents.orchestration.models import RouteSignals  # noqa: E402
from ndt_agents.orchestration.prompt_registry import load_prompt_registry  # noqa: E402
from ndt_agents.orchestration.review import MainAggregationGate  # noqa: E402
from ndt_agents.orchestration.scheduler import ScheduleResult  # noqa: E402
from ndt_agents.security.models import SecurityEnvironment  # noqa: E402

ACKNOWLEDGEMENT = DEEPSEEK_POLICY_ACKNOWLEDGEMENT
TASK_ID = UUID("00000000-0000-4000-8000-000000000451")
SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("PROJECT_OPERATOR",),
    permission_version="permissions-1",
)


def _agent_result_schema(context: ChildTaskContext) -> dict[str, Any]:
    return general_agent_result_schema(context)


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


async def run_with_provider(
    provider: ModelInferenceProvider,
    *,
    configured_models: ConfiguredModelRuntime | None = None,
    agent_runtime: ConfiguredAgentRuntime | None = None,
) -> tuple[dict[str, object], bool]:
    if configured_models is None:
        configured_models = load_model_runtime_configuration(
            ROOT / "config/runtime/model-bindings.local.yaml",
            env_file_path=ROOT / ".env",
            expected_environment=SecurityEnvironment.LOCAL,
        )
    traces = TraceService(
        service_name="deepseek-live-agent-smoke",
        service_version="1.0.0",
        exporter=InMemorySpanExporter(),
    )
    audit = AuditService(InMemoryAuditRepository(), traces)
    try:
        active_agents = agent_runtime or _agent_runtime(configured_models)
        delegate = GeneralModelDelegate(configured_models, provider, audit)
        runtime = ConfiguredOrchestrationRuntime(
            ConfiguredExecutorFactory(
                active_agents,
                build_general_delegate_catalog(active_agents, delegate),
            )
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
        if assignment.outcome is None or assignment.outcome.status != "COMPLETED":
            inference = delegate.last_inference
            if inference is not None:
                return _inference_failure(
                    inference,
                    delegate.last_error_code or assignment.error_code,
                ), False
            return _sanitized_failure(
                delegate.last_error_code or assignment.error_code or "LIVE_AGENT_CHILD_FAILED"
            ), False
        aggregation = MainAggregationGate.general(execution.contexts[0], assignment.outcome)
        inference = delegate.last_inference
        if inference is None:
            return _sanitized_failure("LIVE_AGENT_INFERENCE_MISSING"), False
        assert execution.main_result.decision is not None
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
            delegate.calls == 1
            and inference.status is ModelInferenceStatus.SUCCESS
            and inference.evidence.physical_llm_calls == 1
            and inference.evidence.physical_tool_calls == 0
            and inference.evidence.physical_network_calls == 1
            and not inference.formal_use_candidate
        )
        return report, success
    finally:
        traces.shutdown()


def _inference_failure(
    inference: ModelInferenceResult,
    code: str | None,
) -> dict[str, object]:
    evidence = inference.evidence
    return {
        "result": "FAILED",
        "failure_code": code or inference.failure_code or "MODEL_PROVIDER_FAILED",
        "physical_llm_calls": evidence.physical_llm_calls,
        "physical_tool_calls": evidence.physical_tool_calls,
        "physical_network_calls": evidence.physical_network_calls,
        "provider_id": evidence.provider_id,
        "model_id": evidence.model_id,
        "model_snapshot": evidence.model_snapshot,
        "input_tokens": evidence.input_tokens,
        "output_tokens": evidence.output_tokens,
        "finish_reason": evidence.finish_reason,
        "model_result_sha256": inference.result_sha256,
        "secret_output": False,
    }


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
