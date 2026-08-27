"""S6-02-LOCAL-APP packaging and authenticated local composition tests."""

from __future__ import annotations

import socket
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ndt_agents.client import ClientTaskClass, TaskCreateRequest
from ndt_agents.runtime.config import AppSettings, RuntimeEnvironment
from ndt_agents.runtime.local_workbench import (
    LOCAL_WORKBENCH_SESSION_PATH,
    create_local_workbench_app,
)
from tests.client.test_general_model_workbench import local_settings
from tests.tools.test_deepseek_agent_live_smoke import DeterministicAgentProvider

ROOT = Path(__file__).resolve().parents[2]


def enabled_settings(tmp_path: Path) -> AppSettings:
    values = local_settings(tmp_path, match_workbench_scope=False).model_dump()
    values["local_workbench_enabled"] = True
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
    base = local_settings(tmp_path).model_dump()

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
    assert completed.json()["state"] == "SUCCEEDED"
    assert unsupported.status_code == 202
    assert unsupported.json()["state"] == "FAILED"
    assert provider.calls == 1


def test_python_project_has_pinned_build_backend_and_console_entry() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["build-system"] == {
        "requires": ["uv_build==0.11.20"],
        "build-backend": "uv_build",
    }
    assert project["project"]["scripts"]["ndt-agents"] == ("ndt_agents.runtime.__main__:entrypoint")
    assert project["tool"]["uv"]["package"] is True
