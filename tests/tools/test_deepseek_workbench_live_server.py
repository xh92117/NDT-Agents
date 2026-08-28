"""Offline tests for the loopback-only live Web runner."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.orchestration.test_professional_model_delegate import (
    ProfessionalReviewProvider,
    professional_settings,
)
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
        "task_class": "P1",
        "goal": goal,
        "success_criteria": list(FIXED_SUCCESS_CRITERIA),
        "idempotency_key": "s6-web-live-offline-test",
    }


def test_runner_rejects_non_loopback_settings_before_provider(tmp_path: Path) -> None:
    provider = ProfessionalReviewProvider()
    settings = professional_settings(tmp_path, match_workbench_scope=False).model_copy(
        update={"host": "0.0.0.0", "port": PORT}
    )
    try:
        create_live_app(settings, model_provider=provider)
    except ValueError as error:
        assert "loopback" in str(error)
    else:
        raise AssertionError("non-loopback live runner settings were accepted")
    assert provider.calls == 0


def test_fixed_session_p1_task_calls_professional_and_review_once_each(tmp_path: Path) -> None:
    provider = ProfessionalReviewProvider()
    settings = professional_settings(tmp_path, match_workbench_scope=False).model_copy(
        update={"host": HOST, "port": PORT}
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
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": response.json()["task_id"], "after_sequence": 0},
        )
        completed = client.get(
            "/v1/workbench/task",
            params={"task_id": response.json()["task_id"]},
        )
        replay = client.post("/v1/workbench/tasks", json=_request())
        evidence = client.get("/local-live/evidence")
        evidence_view = client.get("/local-live/evidence/view")

    assert denied.status_code == 403
    assert denied.json()["error_code"] == "LIVE_SYNTHETIC_REQUEST_REQUIRED"
    assert response.status_code == 202
    assert response.json()["state"] == "ACCEPTED"
    assert completed.json()["state"] == "SUCCEEDED", (events.text, evidence.json())
    assert replay.json()["task_id"] == response.json()["task_id"]
    assert replay.json()["state"] == "SUCCEEDED"
    assert provider.calls == 2
    professional, review = provider.requests
    assert professional.maximum_input_tokens == 3_600
    assert professional.maximum_output_tokens == 2_400
    assert review.maximum_input_tokens == 3_000
    assert review.maximum_output_tokens == 1_000
    assert evidence.json()["result"] == "SUCCESS"
    assert evidence.json()["professional_delegate_calls"] == 1
    assert evidence.json()["review_delegate_calls"] == 1
    assert evidence.json()["input_tokens"] == 600
    assert evidence.json()["output_tokens"] == 200
    assert evidence.json()["professional_input_tokens"] == 300
    assert evidence.json()["professional_output_tokens"] == 100
    assert evidence.json()["professional_finish_reason"] == "stop"
    assert evidence.json()["review_input_tokens"] == 300
    assert evidence.json()["review_output_tokens"] == 100
    assert evidence.json()["review_finish_reason"] == "stop"
    assert evidence.json()["physical_llm_calls"] == 2
    assert evidence.json()["physical_network_calls"] == 2
    assert evidence.json()["physical_tool_calls"] == 0
    assert evidence.json()["review_completed"] is True
    assert evidence.json()["formal_use_candidate"] is False
    assert evidence.json()["secret_output"] is False
    assert evidence_view.status_code == 200
    assert evidence_view.headers["content-type"].startswith("text/html")
    assert "&quot;physical_llm_calls&quot;: 2" in evidence_view.text
    assert "Synthetic Technical QA limitations were identified." not in evidence_view.text
