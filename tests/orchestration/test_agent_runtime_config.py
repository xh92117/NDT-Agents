"""S1-14 strict DeerFlow-inspired agent runtime configuration tests."""

from __future__ import annotations

import socket
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ndt_agents.models.config import ConfiguredModelRuntime, load_model_runtime_configuration
from ndt_agents.orchestration.agent_config import (
    AgentRuntimeConfigurationError,
    load_agent_runtime_configuration,
)
from ndt_agents.orchestration.child_models import ChildAgentKind
from ndt_agents.orchestration.prompt_registry import PromptRegistry, load_prompt_registry
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings, ConfigurationError

ROOT = Path(__file__).resolve().parents[2]
MODEL_CONFIG = ROOT / "config" / "runtime" / "model-bindings.example.yaml"
AGENT_CONFIG = ROOT / "config" / "runtime" / "agent-runtime.example.yaml"
PROMPT_CONFIG = ROOT / "prompts" / "professional" / "catalog.v1.yaml"


def model_runtime() -> ConfiguredModelRuntime:
    return load_model_runtime_configuration(MODEL_CONFIG, environ={})


def prompt_registry() -> PromptRegistry:
    return load_prompt_registry(PROMPT_CONFIG)


def valid_yaml() -> str:
    return """\
schema_version: 1.1.0
config_version: 1.0.0
models:
  - name: reference
    display_name: Reference model
    binding_id: personal-deepseek
    binding_version: 1.0.0
    model_id: deepseek-v4-pro
    max_input_tokens: 120000
    max_output_tokens: 60000
subagents:
  default_max_turns: 2
  hard_max_turns: 4
  default_timeout_ms: 30000
  hard_timeout_ms: 120000
  max_concurrent: 3
  hard_max_concurrent: 4
  max_total_per_run: 6
  hard_max_total_per_run: 10
  agents:
    - name: general
      kind: GENERAL
      description: General bounded execution path.
      model: reference
      prompt: general
      skill_version: general-1
      graph_version: child-react-1.0.0
      allowed_tools: []
"""


def write_yaml(tmp_path: Path, text: str, name: str = "agent-runtime.local.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_checked_in_deerflow_shaped_example_resolves_model_and_agent_profiles() -> None:
    runtime = load_agent_runtime_configuration(
        AGENT_CONFIG,
        model_runtime=model_runtime(),
        prompt_registry=prompt_registry(),
    )

    assert runtime.status.models == 11
    assert runtime.status.prompts == 8
    assert runtime.status.agents == 7
    assert runtime.status.general_agents == 1
    assert runtime.profile("general").model_name == "primary"
    assert runtime.profile("general").prompt_name == "general"
    assert runtime.profile("general").prompt_version == "1.1.0"
    assert (
        runtime.profile("general").prompt_sha256
        == runtime.prompt_instruction("general").instruction_sha256
    )
    assert runtime.profile("general").max_turns == 2
    assert runtime.profile("general").timeout_ms == 30000
    definition = runtime.build_agent_registry().require("general", ChildAgentKind.GENERAL)
    assert definition.model_version == "primary"
    assert definition.allowed_tools == frozenset()
    assert runtime.status.configuration_sha256 == runtime.configuration_sha256
    assert "api_key" not in runtime.document.model_dump_json().lower()
    assert "use" not in runtime.document.model_dump(mode="json")


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda text: text + "unexpected: true\n", "AGENT_CONFIG_INVALID"),
        (
            lambda text: text.replace(
                "    display_name: Reference model\n",
                "    display_name: Reference model\n    display_name: Duplicate\n",
            ),
            "AGENT_CONFIG_INVALID",
        ),
        (
            lambda text: text.replace(
                "schema_version: 1.1.0\n",
                "defaults: &defaults\n  max_turns: 2\nschema_version: 1.1.0\n",
            ),
            "AGENT_CONFIG_INVALID",
        ),
        (
            lambda text: text.replace("model: reference", "model: missing"),
            "AGENT_CONFIG_REFERENCE_INVALID",
        ),
        (
            lambda text: text.replace("prompt: general", "prompt: missing"),
            "AGENT_CONFIG_REFERENCE_INVALID",
        ),
        (
            lambda text: text.replace("name: general", "name: specialist").replace(
                "kind: GENERAL", "kind: PROFESSIONAL"
            ),
            "AGENT_CONFIG_INVALID",
        ),
        (
            lambda text: text.replace("binding_version: 1.0.0", "binding_version: 9.0.0"),
            "AGENT_CONFIG_REFERENCE_INVALID",
        ),
        (
            lambda text: text.replace("allowed_tools: []", "allowed_tools: [missing@1.0.0]"),
            "AGENT_CONFIG_REFERENCE_INVALID",
        ),
    ],
)
def test_invalid_or_unresolved_agent_configuration_fails_closed(
    tmp_path: Path, mutate: Callable[[str], str], code: str
) -> None:
    path = write_yaml(tmp_path, mutate(valid_yaml()))

    with pytest.raises(AgentRuntimeConfigurationError) as captured:
        load_agent_runtime_configuration(
            path,
            model_runtime=model_runtime(),
            prompt_registry=prompt_registry(),
        )

    assert captured.value.code == code


