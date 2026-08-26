"""S6-05 assurance catalog and fail-closed aggregation tests."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from ndt_agents.operations.assurance import (
    AssuranceCatalog,
    AssuranceEnvironment,
    AssuranceResult,
    AssuranceStatus,
    EvidenceRequirement,
    assess_assurance,
    assurance_catalog_sha256,
    build_assurance_catalog,
)

BUILD = "b" * 64


def result(case_id: str, catalog_hash: str, **updates: Any) -> AssuranceResult:
    values: dict[str, Any] = {
        "case_id": case_id,
        "catalog_sha256": catalog_hash,
        "build_sha256": BUILD,
        "environment": AssuranceEnvironment.LOCAL,
        "passed": True,
        "p0_findings": 0,
        "p1_findings": 0,
        "tenant_leaks": 0,
        "duplicate_committed_side_effects": 0,
        "retry_limit_violations": 0,
        "unrepaired_failures": 1,
        "explained_unrepaired_failures": 1,
        "evidence_sha256": "e" * 64,
        "evidence_uri": f"evidence://{case_id}",
    }
    values.update(updates)
    return AssuranceResult(**values)


def automated_results() -> tuple[AssuranceCatalog, tuple[AssuranceResult, ...]]:
    catalog = build_assurance_catalog()
    results = tuple(
        result(case.case_id, catalog.catalog_sha256)
        for case in catalog.cases
        if case.requirement is EvidenceRequirement.AUTOMATED
    )
    return catalog, results


def test_catalog_is_stable_complete_and_hash_bound() -> None:
    first = build_assurance_catalog()
    second = build_assurance_catalog()
    assert first == second
    assert first.catalog_sha256 == assurance_catalog_sha256(first)
    assert len(first.cases) == 11
    assert {case.requirement for case in first.cases} == set(EvidenceRequirement)
    with pytest.raises(ValidationError):
        AssuranceCatalog.model_validate(
            {**first.model_dump(mode="json"), "catalog_version": "tampered"}
        )


def test_green_local_automation_is_blocked_on_external_evidence() -> None:
    catalog, results = automated_results()
    assessment = assess_assurance(catalog, BUILD, results)
    assert assessment.status is AssuranceStatus.BLOCKED
    assert assessment.automated_passed == 7
    assert assessment.external_case_ids == (
        "S6SEC-008",
        "S6SEC-009",
        "S6SEC-010",
        "S6SEC-011",
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"passed": False},
        {"p0_findings": 1},
        {"p1_findings": 1},
        {"tenant_leaks": 1},
        {"duplicate_committed_side_effects": 1},
        {"retry_limit_violations": 1},
        {"explained_unrepaired_failures": 0},
        {"build_sha256": "c" * 64},
        {"catalog_sha256": "d" * 64},
    ],
)
def test_unsafe_or_misbound_evidence_fails_closed(updates: dict[str, Any]) -> None:
    catalog, results = automated_results()
    changed = result(results[0].case_id, catalog.catalog_sha256, **updates)
    assessment = assess_assurance(catalog, BUILD, (changed, *results[1:]))
    assert assessment.status is AssuranceStatus.FAILED


def test_missing_automated_case_and_unknown_or_duplicate_case_fail() -> None:
    catalog, results = automated_results()
    assert assess_assurance(catalog, BUILD, results[1:]).status is AssuranceStatus.FAILED
    assert assess_assurance(catalog, BUILD, (*results, results[0])).status is AssuranceStatus.FAILED
    unknown = result("S6SEC-999", catalog.catalog_sha256)
    assert assess_assurance(catalog, BUILD, (*results, unknown)).status is AssuranceStatus.FAILED


def test_only_declared_live_hardware_and_independent_environments_clear_gate() -> None:
    catalog, automated = automated_results()
    environment = {
        EvidenceRequirement.LIVE: AssuranceEnvironment.PRODUCTION_LIKE,
        EvidenceRequirement.HARDWARE: AssuranceEnvironment.HARDWARE_LAB,
        EvidenceRequirement.INDEPENDENT: AssuranceEnvironment.INDEPENDENT_PENETRATION,
    }
    external = tuple(
        result(
            case.case_id,
            catalog.catalog_sha256,
            environment=environment[case.requirement],
        )
        for case in catalog.cases
        if case.requirement is not EvidenceRequirement.AUTOMATED
    )
    assessment = assess_assurance(catalog, BUILD, (*automated, *external))
    assert assessment.status is AssuranceStatus.PASS
    simulated = external[0].model_copy(update={"environment": AssuranceEnvironment.LOCAL})
    blocked = assess_assurance(catalog, BUILD, (*automated, simulated, *external[1:]))
    assert blocked.status is AssuranceStatus.BLOCKED
    assert blocked.external_case_ids == (simulated.case_id,)
