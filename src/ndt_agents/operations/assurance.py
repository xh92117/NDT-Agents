"""Versioned S6-05 security and resilience evidence aggregation."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel


class AssuranceEnvironment(StrEnum):
    LOCAL = "LOCAL"
    CI = "CI"
    STAGING = "STAGING"
    PRODUCTION_LIKE = "PRODUCTION_LIKE"
    HARDWARE_LAB = "HARDWARE_LAB"
    INDEPENDENT_PENETRATION = "INDEPENDENT_PENETRATION"


class EvidenceRequirement(StrEnum):
    AUTOMATED = "AUTOMATED"
    LIVE = "LIVE"
    HARDWARE = "HARDWARE"
    INDEPENDENT = "INDEPENDENT"


class AssuranceCase(StrictModel):
    case_id: str = Field(pattern=r"^S6SEC-[0-9]{3}$")
    title: str = Field(min_length=1, max_length=256)
    requirement: EvidenceRequirement
    test_groups: tuple[str, ...] = Field(min_length=1)
    invariant: str = Field(min_length=1, max_length=1000)


class AssuranceCatalog(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    catalog_version: str = Field(min_length=1, max_length=128)
    cases: tuple[AssuranceCase, ...] = Field(min_length=1)
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("assurance case IDs must be unique")
        if self.catalog_sha256 != assurance_catalog_sha256(self):
            raise ValueError("assurance catalog hash is invalid")
        return self


class AssuranceResult(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    case_id: str
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment: AssuranceEnvironment
    passed: bool
    p0_findings: int = Field(ge=0)
    p1_findings: int = Field(ge=0)
    tenant_leaks: int = Field(ge=0)
    duplicate_committed_side_effects: int = Field(ge=0)
    retry_limit_violations: int = Field(ge=0)
    unrepaired_failures: int = Field(ge=0)
    explained_unrepaired_failures: int = Field(ge=0)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_uri: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_explanations(self) -> Self:
        if self.explained_unrepaired_failures > self.unrepaired_failures:
            raise ValueError("explained failures cannot exceed unrepaired failures")
        return self


class AssuranceStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class AssuranceAssessment(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: AssuranceStatus
    catalog_sha256: str
    build_sha256: str
    automated_passed: int = Field(ge=0)
    required_total: int = Field(ge=1)
    external_case_ids: tuple[str, ...]
    reason_code: str
    next_action: str


def assurance_catalog_sha256(catalog: AssuranceCatalog) -> str:
    payload = catalog.model_dump(mode="json", exclude={"catalog_sha256"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def build_assurance_catalog() -> AssuranceCatalog:
    cases = (
        AssuranceCase(
            case_id="S6SEC-001",
            title="Tenant and permission isolation",
            requirement=EvidenceRequirement.AUTOMATED,
            test_groups=("SEC-TENANT", "SEC-CACHE"),
            invariant="Zero cross-tenant or stale-permission access.",
        ),
        AssuranceCase(
            case_id="S6SEC-002",
            title="Audit and approval integrity",
            requirement=EvidenceRequirement.AUTOMATED,
            test_groups=("OBS-AUDIT", "INT-APPROVAL"),
            invariant="Every guarded decision is hash-bound and replay safe.",
        ),
        AssuranceCase(
            case_id="S6SEC-003",
            title="Tool, path, upload, and prompt boundary",
            requirement=EvidenceRequirement.AUTOMATED,
            test_groups=("SEC-TOOLS", "SEC-BASH"),
            invariant="Untrusted input cannot gain authority or unsafe execution.",
        ),
        AssuranceCase(
            case_id="S6SEC-004",
            title="Model and provider malformed response",
            requirement=EvidenceRequirement.AUTOMATED,
            test_groups=("PROVIDER-SMOKE", "RES-ALL"),
            invariant="Malformed, timeout, and provider failures are typed and bounded.",
        ),
        AssuranceCase(
            case_id="S6SEC-005",
            title="Process loss and queue redelivery",
            requirement=EvidenceRequirement.AUTOMATED,
            test_groups=("RES-CHECKPOINT", "RES-ALL"),
            invariant="Recovery repeats no committed side effect.",
        ),
        AssuranceCase(
            case_id="S6SEC-006",
            title="Lifecycle, legal hold, and erasure",
            requirement=EvidenceRequirement.AUTOMATED,
            test_groups=("INT-DATA-LIFECYCLE",),
            invariant="Deletion and erasure remain approval and hold constrained.",
        ),
        AssuranceCase(
            case_id="S6SEC-007",
            title="Dependency, license, and secret scan",
            requirement=EvidenceRequirement.AUTOMATED,
            test_groups=("SEC-ALL",),
            invariant="No unmitigated critical dependency or checked-in secret.",
        ),
        AssuranceCase(
            case_id="S6SEC-008",
            title="Live database and object-store failover",
            requirement=EvidenceRequirement.LIVE,
            test_groups=("RES-ALL",),
            invariant="Approved SLO, RPO, RTO, integrity, and isolation hold during failover.",
        ),
        AssuranceCase(
            case_id="S6SEC-009",
            title="Live identity, KMS, queue, cache, and index faults",
            requirement=EvidenceRequirement.LIVE,
            test_groups=("SEC-ALL", "RES-ALL"),
            invariant="Dependency loss enters the approved degraded mode without leaks.",
        ),
        AssuranceCase(
            case_id="S6SEC-010",
            title="Hardware and instrument disconnect",
            requirement=EvidenceRequirement.HARDWARE,
            test_groups=("INT-INSTRUMENT", "RES-ALL"),
            invariant="Disconnect produces typed state and no unsafe physical action.",
        ),
        AssuranceCase(
            case_id="S6SEC-011",
            title="Independent penetration test",
            requirement=EvidenceRequirement.INDEPENDENT,
            test_groups=("SEC-ALL",),
            invariant="No open P0 or P1 finding remains.",
        ),
    )
    provisional = AssuranceCatalog.model_construct(
        catalog_version="s6-assurance-1", cases=cases, catalog_sha256="0" * 64
    )
    return AssuranceCatalog(
        catalog_version="s6-assurance-1",
        cases=cases,
        catalog_sha256=assurance_catalog_sha256(provisional),
    )


def assess_assurance(
    catalog: AssuranceCatalog, build_sha256: str, results: tuple[AssuranceResult, ...]
) -> AssuranceAssessment:
    expected = {case.case_id: case for case in catalog.cases}
    if len({item.case_id for item in results}) != len(results) or any(
        item.case_id not in expected for item in results
    ):
        return _assessment(
            catalog,
            build_sha256,
            AssuranceStatus.FAILED,
            0,
            (),
            "ASSURANCE_RESULT_SET_INVALID",
            "Provide one result for each known case identity.",
        )
    by_id = {item.case_id: item for item in results}
    automated_passed = 0
    external: list[str] = []
    for case in catalog.cases:
        result = by_id.get(case.case_id)
        if result is None:
            if case.requirement is EvidenceRequirement.AUTOMATED:
                return _assessment(
                    catalog,
                    build_sha256,
                    AssuranceStatus.FAILED,
                    automated_passed,
                    (),
                    "ASSURANCE_REQUIRED_CASE_MISSING",
                    f"Run required case {case.case_id}.",
                )
            external.append(case.case_id)
            continue
        if result.catalog_sha256 != catalog.catalog_sha256 or result.build_sha256 != build_sha256:
            return _assessment(
                catalog,
                build_sha256,
                AssuranceStatus.FAILED,
                automated_passed,
                (),
                "ASSURANCE_EVIDENCE_BINDING_INVALID",
                "Use evidence for the exact catalog and build.",
            )
        unsafe = (
            not result.passed
            or result.p0_findings
            or result.p1_findings
            or result.tenant_leaks
            or result.duplicate_committed_side_effects
            or result.retry_limit_violations
            or result.explained_unrepaired_failures != result.unrepaired_failures
        )
        if unsafe:
            return _assessment(
                catalog,
                build_sha256,
                AssuranceStatus.FAILED,
                automated_passed,
                (),
                "ASSURANCE_INVARIANT_FAILED",
                f"Correct and rerun {case.case_id}.",
            )
        if not _environment_satisfies(case.requirement, result.environment):
            external.append(case.case_id)
        elif case.requirement is EvidenceRequirement.AUTOMATED:
            automated_passed += 1
    if external:
        return _assessment(
            catalog,
            build_sha256,
            AssuranceStatus.BLOCKED,
            automated_passed,
            tuple(external),
            "ASSURANCE_EXTERNAL_EVIDENCE_MISSING",
            (
                "Run the remaining cases in their declared live, hardware, "
                "or independent environments."
            ),
        )
    return _assessment(
        catalog,
        build_sha256,
        AssuranceStatus.PASS,
        automated_passed,
        (),
        "ASSURANCE_ACCEPTED",
        "Preserve this evidence with the immutable release candidate.",
    )


def _environment_satisfies(
    requirement: EvidenceRequirement, environment: AssuranceEnvironment
) -> bool:
    allowed = {
        EvidenceRequirement.AUTOMATED: set(AssuranceEnvironment),
        EvidenceRequirement.LIVE: {
            AssuranceEnvironment.STAGING,
            AssuranceEnvironment.PRODUCTION_LIKE,
        },
        EvidenceRequirement.HARDWARE: {AssuranceEnvironment.HARDWARE_LAB},
        EvidenceRequirement.INDEPENDENT: {AssuranceEnvironment.INDEPENDENT_PENETRATION},
    }
    return environment in allowed[requirement]


def _assessment(
    catalog: AssuranceCatalog,
    build_sha256: str,
    status: AssuranceStatus,
    automated_passed: int,
    external: tuple[str, ...],
    code: str,
    action: str,
) -> AssuranceAssessment:
    return AssuranceAssessment(
        status=status,
        catalog_sha256=catalog.catalog_sha256,
        build_sha256=build_sha256,
        automated_passed=automated_passed,
        required_total=len(catalog.cases),
        external_case_ids=external,
        reason_code=code,
        next_action=action,
    )
