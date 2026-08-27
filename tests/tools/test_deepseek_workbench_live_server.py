"""Offline tests for the loopback-only live Web runner."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ndt_agents.orchestration.general_model_delegate import DEEPSEEK_POLICY_ACKNOWLEDGEMENT
from tests.client.test_general_model_workbench import local_settings
from tests.tools.test_deepseek_agent_live_smoke import DeterministicAgentProvider
from tools.deepseek_workbench_live_server import (
    FIXED_GOAL,
    FIXED_SUCCESS_CRITERIA,
    HOST,
    PORT,
    create_live_app,
)


def _request(*, goal: str = FIXED_GOAL) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "task_class": "G0",
        "goal": goal,
        "success_criteria": list(FIXED_SUCCESS_CRITERIA),
        "idempotency_key": "s6-web-live-offline-test",
    }


def test_runner_rejects_non_loopback_settings_before_provider(tmp_path: Path) -> None:
    provider = DeterministicAgentProvider()
    settings = local_settings(tmp_path, match_workbench_scope=False).model_copy(
        update={"host": "0.0.0.0", "port": PORT}
    )
    try:
        create_live_app(settings, model_provider=provider)
    except ValueError as error:
        assert "loopback" in str(error)
    else:
        raise AssertionError("non-loopback live runner settings were accepted")
    assert provider.calls == 0


def test_fixed_session_task_calls_injected_provider_once(tmp_path: Path) -> None:
    provider = DeterministicAgentProvider()
    settings = local_settings(tmp_path, match_workbench_scope=False).model_copy(
        update={
            "host": HOST,
            "port": PORT,
            "deepseek_policy_acknowledgement": DEEPSEEK_POLICY_ACKNOWLEDGEMENT,
        }
    )
    app = create_live_app(
        settings,
        model_provider=provider,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
    )
    with TestClient(app) as client:
        assert client.get("/local-live/session").status_code == 200
        denied = client.post(
            "/v1/workbench/tasks",
            json=_request(goal="Changed input."),
        )
        response = client.post("/v1/workbench/tasks", json=_request())
        replay = client.post("/v1/workbench/tasks", json=_request())
        evidence = client.get("/local-live/evidence")

    assert denied.status_code == 403
    assert denied.json()["error_code"] == "LIVE_SYNTHETIC_REQUEST_REQUIRED"
    assert response.status_code == 202
    assert response.json()["state"] == "SUCCEEDED", (response.json(), evidence.json())
    assert replay.json()["task_id"] == response.json()["task_id"]
    assert provider.calls == 1
    assert provider.last_request is not None
    assert provider.last_request.maximum_input_tokens == 3_600
    assert provider.last_request.maximum_output_tokens == 2_400
    assert evidence.json()["result"] == "SUCCESS"
    assert evidence.json()["physical_llm_calls"] == 1
    assert evidence.json()["physical_network_calls"] == 1
    assert evidence.json()["physical_tool_calls"] == 0
    assert evidence.json()["formal_use_candidate"] is False
    assert evidence.json()["secret_output"] is False
