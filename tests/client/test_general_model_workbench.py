"""S6-02-APP local General delegate and authenticated Web task E2E tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ndt_agents.client import ClientTaskClass, WorkbenchRuntime
from ndt_agents.models.inference import (
    ModelProviderError,
    ModelProviderRequest,
)
from ndt_agents.orchestration.general_model_delegate import (
    DEEPSEEK_POLICY_ACKNOWLEDGEMENT,
)
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings, RuntimeEnvironment
from tests.client.test_web_workbench import (
    PROJECT_ID,
    TENANT_ID,
    create_request,
    headers,
    identity,
    signing_material,
    token,
)
from tests.models.test_model_runtime_config import binding_payload, write_configuration
from tests.orchestration.test_agent_runtime_config import valid_yaml, write_yaml
from tests.tools.test_deepseek_agent_live_smoke import DeterministicAgentProvider

ROOT = Path(__file__).resolve().parents[2]


class FailingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def infer(self, _request: ModelProviderRequest) -> object:
        self.calls += 1
        raise ModelProviderError(
            "MODEL_PROVIDER_UNAVAILABLE",
            "synthetic provider outage",
            retryable=True,
            next_action="Wait for an explicitly authorized new call.",
            physical_network_calls=1,
        )


def local_settings(tmp_path: Path, *, match_workbench_scope: bool = True) -> AppSettings:
    binding = binding_payload()
    if match_workbench_scope:
        binding.update(
            {
                "tenant_id": str(TENANT_ID),
                "project_id": str(PROJECT_ID),
                "permission_version": "permissions-s6-1",
            }
        )
    model_path = write_configuration(tmp_path / "models", bindings=[binding])
    agent_directory = tmp_path / "agents"
    agent_directory.mkdir()
    agent_path = write_yaml(agent_directory, valid_yaml())
    return AppSettings(
        environment=RuntimeEnvironment.LOCAL,
        model_config_path=str(model_path),
        prompt_config_path=str(ROOT / "prompts/professional/catalog.v1.yaml"),
        agent_config_path=str(agent_path),
        general_model_delegate_enabled=True,
        deepseek_policy_acknowledgement=DEEPSEEK_POLICY_ACKNOWLEDGEMENT,
    )


def test_default_off_and_local_acknowledgement_fail_closed(tmp_path: Path) -> None:
    assert AppSettings().general_model_delegate_enabled is False
    binding = binding_payload()
    binding.update(
        {
            "tenant_id": str(TENANT_ID),
            "project_id": str(PROJECT_ID),
            "permission_version": "permissions-s6-1",
        }
    )
    model_path = write_configuration(tmp_path / "models", bindings=[binding])
    agent_directory = tmp_path / "agents"
    agent_directory.mkdir()
    agent_path = write_yaml(agent_directory, valid_yaml())
    values = {
        "model_config_path": str(model_path),
        "prompt_config_path": str(ROOT / "prompts/professional/catalog.v1.yaml"),
        "agent_config_path": str(agent_path),
        "general_model_delegate_enabled": True,
    }
    with pytest.raises(ValidationError):
        AppSettings.model_validate(values)
    with pytest.raises(ValidationError):
        AppSettings.model_validate(
            {
                **values,
                "environment": RuntimeEnvironment.CI,
                "deepseek_policy_acknowledgement": DEEPSEEK_POLICY_ACKNOWLEDGEMENT,
            }
        )


def test_authenticated_g0_task_runs_main_general_and_terminal_events(tmp_path: Path) -> None:
    private_key, jwks = signing_material()
    provider = DeterministicAgentProvider()
    runtime = WorkbenchRuntime()
    app = create_app(
        local_settings(tmp_path),
        configure_logs=False,
        identity=identity(jwks),
        workbench=runtime,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    request = create_request(
        task_class=ClientTaskClass.GENERAL,
        goal="Summarize the synthetic integration limitations.",
        success_criteria=("State synthetic scope", "State non-formal use"),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=request.model_dump(mode="json"),
        )
        replay = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=request.model_dump(mode="json"),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": response.json()["task_id"], "after_sequence": 0},
            headers=headers(token(private_key)),
        )

    assert response.status_code == 202
    assert replay.json()["task_id"] == response.json()["task_id"]
    assert replay.json()["state"] == "SUCCEEDED"
    assert response.json()["state"] == "SUCCEEDED", (
        response.json(),
        events.text,
        app.state.general_model_delegate.last_error_code,
    )
    assert response.json()["formal_use_allowed"] is False
    assert provider.calls == 1, events.text
    assert provider.last_request is not None
    assert provider.last_request.maximum_input_tokens == 3_600
    assert provider.last_request.maximum_output_tokens == 2_048
    assert (
        str(provider.last_request.canonical_data.scope.tenant_id)
        == response.json()["scope"]["tenant_id"]
    )
    assert events.text.count("event: task-event") == 3
    assert '"sequence":1' in events.text
    assert '"sequence":2' in events.text
    assert '"sequence":3' in events.text
    assert '"state":"SUCCEEDED"' in events.text
    assert "Synthetic local model evidence remains review-required" in events.text
    delegate = app.state.general_model_delegate
    assert delegate.calls == 1
    assert delegate.last_inference is not None
    assert delegate.last_inference.review_required is True
    assert delegate.last_inference.formal_use_candidate is False
    assert delegate.last_inference.evidence.physical_tool_calls == 0


def test_non_general_task_is_denied_before_provider_call(tmp_path: Path) -> None:
    private_key, jwks = signing_material()
    provider = DeterministicAgentProvider()
    app = create_app(
        local_settings(tmp_path),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=create_request().model_dump(mode="json"),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": response.json()["task_id"], "after_sequence": 0},
            headers=headers(token(private_key)),
        )

    assert response.json()["state"] == "FAILED"
    assert provider.calls == 0
    assert "CLIENT_GENERAL_MODEL_TASK_CLASS_DENIED" in events.text


def test_model_binding_scope_mismatch_is_denied_before_provider_call(tmp_path: Path) -> None:
    private_key, jwks = signing_material()
    provider = DeterministicAgentProvider()
    app = create_app(
        local_settings(tmp_path, match_workbench_scope=False),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=create_request(task_class=ClientTaskClass.GENERAL).model_dump(mode="json"),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": response.json()["task_id"], "after_sequence": 0},
            headers=headers(token(private_key)),
        )

    assert response.json()["state"] == "FAILED"
    assert provider.calls == 0
    assert "MODEL_SCOPE_MISMATCH" in events.text


def test_malformed_model_output_fails_typed_after_one_call(tmp_path: Path) -> None:
    private_key, jwks = signing_material()
    provider = DeterministicAgentProvider(malformed=True)
    app = create_app(
        local_settings(tmp_path),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=create_request(task_class=ClientTaskClass.GENERAL).model_dump(mode="json"),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": response.json()["task_id"], "after_sequence": 0},
            headers=headers(token(private_key)),
        )

    assert response.json()["state"] == "FAILED"
    assert provider.calls == 1
    assert "MODEL_OUTPUT_SCHEMA_INVALID" in events.text


def test_provider_failure_is_typed_without_retry(tmp_path: Path) -> None:
    private_key, jwks = signing_material()
    provider = FailingProvider()
    app = create_app(
        local_settings(tmp_path),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=create_request(task_class=ClientTaskClass.GENERAL).model_dump(mode="json"),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": response.json()["task_id"], "after_sequence": 0},
            headers=headers(token(private_key)),
        )

    assert response.json()["state"] == "FAILED"
    assert provider.calls == 1
    assert "MODEL_PROVIDER_UNAVAILABLE" in events.text


def test_application_delegate_has_no_test_or_smoke_tool_dependency() -> None:
    source = (ROOT / "src/ndt_agents/orchestration/general_model_delegate.py").read_text(
        encoding="utf-8"
    )
    assert "from tests" not in source
    assert "tools.deepseek_agent_live_smoke" not in source
    shell = (ROOT / "src/ndt_agents/client/web/index.html").read_text(encoding="utf-8")
    assert "SYNTHETIC test input only" in shell
    assert "Do not submit customer" in shell
