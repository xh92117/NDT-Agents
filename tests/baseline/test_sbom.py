"""CycloneDX and license-decision coverage checks for S0-08."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SBOM: dict[str, Any] = json.loads((ROOT / "sbom" / "cyclonedx.v1.json").read_text("utf-8"))
DECISIONS: dict[str, Any] = json.loads(
    (ROOT / "security" / "license-decisions.v1.json").read_text("utf-8")
)
LOCK = tomllib.loads((ROOT / "uv.lock").read_text("utf-8"))


def test_sbom_format_and_lock_coverage() -> None:
    assert SBOM["bomFormat"] == "CycloneDX"
    assert SBOM["specVersion"] == "1.6"
    lock_packages = {
        (package["name"], package["version"])
        for package in LOCK["package"]
        if package["name"] != "ndt-agents" and "version" in package
    }
    sbom_packages = {(component["name"], component["version"]) for component in SBOM["components"]}
    assert sbom_packages == lock_packages


def test_every_component_has_a_non_approved_license_decision() -> None:
    sbom_purls = {component["purl"] for component in SBOM["components"]}
    decision_purls = {component["purl"] for component in DECISIONS["components"]}
    assert decision_purls == sbom_purls
    assert DECISIONS["approval"]["state"] == "PENDING_HUMAN_REVIEW"
    assert all(component["decision"] == "PENDING" for component in DECISIONS["components"])


def test_license_inventory_is_bound_to_exact_sbom_hash() -> None:
    path = ROOT / DECISIONS["sbom_path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == DECISIONS["sbom_sha256"]