def test_duplicate_model_and_agent_names_and_limits_are_rejected(tmp_path: Path) -> None:
    duplicate_model = valid_yaml().replace(
        "subagents:\n",
        valid_yaml().split("models:\n", maxsplit=1)[1].split("subagents:\n")[0] + "subagents:\n",
    )
    duplicate_agent = valid_yaml().replace(
        "      allowed_tools: []\n",
        "      allowed_tools: []\n"
        "    - name: general\n"
        "      kind: GENERAL\n"
        "      description: Duplicate.\n"
        "      model: reference\n"
        "      prompt: general\n"
        "      skill_version: general-1\n"
        "      graph_version: child-react-1.0.0\n"
        "      allowed_tools: []\n",
    )
    invalid_limits = valid_yaml().replace("default_max_turns: 2", "default_max_turns: 5")

    for text in (duplicate_model, duplicate_agent, invalid_limits):
        with pytest.raises(AgentRuntimeConfigurationError) as captured:
            load_agent_runtime_configuration(
                write_yaml(tmp_path, text),
                model_runtime=model_runtime(),
                prompt_registry=prompt_registry(),
            )
        assert captured.value.code == "AGENT_CONFIG_INVALID"


def test_agent_configuration_path_requires_yaml_utf8_without_bom(tmp_path: Path) -> None:
    wrong_extension = write_yaml(tmp_path, valid_yaml(), "agents.json")
    bom = tmp_path / "agents.yaml"
    bom.write_bytes(b"\xef\xbb\xbf" + valid_yaml().encode())

    for path, code in (
        (wrong_extension, "AGENT_CONFIG_EXTENSION_INVALID"),
        (bom, "AGENT_CONFIG_ENCODING_INVALID"),
    ):
        with pytest.raises(AgentRuntimeConfigurationError) as captured:
            load_agent_runtime_configuration(
                path,
                model_runtime=model_runtime(),
                prompt_registry=prompt_registry(),
            )
        assert captured.value.code == code


def test_startup_loads_agent_runtime_offline_and_reports_nonsecret_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("agent runtime configuration attempted a network call")

    with monkeypatch.context() as isolated:
        isolated.setattr(socket.socket, "connect", deny_network)
        app = create_app(
            AppSettings(
                model_config_path=str(MODEL_CONFIG),
                prompt_config_path=str(PROMPT_CONFIG),
                agent_config_path=str(AGENT_CONFIG),
            ),
            configure_logs=False,
            model_environment={},
        )

    assert app.state.agent_runtime.status.agents == 7
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert {item["name"] for item in response.json()["checks"]} == {
        "application",
        "model_configuration",
        "prompt_configuration",
        "agent_configuration",
    }
    assert "DEEPSEEK_API_KEY" not in response.text


def test_agent_configuration_requires_model_configuration() -> None:
    settings = AppSettings.from_environment(
        {
            "NDT_MODEL_CONFIG": "models.yaml",
            "NDT_PROMPT_CONFIG": "prompts.yaml",
            "NDT_AGENT_CONFIG": "agents.yaml",
        }
    )
    assert settings.agent_config_path == "agents.yaml"

    with pytest.raises(ConfigurationError) as captured:
        AppSettings.from_environment({"NDT_AGENT_CONFIG": "agents.yaml"})
    assert captured.value.code == "CONFIG_VALIDATION_FAILED"
