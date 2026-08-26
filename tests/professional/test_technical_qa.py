"""S4-01 Technical QA Skill and citation validation tests."""

from __future__ import annotations

import hashlib
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
from ndt_agents.professional.qa import (
    ClaimApplicability,
    ClaimConclusionLevel,
    ClaimSeverity,
    QAClaimSupport,
    TechnicalQACandidate,
    TechnicalQACandidateClaim,
    TechnicalQARequest,
    TechnicalQASkill,
)

TENANT = UUID("00000000-0000-4000-8000-000000000101")
PROJECT = UUID("00000000-0000-4000-8000-000000000201")
USER = UUID("00000000-0000-4000-8000-000000000301")
TASK = UUID("00000000-0000-4000-8000-000000000401")
EMBEDDING = DeterministicHashEmbedding(dimension=64)
REPO_ROOT = Path(__file__).resolve().parents[2]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def scope(
    *,
    tenant: UUID = TENANT,
    project: UUID = PROJECT,
    user: UUID = USER,
    permission: str = "permissions-1",
) -> TenantScope:
    return TenantScope(
        tenant_id=tenant,
        project_id=project,
        user_id=user,
        role_codes=("knowledge-reader",),
        permission_version=permission,
    )


def document(owner: TenantScope, key: str, text: str) -> CanonicalDocument:
    content_hash = digest(text)
    element_id = digest(f"element:{key}")
    chunk_id = digest(f"chunk:{key}")
    return CanonicalDocument(
        document_id=digest(f"document-id:{key}"),
        document_sha256=digest(f"document:{key}:{text}"),
        scope=owner,
        artifact_id="00000000-0000-4000-8000-000000000001",
        artifact_version="source-v1",
        source_sha256=digest(f"source:{key}"),
        source_media_type="application/pdf",
        source_title=f"Authorized source {key}",
        language="en",
        parser_name="mineru",
        parser_version="3.0.0",
        metadata={"standard_id": key},
        source_block_count=1,
        elements=(
            CanonicalElement(
                element_id=element_id,
                sequence=0,
                kind=ElementKind.PARAGRAPH,
                page_index=0,
                bbox=BoundingBox(coordinates=(10, 20, 900, 100)),
                locator_type=LocatorType.CLAUSE,
                locator="clause:5.2",
                source_block_orders=(0,),
                content=text,
                content_sha256=content_hash,
            ),
        ),
        chunks=(
            KnowledgeChunk(
                chunk_id=chunk_id,
                index=0,
                element_id=element_id,
                part_index=0,
                part_count=1,
                page_index=0,
                section_path=("Calibration",),
                locator_type=LocatorType.CLAUSE,
                locator="clause:5.2",
                text=text,
                content_sha256=content_hash,
            ),
        ),
    )


def snapshot(
    owner: TenantScope,
    key: str,
    text: str,
    *,
    status: IndexStatus = IndexStatus.PUBLISHED,
    index_version: str = "index-v1",
) -> IndexSnapshot:
    draft = HybridIndexer(EMBEDDING).build(
        owner,
        IndexBuildRequest(
            corpus_id="ndt-standards",
            corpus_version="corpus-v1",
            index_version=index_version,
            document=document(owner, key, text),
        ),
    )
    return IndexSnapshot.model_validate({**draft.model_dump(), "status": status})


def request(**changes: object) -> TechnicalQARequest:
    values: dict[str, object] = {
        "task_id": TASK,
        "request_id": "qa-request-1",
        "question": "What calibration is required for ultrasonic testing?",
        "method_code": "UT",
        "structure_class": "BRIDGE",
        "material_class": "REINFORCED_CONCRETE",
        "corpus_id": "ndt-standards",
        "corpus_version": "corpus-v1",
        "index_version": "index-v1",
        "embedding_version": EMBEDDING.version,
    }
    values.update(changes)
    return TechnicalQARequest.model_validate(values)


