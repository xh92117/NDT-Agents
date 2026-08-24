"""S5-07 YAML/environment bootstrap and local secret-source tests."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from ndt_agents.models import BindingState
from ndt_agents.models.config import (
    ModelConfigurationError,
    load_model_runtime_configuration,
)
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings, ConfigurationError
from ndt_agents.security import SecurityEnvironment, SecurityError

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config" / "model-providers" / "deepseek-v4.v1.json"
EXAMPLE_CONFIG = ROOT / "config" / "runtime" / "model-bindings.example.yaml"
EXAMPLE_ENV = ROOT / ".env.example"


def binding_payload(
    *, state: str = "ENABLED", binding_id: str = "personal-deepseek"
) -> dict[str, Any]:
    return {
        "binding_id": binding_id,
        "version": "1.0.0",
        "provider_id": "deepseek",
        "provider_version": "1.0.0",
        "environment": "local",
        "tenant_id": "00000000-0000-4000-8000-000000000101",
        "project_id": "00000000-0000-4000-8000-000000000102",
        "permission_version": "permissions-1",
        "endpoint_id": "openai-chat",
        "state": state,
        "allowed_model_ids": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "default_model_id": "deepseek-v4-pro",
        "fallback_model_ids": ["deepseek-v4-flash"],
        "allowed_data_classes": ["PUBLIC", "SYNTHETIC"],
        "required_permission": "model.invoke.deepseek",
        "budget_policy_version": "budget-policy-1.0.0",
        "timeout_ms": 120000,
        "max_attempts": 2,
        "max_concurrency": 1,
        "max_input_tokens": 120000,
        "max_output_tokens": 60000,
        "secret": {
            "source": "ENVIRONMENT",
            "variable": "DEEPSEEK_API_KEY",
            "version": "local-v1",
            "secret_id": "deepseek-api-key",
            "purpose": "model.deepseek.credential",
        },
    }


def write_configuration(
    tmp_path: Path,
    *,
    bindings: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    runtime_dir = tmp_path / "runtime"
    catalog_dir = tmp_path / "model-providers"
    runtime_dir.mkdir(parents=True)
    catalog_dir.mkdir(parents=True)
    shutil.copyfile(CATALOG, catalog_dir / CATALOG.name)
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "config_version": "1.0.0",
        "catalogs": [f"../model-providers/{CATALOG.name}"],
        "bindings": bindings if bindings is not None else [binding_payload()],
    }
    if extra:
        payload.update(extra)
    path = runtime_dir / "model-bindings.local.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_yaml_and_env_file_assemble_reference_only_runtime(tmp_path: Path) -> None:
    config_path = write_configuration(tmp_path)
    env_path = tmp_path / ".env.local"
    env_path.write_text('DEEPSEEK_API_KEY="file-secret-value"\n', encoding="utf-8")

    runtime = load_model_runtime_configuration(
        config_path,
        env_file_path=env_path,
        environ={},
    )

    assert runtime.catalog.catalog_id == "deepseek-v4"
    assert len(runtime.bindings) == 1
    route = runtime.bindings[0]
    assert route.state is BindingState.ENABLED
    assert route.default_model_id == "deepseek-v4-pro"
    ref = runtime.secret_provider.current_ref(route.secret_selector)
    assert ref.version == "local-v1"
    assert runtime.secret_provider.reveal(ref).get_secret_value() == "file-secret-value"
    assert runtime.status.enabled_bindings == 1
    assert runtime.status.provisioned_secrets == 1
    serialized = json.dumps(runtime.status.model_dump(mode="json"), sort_keys=True)
    assert "file-secret-value" not in serialized
    assert "file-secret-value" not in repr(runtime)


def test_process_environment_overrides_file_without_changing_config_hash(tmp_path: Path) -> None:
    config_path = write_configuration(tmp_path)
    env_path = tmp_path / ".env.local"
    env_path.write_text("DEEPSEEK_API_KEY=file-secret\n", encoding="utf-8")
    from_file = load_model_runtime_configuration(config_path, env_file_path=env_path, environ={})
    from_process = load_model_runtime_configuration(
        config_path,
        env_file_path=env_path,
        environ={"DEEPSEEK_API_KEY": "process-secret"},
    )

    selector = from_process.bindings[0].secret_selector
    ref = from_process.secret_provider.current_ref(selector)
    assert from_process.secret_provider.reveal(ref).get_secret_value() == "process-secret"
    assert from_process.configuration_sha256 == from_file.configuration_sha256
    assert "file-secret" not in from_file.configuration_sha256
    assert "process-secret" not in from_process.configuration_sha256


def test_enabled_binding_requires_secret_but_disabled_binding_does_not(tmp_path: Path) -> None:
    enabled_path = write_configuration(tmp_path / "enabled")
    with pytest.raises(ModelConfigurationError) as captured:
        load_model_runtime_configuration(enabled_path, environ={})
    assert captured.value.code == "MODEL_CONFIG_SECRET_MISSING"
    assert captured.value.next_action
    assert "DEEPSEEK_API_KEY" not in str(captured.value)

    disabled_path = write_configuration(
        tmp_path / "disabled", bindings=[binding_payload(state="DISABLED")]
    )
    runtime = load_model_runtime_configuration(disabled_path, environ={})
    assert runtime.status.enabled_bindings == 0
    assert runtime.status.provisioned_secrets == 0
    with pytest.raises(SecurityError) as missing:
        runtime.secret_provider.current_ref(runtime.bindings[0].secret_selector)
    assert missing.value.code == "SECRET_NOT_FOUND"


def test_multiple_bindings_use_independent_environment_sources(tmp_path: Path) -> None:
    backup = binding_payload(binding_id="backup-deepseek")
    backup["secret"] = {
        **backup["secret"],
        "variable": "DEEPSEEK_BACKUP_API_KEY",
        "secret_id": "deepseek-backup-key",
    }
    path = write_configuration(tmp_path, bindings=[binding_payload(), backup])
    runtime = load_model_runtime_configuration(
        path,
        environ={
            "DEEPSEEK_API_KEY": "primary-value",
            "DEEPSEEK_BACKUP_API_KEY": "backup-value",
        },
    )

    assert runtime.status.bindings == 2
    assert runtime.status.provisioned_secrets == 2
    values = {
        binding.binding_id: runtime.secret_provider.reveal(
            runtime.secret_provider.current_ref(binding.secret_selector)
        ).get_secret_value()
        for binding in runtime.bindings
    }
    assert values == {
        "backup-deepseek": "backup-value",
        "personal-deepseek": "primary-value",
    }


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("schema_version: '1.0.0'\nunknown: true\n", "MODEL_CONFIG_INVALID"),
        ("value: !unsafe tag\n", "MODEL_CONFIG_INVALID"),
        ("value: &anchor [1]\ncopy: *anchor\n", "MODEL_CONFIG_INVALID"),
    ],
)
def test_yaml_rejects_unknown_fields_tags_and_aliases(
    tmp_path: Path, content: str, code: str
) -> None:
    path = tmp_path / "runtime.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ModelConfigurationError) as captured:
        load_model_runtime_configuration(path, environ={})
    assert captured.value.code == code
    assert content not in str(captured.value)


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"\xef\xbb\xbfDEEPSEEK_API_KEY=value\n", "MODEL_ENV_ENCODING_INVALID"),
        (b"DEEPSEEK_API_KEY=one\nDEEPSEEK_API_KEY=two\n", "MODEL_ENV_DUPLICATE"),
        (b"export DEEPSEEK_API_KEY=value\n", "MODEL_ENV_INVALID"),
    ],
)
def test_env_file_rejects_bom_duplicates_and_shell_syntax(
    tmp_path: Path, content: bytes, code: str
) -> None:
    config_path = write_configuration(tmp_path)
    env_path = tmp_path / ".env.local"
    env_path.write_bytes(content)
    with pytest.raises(ModelConfigurationError) as captured:
        load_model_runtime_configuration(config_path, env_file_path=env_path, environ={})
    assert captured.value.code == code


def test_yaml_rejects_plaintext_secret_and_unsafe_catalog_path(tmp_path: Path) -> None:
    secret = binding_payload()
    secret["secret"]["value"] = "forbidden-secret"
    path = write_configuration(tmp_path / "secret", bindings=[secret])
    with pytest.raises(ModelConfigurationError) as captured:
        load_model_runtime_configuration(path, environ={"DEEPSEEK_API_KEY": "safe-value"})
    assert captured.value.code == "MODEL_CONFIG_INVALID"
    assert "forbidden-secret" not in str(captured.value)

    unsafe = write_configuration(tmp_path / "unsafe")
    payload = yaml.safe_load(unsafe.read_text(encoding="utf-8"))
    payload["catalogs"] = ["../../outside.json"]
    unsafe.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ModelConfigurationError) as captured:
        load_model_runtime_configuration(unsafe, environ={"DEEPSEEK_API_KEY": "safe-value"})
    assert captured.value.code == "MODEL_CATALOG_PATH_DENIED"


def test_environment_secret_source_is_read_only_and_forbidden_in_production(
    tmp_path: Path,
) -> None:
    local_path = write_configuration(tmp_path / "local")
    runtime = load_model_runtime_configuration(
        local_path, environ={"DEEPSEEK_API_KEY": "local-value"}
    )
    selector = runtime.bindings[0].secret_selector
    ref = runtime.secret_provider.current_ref(selector)
    with pytest.raises(SecurityError) as rotate:
        runtime.secret_provider.rotate(selector, "local-v2", runtime.secret_provider.reveal(ref))
    assert rotate.value.code == "SECRET_PROVIDER_READ_ONLY"
    with pytest.raises(SecurityError) as revoke:
        runtime.secret_provider.revoke(ref)
    assert revoke.value.code == "SECRET_PROVIDER_READ_ONLY"

    production = binding_payload()
    production["environment"] = "production"
    production_path = write_configuration(tmp_path / "production", bindings=[production])
    with pytest.raises(ModelConfigurationError) as captured:
        load_model_runtime_configuration(
            production_path, environ={"DEEPSEEK_API_KEY": "production-value"}
        )
    assert captured.value.code == "MODEL_ENV_SECRET_PRODUCTION_DENIED"


def test_app_settings_load_model_paths_and_reject_unsafe_combinations() -> None:
    settings = AppSettings.from_environment(
        {
            "NDT_MODEL_CONFIG": "config/runtime/model-bindings.local.yaml",
            "NDT_MODEL_ENV_FILE": ".env.local",
        }
    )
    assert settings.model_config_path == "config/runtime/model-bindings.local.yaml"
    assert settings.model_env_file == ".env.local"

    with pytest.raises(ConfigurationError) as missing_config:
        AppSettings.from_environment({"NDT_MODEL_ENV_FILE": ".env.local"})
    assert missing_config.value.code == "CONFIG_VALIDATION_FAILED"
    with pytest.raises(ConfigurationError) as production_file:
        AppSettings.from_environment(
            {
                "NDT_ENVIRONMENT": "production",
                "NDT_MODEL_CONFIG": "model.yaml",
                "NDT_MODEL_ENV_FILE": ".env.local",
            }
        )
    assert production_file.value.code == "CONFIG_UNSAFE"


def test_app_startup_attaches_model_runtime_and_reports_non_secret_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = write_configuration(tmp_path)

    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("model configuration startup attempted a network call")

    with monkeypatch.context() as isolated:
        isolated.setattr(socket.socket, "connect", deny_network)
        app = create_app(
            AppSettings(model_config_path=str(config_path)),
            configure_logs=False,
            model_environment={"DEEPSEEK_API_KEY": "startup-secret"},
        )

    assert app.state.model_runtime.status.bindings == 1
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    checks = response.json()["checks"]
    assert {check["name"] for check in checks} == {"application", "model_configuration"}
    assert "startup-secret" not in response.text


def test_app_without_model_config_remains_provider_neutral() -> None:
    app = create_app(AppSettings(), configure_logs=False)
    assert app.state.model_runtime is None
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.json()["checks"] == [
        {"name": "application", "status": "PASS", "error_code": None}
    ]


def test_checked_in_examples_are_nonsecret_ignored_and_loadable() -> None:
    runtime = load_model_runtime_configuration(
        EXAMPLE_CONFIG,
        env_file_path=EXAMPLE_ENV,
        environ={},
    )
    assert runtime.status.bindings == 1
    assert runtime.status.enabled_bindings == 0
    assert runtime.status.provisioned_secrets == 0
    env_text = EXAMPLE_ENV.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=" in env_text
    assert "sk-" not in env_text
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "config/runtime/*.local.yaml" in gitignore


def assert_invalid_model_yaml(tmp_path: Path, content: bytes, code: str) -> None:
    path = tmp_path / "model.yaml"
    path.write_bytes(content)
    with pytest.raises(ModelConfigurationError) as captured:
        load_model_runtime_configuration(path, environ={})
    assert captured.value.code == code


def test_model_yaml_rejects_oversized_file(tmp_path: Path) -> None:
    assert_invalid_model_yaml(
        tmp_path,
        b"x" * (256 * 1024 + 1),
        "MODEL_CONFIG_TOO_LARGE",
    )


def test_model_yaml_rejects_invalid_utf8(tmp_path: Path) -> None:
    assert_invalid_model_yaml(
        tmp_path,
        b"\xff\xfeinvalid",
        "MODEL_CONFIG_ENCODING_INVALID",
    )


def test_environment_file_size_and_application_environment_are_exact(tmp_path: Path) -> None:
    path = write_configuration(tmp_path)
    env_path = tmp_path / ".env.local"
    env_path.write_bytes(b"X" * (64 * 1024 + 1))
    with pytest.raises(ModelConfigurationError) as oversized:
        load_model_runtime_configuration(path, env_file_path=env_path, environ={})
    assert oversized.value.code == "MODEL_ENV_TOO_LARGE"

    with pytest.raises(ModelConfigurationError) as mismatch:
        load_model_runtime_configuration(
            path,
            environ={"DEEPSEEK_API_KEY": "safe-value"},
            expected_environment=SecurityEnvironment.CI,
        )
    assert mismatch.value.code == "MODEL_CONFIG_ENVIRONMENT_MISMATCH"
