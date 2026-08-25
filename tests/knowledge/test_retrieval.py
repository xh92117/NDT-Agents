"""S3-07 hybrid retrieval, authorization, citation, and frozen evaluation tests."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import TenantScope
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
    HybridRetrievalService,
    IndexBuildRequest,
    IndexSnapshot,
    IndexStatus,
    InMemoryKnowledgeIndex,
    RetrievalQuery,
    tokenize,
)

TENANT = UUID("00000000-0000-4000-8000-000000000101")
PROJECT = UUID("00000000-0000-4000-8000-000000000201")
USER = UUID("00000000-0000-4000-8000-000000000301")
EMBEDDING = DeterministicHashEmbedding(dimension=64)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def scope(
    *,
    tenant: UUID = TENANT,
    project: UUID = PROJECT,
    user: UUID = USER,
    roles: tuple[str, ...] = ("knowledge-reader",),
    permission: str = "permissions-1",
) -> TenantScope:
    return TenantScope(
        tenant_id=tenant,
        project_id=project,
        user_id=user,
        role_codes=roles,
        permission_version=permission,
    )


def document(owner: TenantScope, key: str, text: str) -> CanonicalDocument:
    element_id = digest(f"element:{key}")
    chunk_id = digest(f"chunk:{key}")
    content_hash = digest(text)
    element = CanonicalElement(
        element_id=element_id,
        sequence=0,
        kind=ElementKind.PARAGRAPH,
        page_index=0,
        bbox=BoundingBox(coordinates=(10, 20, 900, 100)),
        locator_type=LocatorType.PAGE,
        locator="page:1",
        source_block_orders=(0,),
        content=text,
        content_sha256=content_hash,
    )
    chunk = KnowledgeChunk(
        chunk_id=chunk_id,
        index=0,
        element_id=element_id,
        part_index=0,
        part_count=1,
        page_index=0,
        section_path=("Inspection",),
        locator_type=LocatorType.PAGE,
        locator="page:1",
        text=text,
        content_sha256=content_hash,
    )
    return CanonicalDocument(
        document_id=digest(f"document-id:{key}"),
        document_sha256=digest(f"document:{key}:{text}"),
        scope=owner,
        artifact_id="00000000-0000-4000-8000-000000000001",
        artifact_version="source-v1",
        source_sha256=digest(f"source:{key}"),
        source_media_type="application/pdf",
        source_title=f"Standard {key}",
        language="zh-CN",
        parser_name="mineru",
        parser_version="3.0.0",
        metadata={"standard_id": key},
        source_block_count=1,
        elements=(element,),
        chunks=(chunk,),
    )


def build(
    owner: TenantScope,
    key: str,
    text: str,
    *,
    status: IndexStatus = IndexStatus.PUBLISHED,
    corpus_version: str = "corpus-v1",
    index_version: str = "index-v1",
    roles: tuple[str, ...] = (),
    metadata: dict[str, str] | None = None,
) -> IndexSnapshot:
    draft = HybridIndexer(EMBEDDING).build(
        owner,
        IndexBuildRequest(
            corpus_id="ndt-standards",
            corpus_version=corpus_version,
            index_version=index_version,
            document=document(owner, key, text),
            required_roles=roles,
            metadata=metadata or {},
        ),
    )
    return IndexSnapshot.model_validate({**draft.model_dump(), "status": status})


def query(text: str, **changes: object) -> RetrievalQuery:
    values: dict[str, object] = {
        "text": text,
        "corpus_id": "ndt-standards",
        "corpus_version": "corpus-v1",
        "index_version": "index-v1",
        "embedding_version": EMBEDDING.version,
    }
    values.update(changes)
    return RetrievalQuery.model_validate(values)


def service(*snapshots: IndexSnapshot) -> HybridRetrievalService:
    repository = InMemoryKnowledgeIndex()
    for snapshot in snapshots:
        repository.replace(snapshot)
    return HybridRetrievalService(repository, EMBEDDING)


def test_index_snapshot_is_stable_complete_and_draft_by_default() -> None:
    owner = scope()
    request = IndexBuildRequest(
        corpus_id="ndt-standards",
        corpus_version="corpus-v1",
        index_version="index-v1",
        document=document(owner, "GB-A", "裂缝宽度不得超过 0.20 mm"),
        required_roles=("knowledge-reader", "knowledge-reader"),
        metadata={"region": "cn"},
    )
    indexer = HybridIndexer(EMBEDDING)

    first = indexer.build(owner, request)
    second = indexer.build(owner, request)

    assert first == second
    assert first.status is IndexStatus.DRAFT
    assert first.required_roles == ("knowledge-reader",)
    assert first.embedding_dimension == 64
    assert first.records[0].source_sha256 == request.document.source_sha256
    assert first.records[0].locator == "page:1"


def test_tokenizer_covers_latin_numbers_and_chinese_bigrams() -> None:
    tokens = tokenize("UT crack 0.20 mm 裂缝宽度")

    assert {"ut", "crack", "0.20", "mm", "裂", "裂缝", "宽度"}.issubset(tokens)


def test_retrieval_returns_relevant_text_and_complete_citation() -> None:
    snapshot = build(scope(), "GB-CRACK", "桥梁裂缝宽度限值为 0.20 mm")

    result = service(snapshot).retrieve(scope(), query("裂缝宽度 0.20 mm"))

    assert result.authorized_snapshot_count == 1
    assert result.hits[0].text == snapshot.records[0].text
    citation = result.hits[0].citation
    assert citation.chunk_id == snapshot.records[0].chunk_id
    assert citation.source_sha256 == snapshot.records[0].source_sha256
    assert citation.document_sha256 == snapshot.document_sha256
    assert citation.parser_name == "mineru"
    assert citation.locator == "page:1"


@pytest.mark.parametrize(
    "other",
    [
        scope(tenant=UUID("00000000-0000-4000-8000-000000000102")),
        scope(project=UUID("00000000-0000-4000-8000-000000000202")),
        scope(user=UUID("00000000-0000-4000-8000-000000000302")),
        scope(permission="permissions-2"),
    ],
)
def test_exact_scope_isolation_precedes_scoring(other: TenantScope) -> None:
    authorized = build(scope(), "AUTHORIZED", "authorized unique crack rule")
    unauthorized = build(other, "UNAUTHORIZED", "secret unique crack rule")

    result = service(authorized, unauthorized).retrieve(scope(), query("secret unique crack rule"))

    assert result.authorized_snapshot_count == 1
    assert all("secret" not in hit.text for hit in result.hits)


def test_role_and_metadata_filters_are_enforced_before_scoring() -> None:
    restricted = build(
        scope(),
        "RESTRICTED",
        "restricted ultrasonic threshold",
        roles=("standard-approver",),
        metadata={"region": "cn"},
    )
    wrong_region = build(
        scope(),
        "REGION",
        "regional ultrasonic threshold",
        metadata={"region": "eu"},
    )

    result = service(restricted, wrong_region).retrieve(
        scope(), query("ultrasonic threshold", required_metadata={"region": "cn"})
    )

    assert result.authorized_snapshot_count == 0
    assert result.hits == ()


@pytest.mark.parametrize(
    "status",
    [IndexStatus.DRAFT, IndexStatus.SUPERSEDED, IndexStatus.WITHDRAWN],
)
def test_non_published_snapshot_is_excluded(status: IndexStatus) -> None:
    snapshot = build(scope(), "STATE", "state-only phrase", status=status)

    result = service(snapshot).retrieve(scope(), query("state-only phrase"))

    assert result.authorized_snapshot_count == 0
    assert result.hits == ()


@pytest.mark.parametrize(
    ("corpus_version", "index_version"),
    [("corpus-v0", "index-v1"), ("corpus-v1", "index-v0")],
)
def test_stale_corpus_and_index_versions_are_excluded(
    corpus_version: str, index_version: str
) -> None:
    snapshot = build(
        scope(),
        "STALE",
        "stale-only phrase",
        corpus_version=corpus_version,
        index_version=index_version,
    )

    result = service(snapshot).retrieve(scope(), query("stale-only phrase"))

    assert result.authorized_snapshot_count == 0


def test_embedding_version_mismatch_is_rejected() -> None:
    snapshot = build(scope(), "STALE", "stale-only phrase")

    with pytest.raises(ValueError, match="EMBEDDING_VERSION_MISMATCH"):
        service(snapshot).retrieve(
            scope(), query("stale-only phrase", embedding_version="other-v1")
        )


def test_candidate_and_top_k_limits_are_bounded_and_stable() -> None:
    snapshots = tuple(
        build(scope(), f"DOC-{index}", "common inspection phrase") for index in range(12)
    )
    retrieval = service(*snapshots)

    first = retrieval.retrieve(scope(), query("common inspection", top_k=3, candidate_limit=5))
    second = retrieval.retrieve(scope(), query("common inspection", top_k=3, candidate_limit=5))

    assert first == second
    assert first.candidate_count == 5
    assert len(first.hits) == 3
    with pytest.raises(ValidationError):
        query("common", top_k=11)
    with pytest.raises(ValidationError):
        query("common", candidate_limit=101)


def test_invalid_embedding_shape_is_rejected() -> None:
    snapshot = build(scope(), "SHAPE", "shape validation")
    record = snapshot.records[0]

    with pytest.raises(ValidationError, match="dimension"):
        IndexSnapshot.model_validate(
            {
                **snapshot.model_dump(),
                "records": ({**record.model_dump(), "vector": record.vector[:-1]},),
            }
        )


@dataclass(frozen=True)
class FrozenCase:
    query_text: str
    relevant_key: str


def test_frozen_retrieval_metrics_and_traceability_meet_thresholds() -> None:
    corpus = {
        "CRACK": "桥梁裂缝宽度限值为 0.20 mm crack width",
        "UT": "超声检测 UT 声速校准值为 5900 m/s ultrasonic calibration",
        "MT": "磁粉检测 MT 磁化方向应互相垂直 magnetic particle",
        "RT": "射线检测 RT 底片黑度范围 2.0 至 4.0 radiographic density",
        "PAUT": "相控阵 PAUT 楔块延迟校准 wedge delay calibration",
        "CORROSION": "钢筋腐蚀电位小于 -350 mV corrosion potential",
    }
    cases = (
        FrozenCase("裂缝宽度 0.20 mm", "CRACK"),
        FrozenCase("UT 5900 m/s 声速校准", "UT"),
        FrozenCase("磁粉 磁化方向 垂直", "MT"),
        FrozenCase("RT 黑度 2.0 4.0", "RT"),
        FrozenCase("PAUT wedge delay", "PAUT"),
        FrozenCase("腐蚀电位 -350 mV", "CORROSION"),
    )
    snapshots = tuple(build(scope(), key, text) for key, text in corpus.items())
    retrieval = service(*snapshots)
    recalls: list[float] = []
    discounted_gains: list[float] = []
    citation_checks: list[float] = []
    traceability_checks: list[float] = []
    expected_chunks = {key: digest(f"chunk:{key}") for key in corpus}
    records = {record.chunk_id: record for snapshot in snapshots for record in snapshot.records}

    for case in cases:
        result = retrieval.retrieve(scope(), query(case.query_text, top_k=6))
        ids = [hit.chunk_id for hit in result.hits]
        expected = expected_chunks[case.relevant_key]
        recalls.append(float(expected in ids))
        rank = ids.index(expected) + 1 if expected in ids else 0
        discounted_gains.append(1 / math.log2(rank + 1) if rank else 0.0)
        for hit in result.hits:
            record = records[hit.chunk_id]
            citation_checks.append(float(hit.citation.content_sha256 == record.content_sha256))
            traceability_checks.append(
                float(
                    hit.citation.document_id == record.document_id
                    and hit.citation.source_sha256 == record.source_sha256
                    and hit.citation.locator == record.locator
                )
            )

    assert sum(recalls) / len(recalls) >= 0.92
    assert sum(discounted_gains) / len(discounted_gains) >= 0.85
    assert sum(citation_checks) / len(citation_checks) >= 0.95
    assert sum(traceability_checks) / len(traceability_checks) == 1.0