def support(chunk_id: str) -> QAClaimSupport:
    return QAClaimSupport(
        chunk_id=chunk_id,
        quote="Ultrasonic testing requires calibration before inspection.",
        matching_terms=("calibration", "ultrasonic"),
    )


def claim(
    chunk_id: str | None,
    *,
    severity: ClaimSeverity = ClaimSeverity.MATERIAL,
    conclusion: ClaimConclusionLevel = ClaimConclusionLevel.PRELIMINARY_ASSESSMENT,
    human: bool = False,
) -> TechnicalQACandidateClaim:
    return TechnicalQACandidateClaim(
        statement="Ultrasonic testing requires calibration before inspection.",
        severity=severity,
        applicability=ClaimApplicability.APPLICABLE,
        conclusion_level=conclusion,
        limitations=("The exact calibration procedure depends on the applicable standard.",),
        uncertainty="Instrument-specific settings were not supplied.",
        supports=(support(chunk_id),) if chunk_id is not None else (),
        human_confirmation_required=human,
    )


def candidate(item: TechnicalQACandidateClaim) -> TechnicalQACandidate:
    return TechnicalQACandidate(
        summary="Calibration is required before ultrasonic inspection.",
        claims=(item,),
        overall_limitation="This is an evidence-bound preliminary answer, not a formal conclusion.",
    )


def skill(*items: IndexSnapshot) -> TechnicalQASkill:
    repository = InMemoryKnowledgeIndex()
    for item in items:
        repository.replace(item)
    return TechnicalQASkill(repository, EMBEDDING)


def test_supported_answer_is_stable_and_reconstructs_exact_citation() -> None:
    item = snapshot(
        scope(),
        "UT-CAL",
        "Ultrasonic testing requires calibration before inspection.",
    )
    qa = skill(item)
    typed_candidate = candidate(claim(item.records[0].chunk_id))

    first = qa.execute(scope(), request(), typed_candidate)
    second = qa.execute(scope(), request(), typed_candidate)

    assert first == second
    assert first.status is AgentStatus.SUCCESS
    assert first.human_confirmation_required is False
    assert first.evidence_snapshot_ids == (item.snapshot_id,)
    assert first.claims[0].claim_id.startswith("claim-")
    citation = first.claims[0].citations[0]
    assert citation.snapshot_id == item.snapshot_id
    assert citation.document_sha256 == item.document_sha256
    assert citation.content_sha256 == item.records[0].content_sha256
    assert citation.locator == "clause:5.2"
    assert citation.quote in item.records[0].text


def test_missing_applicability_inputs_stop_before_retrieval() -> None:
    result = skill().execute(scope(), request(method_code=None, material_class=None), None)

    assert result.status is AgentStatus.NEEDS_USER
    assert result.claims == ()
    assert result.retrieval_query_sha256 == "0" * 64
    assert result.missing_inputs == ("method_code", "material_class")
    assert {item.code for item in result.issues} == {"QA_REQUIRED_INPUT_MISSING"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("method_code", "XRF"),
        ("structure_class", "AIRCRAFT"),
        ("material_class", "TIMBER"),
    ],
)
def test_out_of_domain_request_requires_qualified_human(field: str, value: str) -> None:
    result = skill().execute(scope(), request(**{field: value}), None)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert result.human_confirmation_required is True
    assert result.issues[0].code == "QA_DOMAIN_OUT_OF_SCOPE"


def test_candidate_is_required_after_safe_preflight() -> None:
    result = skill().execute(scope(), request(), None)

    assert result.status is AgentStatus.NEEDS_USER
    assert result.issues[0].code == "QA_CANDIDATE_MISSING"


