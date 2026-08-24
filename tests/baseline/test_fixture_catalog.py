"""Rights, coverage, integrity, and de-identification checks for S0-06 fixtures."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG: dict[str, Any] = json.loads((ROOT / "fixtures" / "v1" / "catalog.json").read_text("utf-8"))


def test_fixture_counts_and_balance() -> None:
    assert len(CATALOG["documents"]) == 192
    assert len(CATALOG["raw_inspection_samples"]) == 60
    assert len(CATALOG["templates"]) == 2
    method_counts = Counter(item["features"][0] for item in CATALOG["raw_inspection_samples"])
    assert method_counts == {"UT": 10, "GPR": 10, "IE": 10, "RT": 10, "AE": 10, "MV": 10}


def test_document_format_and_feature_coverage() -> None:
    format_counts = Counter(item["fixture_type"] for item in CATALOG["documents"])
    assert set(format_counts.values()) == {24}
    assert set(format_counts) == {
        "pdf-text",
        "pdf-scan",
        "docx",
        "xlsx",
        "pptx",
        "markdown",
        "text",
        "png-scan",
    }
    features = {feature for item in CATALOG["documents"] for feature in item["features"]}
    assert {"text", "table", "formula", "image", "scan", "unicode"}.issubset(features)


def test_all_cataloged_files_exist_and_match_hash() -> None:
    items = CATALOG["documents"] + CATALOG["raw_inspection_samples"] + CATALOG["templates"]
    for item in items:
        path = ROOT / item["path"]
        assert path.is_file(), item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        assert path.stat().st_size == item["size_bytes"]


def test_fixture_tree_contains_no_uncataloged_files() -> None:
    fixture_root = ROOT / "fixtures" / "v1"
    cataloged = {
        item["path"]
        for item in (
            CATALOG["documents"] + CATALOG["raw_inspection_samples"] + CATALOG["templates"]
        )
    }
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in fixture_root.rglob("*")
        if path.is_file() and path != fixture_root / "catalog.json"
    }
    assert actual == cataloged


def test_rights_deidentification_and_training_exclusion() -> None:
    items = CATALOG["documents"] + CATALOG["raw_inspection_samples"] + CATALOG["templates"]
    for item in items:
        assert item["rights_basis"] == "PROJECT_GENERATED_SYNTHETIC"
        assert item["deidentification"] == "SYNTHETIC_NO_PERSONAL_DATA"
        assert item["training_use"] == "PROHIBITED"
    assert CATALOG["external_sources"] == []
    assert CATALOG["state"] == "PARTIAL_SYNTHETIC_BASELINE"


def test_missing_real_sources_are_explicit_blockers() -> None:
    gaps = {item["gap_id"]: item for item in CATALOG["known_gaps"]}
    assert set(gaps) == {"GAP-STANDARDS-RIGHTS", "GAP-REAL-DEVICE-DATA"}
    assert all(item["state"] == "BLOCKING" for item in gaps.values())
