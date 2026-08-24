"""S0-05 personal runtime candidate and offline provider-smoke checks."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = ROOT / "architecture" / "personal-development-runtime.v1.json"
GOVERNANCE_PATH = ROOT / "security" / "personal-project-governance.v1.json"
ADR_PATH = ROOT / "docs" / "decisions" / "ADR-0001-reference-runtime.md"
PACKET_PATH = ROOT / "docs" / "security" / "s0-approval-packet.md"
SMOKE_TOOL_PATH = ROOT / "tools" / "provider_smoke.py"


def load_json(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smoke_tool() -> dict[str, Any]:
    return runpy.run_path(str(SMOKE_TOOL_PATH))


def test_runtime_candidate_is_bound_to_personal_governance() -> None:
    runtime = load_json(RUNTIME_PATH)
    assert runtime["candidate_version"] == "1.1.0"
    assert runtime["state"] == "PROVISIONAL_PERSONAL_DEVELOPMENT_ONLY"
    assert runtime["governance_path"] == "security/personal-project-governance.v1.json"
    assert runtime["governance_sha256"] == sha256(GOVERNANCE_PATH)
    assert runtime["scope"] == {
        "allowed_data_classes": ["PUBLIC", "SYNTHETIC"],
        "jurisdiction": "CN_MAINLAND",
        "project_stage": "PERSONAL_PRE_COMMERCIAL",
    }


def test_selected_route_is_offline_and_non_production() -> None:
    selection = load_json(RUNTIME_PATH)["selected_runtime"]
    assert selection == {
        "application_execution": "WINDOWS_HOST_PYTHON_3_12",
        "container_target": "LINUX_DOCKER_COMPOSE_DEFERRED",
        "model_route": "DETERMINISTIC_FAKE_ONLY",
        "network_model_calls": "DISABLED",
        "production_eligible": False,
    }


def test_observed_host_is_sized_only_for_core_repository_work() -> None:
    runtime = load_json(RUNTIME_PATH)
    host = runtime["observed_host"]
    assert host["cpu"] == "13th Gen Intel(R) Core(TM) i7-1355U"
    assert host["logical_cores"] == 12
    assert host["memory_gib"] == 15.64
    assert host["nvidia_gpu"] == "NVIDIA GeForce RTX 2050"
    assert host["nvidia_vram_mib"] == 4096
    assert host["docker_engine"] == "UNAVAILABLE"
    assert runtime["profile_assessment"] == {
        "CORE_REPOSITORY_DEVELOPMENT": "PASS",
        "DEV-CPU-1": "NOT_MET_MEMORY_BELOW_32_GIB",
        "LOCAL-LLM-1": "NOT_SIZED_MODEL_AND_BENCHMARK_UNFROZEN",
        "MINERU_CPU_PIPELINE": "NOT_VALIDATED_ON_THIS_HOST",
    }


def test_hosted_and_local_model_candidates_remain_blocked() -> None:
    candidates = load_json(RUNTIME_PATH)["provider_candidates"]
    assert candidates["deterministic_fake"]["status"] == "SELECTED_OFFLINE"
    china_region = candidates["china_region_hosted"]
    assert china_region["status"] == "CATALOGED_POLICY_REVIEW_AND_SECRET_PENDING"
    assert china_region["credentials_requested"] is False
    assert china_region["provider"] == "deepseek"
    assert china_region["default_model_candidate"] == "deepseek-v4-pro"
    assert china_region["fallback_model_candidate"] == "deepseek-v4-flash"
    assert china_region["secret_reference_status"] == "NOT_PROVISIONED"
    catalog_path = ROOT / china_region["catalog_path"]
    assert china_region["catalog_sha256"] == sha256(catalog_path)
    assert "RETENTION_AND_TRAINING_POLICY" in china_region["required_before_live_call"]
    openai = candidates["openai_responses"]
    assert openai["status"] == "BLOCKED_UNSUPPORTED_CURRENT_JURISDICTION"
    assert openai["prototype_model"] == "gpt-5.6-terra"
    assert openai["current_jurisdiction_listed"] is False
    assert openai["credentials_requested"] is False
    assert openai["official_supported_countries_url"] == (
        "https://developers.openai.com/api/docs/supported-countries"
    )
    assert candidates["local_vllm"]["status"] == "DEFERRED_MODEL_AND_HARDWARE_UNFROZEN"


def test_offline_provider_smoke_exercises_strict_and_failure_paths() -> None:
    namespace = smoke_tool()
    report = namespace["run_smoke"]()
    assert report == load_json(RUNTIME_PATH)["provider_smoke"]["deterministic_fake"]
    assert report["result"] == "PASS"
    assert report["network_calls"] == 0
    assert set(report["typed_failure_states"]) == {
        "CANCELLED",
        "INCOMPLETE",
        "RATE_LIMITED",
        "REFUSED",
        "TIMED_OUT",
    }
    assert all(value == "PASS" for value in report["checks"].values())


def test_fake_smoke_contracts_reject_unknown_fields_and_never_contain_secrets() -> None:
    namespace = smoke_tool()
    request_type = namespace["SmokeRequest"]
    function_type = namespace["SyntheticFunctionArgs"]
    with pytest.raises(ValidationError):
        request_type.model_validate(
            {
                "schema_version": "1.0.0",
                "prompt": "synthetic",
                "max_output_tokens": 64,
                "timeout_ms": 1000,
                "unknown": "rejected",
            }
        )
    with pytest.raises(ValidationError):
        function_type.model_validate({"left": 1, "right": 2, "unknown": 3})

    serialized = json.dumps(namespace["run_smoke"](), sort_keys=True).lower()
    assert '"api_key":' not in serialized
    assert '"credential":' not in serialized
    assert '"secret":' not in serialized
    assert "sk-" not in serialized


def test_adr_states_personal_runtime_and_live_provider_boundaries() -> None:
    adr = ADR_PATH.read_text("utf-8")
    for required in (
        "PERSONAL-DEV-1",
        "DETERMINISTIC_FAKE_ONLY",
        "BLOCKED_UNSUPPORTED_CURRENT_JURISDICTION",
        "PROVIDER-SMOKE",
        "architecture/personal-development-runtime.v1.json",
    ):
        assert required in adr


def test_approval_packet_binds_the_runtime_candidate() -> None:
    packet = PACKET_PATH.read_text("utf-8")
    assert sha256(RUNTIME_PATH) in packet
    assert "PERSONAL-DEV-1" in packet
