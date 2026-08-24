"""Offline integrity checks for the S0-08 official license-evidence snapshot."""

from __future__ import annotations

import hashlib
import json
import re
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / "security" / "license-evidence.v1.json"
SBOM_PATH = ROOT / "sbom" / "cyclonedx.v1.json"
DECISIONS_PATH = ROOT / "security" / "license-decisions.v1.json"
LOCK_PATH = ROOT / "uv.lock"
BASELINE_PATH = ROOT / "security" / "security-baseline.v1.json"
PACKET_PATH = ROOT / "docs" / "security" / "s0-approval-packet.md"
TOOL = runpy.run_path(str(ROOT / "tools" / "refresh_license_evidence.py"))
classify_evidence_state = cast(
    Callable[[str, str, list[str]], str], TOOL["classify_evidence_state"]
)


def load_json(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_classifier_never_turns_legacy_metadata_into_spdx_or_approval() -> None:
    assert classify_evidence_state("MIT", "", []) == "SPDX_EXPRESSION"
    assert classify_evidence_state("", "MIT", []) == "LEGACY_METADATA_REQUIRES_TEXT_REVIEW"
    assert (
        classify_evidence_state("", "", ["License :: OSI Approved :: MIT License"])
        == "LEGACY_METADATA_REQUIRES_TEXT_REVIEW"
    )
    assert classify_evidence_state("", "", []) == "MISSING_LICENSE_METADATA"


def test_snapshot_covers_the_exact_sbom_and_lock() -> None:
    evidence = load_json(EVIDENCE_PATH)
    sbom = load_json(SBOM_PATH)
    assert evidence["evidence_version"] == "1.0.0"
    assert evidence["sbom_path"] == "sbom/cyclonedx.v1.json"
    assert evidence["sbom_sha256"] == sha256(SBOM_PATH)
    assert evidence["uv_lock_path"] == "uv.lock"
    assert evidence["uv_lock_sha256"] == sha256(LOCK_PATH)

    sbom_purls = {component["purl"] for component in sbom["components"]}
    evidence_purls = {component["purl"] for component in evidence["components"]}
    assert evidence_purls == sbom_purls
    assert len(evidence_purls) == len(evidence["components"])
    sbom_by_purl = {component["purl"]: component for component in sbom["components"]}
    for component in evidence["components"]:
        sbom_component = sbom_by_purl[component["purl"]]
        assert component["name"] == sbom_component["name"]
        assert component["version"] == sbom_component["version"]
        assert component["scope"] == sbom_component["properties"][0]["value"]


def test_every_component_has_hash_bound_official_metadata() -> None:
    evidence = load_json(EVIDENCE_PATH)
    state_counts: dict[str, int] = {}
    for component in evidence["components"]:
        assert component["source_url"].startswith("https://pypi.org/pypi/")
        assert component["source_url"].endswith("/json")
        assert re.fullmatch(r"[0-9a-f]{64}", component["source_response_sha256"])
        expected_state = classify_evidence_state(
            component["license_expression"] or "",
            component["legacy_license"]["value"] or "",
            component["license_classifiers"],
        )
        assert component["evidence_state"] == expected_state
        state_counts[expected_state] = state_counts.get(expected_state, 0) + 1
        legacy = component["legacy_license"]
        encoded = (legacy["value"] or "").encode("utf-8")
        assert legacy["utf8_bytes"] == len(encoded)
        assert legacy["sha256"] == hashlib.sha256(encoded).hexdigest()

    assert evidence["summary"] == {
        "component_count": len(evidence["components"]),
        "legacy_metadata_review_count": state_counts.get("LEGACY_METADATA_REQUIRES_TEXT_REVIEW", 0),
        "missing_license_metadata_count": state_counts.get("MISSING_LICENSE_METADATA", 0),
        "spdx_expression_count": state_counts.get("SPDX_EXPRESSION", 0),
    }


def test_evidence_and_decisions_cannot_claim_human_approval() -> None:
    evidence = load_json(EVIDENCE_PATH)
    decisions = load_json(DECISIONS_PATH)
    assert evidence["approval"] == {
        "required_roles": ["LEGAL_OWNER", "SECURITY_OWNER"],
        "state": "EVIDENCE_ONLY_PENDING_HUMAN_REVIEW",
    }
    assert evidence["policy"]["automatic_approval"] is False
    assert evidence["policy"]["metadata_source"] == "PYPI_VERSION_JSON"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", evidence["captured_at"])
    assert decisions["approval"]["state"] == "PENDING_HUMAN_REVIEW"
    assert decisions["license_evidence_path"] == "security/license-evidence.v1.json"
    assert decisions["license_evidence_sha256"] == sha256(EVIDENCE_PATH)

    evidence_by_purl = {item["purl"]: item for item in evidence["components"]}
    assert {item["purl"] for item in decisions["components"]} == set(evidence_by_purl)
    for decision in decisions["components"]:
        source = evidence_by_purl[decision["purl"]]
        assert decision["decision"] == "PENDING"
        assert decision["license_evidence_state"] == source["evidence_state"]
        assert decision["license_source_url"] == source["source_url"]
        expected_license = source["license_expression"] or source["evidence_state"]
        assert decision["declared_license"] == expected_license


def test_all_direct_dependencies_have_at_least_declared_or_legacy_metadata() -> None:
    evidence = load_json(EVIDENCE_PATH)
    direct = [item for item in evidence["components"] if item["scope"] != "TRANSITIVE"]
    assert direct
    assert all(item["evidence_state"] != "MISSING_LICENSE_METADATA" for item in direct)


def test_approval_packet_binds_every_exact_review_target() -> None:
    packet = PACKET_PATH.read_text("utf-8")
    for path in (BASELINE_PATH, SBOM_PATH, EVIDENCE_PATH, DECISIONS_PATH, LOCK_PATH):
        assert sha256(path) in packet, path.relative_to(ROOT)
    assert "PENDING_ACCOUNTABLE_REVIEW" in packet
    assert "APPROVED | CHANGES_REQUESTED | REJECTED" in packet
