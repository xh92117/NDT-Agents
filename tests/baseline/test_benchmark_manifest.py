"""Count, coverage, integrity, and split checks for S0-07 benchmarks."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST: dict[str, Any] = json.loads(
    (ROOT / "benchmarks" / "v1" / "manifest.json").read_text("utf-8")
)
EXPECTED_COUNTS = {
    "routing": 1000,
    "technical-qa": 288,
    "inspection-plan": 60,
    "report": 40,
    "compression-restore": 200,
    "bash-encoding": 300,
    "fault": 120,
    "tenant-isolation": 1000,
}


def load_cases(entry: dict[str, Any]) -> list[dict[str, Any]]:
    path = ROOT / entry["path"]
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_manifest_counts_hashes_and_unique_ids() -> None:
    assert {entry["dataset"] for entry in MANIFEST["datasets"]} == set(EXPECTED_COUNTS)
    all_ids: list[str] = []
    for entry in MANIFEST["datasets"]:
        path = ROOT / entry["path"]
        cases = load_cases(entry)
        assert entry["case_count"] == EXPECTED_COUNTS[entry["dataset"]] == len(cases)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert sum(entry["splits"].values()) == len(cases)
        assert entry["splits"]["FROZEN_TEST"] > 0
        all_ids.extend(case["case_id"] for case in cases)
    assert len(all_ids) == 3008
    assert len(set(all_ids)) == len(all_ids)


def test_rights_deidentification_and_training_separation() -> None:
    assert MANIFEST["state"] == "PENDING_EXPERT_ADJUDICATION_AND_REAL_DATA"
    assert MANIFEST["training_use"] == "PROHIBITED"
    for entry in MANIFEST["datasets"]:
        for case in load_cases(entry):
            assert case["rights_basis"] == "PROJECT_GENERATED_SYNTHETIC"
            assert case["deidentification"] == "SYNTHETIC_NO_PERSONAL_DATA"
            assert case["training_use"] == "PROHIBITED"
            assert case["split"] in {"CALIBRATION", "DEVELOPMENT_EVAL", "FROZEN_TEST"}


def test_routing_qa_and_professional_review_coverage() -> None:
    by_name = {entry["dataset"]: entry for entry in MANIFEST["datasets"]}
    routing = load_cases(by_name["routing"])
    route_counts = Counter(case["expected"]["route"] for case in routing)
    assert set(route_counts.values()) == {200}
    assert all("route_signals" in case for case in routing)
    assert all(
        case["expected"]["professional_agents"]
        == len(case["route_signals"]["professional_assignments"])
        for case in routing
    )

    qa = load_cases(by_name["technical-qa"])
    assert len({(case["method"], case["structure_class"]) for case in qa}) == 36
    assert len({case["material"] for case in qa}) == 5

    for name in ("technical-qa", "inspection-plan", "report"):
        cases = load_cases(by_name[name])
        assert all(case["review_status"] == "PENDING_DOMAIN_EXPERT_GOLD" for case in cases)


def test_safety_case_expected_outcomes() -> None:
    by_name = {entry["dataset"]: entry for entry in MANIFEST["datasets"]}
    tenant = load_cases(by_name["tenant-isolation"])
    assert len({case["layer"] for case in tenant}) == 10
    assert all(case["expected"]["decision"] == "DENY" for case in tenant)
    assert all(case["expected"]["leaked_objects"] == 0 for case in tenant)

    fault = load_cases(by_name["fault"])
    assert len({case["fault"] for case in fault}) == 12
    assert all(case["expected"]["duplicate_side_effects"] == 0 for case in fault)


def test_compression_restore_and_encoding_coverage() -> None:
    by_name = {entry["dataset"]: entry for entry in MANIFEST["datasets"]}
    compression = load_cases(by_name["compression-restore"])
    assert {case["compression_level"] for case in compression} == {"C0", "C1", "C2", "C3"}
    assert {case["expected"]["restore_mode"] for case in compression} == {
        "DIRECT",
        "INTENT",
        "PREVIEW_CONFIRM",
        "BRANCH",
    }

    encoding = load_cases(by_name["bash-encoding"])
    assert len({(case["encoding"], case["path_type"]) for case in encoding}) == 30
    malformed = [case for case in encoding if case["encoding"] == "MALFORMED"]
    assert all(case["expected"]["status"] == "MANUAL_REVIEW" for case in malformed)
