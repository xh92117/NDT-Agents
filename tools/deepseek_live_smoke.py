"""One-call, explicitly acknowledged DeepSeek synthetic smoke through S5-07."""

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

from ndt_agents.models.config import (  # noqa: E402
    ModelConfigurationError,
    load_model_runtime_configuration,
)
from ndt_agents.models.deepseek import build_deepseek_provider  # noqa: E402
from ndt_agents.models.inference import (  # noqa: E402
    ModelInferenceError,
    ModelInferenceGateway,
    ModelInferenceStatus,
    build_application_instruction,
    build_model_inference_request,
)
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
from ndt_agents.orchestration.budget import (  # noqa: E402
    BudgetGuard,
    default_budget_policy,
)
from ndt_agents.professional.processing import DataOrigin  # noqa: E402
from ndt_agents.security.models import SecurityEnvironment  # noqa: E402
from tests.models.test_model_api_registry import RUN_ID, SCOPE, TASK_ID  # noqa: E402
from tests.models.test_model_inference import dataset, profile_payload  # noqa: E402

ACKNOWLEDGEMENT = "I_ACKNOWLEDGE_UNVERIFIED_DEEPSEEK_PROVIDER_POLICY"
CALL_ID = UUID("00000000-0000-4000-8000-000000000499")
OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"const": "SYNTHETIC_SMOKE"},
        "acknowledgement": {"const": "DEEPSEEK_LIVE_SMOKE_OK"},
    },
    "required": ["kind", "acknowledgement"],
}
DECLARED_ERRORS = tuple(
    sorted(
        {
            "MODEL_INCOMPLETE",
            "MODEL_PROVIDER_AUTHENTICATION_FAILED",
            "MODEL_PROVIDER_BALANCE_EXHAUSTED",
            "MODEL_PROVIDER_FAILED",
            "MODEL_PROVIDER_IDENTITY_INVALID",
            "MODEL_PROVIDER_NETWORK_FAILED",
            "MODEL_PROVIDER_REQUEST_INVALID",
            "MODEL_PROVIDER_REQUEST_TOO_LARGE",
            "MODEL_PROVIDER_RESPONSE_INVALID",
            "MODEL_PROVIDER_RESPONSE_TOO_LARGE",
            "MODEL_PROVIDER_ROUTE_INVALID",
            "MODEL_PROVIDER_SECRET_UNAVAILABLE",
            "MODEL_PROVIDER_TIMEOUT",
            "MODEL_PROVIDER_TIMEOUT_INVALID",
            "MODEL_PROVIDER_TLS_FAILED",
            "MODEL_PROVIDER_UNAVAILABLE",
            "MODEL_RATE_LIMITED",
            "MODEL_REFUSED",
        }
    )
)
RETRYABLE_ERRORS = tuple(
    sorted(
        {
            "MODEL_PROVIDER_NETWORK_FAILED",
            "MODEL_PROVIDER_TIMEOUT",
            "MODEL_PROVIDER_UNAVAILABLE",
            "MODEL_RATE_LIMITED",
        }
    )
)


def _profile() -> InspectionModelProfile:
    payload = profile_payload()
    payload.update(
        {
            "profile_id": "deepseek-live-synthetic-smoke",
            "output_schema_id": "deepseek-live-synthetic-smoke@1.0.0",
            "output_schema": OUTPUT_SCHEMA,
            "output_schema_sha256": canonical_sha256(OUTPUT_SCHEMA),
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
                "max_output_bytes": 4_096,
            },
            "declared_error_codes": DECLARED_ERRORS,
            "retryable_error_codes": RETRYABLE_ERRORS,
        }
    )
    return build_inspection_model_profile(payload)


def _sanitized_failure(code: str) -> dict[str, object]:
    return {
        "result": "FAILED",
        "failure_code": code,
        "physical_network_calls": 0,
        "secret_output": False,
    }


async def _run() -> tuple[dict[str, object], bool]:
    configured = load_model_runtime_configuration(
        ROOT / "config" / "runtime" / "model-bindings.local.yaml",
        env_file_path=ROOT / ".env",
        expected_environment=SecurityEnvironment.LOCAL,
    )
    exporter = InMemorySpanExporter()
    traces = TraceService(
        service_name="deepseek-live-smoke",
        service_version="1.0.0",
        exporter=exporter,
    )
    repository = InMemoryAuditRepository()
    audit = AuditService(repository, traces)
    try:
        registry = configured.build_registry(audit)
        profile = _profile()
        profiles = InspectionModelProfileRegistry(registry, (profile,))
        instruction = build_application_instruction(
            instruction_id="deepseek-live-synthetic-smoke",
            instruction_version="1.0.0",
            text=(
                "Process only the supplied fixed synthetic manifest. Return exactly the JSON "
                "envelope required by response_contract. Do not infer a real inspection finding, "
                "call a tool, or add fields."
            ),
        )
        canonical = dataset(origin=DataOrigin.SIMULATED)
        request = build_model_inference_request(
            {
                "task_id": TASK_ID,
                "run_id": RUN_ID,
                "call_id": CALL_ID,
                "request_id": "deepseek-live-synthetic-smoke-20260826",
                "scope": SCOPE,
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
                "parameters": {"smoke_kind": "fixed-synthetic"},
                "maximum_input_tokens": 9_000,
                "maximum_output_tokens": 256,
                "formal_use_requested": False,
            }
        )
        gateway = ModelInferenceGateway(
            profiles,
            (instruction,),
            build_deepseek_provider(configured, timeout_seconds=30),
            BudgetGuard(default_budget_policy("P1")),
            audit,
        )
        with traces.start_span("model.inference.deepseek-live-smoke"):
            result = await gateway.infer(request)
        output_valid = result.output == {
            "kind": "SYNTHETIC_SMOKE",
            "acknowledgement": "DEEPSEEK_LIVE_SMOKE_OK",
        }
        report: dict[str, object] = {
            "result": result.status.value,
            "provider_id": result.evidence.provider_id,
            "endpoint_id": result.evidence.endpoint_id,
            "model_id": result.evidence.model_id,
            "model_snapshot": result.evidence.model_snapshot,
            "input_tokens": result.evidence.input_tokens,
            "output_tokens": result.evidence.output_tokens,
            "physical_llm_calls": result.evidence.physical_llm_calls,
            "physical_network_calls": result.evidence.physical_network_calls,
            "finish_reason": result.evidence.finish_reason,
            "failure_code": result.failure_code,
            "retryable": result.retryable,
            "output_valid": output_valid,
            "output_sha256": result.evidence.output_sha256,
            "evidence_sha256": result.evidence.evidence_sha256,
            "result_sha256": result.result_sha256,
            "review_required": result.review_required,
            "formal_use_candidate": result.formal_use_candidate,
            "secret_output": False,
        }
        success = (
            result.status is ModelInferenceStatus.SUCCESS
            and output_valid
            and result.evidence.physical_network_calls == 1
        )
        return report, success
    finally:
        traces.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acknowledgement")
    args = parser.parse_args()
    if args.acknowledgement != ACKNOWLEDGEMENT:
        print(json.dumps(_sanitized_failure("DEEPSEEK_POLICY_ACKNOWLEDGEMENT_REQUIRED")))
        return 2
    try:
        report, success = asyncio.run(_run())
    except (ModelConfigurationError, ModelInferenceError) as error:
        print(json.dumps(_sanitized_failure(error.code), sort_keys=True))
        return 1
    except Exception:
        print(json.dumps(_sanitized_failure("DEEPSEEK_SMOKE_INTERNAL_FAILURE"), sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
