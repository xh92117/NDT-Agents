"""Static smoke checks for the GitHub Actions S0 quality workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
WORKFLOW_TEXT = WORKFLOW_PATH.read_text("utf-8")
WORKFLOW: dict[str, Any] = yaml.safe_load(WORKFLOW_TEXT)
ATTRIBUTES_TEXT = (ROOT / ".gitattributes").read_text("utf-8")


def test_workflow_has_read_only_permissions_and_bounded_job() -> None:
    assert WORKFLOW["permissions"] == {"contents": "read"}
    quality = WORKFLOW["jobs"]["quality"]
    assert quality["runs-on"] == "ubuntu-24.04"
    assert quality["timeout-minutes"] == 30


def test_all_external_actions_are_pinned_to_full_commit_sha() -> None:
    action_references = re.findall(r"uses:\s+([^\s]+)", WORKFLOW_TEXT)
    assert len(action_references) == 4
    assert all(re.search(r"@[0-9a-f]{40}$", reference) for reference in action_references)


def test_workflow_runs_all_s0_quality_controls() -> None:
    for required in (
        "uv sync --locked",
        "tools/generate_schemas.py",
        "tools/generate_fixture_catalog.py",
        "tools/generate_benchmarks.py",
        "tools/generate_sbom.py",
        "git diff --exit-code",
        "tools/check_controlled_docs.py",
        "uv run pytest",
        "uv run ruff check",
        "uv run mypy",
        "uv run pip-audit",
        "actions/upload-artifact@",
    ):
        assert required in WORKFLOW_TEXT


def test_repository_attributes_preserve_text_and_binary_fixture_bytes() -> None:
    for required in (
        "*.json text eol=lf",
        "*.jsonl text eol=lf",
        "*.md text eol=lf",
        "*.txt text eol=lf",
        "*.docx binary",
        "*.pdf binary",
        "*.png binary",
        "*.pptx binary",
        "*.xlsx binary",
    ):
        assert required in ATTRIBUTES_TEXT


def test_generated_text_artifacts_are_utf8_lf() -> None:
    generated_paths = [
        *sorted((ROOT / "schemas" / "v1").glob("*.json")),
        *sorted((ROOT / "examples" / "contracts" / "v1").glob("*.json")),
        *sorted((ROOT / "benchmarks" / "v1").glob("*.json")),
        *sorted((ROOT / "benchmarks" / "v1").glob("*.jsonl")),
        *sorted((ROOT / "fixtures" / "v1").rglob("*.json")),
        *sorted((ROOT / "fixtures" / "v1").rglob("*.md")),
        *sorted((ROOT / "fixtures" / "v1").rglob("*.txt")),
        ROOT / "sbom" / "cyclonedx.v1.json",
        ROOT / "security" / "license-decisions.v1.json",
    ]
    assert generated_paths
    for path in generated_paths:
        content = path.read_bytes()
        assert b"\r" not in content, path.relative_to(ROOT)
        content.decode("utf-8")
