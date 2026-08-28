"""S6-02-WEB-STABILITY combined deterministic G0 and P1 Web checks."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ndt_agents.client import ClientTaskClass
from ndt_agents.models.inference import ModelProviderRequest
from ndt_agents.runtime.config import AppSettings
from ndt_agents.runtime.local_workbench import (
    LOCAL_WORKBENCH_SESSION_PATH,
    create_local_workbench_app,
)
from tests.client.test_web_workbench import create_request
from tests.orchestration.test_professional_model_delegate import ProfessionalReviewProvider
from tests.runtime.test_local_workbench_app import enabled_settings
from tests.tools.test_deepseek_agent_live_smoke import DeterministicAgentProvider


class CombinedDeterministicProvider:
    """Dispatch strict offline General and reviewed-professional schemas without network."""

    def __init__(self) -> None:
        self.general = DeterministicAgentProvider()
        self.professional = ProfessionalReviewProvider()

    async def infer(self, request: ModelProviderRequest) -> object:
        output_schema_id = request.output_schema_id
        if output_schema_id == "general-agent-result@1.0.0":
            return await self.general.infer(request)
        return await self.professional.infer(request)


def reviewed_local_settings(tmp_path: Path) -> AppSettings:
    settings = enabled_settings(tmp_path)
    assert settings.agent_config_path is not None
    agent_path = Path(settings.agent_config_path)
    agent_path.write_text(
        agent_path.read_text(encoding="utf-8")
        + """\
    - name: technical_qa
      kind: PROFESSIONAL
      description: Synthetic Technical QA limitations path.
      model: reference
      prompt: technical_qa
      skill_version: technical-qa-1.0.0
      graph_version: child-react-1.0.0
      allowed_tools: []
      max_turns: 3
      timeout_ms: 90000
""",
        encoding="utf-8",
    )
    return AppSettings.model_validate(
        {**settings.model_dump(), "professional_model_delegate_enabled": True}
    )


def test_combined_local_web_g0_and_p1_replay_without_duplicate_calls(tmp_path: Path) -> None:
    settings = reviewed_local_settings(tmp_path)
    provider = CombinedDeterministicProvider()
    app = create_local_workbench_app(
        settings,
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    general_request = create_request(
        task_class=ClientTaskClass.GENERAL,
        goal="Summarize the synthetic Web stability limits.",
        success_criteria=("State synthetic scope", "State non-formal use"),
        idempotency_key="web-stability-general-0001",
    ).model_dump(mode="json")
    professional_request = create_request(
        task_class=ClientTaskClass.PROFESSIONAL_SYNC,
        goal="Review the synthetic Technical QA stability path.",
        success_criteria=("Run independent review", "Preserve non-formal use"),
        idempotency_key="web-stability-professional-0001",
    ).model_dump(mode="json")

    with TestClient(app) as client:
        assert client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False).status_code == 303
        capabilities = client.get("/v1/workbench/capabilities")
        general = client.post("/v1/workbench/tasks", json=general_request)
        general_replay = client.post("/v1/workbench/tasks", json=general_request)
        professional = client.post("/v1/workbench/tasks", json=professional_request)
        professional_replay = client.post("/v1/workbench/tasks", json=professional_request)
        general_events = client.get(
            "/v1/workbench/events",
            params={"task_id": general.json()["task_id"], "after_sequence": 0},
        )
        professional_events = client.get(
            "/v1/workbench/events",
            params={"task_id": professional.json()["task_id"], "after_sequence": 0},
        )
        general_terminal = client.get(
            "/v1/workbench/task", params={"task_id": general.json()["task_id"]}
        )
        professional_terminal = client.get(
            "/v1/workbench/task", params={"task_id": professional.json()["task_id"]}
        )
        professional_terminal_replay = client.get(
            "/v1/workbench/events",
            params={"task_id": professional.json()["task_id"], "after_sequence": 5},
        )

    reopened_provider = CombinedDeterministicProvider()
    reopened_app = create_local_workbench_app(
        settings,
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=reopened_provider,
    )
    with TestClient(reopened_app) as client:
        client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False)
        general_after_restart = client.post("/v1/workbench/tasks", json=general_request)
        professional_after_restart = client.post("/v1/workbench/tasks", json=professional_request)
        professional_events_after_restart = client.get(
            "/v1/workbench/events",
            params={"task_id": professional.json()["task_id"], "after_sequence": 0},
        )

    assert capabilities.json()["task_classes"] == ["G0", "P1"]
    assert general.json()["state"] == "ACCEPTED"
    assert general_terminal.json()["state"] == "SUCCEEDED"
    assert general_replay.json()["task_id"] == general.json()["task_id"]
    assert professional.json()["state"] == "ACCEPTED"
    assert professional_terminal.json()["state"] == "SUCCEEDED"
    assert professional_replay.json()["task_id"] == professional.json()["task_id"]
    assert provider.general.calls == 1
    assert provider.professional.calls == 2
    assert general_after_restart.json() == general_terminal.json()
    assert professional_after_restart.json() == professional_terminal.json()
    assert reopened_provider.general.calls == 0
    assert reopened_provider.professional.calls == 0
    assert general_events.text.count("event: task-event") == 3
    assert professional_events.text.count("event: task-event") == 5
    assert professional_events.text.index('"state":"REVIEW_REQUIRED"') < (
        professional_events.text.index('"state":"SUCCEEDED"')
    )
    assert professional_terminal_replay.text.count("event: task-event") == 0
    assert '"last_sequence":5' in professional_terminal_replay.text
    assert professional_events_after_restart.text.count("event: task-event") == 5
