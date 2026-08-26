"""S1-17 common provider and planned child-profile configuration tests."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from ndt_agents.models.config import load_model_runtime_configuration
from ndt_agents.models.registry import BindingState, CredentialScheme, ModelDataClass
from ndt_agents.orchestration.agent_config import load_agent_runtime_configuration
from ndt_agents.orchestration.child_models import ChildAgentKind
from ndt_agents.orchestration.prompt_registry import load_prompt_registry

ROOT = Path(__file__).resolve().parents[2]
MODEL_CONFIG = ROOT / "config" / "runtime" / "model-bindings.example.yaml"
AGENT_CONFIG = ROOT / "config" / "runtime" / "agent-runtime.example.yaml"
PROMPT_CONFIG = ROOT / "prompts" / "professional" / "catalog.v1.yaml"
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG_GUIDE = ROOT / "docs" / "contracts" / "model-agent-configuration-v1.md"

EXPECTED_PROVIDERS = {
    "alibaba",
    "anthropic",
    "baidu",
    "deepseek",
    "doubao",
    "google",
    "minimax",
    "moonshot",
    "openai",
    "tencent",
    "zhipu",
}
EXPECTED_AGENT_KINDS = {
    "general": ChildAgentKind.GENERAL,
    "technical_qa": ChildAgentKind.PROFESSIONAL,
    "inspection_plan": ChildAgentKind.PROFESSIONAL,
    "inspection_report": ChildAgentKind.PROFESSIONAL,
    "data_processing": ChildAgentKind.PROFESSIONAL,
    "method_compatibility": ChildAgentKind.PROFESSIONAL,
    "knowledge": ChildAgentKind.PROFESSIONAL,
}
EXPECTED_SECRET_VARIABLES = {
    "DASHSCOPE_API_KEY",
    "ANTHROPIC_API_KEY",
    "ARK_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "HUNYUAN_API_KEY",
    "MINIMAX_API_KEY",
    "MOONSHOT_API_KEY",
    "OPENAI_API_KEY",
    "QIANFAN_API_KEY",
    "ZHIPU_API_KEY",
}


def test_common_provider_example_loads_offline_and_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("configuration loading attempted a network call")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    runtime = load_model_runtime_configuration(MODEL_CONFIG, environ={})

    assert {item.provider_id for item in runtime.catalog.providers} == EXPECTED_PROVIDERS
    assert len(runtime.bindings) == len(EXPECTED_PROVIDERS)
    assert all(binding.state is BindingState.DISABLED for binding in runtime.bindings)
    assert all(
        binding.allowed_data_classes == frozenset({ModelDataClass.PUBLIC, ModelDataClass.SYNTHETIC})
        for binding in runtime.bindings
    )
    assert all(not provider.production_eligible for provider in runtime.catalog.providers)
    anthropic = next(
        provider for provider in runtime.catalog.providers if provider.provider_id == "anthropic"
    )
    assert anthropic.credential_scheme is CredentialScheme.API_KEY_HEADER
    assert anthropic.credential_header == "x-api-key"
    assert runtime.status.enabled_bindings == 0
    assert runtime.status.provisioned_secrets == 0


def test_provider_and_secret_identities_are_unique_and_case_sensitive() -> None:
    runtime = load_model_runtime_configuration(MODEL_CONFIG, environ={})
    bindings = runtime.bindings

    assert len({item.binding_id for item in bindings}) == len(bindings)
    assert len({item.secret_selector.secret_id for item in bindings}) == len(bindings)
    assert {item.secret_selector.purpose for item in bindings} == {
        f"model.{provider}.credential" for provider in EXPECTED_PROVIDERS
    }
    assert "MiniMax-M2.7" in {model.model_id for model in runtime.catalog.models}
    assert (
        runtime.catalog.models[
            next(
                index
                for index, model in enumerate(runtime.catalog.models)
                if model.model_id == "MiniMax-M2.7"
            )
        ].model_snapshot
        == "MiniMax-M2.7"
    )


def test_checked_in_environment_template_contains_only_blank_secret_slots() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for variable in EXPECTED_SECRET_VARIABLES | {"MINERU_API_TOKEN"}:
        assert f"{variable}=\n" in text
    assert "sk-" not in text
    assert "Bearer " not in text


def test_planned_child_profiles_resolve_from_one_configuration() -> None:
    models = load_model_runtime_configuration(MODEL_CONFIG, environ={})
    runtime = load_agent_runtime_configuration(
        AGENT_CONFIG,
        model_runtime=models,
        prompt_registry=load_prompt_registry(PROMPT_CONFIG),
    )

    assert {profile.name: profile.kind for profile in runtime.profiles} == EXPECTED_AGENT_KINDS
    assert all(profile.allowed_tools == () for profile in runtime.profiles)
    assert all(
        profile.max_turns <= runtime.document.subagents.hard_max_turns
        for profile in runtime.profiles
    )
    assert all(
        profile.timeout_ms <= runtime.document.subagents.hard_timeout_ms
        for profile in runtime.profiles
    )
    assert "review" not in EXPECTED_AGENT_KINDS


def test_mineru_hosted_variables_are_reserved_while_cli_remains_active() -> None:
    guide = CONFIG_GUIDE.read_text(encoding="utf-8")
    normalized = " ".join(guide.lower().split())

    assert "MinerUCliRunner" in guide
    assert "MINERU_API_TOKEN" in guide
    assert "reserved" in normalized
    assert "not an active api adapter" in normalized
