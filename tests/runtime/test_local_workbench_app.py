"""S6-02-LOCAL-APP packaging and authenticated local composition tests."""

from __future__ import annotations

import socket
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ndt_agents.client import ClientTaskClass, TaskCreateRequest, WorkbenchPersistenceError
from ndt_agents.runtime.config import AppSettings, RuntimeEnvironment
from ndt_agents.runtime.local_workbench import (
    LOCAL_WORKBENCH_SESSION_PATH,
    create_local_workbench_app,
)
from tests.client.test_general_model_workbench import local_settings
from tests.orchestration.test_professional_model_delegate import ProfessionalReviewProvider
from tests.tools.test_deepseek_agent_live_smoke import DeterministicAgentProvider

ROOT = Path(__file__).resolve().parents[2]


def enabled_settings(tmp_path: Path) -> AppSettings:
    values = local_settings(tmp_path, match_workbench_scope=False).model_dump()
    values["local_workbench_enabled"] = True
    values["local_workbench_state_path"] = str(tmp_path / "workbench.sqlite3")
    return AppSettings.model_validate(values)


def request_payload(task_class: ClientTaskClass) -> dict[str, object]:
    return TaskCreateRequest(
        task_class=task_class,
        goal="Summarize one synthetic local frontend integration check.",
        success_criteria=("State synthetic scope", "State non-formal use"),
        idempotency_key=f"local-workbench-{task_class.value.lower()}-0001",
    ).model_dump(mode="json")


def test_local_workbench_setting_is_default_off_and_fail_closed(tmp_path: Path) -> None:
    assert AppSettings().local_workbench_enabled is False
    assert AppSettings().local_workbench_state_path is None
    base = local_settings(tmp_path).model_dump()

    with pytest.raises(ValidationError):
        AppSettings.model_validate(
            {**base, "local_workbench_state_path": str(tmp_path / "workbench.sqlite3")}
        )

    with pytest.raises(ValidationError):
        AppSettings.model_validate({**base, "local_workbench_enabled": True, "host": "0.0.0.0"})
    with pytest.raises(ValidationError):
        AppSettings.model_validate(
            {
                **base,
                "local_workbench_enabled": True,
                "environment": RuntimeEnvironment.PRODUCTION,
            }
        )
    with pytest.raises(ValidationError):
        AppSettings.model_validate(
            {
                **base,
                "local_workbench_enabled": True,
                "general_model_delegate_enabled": False,
                "deepseek_policy_acknowledgement": None,
            }
        )


def test_local_session_mounts_g0_workbench_without_network_or_secret_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = DeterministicAgentProvider()

    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("local workbench startup attempted a physical network call")

    with monkeypatch.context() as isolated:
        isolated.setattr(socket.socket, "connect", deny_network)
        app = create_local_workbench_app(
            enabled_settings(tmp_path),
            configure_logs=False,
            model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
            model_provider=provider,
        )

    with TestClient(app) as client:
        denied = client.get("/v1/workbench/capabilities")
        session = client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False)
        shell = client.get(session.headers["location"])
        capabilities = client.get("/v1/workbench/capabilities")
        completed = client.post(
            "/v1/workbench/tasks",
            json=request_payload(ClientTaskClass.GENERAL),
        )
        unsupported = client.post(
            "/v1/workbench/tasks",
            json=request_payload(ClientTaskClass.PROFESSIONAL_SYNC),
        )
        completed_events = client.get(
            "/v1/workbench/events",
            params={"task_id": completed.json()["task_id"], "after_sequence": 0},
        )
        unsupported_events = client.get(
            "/v1/workbench/events",
            params={"task_id": unsupported.json()["task_id"], "after_sequence": 0},
        )
        completed_terminal = client.get(
            "/v1/workbench/task", params={"task_id": completed.json()["task_id"]}
        )
        unsupported_terminal = client.get(
            "/v1/workbench/task", params={"task_id": unsupported.json()["task_id"]}
        )

    assert denied.status_code == 401
    assert session.status_code == 303
    assert session.headers["location"] == "/workbench"
    cookie = session.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "DEEPSEEK_API_KEY" not in cookie + session.text + shell.text
    assert shell.status_code == 200
    assert capabilities.status_code == 200
    assert capabilities.json()["task_classes"] == ["G0"]
    assert capabilities.json()["execution_mode"] == "GENERAL_LOCAL"
    assert completed.status_code == 202
    assert completed.json()["state"] == "ACCEPTED"
    assert completed_terminal.json()["state"] == "SUCCEEDED"
    assert '"state":"SUCCEEDED"' in completed_events.text
    assert unsupported.status_code == 202
    assert unsupported.json()["state"] == "ACCEPTED"
    assert unsupported_terminal.json()["state"] == "FAILED"
    assert "CLIENT_GENERAL_MODEL_TASK_CLASS_DENIED" in unsupported_events.text
    assert provider.calls == 1


