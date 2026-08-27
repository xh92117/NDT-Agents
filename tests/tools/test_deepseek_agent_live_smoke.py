"""Offline tests for the bounded Main-to-General DeepSeek smoke."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ndt_agents.models.config import (
    ConfiguredModelRuntime,
    load_model_runtime_configuration,
)
from ndt_agents.models.inference import (
    ModelMetric,
    ModelProviderReply,
    ModelProviderRequest,
    ModelProviderStatus,
)
from ndt_agents.orchestration.agent_config import (
    ConfiguredAgentRuntime,
    load_agent_runtime_configuration,
)
from ndt_agents.orchestration.prompt_registry import load_prompt_registry
from tests.models.test_model_runtime_config import write_configuration
from tests.orchestration.test_agent_runtime_config import valid_yaml, write_yaml
from tools.deepseek_agent_live_smoke import (
    TASK_ID,
    _agent_result_schema,
    _sanitized_failure,
    _task,
    run_with_provider,
)

ROOT = Path(__file__).resolve().parents[2]


def _offline_runtimes(
    tmp_path: Path,
) -> tuple[ConfiguredModelRuntime, ConfiguredAgentRuntime]:
    configured_models = load_model_runtime_configuration(
        write_configuration(tmp_path / "models"),
        environ={"DEEPSEEK_API_KEY": "offline-placeholder"},
    )
    agent_directory = tmp_path / "agents"
    agent_directory.mkdir()
    agent_runtime = load_agent_runtime_configuration(
        write_yaml(agent_directory, valid_yaml()),
        model_runtime=configured_models,
        prompt_registry=load_prompt_registry(ROOT / "prompts/professional/catalog.v1.yaml"),
    )
    return configured_models, agent_runtime


class DeterministicAgentProvider:
    def __init__(self, *, malformed: bool = False) -> None:
        self.calls = 0
        self.malformed = malformed
        self.last_request: ModelProviderRequest | None = None
        self.last_output: dict[str, Any] | None = None

    async def infer(self, request: ModelProviderRequest) -> object:
        self.calls += 1
        self.last_request = request
        child = request.parameters["child_context"]
        assert isinstance(child, dict)
        output: dict[str, Any] = {
            "schema_version": "1.0.0",
            "task_id": child["parent_task_id"],
            "run_id": child["run_id"],
            "status": "SUCCESS",
            "summary": "The bounded synthetic integration path completed.",
            "structured_data": {
                "completed_work": ["Validated the configured General child path."],
                "limitations": ["Synthetic personal-development evidence only."],
                "next_action": "Review sanitized evidence before another call.",
            },
            "artifacts": [],
            "evidence": [],
            "confidence": Decimal("0.9"),
            "issues": [],
            "retryable": False,
            "failure_code": None,
            "completed_at": "2026-08-27T00:00:00Z",
        }
        if self.malformed:
            output.pop("summary")
        self.last_output = output
        return ModelProviderReply(
            call_id=request.call_id,
            provider_request_sha256=request.provider_request_sha256,
            provider_id=request.provider_id,
            provider_version=request.provider_version,
            endpoint_id=request.endpoint_id,
            model_id=request.model_id,
            model_snapshot=request.model_snapshot,
            provider_request_id="offline-live-agent-1",
            status=ModelProviderStatus.SUCCESS,
            output=output,
            artifacts=(),
            input_tokens=400,
            output_tokens=120,
            confidence=Decimal("0.90"),
            metrics=(ModelMetric(metric="quality_score", value=Decimal("1")),),
            finish_reason="stop",
            physical_network_calls=1,
        )


def test_live_agent_schema_is_exact_scope_and_non_formal() -> None:
    task = _task()
    assert task.task_id == TASK_ID
    assert task.task_class == "G0"
    assert task.allowed_tools == ()
    assert task.budget.policy_id == "budget-g0-live-smoke-v1"
    assert task.budget.total_tokens.default == 4_000
    assert task.budget.total_tokens.active == 6_000
    assert task.budget.total_tokens.hard == 8_000
    schema = _agent_result_schema(
        type("Context", (), {"parent_task_id": task.task_id, "run_id": TASK_ID})()
    )
    assert schema["additionalProperties"] is False
    assert schema["properties"]["task_id"] == {"const": str(TASK_ID)}
    assert schema["properties"]["artifacts"]["maxItems"] == 0
    assert schema["properties"]["evidence"]["maxItems"] == 0


def test_offline_provider_runs_main_general_and_aggregation_once(tmp_path: Path) -> None:
    provider = DeterministicAgentProvider()
    configured_models, agent_runtime = _offline_runtimes(tmp_path)
    report, success = asyncio.run(
        run_with_provider(
            provider,
            configured_models=configured_models,
            agent_runtime=agent_runtime,
        )
    )

    errors = []
    if provider.last_request is not None and provider.last_output is not None:
        errors = [
            error.message
            for error in Draft202012Validator(provider.last_request.output_schema).iter_errors(
                provider.last_output
            )
        ]
    assert success is True, (report, errors)
    assert provider.calls == 1, report
    assert report["result"] == "SUCCESS"
    assert report["route"] == "GENERAL_SYNC"
    assert report["aggregation_source"] == "GENERAL"
    assert report["physical_llm_calls"] == 1
    assert report["physical_tool_calls"] == 0
    assert report["physical_network_calls"] == 1
    assert report["input_tokens"] == 400
    assert report["output_tokens"] == 120
    assert report["finish_reason"] == "stop"
    assert report["formal_use_candidate"] is False
    assert report["secret_output"] is False
    assert provider.last_request is not None
    assert provider.last_request.maximum_input_tokens == 3_400
    assert provider.last_request.maximum_output_tokens == 2_048
    assert (
        provider.last_request.maximum_input_tokens + provider.last_request.maximum_output_tokens
        <= _task().budget.total_tokens.active
    )


def test_malformed_provider_output_fails_without_aggregation(tmp_path: Path) -> None:
    provider = DeterministicAgentProvider(malformed=True)
    configured_models, agent_runtime = _offline_runtimes(tmp_path)
    report, success = asyncio.run(
        run_with_provider(
            provider,
            configured_models=configured_models,
            agent_runtime=agent_runtime,
        )
    )

    assert success is False
    assert provider.calls == 1
    assert report["result"] == "FAILED"
    assert report["failure_code"] == "MODEL_OUTPUT_SCHEMA_INVALID"
    assert report["physical_network_calls"] == 1


def test_acknowledgement_failure_is_sanitized_and_zero_call() -> None:
    assert _sanitized_failure("DEEPSEEK_POLICY_ACKNOWLEDGEMENT_REQUIRED") == {
        "result": "FAILED",
        "failure_code": "DEEPSEEK_POLICY_ACKNOWLEDGEMENT_REQUIRED",
        "physical_llm_calls": 0,
        "physical_tool_calls": 0,
        "physical_network_calls": 0,
        "secret_output": False,
    }
