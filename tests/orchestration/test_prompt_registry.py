"""S1-18 strict prompt catalog, content, and configuration-binding tests."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from ndt_agents.models.config import load_model_runtime_configuration
from ndt_agents.orchestration.agent_config import load_agent_runtime_configuration
from ndt_agents.orchestration.prompt_registry import PromptRegistryError, load_prompt_registry

ROOT = Path(__file__).resolve().parents[2]
PROMPT_ROOT = ROOT / "prompts" / "professional"
PROMPT_CONFIG = PROMPT_ROOT / "catalog.v1.yaml"
MODEL_CONFIG = ROOT / "config" / "runtime" / "model-bindings.example.yaml"
AGENT_CONFIG = ROOT / "config" / "runtime" / "agent-runtime.example.yaml"

EXPECTED_PROMPTS = {
    "data_processing",
    "general",
    "inspection_plan",
    "inspection_report",
    "knowledge",
    "method_compatibility",
    "review",
    "technical_qa",
}


def copy_catalog(tmp_path: Path) -> Path:
    target = tmp_path / "prompts"
    shutil.copytree(PROMPT_ROOT, target)
    return target / "catalog.v1.yaml"


def read_payload(catalog: Path) -> dict[str, Any]:
    payload = yaml.safe_load(catalog.read_text("utf-8"))
    assert isinstance(payload, dict)
    return payload


def write_payload(catalog: Path, payload: dict[str, Any]) -> None:
    catalog.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def entry(payload: dict[str, Any], prompt_id: str) -> dict[str, Any]:
    prompts = payload["prompts"]
    assert isinstance(prompts, list)
    result = next(item for item in prompts if item["prompt_id"] == prompt_id)
    assert isinstance(result, dict)
    return result


def test_checked_in_catalog_resolves_exact_optimized_prompts() -> None:
    registry = load_prompt_registry(PROMPT_CONFIG)

    assert {prompt.prompt_id for prompt in registry.prompts} == EXPECTED_PROMPTS
    assert registry.resolve("technical_qa").version == "1.2.0"
    assert registry.resolve("review").version == "1.2.0"
    assert all(
        prompt.version == "1.1.0"
        for prompt in registry.prompts
        if prompt.prompt_id not in {"review", "technical_qa"}
    )
    assert len({prompt.relative_path for prompt in registry.prompts}) == len(registry.prompts)
    assert len({prompt.sha256 for prompt in registry.prompts}) == len(registry.prompts)
    assert all(prompt.instruction.text for prompt in registry.prompts)
    assert all(
        prompt.sha256 == hashlib.sha256(prompt.instruction.text.encode("utf-8")).hexdigest()
        for prompt in registry.prompts
    )

    for prompt_id in EXPECTED_PROMPTS - {"review"}:
        text = registry.resolve(prompt_id).instruction.text.lower()
        assert "untrusted" in text
        assert "user" in text
    assert "read-only review agent" in registry.resolve("review").instruction.text.lower()
    assert "human_confirmation_required=true" in registry.resolve("technical_qa").instruction.text
    assert "all template sections in order" in registry.resolve("inspection_plan").instruction.text
    assert "approval-pending" in registry.resolve("inspection_report").instruction.text
    assert "one attempt" in registry.resolve("data_processing").instruction.text
    assert "execute no algorithm" in registry.resolve("method_compatibility").instruction.text
    assert "publish directly" in registry.resolve("knowledge").instruction.text.lower()
    models = load_model_runtime_configuration(MODEL_CONFIG, environ={})
    runtime = load_agent_runtime_configuration(
        AGENT_CONFIG,
        model_runtime=models,
        prompt_registry=registry,
    )
    assert {profile.name: profile.prompt_name for profile in runtime.profiles} == {
        prompt_id: prompt_id for prompt_id in EXPECTED_PROMPTS - {"review"}
    }


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("duplicate", "PROMPT_CATALOG_INVALID"),
        ("unknown", "PROMPT_CATALOG_INVALID"),
        ("absolute", "PROMPT_CATALOG_INVALID"),
        ("escape", "PROMPT_CATALOG_INVALID"),
        ("missing", "PROMPT_NOT_FOUND"),
        ("hash", "PROMPT_HASH_MISMATCH"),
        ("bom", "PROMPT_ENCODING_INVALID"),
        ("encoding", "PROMPT_ENCODING_INVALID"),
        ("oversized", "PROMPT_CONTENT_INVALID"),
    ],
)
def test_invalid_prompt_catalog_or_content_fails_closed(
    tmp_path: Path,
    mutation: str,
    code: str,
) -> None:
    catalog = copy_catalog(tmp_path)
    payload = read_payload(catalog)
    general = entry(payload, "general")
    general_path = catalog.parent / str(general["path"])
    if mutation == "duplicate":
        payload["prompts"].append(dict(general))
        write_payload(catalog, payload)
    elif mutation == "unknown":
        payload["unknown"] = True
        write_payload(catalog, payload)
    elif mutation == "absolute":
        general["path"] = "C:/outside.md"
        write_payload(catalog, payload)
    elif mutation == "escape":
        general["path"] = "../outside.md"
        write_payload(catalog, payload)
    elif mutation == "missing":
        general["path"] = "missing.md"
        write_payload(catalog, payload)
    elif mutation == "hash":
        general_path.write_text(general_path.read_text("utf-8") + "\nChanged.\n", "utf-8")
    elif mutation == "bom":
        general_path.write_bytes(b"\xef\xbb\xbf" + general_path.read_bytes())
    elif mutation == "encoding":
        general_path.write_bytes(b"\xff\xfeinvalid")
    else:
        general_path.write_bytes(b"x" * (100 * 1024 + 1))

    with pytest.raises(PromptRegistryError) as captured:
        load_prompt_registry(catalog)

    assert captured.value.code == code


def test_prompt_catalog_rejects_yaml_aliases_and_duplicate_keys(tmp_path: Path) -> None:
    catalog = copy_catalog(tmp_path)
    original = catalog.read_text("utf-8")
    variants = (
        "defaults: &defaults\n  version: 1.1.0\n" + original,
        original.replace(
            "catalog_version: 1.1.0\n",
            "catalog_version: 1.1.0\ncatalog_version: 1.1.0\n",
        ),
    )
    for index, text in enumerate(variants):
        candidate = catalog.parent / f"invalid-{index}.yaml"
        candidate.write_text(text, "utf-8")
        with pytest.raises(PromptRegistryError) as captured:
            load_prompt_registry(candidate)
        assert captured.value.code == "PROMPT_CATALOG_INVALID"


def test_prompt_catalog_rejects_symbolic_link_components_when_supported(tmp_path: Path) -> None:
    catalog = copy_catalog(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("External prompt must not load.", "utf-8")
    linked = catalog.parent / "linked.md"
    try:
        os.symlink(outside, linked)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic-link creation is unavailable on this host")
    payload = read_payload(catalog)
    general = entry(payload, "general")
    general["path"] = "linked.md"
    general["sha256"] = hashlib.sha256(outside.read_bytes()).hexdigest()
    write_payload(catalog, payload)

    with pytest.raises(PromptRegistryError) as captured:
        load_prompt_registry(catalog)

    assert captured.value.code == "PROMPT_PATH_DENIED"


def test_prompt_change_invalidates_catalog_and_agent_configuration_hashes(tmp_path: Path) -> None:
    current_prompts = load_prompt_registry(PROMPT_CONFIG)
    changed_catalog = copy_catalog(tmp_path)
    payload = read_payload(changed_catalog)
    general = entry(payload, "general")
    general_path = changed_catalog.parent / str(general["path"])
    general_path.write_text(general_path.read_text("utf-8") + "\nAdditional boundary.\n", "utf-8")
    general["sha256"] = hashlib.sha256(general_path.read_bytes()).hexdigest()
    write_payload(changed_catalog, payload)
    changed_prompts = load_prompt_registry(changed_catalog)
    models = load_model_runtime_configuration(MODEL_CONFIG, environ={})
    current_runtime = load_agent_runtime_configuration(
        AGENT_CONFIG,
        model_runtime=models,
        prompt_registry=current_prompts,
    )
    changed_runtime = load_agent_runtime_configuration(
        AGENT_CONFIG,
        model_runtime=models,
        prompt_registry=changed_prompts,
    )

    assert changed_prompts.catalog_sha256 != current_prompts.catalog_sha256
    assert changed_runtime.configuration_sha256 != current_runtime.configuration_sha256
    assert (
        changed_runtime.profile("general").prompt_sha256
        != current_runtime.profile("general").prompt_sha256
    )
