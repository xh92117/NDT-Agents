"""S4-02 inspection-plan Skill, template, and completeness tests."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import AgentStatus, TenantScope
from ndt_agents.knowledge.normalization import (
    CanonicalDocument,
    CanonicalElement,
    ElementKind,
    KnowledgeChunk,
    LocatorType,
)
from ndt_agents.knowledge.parsing import BoundingBox
from ndt_agents.knowledge.retrieval import (
    DeterministicHashEmbedding,
    HybridIndexer,
    IndexBuildRequest,
    IndexSnapshot,
    IndexStatus,
    InMemoryKnowledgeIndex,
)
from ndt_agents.knowledge.standards import (
    RightsBasis,
    StandardCatalog,
    StandardLifecycle,
    StandardVersion,
    StandardVersionDraft,
    finalize_standard_version,
)
from ndt_agents.professional.planning import (
    PLAN_REQUIRED_SECTIONS,
    InspectionPlanCandidate,
    InspectionPlanRequest,
    InspectionPlanSkill,
    PlanInputGap,
    PlannedMethod,
    PlanQuantity,
    PlanScenario,
    PlanSection,
    PlanStandardBasis,
    load_inspection_plan_template,
)
from ndt_agents.professional.qa import (
    ClaimApplicability,
    ClaimConclusionLevel,
    ClaimSeverity,
    QAClaimSupport,
    TechnicalQACandidate,
    TechnicalQACandidateClaim,
    TechnicalQARequest,
    TechnicalQAResult,
    TechnicalQASkill,
)

ROOT = Path(__file__).resolve().parents[2]
TENANT = UUID("10000000-0000-4000-8000-000000000101")
PROJECT = UUID("10000000-0000-4000-8000-000000000201")
USER = UUID("10000000-0000-4000-8000-000000000301")
TASK = UUID("10000000-0000-4000-8000-000000000401")
STRUCTURE = UUID("10000000-0000-4000-8000-000000000501")
COMPONENT = UUID("10000000-0000-4000-8000-000000000601")
EMBEDDING = DeterministicHashEmbedding(dimension=64)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def scope(*, project: UUID = PROJECT, permission: str = "permissions-1") -> TenantScope:
    return TenantScope(
        tenant_id=TENANT,
        project_id=project,
        user_id=USER,
        role_codes=("knowledge-reader",),
        permission_version=permission,
    )


def standard(
    owner: TenantScope, *, lifecycle: StandardLifecycle = StandardLifecycle.CURRENT
) -> StandardVersion:
    return finalize_standard_version(
        StandardVersionDraft(
            scope=owner,
            standard_type="NDT_METHOD",
            standard_identifier="NDT-UT-001",
            edition="2026",
            title="Synthetic ultrasonic inspection basis",
            publication_date=date(2025, 1, 1),
            effective_date=date(2025, 6, 1),
            regions=("CN",),
            lifecycle=lifecycle,
            rights_basis=RightsBasis.LICENSED,
            rights_reference="rights://synthetic/ut",
        )
    )


def document(owner: TenantScope, key: str, text: str) -> CanonicalDocument:
    element_id = digest(f"element:{key}")
    chunk_id = digest(f"chunk:{key}")
    content_hash = digest(text)
    return CanonicalDocument(
        document_id=digest(f"document-id:{key}"),
        document_sha256=digest(f"document:{key}:{text}"),
        scope=owner,
        artifact_id="10000000-0000-4000-8000-000000000001",
        artifact_version="source-v1",
        source_sha256=digest(f"source:{key}"),
        source_media_type="application/pdf",
        source_title="Synthetic ultrasonic standard",
        language="en",
        parser_name="mineru",
        parser_version="3.0.0",
        metadata={"standard_id": key},
        source_block_count=1,
        elements=(
            CanonicalElement(
                element_id=element_id,
                sequence=0,
                kind=ElementKind.CLAUSE,
                page_index=2,
                bbox=BoundingBox(coordinates=(10, 20, 900, 100)),
                locator_type=LocatorType.CLAUSE,
                locator="clause:7.1",
                source_block_orders=(0,),
                content=text,
                content_sha256=content_hash,
                clause_identifier="7.1",
            ),
        ),
        chunks=(
            KnowledgeChunk(
                chunk_id=chunk_id,
                index=0,
                element_id=element_id,
                part_index=0,
                part_count=1,
                page_index=2,
                section_path=("Inspection planning",),
                locator_type=LocatorType.CLAUSE,
                locator="clause:7.1",
                text=text,
                content_sha256=content_hash,
            ),
        ),
    )


def snapshot(owner: TenantScope, version: StandardVersion) -> IndexSnapshot:
    text = "Ultrasonic inspection requires calibrated equipment and ten sampling points."
    draft = HybridIndexer(EMBEDDING).build(
        owner,
        IndexBuildRequest(
            corpus_id="ndt-standards",
            corpus_version="corpus-v1",
            index_version="index-v1",
            document=document(owner, "UT-PLAN", text),
            metadata={"standard_version_id": version.version_id},
        ),
    )
    return IndexSnapshot.model_validate({**draft.model_dump(), "status": IndexStatus.PUBLISHED})


def qa_result(owner: TenantScope, item: IndexSnapshot) -> TechnicalQAResult:
    request = TechnicalQARequest(
        task_id=TASK,
        request_id="qa-for-plan",
        question="What ultrasonic inspection planning controls are required?",
        method_code="UT",
        structure_class="BRIDGE",
        material_class="REINFORCED_CONCRETE",
        corpus_id="ndt-standards",
        corpus_version="corpus-v1",
        index_version="index-v1",
        embedding_version=EMBEDDING.version,
    )
    claim = TechnicalQACandidateClaim(
        statement="Ultrasonic inspection requires calibrated equipment and ten sampling points.",
        severity=ClaimSeverity.MATERIAL,
        applicability=ClaimApplicability.APPLICABLE,
        conclusion_level=ClaimConclusionLevel.EVIDENCE_STATEMENT,
        limitations=("Site access can require layout adjustment.",),
        uncertainty="Instrument model is selected during mobilization.",
        supports=(
            QAClaimSupport(
                chunk_id=item.records[0].chunk_id,
                quote=item.records[0].text,
                matching_terms=("calibrated", "ultrasonic"),
            ),
        ),
    )
    repository = InMemoryKnowledgeIndex()
    repository.replace(item)
    return TechnicalQASkill(repository, EMBEDDING).execute(
        owner,
        request,
        TechnicalQACandidate(
            summary="Use calibrated ultrasonic equipment with explicit coverage.",
            claims=(claim,),
            overall_limitation="This basis does not replace site-specific engineering review.",
        ),
    )


def plan_request(**changes: object) -> InspectionPlanRequest:
    values: dict[str, object] = {
        "task_id": TASK,
        "request_id": "plan-request-1",
        "scenario": PlanScenario.ACCEPTANCE,
        "objective": "Verify bridge-deck ultrasonic inspection coverage.",
        "structure_id": STRUCTURE,
        "component_ids": (COMPONENT,),
        "structure_class": "BRIDGE",
        "material_class": "REINFORCED_CONCRETE",
        "requested_methods": ("UT",),
        "region": "CN",
        "as_of": date(2026, 8, 25),
        "standard_types": ("NDT_METHOD",),
    }
    values.update(changes)
    return InspectionPlanRequest.model_validate(values)


def candidate(result: TechnicalQAResult, **changes: object) -> InspectionPlanCandidate:
    claim = result.claims[0]
    basis = PlanStandardBasis(
        basis_id="ut-basis",
        standard_version_id="0" * 64,
        qa_claim_id=claim.claim_id,
        chunk_id=claim.citations[0].chunk_id,
    )
    values: dict[str, object] = {
        "summary": "Acceptance inspection plan for the bridge deck.",
        "sections": tuple(
            PlanSection(section_id=name, content=f"Controlled {name} content.")
            for name in PLAN_REQUIRED_SECTIONS
        ),
        "quantities": (
            PlanQuantity(
                quantity_id="ut-sampling-points",
                name="Ultrasonic sampling points",
                dimension="COUNT",
                unit="point",
                lower=Decimal("10"),
                target=Decimal("10"),
                upper=Decimal("12"),
            ),
        ),
        "methods": (
            PlannedMethod(
                method_code="UT",
                purpose="Verify internal consistency indications.",
                layout="Ten points on a fixed coordinate grid.",
                equipment_ids=("ut-device-1",),
                calibration_procedure="Verify calibration before and after acquisition.",
                procedure="Acquire and preserve every waveform at each planned point.",
                sampling_quantity_id="ut-sampling-points",
                acceptance_basis_ids=("ut-basis",),
                safety_controls=("Control access to the inspection area.",),
            ),
        ),
        "standard_basis": (basis,),
        "limitations": ("Access restrictions may require an approved layout revision.",),
        "deliverables": ("Reviewed inspection data package", "Approval-pending plan artifact"),
        "qa_result": result,
    }
    values.update(changes)
    return InspectionPlanCandidate.model_validate(values)


def runtime(
    owner: TenantScope | None = None,
    *,
    lifecycle: StandardLifecycle = StandardLifecycle.CURRENT,
) -> tuple[InspectionPlanSkill, TechnicalQAResult, StandardVersion]:
    resolved_owner = owner or scope()
    version = standard(resolved_owner, lifecycle=lifecycle)
    item = snapshot(resolved_owner, version)
    catalog = StandardCatalog()
    catalog.register(resolved_owner, version)
    repository = InMemoryKnowledgeIndex()
    repository.replace(item)
    template = load_inspection_plan_template(ROOT / "fixtures/v1/templates/inspection-plan.v1.json")
    return (
        InspectionPlanSkill(template, repository, catalog),
        qa_result(resolved_owner, item),
        version,
    )


def with_standard_id(
    item: InspectionPlanCandidate, version: StandardVersion
) -> InspectionPlanCandidate:
    basis = item.standard_basis[0].model_copy(update={"standard_version_id": version.version_id})
    return item.model_copy(update={"standard_basis": (basis,)})


def test_generated_template_contains_every_required_section_in_order() -> None:
    template = load_inspection_plan_template(ROOT / "fixtures/v1/templates/inspection-plan.v1.json")

    assert template.required_sections == PLAN_REQUIRED_SECTIONS
    assert len(template.required_sections) == 17


def test_complete_plan_is_stable_review_required_and_approval_pending() -> None:
    skill, qa, version = runtime()
    typed_candidate = with_standard_id(candidate(qa), version)

    first = skill.validate(scope(), plan_request(), typed_candidate)
    second = skill.validate(scope(), plan_request(), typed_candidate)

    assert first == second
    assert first.status is AgentStatus.SUCCESS
    assert first.issues == ()
    assert first.review_required is True
    assert first.approval_state == "PENDING"
    assert first.formal_use_allowed is False
    assert len(first.sections) == 17
    assert first.plan_sha256 == second.plan_sha256


def test_missing_required_input_must_be_explicit_and_blocking_gap_stops_plan() -> None:
    skill, qa, version = runtime()
    gap = PlanInputGap(
        field_path="request.objective",
        reason="Owner objective is not supplied.",
        impact="Method coverage cannot be finalized.",
        owner_role="PROJECT_OWNER",
        blocking=True,
    )
    typed_candidate = with_standard_id(candidate(qa, input_gaps=(gap,)), version)

    result = skill.validate(scope(), plan_request(objective=None), typed_candidate)

    assert result.status is AgentStatus.NEEDS_USER
    assert "PLAN_MISSING_INPUT_UNDECLARED" not in {item.code for item in result.issues}
    assert result.input_gaps == (gap,)


def test_undeclared_missing_input_and_invalid_section_set_are_reported() -> None:
    skill, qa, version = runtime()
    sections = tuple(
        PlanSection(section_id=name, content="content")
        for name in (*PLAN_REQUIRED_SECTIONS[:-1], "unknown_section")
    )
    typed_candidate = with_standard_id(candidate(qa, sections=sections), version)

    result = skill.validate(scope(), plan_request(objective=None), typed_candidate)

    assert result.status is AgentStatus.NEEDS_USER
    assert {item.code for item in result.issues} >= {
        "PLAN_MISSING_INPUT_UNDECLARED",
        "PLAN_SECTION_SET_INVALID",
    }


def test_unknown_and_omitted_requested_method_cannot_pass() -> None:
    skill, qa, version = runtime()
    original = candidate(qa)
    method = original.methods[0].model_copy(update={"method_code": "XRF"})
    typed_candidate = with_standard_id(original.model_copy(update={"methods": (method,)}), version)

    result = skill.validate(scope(), plan_request(), typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert {item.code for item in result.issues} >= {
        "PLAN_METHOD_OUT_OF_SCOPE",
        "PLAN_REQUESTED_METHOD_MISSING",
    }


def test_quantity_and_basis_references_must_exist() -> None:
    skill, qa, version = runtime()
    original = candidate(qa)
    method = original.methods[0].model_copy(
        update={
            "sampling_quantity_id": "missing-quantity",
            "acceptance_basis_ids": ("missing-basis",),
        }
    )
    typed_candidate = with_standard_id(original.model_copy(update={"methods": (method,)}), version)

    result = skill.validate(scope(), plan_request(), typed_candidate)

    assert result.status is AgentStatus.NEEDS_USER
    assert {item.code for item in result.issues} >= {
        "PLAN_QUANTITY_REFERENCE_MISSING",
        "PLAN_BASIS_REFERENCE_MISSING",
    }


def test_wrong_region_standard_is_not_applicable() -> None:
    skill, qa, version = runtime()
    typed_candidate = with_standard_id(candidate(qa), version)

    result = skill.validate(scope(), plan_request(region="US"), typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert "PLAN_STANDARD_NOT_APPLICABLE" in {item.code for item in result.issues}


def test_cross_scope_qa_evidence_is_rejected() -> None:
    foreign_project = UUID("10000000-0000-4000-8000-000000000202")
    skill, _, version = runtime()
    _, foreign_qa, _ = runtime(scope(project=foreign_project))
    typed_candidate = with_standard_id(candidate(foreign_qa), version)

    result = skill.validate(scope(), plan_request(), typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert {item.code for item in result.issues} >= {
        "PLAN_QA_SCOPE_DENIED",
        "PLAN_BASIS_SNAPSHOT_INVALID",
    }


def test_tampered_qa_result_hash_is_rejected() -> None:
    skill, qa, version = runtime()
    tampered = qa.model_copy(update={"summary": "Tampered after QA finalization."})
    typed_candidate = with_standard_id(candidate(qa), version).model_copy(
        update={"qa_result": tampered}
    )

    result = skill.validate(scope(), plan_request(), typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert "PLAN_QA_HASH_INVALID" in {item.code for item in result.issues}


def test_quantity_contract_rejects_unregistered_unit_and_inverted_range() -> None:
    with pytest.raises(ValidationError, match="unit is not registered"):
        PlanQuantity(
            quantity_id="bad-unit",
            name="Bad unit",
            dimension="COUNT",
            unit="mm",
            target=Decimal("1"),
        )
    with pytest.raises(ValidationError, match="lower bound"):
        PlanQuantity(
            quantity_id="bad-range",
            name="Bad range",
            dimension="LENGTH",
            unit="mm",
            lower=Decimal("2"),
            target=Decimal("1"),
        )


def test_candidate_cannot_fabricate_approval_state() -> None:
    _, qa, _ = runtime()
    payload = candidate(qa).model_dump(mode="json")
    payload["approval_state"] = "APPROVED"

    with pytest.raises(ValidationError, match="approval_state"):
        InspectionPlanCandidate.model_validate(payload)


def test_versioned_plan_skill_and_prompt_assets_match_runtime_contract() -> None:
    skill_text = (ROOT / "skills/professional/inspection-plan/SKILL.md").read_text("utf-8")
    prompt_text = (ROOT / "prompts/professional/inspection-plan.v1.md").read_text("utf-8")

    assert "version: 1.0.0" in skill_text
    assert "InspectionPlanResult@1.0.0" in skill_text
    assert "TPL-INSPECTION-PLAN-V1" in prompt_text
    assert "all template sections in order" in prompt_text