def test_unrelated_quote_cannot_be_reused_for_claim() -> None:
    item = snapshot(
        scope(),
        "UT-CAL",
        "Ultrasonic testing requires calibration before inspection.",
    )
    unrelated = TechnicalQACandidateClaim(
        statement="Bridge load capacity is adequate.",
        severity=ClaimSeverity.MATERIAL,
        applicability=ClaimApplicability.APPLICABLE,
        conclusion_level=ClaimConclusionLevel.PRELIMINARY_ASSESSMENT,
        limitations=("No structural analysis was supplied.",),
        uncertainty="Load data is missing.",
        supports=(
            QAClaimSupport(
                chunk_id=item.records[0].chunk_id,
                quote=item.records[0].text,
                matching_terms=("ultrasonic",),
            ),
        ),
    )

    result = skill(item).execute(scope(), request(), candidate(unrelated))

    assert result.status is AgentStatus.PARTIAL_SUCCESS
    assert result.claims[0].citations == ()
    assert {item.code for item in result.issues} == {
        "QA_SUPPORT_UNRELATED",
        "QA_CLAIM_UNSUPPORTED",
    }


def test_nonretrieved_or_stale_support_is_rejected() -> None:
    stale = snapshot(
        scope(),
        "UT-CAL",
        "Ultrasonic testing requires calibration before inspection.",
        index_version="index-v0",
    )

    result = skill(stale).execute(scope(), request(), candidate(claim(stale.records[0].chunk_id)))

    assert result.status is AgentStatus.PARTIAL_SUCCESS
    assert result.claims[0].citations == ()
    assert result.issues[0].code == "QA_SUPPORT_NOT_RETRIEVED"


def test_draft_and_cross_scope_evidence_cannot_support_critical_claim() -> None:
    draft = snapshot(
        scope(),
        "DRAFT",
        "Ultrasonic testing requires calibration before inspection.",
        status=IndexStatus.DRAFT,
    )
    foreign = snapshot(
        scope(project=UUID("00000000-0000-4000-8000-000000000202")),
        "FOREIGN",
        "Ultrasonic testing requires calibration before inspection.",
    )
    critical = claim(
        draft.records[0].chunk_id,
        severity=ClaimSeverity.CRITICAL,
        human=True,
    )

    result = skill(draft, foreign).execute(scope(), request(), candidate(critical))

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert result.claims[0].citations == ()
    assert "QA_CLAIM_UNSUPPORTED" in {item.code for item in result.issues}


def test_formal_conclusion_remains_human_required_even_with_valid_evidence() -> None:
    item = snapshot(
        scope(),
        "UT-CAL",
        "Ultrasonic testing requires calibration before inspection.",
    )
    formal = claim(
        item.records[0].chunk_id,
        conclusion=ClaimConclusionLevel.FORMAL_CONCLUSION,
        human=True,
    )

    result = skill(item).execute(scope(), request(), candidate(formal))

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert len(result.claims[0].citations) == 1
    assert result.issues[0].code == "QA_FORMAL_CONCLUSION_REQUIRES_HUMAN"


def test_candidate_contract_rejects_duplicate_claims_and_uncanonical_terms() -> None:
    item = claim(digest("chunk"))

    with pytest.raises(ValidationError, match="claims must be unique"):
        TechnicalQACandidate(
            summary="Duplicate.",
            claims=(item, item),
            overall_limitation="Not formal.",
        )
    with pytest.raises(ValidationError, match="canonical"):
        QAClaimSupport(
            chunk_id=digest("chunk"),
            quote="Ultrasonic calibration",
            matching_terms=("ultrasonic", "calibration"),
        )


def test_versioned_skill_and_prompt_assets_match_runtime_versions() -> None:
    skill_text = (REPO_ROOT / "skills/professional/technical-qa/SKILL.md").read_text(
        encoding="utf-8"
    )
    prompt_text = (REPO_ROOT / "prompts/professional/technical-qa.v1.md").read_text(
        encoding="utf-8"
    )

    assert "version: 1.0.0" in skill_text
    assert "TechnicalQAResult@1.0.0" in skill_text
    assert "Technical QA prompt v1.0.0" in prompt_text
    assert "human_confirmation_required=true" in prompt_text
