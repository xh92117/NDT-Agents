"""Deterministic completeness tests for the S0-10 security baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE: dict[str, Any] = json.loads(
    (ROOT / "security" / "security-baseline.v1.json").read_text("utf-8")
)


def test_baseline_is_not_self_approved() -> None:
    assert BASELINE["approval"]["state"] == "PROPOSED_FOR_HUMAN_APPROVAL"
    assert set(BASELINE["approval"]["required_roles"]) == {
        "SECURITY_OWNER",
        "LEGAL_OWNER",
        "OPERATIONS_OWNER",
        "QUALITY_OWNER",
    }


def test_critical_assets_and_trust_boundaries_are_covered() -> None:
    assert len(BASELINE["assets"]) >= 12
    assert len(BASELINE["trust_boundaries"]) >= 9
    assert len(set(BASELINE["assets"])) == len(BASELINE["assets"])
    assert len(set(BASELINE["trust_boundaries"])) == len(BASELINE["trust_boundaries"])


def test_classification_is_complete_and_restricted_data_never_enters_prompts() -> None:
    classes = {item["code"]: item for item in BASELINE["classifications"]}
    assert set(classes) == {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"}
    assert classes["RESTRICTED"]["prompt_allowed"] is False


def test_controls_have_owners_tasks_and_tests() -> None:
    controls = BASELINE["controls"]
    assert len(controls) >= 8
    assert len({item["control_id"] for item in controls}) == len(controls)
    for control in controls:
        assert control["owner"]
        assert control["implementation_tasks"]
        assert control["tests"]


def test_recovery_and_slos_are_measurable() -> None:
    assert BASELINE["recovery"]["task_state_rpo_minutes"] > 0
    assert BASELINE["recovery"]["task_service_rto_minutes"] > 0
    assert len(BASELINE["slos"]) >= 6
    for slo in BASELINE["slos"]:
        assert slo["formula"]
        assert slo["window"]
        assert "objective" in slo or "objective_max" in slo


def test_supply_chain_blocks_unknown_licenses() -> None:
    supply_chain = BASELINE["supply_chain"]
    assert supply_chain["block_unknown_or_incompatible_license"] is True
    assert {"CODE", "CONTAINER", "MODEL"}.issubset(supply_chain["required_inventory"])
