"""S1-01 UNIT-CORE checks for the provider-neutral API scaffold."""

from __future__ import annotations

import json
import logging
import socket

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings, ConfigurationError, RuntimeEnvironment
from ndt_agents.runtime.logging import JsonFormatter, bind_request_id, reset_request_id


def test_settings_load_known_environment_and_are_immutable() -> None:
    settings = AppSettings.from_environment(
        {
            "NDT_ENVIRONMENT": "ci",
            "NDT_LOG_LEVEL": "DEBUG",
            "NDT_HOST": "0.0.0.0",
            "NDT_PORT": "9010",
            "NDT_EXPOSE_API_DOCS": "true",
        }
    )

    assert settings.environment is RuntimeEnvironment.CI
    assert settings.log_level == "DEBUG"
    assert settings.host == "0.0.0.0"
    assert settings.port == 9010
    assert settings.expose_api_docs is True
    with pytest.raises(ValidationError):
        settings.port = 1


@pytest.mark.parametrize(
    ("environment", "expected_code"),
    [
        ({"NDT_UNKNOWN_SETTING": "value"}, "CONFIG_UNKNOWN_ENVIRONMENT_KEY"),
        ({"NDT_PORT": "not-a-port"}, "CONFIG_VALIDATION_FAILED"),
        ({"NDT_ENVIRONMENT": "production", "NDT_EXPOSE_API_DOCS": "true"}, "CONFIG_UNSAFE"),
    ],
)
def test_settings_fail_with_stable_non_disclosing_errors(
    environment: dict[str, str], expected_code: str
) -> None:
    with pytest.raises(ConfigurationError) as captured:
        AppSettings.from_environment(environment)

    assert captured.value.code == expected_code
    assert captured.value.__cause__ is None
    assert "value" not in str(captured.value)
    assert "not-a-port" not in str(captured.value)


def test_json_logs_include_correlation_and_redact_credentials() -> None:
    formatter = JsonFormatter(service_name="ndt-test", environment="ci")
    token = bind_request_id("request-123")
    try:
        record = logging.LogRecord(
            name="ndt_agents.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="authorization=Bearer private-token password=hunter2",
            args=(),
            exc_info=None,
        )
        record.event = "test_event"
        record.path = "/password=path-secret"
        payload = json.loads(formatter.format(record))
    finally:
        reset_request_id(token)

    assert payload["event"] == "test_event"
    assert payload["request_id"] == "request-123"
    assert payload["service"] == "ndt-test"
    assert "private-token" not in payload["message"]
    assert "hunter2" not in payload["message"]
    assert payload["message"].count("[REDACTED]") == 2
    assert "path-secret" not in payload["path"]


def test_app_factory_and_health_checks_need_no_external_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("S1-01 startup attempted external network access")

    with monkeypatch.context() as isolated:
        isolated.setattr(socket.socket, "connect", deny_network)
        app = create_app(AppSettings(environment=RuntimeEnvironment.CI), configure_logs=False)

    with TestClient(app) as client:
        live = client.get("/health/live", headers={"x-request-id": "health-live-1"})
        ready = client.get("/health/ready", headers={"x-request-id": "health-ready-1"})

    assert live.status_code == 200
    assert live.headers["x-request-id"] == "health-live-1"
    assert live.headers["cache-control"] == "no-store"
    assert live.json() == {
        "schema_version": "1.0.0",
        "service": "ndt-agents",
        "service_version": "0.1.0",
        "status": "PASS",
        "checks": [{"name": "process", "status": "PASS", "error_code": None}],
    }
    assert ready.status_code == 200
    assert ready.json()["checks"] == [{"name": "application", "status": "PASS", "error_code": None}]


def test_api_docs_are_disabled_by_default_and_can_be_enabled_outside_production() -> None:
    default_app = create_app(AppSettings(), configure_logs=False)
    documented_app = create_app(AppSettings(expose_api_docs=True), configure_logs=False)

    with TestClient(default_app) as default_client:
        assert default_client.get("/openapi.json").status_code == 404
    with TestClient(documented_app) as documented_client:
        response = documented_client.get("/openapi.json")
        assert response.status_code == 200
        assert response.json()["info"]["version"] == "0.1.0"


def test_invalid_correlation_header_is_not_reflected() -> None:
    app = create_app(AppSettings(), configure_logs=False)

    with TestClient(app) as client:
        response = client.get("/health/live", headers={"x-request-id": "bad id\r\nvalue"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad id\r\nvalue"
    assert len(response.headers["x-request-id"]) == 32


def test_unhandled_error_returns_typed_non_disclosing_problem() -> None:
    app = create_app(AppSettings(), configure_logs=False)

    @app.get("/_test/failure", include_in_schema=False)
    def fail() -> None:
        raise RuntimeError("password=do-not-disclose")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/failure", headers={"x-request-id": "failure-1"})

    assert response.status_code == 500
    assert response.json() == {
        "schema_version": "1.0.0",
        "error_code": "INTERNAL_ERROR",
        "message": "The request could not be completed.",
        "request_id": "failure-1",
        "retryable": False,
        "next_action": "Contact the service operator with the request ID.",
    }
    assert "do-not-disclose" not in response.text