def test_python_project_has_pinned_build_backend_and_console_entry() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["build-system"] == {
        "requires": ["uv_build==0.11.20"],
        "build-backend": "uv_build",
    }
    assert project["project"]["scripts"]["ndt-agents"] == ("ndt_agents.runtime.__main__:entrypoint")
    assert project["tool"]["uv"]["package"] is True


def test_local_session_exposes_p1_only_when_professional_models_are_enabled(
    tmp_path: Path,
) -> None:
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
    values = settings.model_dump()
    values["professional_model_delegate_enabled"] = True
    provider = ProfessionalReviewProvider()
    app = create_local_workbench_app(
        AppSettings.model_validate(values),
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )

    with TestClient(app) as client:
        client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False)
        capabilities = client.get("/v1/workbench/capabilities")
        completed = client.post(
            "/v1/workbench/tasks",
            json=request_payload(ClientTaskClass.PROFESSIONAL_SYNC),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": completed.json()["task_id"], "after_sequence": 0},
        )
        terminal = client.get("/v1/workbench/task", params={"task_id": completed.json()["task_id"]})

    assert capabilities.json()["execution_mode"] == "REVIEWED_PROFESSIONAL"
    assert capabilities.json()["task_classes"] == ["G0", "P1"]
    assert completed.json()["state"] == "ACCEPTED"
    assert terminal.json()["state"] == "SUCCEEDED"
    assert events.text.count("event: task-event") == 5
    assert provider.calls == 2


def test_local_workbench_reopen_replays_without_duplicate_provider_call(tmp_path: Path) -> None:
    settings = enabled_settings(tmp_path)
    first_provider = DeterministicAgentProvider()
    first_app = create_local_workbench_app(
        settings,
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=first_provider,
    )

    with TestClient(first_app) as client:
        client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False)
        completed = client.post(
            "/v1/workbench/tasks",
            json=request_payload(ClientTaskClass.GENERAL),
        )
        completed_events = client.get(
            "/v1/workbench/events",
            params={"task_id": completed.json()["task_id"], "after_sequence": 0},
        )
        completed_terminal = client.get(
            "/v1/workbench/task", params={"task_id": completed.json()["task_id"]}
        )

    second_provider = DeterministicAgentProvider()
    reopened_app = create_local_workbench_app(
        settings,
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=second_provider,
    )
    with TestClient(reopened_app) as client:
        client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False)
        replay = client.post(
            "/v1/workbench/tasks",
            json=request_payload(ClientTaskClass.GENERAL),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": completed.json()["task_id"], "after_sequence": 0},
        )

    assert completed.status_code == 202
    assert replay.status_code == 202
    assert completed.json()["state"] == "ACCEPTED"
    assert completed_terminal.json()["state"] == "SUCCEEDED"
    assert replay.json() == completed_terminal.json()
    assert completed_events.text.count("event: task-event") == 3
    assert events.text.count("event: task-event") == 3
    assert '"terminal":true' in events.text
    assert str(settings.local_workbench_state_path) not in replay.text + events.text
    assert first_provider.calls == 1
    assert second_provider.calls == 0


def test_local_workbench_unavailable_state_path_never_falls_back(tmp_path: Path) -> None:
    settings = enabled_settings(tmp_path)
    values = settings.model_dump()
    values["local_workbench_state_path"] = str(tmp_path / "missing" / "workbench.sqlite3")
    provider = DeterministicAgentProvider()

    with pytest.raises(WorkbenchPersistenceError) as unavailable:
        create_local_workbench_app(
            AppSettings.model_validate(values),
            configure_logs=False,
            model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
            model_provider=provider,
        )

    assert unavailable.value.code == "CLIENT_PERSISTENCE_UNAVAILABLE"
    assert provider.calls == 0
