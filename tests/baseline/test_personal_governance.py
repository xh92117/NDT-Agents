"""Personal-project governance must remain provisional and non-commercial."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_PATH = ROOT / "security" / "personal-project-governance.v1.json"
BASELINE_PATH = ROOT / "security" / "security-baseline.v1.json"
PACKET_PATH = ROOT / "docs" / "security" / "s0-approval-packet.md"


def load_json(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_personal_project_identity_and_jurisdiction_are_provisional() -> None:
    governance = load_json(GOVERNANCE_PATH)
    assert governance["governance_version"] == "1.0.0"
    assert governance["project_stage"] == "PERSONAL_PRE_COMMERCIAL"
    assert governance["governance_mode"] == "SOLE_PROJECT_OWNER"
    assert governance["decision_source"] == {
        "actor_identity": "UNVERIFIED_CURRENT_PROJECT_OWNER",
        "actor_role": "PROJECT_OWNER",
        "recorded_on": "2026-08-24",
        "source": "USER_CONFIRMATION_IN_CODEX_TASK",
    }
    assert governance["jurisdiction"] == {
        "code": "CN_MAINLAND",
        "commercialization_review_required": True,
        "state": "PROVISIONAL_PENDING_COMMERCIAL_REVIEW",
    }


def test_independent_approval_roles_remain_unassigned() -> None:
    governance = load_json(GOVERNANCE_PATH)
    roles = governance["independent_review_roles"]
    assert {item["role"] for item in roles} == {
        "SECURITY_OWNER",
        "LEGAL_OWNER",
        "OPERATIONS_OWNER",
        "QUALITY_OWNER",
    }
    assert all(item["state"] == "UNASSIGNED" for item in roles)
    assert governance["independent_approval_state"] == "NOT_SATISFIED"


def test_existing_baseline_values_are_only_engineering_targets() -> None:
    governance = load_json(GOVERNANCE_PATH)
    baseline = load_json(BASELINE_PATH)
    targets = governance["engineering_targets"]
    assert targets["state"] == "ACCEPTED_AS_PROVISIONAL_ENGINEERING_TARGETS"
    assert targets["baseline_version"] == baseline["baseline_version"]
    assert targets["baseline_sha256"] == sha256(BASELINE_PATH)
    assert targets["retention_days"] == {
        "operational_telemetry_archive": 365,
        "operational_telemetry_hot": 90,
        "rolling_backup": 35,
        "security_and_approval_audit": 2557,
    }
    assert targets["project_evidence_and_reports"] == "NO_AUTO_DELETE_UNTIL_COMMERCIAL_REVIEW"
    assert targets["slos"] == {
        "api_availability": 0.995,
        "accepted_task_durability": 0.999,
    }
    assert targets["recovery_minutes"] == {
        "core_task_rpo": 15,
        "core_task_rto": 240,
        "noncritical_analytics_rto": 1440,
    }


def test_personal_confirmation_cannot_enable_production_or_close_risks() -> None:
    governance = load_json(GOVERNANCE_PATH)
    assert governance["risk_effect"] == {"R-005": "OPEN", "R-007": "OPEN"}
    assert governance["restrictions"] == {
        "commercial_release": "BLOCKED",
        "formal_compliance_claim": "BLOCKED",
        "production_customer_data": "BLOCKED",
        "production_deployment": "BLOCKED",
    }
    serialized = json.dumps(governance, sort_keys=True)
    assert '"approval_state": "APPROVED"' not in serialized


def test_approval_packet_binds_the_personal_governance_record() -> None:
    packet = PACKET_PATH.read_text("utf-8")
    assert sha256(GOVERNANCE_PATH) in packet
    assert "PERSONAL_PRE_COMMERCIAL" in packet
    assert "CN_MAINLAND" in packet
    assert "NOT_SATISFIED" in packet
