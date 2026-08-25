"""S3-07 immutable hybrid knowledge index and scope-safe retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from enum import StrEnum
from threading import RLock
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel, TenantScope
from ndt_agents.knowledge.normalization import CanonicalDocument, LocatorType

INDEX_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_CANDIDATES = 100
MAX_TOP_K = 10
_LATIN_OR_NUMBER = re.compile(r"[a-z]+(?:['-][a-z]+)*|\d+(?:\.\d+)?", re.IGNORECASE)
_HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


class IndexStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class EmbeddingPort(Protocol):
    version: str
    dimension: int

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


class DeterministicHashEmbedding:
    """Offline deterministic embedding used as a replaceable, versioned adapter."""

    version = "deterministic-hash-v1"

    def __init__(self, dimension: int = 64) -> None:
        if not 8 <= dimension <= 4_096:
            raise ValueError("embedding dimension must be between 8 and 4096")
        self.dimension = dimension

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            values = [0.0] * self.dimension
            for token in tokenize(text):
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimension
                sign = 1.0 if digest[4] & 1 else -1.0
                values[index] += sign
            magnitude = math.sqrt(sum(value * value for value in values))
            if magnitude:
                values = [value / magnitude for value in values]
            vectors.append(tuple(values))
        return tuple(vectors)


def tokenize(text: str) -> tuple[str, ...]:
    """Tokenize Latin words, numbers, and Han unigrams/bigrams deterministically."""

    normalized = text.casefold()
    tokens = [match.group(0) for match in _LATIN_OR_NUMBER.finditer(normalized)]
    for match in _HAN_RUN.finditer(normalized):
        run = match.group(0)
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tuple(tokens)


class IndexRecord(StrictModel):
    chunk_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_id: str = Field(min_length=36, max_length=36)
    artifact_version: str = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_title: str = Field(min_length=1, max_length=1_000)
    source_media_type: str = Field(min_length=1, max_length=255)
    parser_name: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    normalizer_version: str = Field(min_length=1, max_length=128)
    page_index: int = Field(ge=0, lt=2_000)
    section_path: tuple[str, ...] = Field(max_length=10)
    locator_type: LocatorType
    locator: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=1, max_length=1_200)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tokens: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    vector: tuple[float, ...] = Field(min_length=8, max_length=4_096)


class IndexSnapshot(StrictModel):
    schema_version: Literal["1.0.0"] = INDEX_CONTRACT_VERSION
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: TenantScope
    corpus_id: str = Field(min_length=1, max_length=128)
    corpus_version: str = Field(min_length=1, max_length=64)
    index_version: str = Field(min_length=1, max_length=64)
    status: IndexStatus = IndexStatus.DRAFT
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_version: str = Field(min_length=1, max_length=128)
    embedding_dimension: int = Field(ge=8, le=4_096)
    required_roles: tuple[str, ...] = Field(default=(), max_length=32)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=64)
    records: tuple[IndexRecord, ...] = Field(min_length=1, max_length=400_000)

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        if any(record.document_id != self.document_id for record in self.records):
            raise ValueError("all index records must belong to the snapshot document")
        if any(len(record.vector) != self.embedding_dimension for record in self.records):
            raise ValueError("record vector dimension must match snapshot configuration")
        if len({record.chunk_id for record in self.records}) != len(self.records):
            raise ValueError("index record chunk IDs must be unique")
        return self


class IndexBuildRequest(StrictModel):
    schema_version: Literal["1.0.0"] = INDEX_CONTRACT_VERSION
    corpus_id: str = Field(min_length=1, max_length=128)
    corpus_version: str = Field(min_length=1, max_length=64)
    index_version: str = Field(min_length=1, max_length=64)
    document: CanonicalDocument
    required_roles: tuple[str, ...] = Field(default=(), max_length=32)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=64)


class HybridIndexer:
    def __init__(self, embedding: EmbeddingPort) -> None:
        self._embedding = embedding

    def build(self, scope: TenantScope, request: IndexBuildRequest) -> IndexSnapshot:
        document = request.document
        if document.scope != scope:
            raise PermissionError("INDEX_SCOPE_DENIED")
        texts = tuple(chunk.text for chunk in document.chunks)
        vectors = self._embedding.embed(texts)
        if len(vectors) != len(texts):
            raise ValueError("INDEX_EMBEDDING_COUNT_INVALID")
        records = tuple(
            IndexRecord(
                chunk_id=chunk.chunk_id,
                document_id=document.document_id,
                document_sha256=document.document_sha256,
                artifact_id=document.artifact_id,
                artifact_version=document.artifact_version,
                source_sha256=document.source_sha256,
                source_title=document.source_title,
                source_media_type=document.source_media_type,
                parser_name=document.parser_name,
                parser_version=document.parser_version,
                normalizer_version=document.normalizer_version,
                page_index=chunk.page_index,
                section_path=chunk.section_path,
                locator_type=chunk.locator_type,
                locator=chunk.locator,
                text=chunk.text,
                content_sha256=chunk.content_sha256,
                tokens=tokenize(chunk.text),
                vector=vector,
            )
            for chunk, vector in zip(document.chunks, vectors, strict=True)
        )
        identity = {
            "scope": scope.model_dump(mode="json"),
            "corpus": [request.corpus_id, request.corpus_version],
            "index": request.index_version,
            "document": document.document_sha256,
            "embedding": [self._embedding.version, self._embedding.dimension],
            "roles": sorted(set(request.required_roles)),
            "metadata": _metadata(request.metadata),
            "records": [record.model_dump(mode="json") for record in records],
        }
        return IndexSnapshot(
            snapshot_id=_canonical_hash(identity),
            scope=scope,
            corpus_id=request.corpus_id,
            corpus_version=request.corpus_version,
            index_version=request.index_version,
            document_id=document.document_id,
            document_sha256=document.document_sha256,
            embedding_version=self._embedding.version,
            embedding_dimension=self._embedding.dimension,
            required_roles=tuple(sorted(set(request.required_roles))),
            metadata=_metadata(request.metadata),
            records=records,
        )


class InMemoryKnowledgeIndex:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, ...], IndexSnapshot] = {}
        self._lock = RLock()

    @staticmethod
    def _key(snapshot: IndexSnapshot) -> tuple[str, ...]:
        scope = snapshot.scope
        return (
            str(scope.tenant_id),
            str(scope.project_id),
            str(scope.user_id),
            scope.permission_version,
            *scope.role_codes,
            snapshot.corpus_id,
            snapshot.corpus_version,
            snapshot.index_version,
            snapshot.document_id,
        )

    def replace(self, snapshot: IndexSnapshot) -> None:
        self.replace_many((snapshot,))

    def replace_many(self, snapshots: tuple[IndexSnapshot, ...]) -> None:
        """Validate a complete batch before one in-memory reference swap."""

        prepared = tuple((self._key(snapshot), snapshot) for snapshot in snapshots)
        if len({key for key, _ in prepared}) != len(prepared):
            raise ValueError("INDEX_ATOMIC_BATCH_DUPLICATE")
        with self._lock:
            updated = dict(self._snapshots)
            updated.update(prepared)
            self._snapshots = updated

    def list_for_scope(self, scope: TenantScope) -> tuple[IndexSnapshot, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (item for item in self._snapshots.values() if item.scope == scope),
                    key=lambda item: item.snapshot_id,
                )
            )


class RetrievalQuery(StrictModel):
    schema_version: Literal["1.0.0"] = INDEX_CONTRACT_VERSION
    text: str = Field(min_length=1, max_length=4_000)
    corpus_id: str = Field(min_length=1, max_length=128)
    corpus_version: str = Field(min_length=1, max_length=64)
    index_version: str = Field(min_length=1, max_length=64)
    embedding_version: str = Field(min_length=1, max_length=128)
    top_k: int = Field(default=6, ge=1, le=MAX_TOP_K)
    candidate_limit: int = Field(default=50, ge=1, le=MAX_CANDIDATES)
    required_metadata: dict[str, str] = Field(default_factory=dict, max_length=32)


class RetrievalCitation(StrictModel):
    artifact_id: str = Field(min_length=36, max_length=36)
    artifact_version: str = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_title: str = Field(min_length=1, max_length=1_000)
    source_media_type: str = Field(min_length=1, max_length=255)
    parser_name: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    normalizer_version: str = Field(min_length=1, max_length=128)
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_index: int = Field(ge=0, lt=2_000)
    section_path: tuple[str, ...]
    locator_type: LocatorType
    locator: str = Field(min_length=1, max_length=512)


class RetrievalHit(StrictModel):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1, max_length=1_200)
    score: float = Field(ge=0)
    lexical_rank: int | None = Field(default=None, ge=1)
    vector_rank: int | None = Field(default=None, ge=1)
    citation: RetrievalCitation


class RetrievalResult(StrictModel):
    schema_version: Literal["1.0.0"] = INDEX_CONTRACT_VERSION
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorized_snapshot_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0, le=MAX_CANDIDATES)
    hits: tuple[RetrievalHit, ...] = Field(max_length=MAX_TOP_K)


class HybridRetrievalService:
    def __init__(self, repository: InMemoryKnowledgeIndex, embedding: EmbeddingPort) -> None:
        self._repository = repository
        self._embedding = embedding

    def retrieve(self, scope: TenantScope, query: RetrievalQuery) -> RetrievalResult:
        if query.embedding_version != self._embedding.version:
            raise ValueError("RETRIEVAL_EMBEDDING_VERSION_MISMATCH")
        snapshots = tuple(
            snapshot
            for snapshot in self._repository.list_for_scope(scope)
            if snapshot.status is IndexStatus.PUBLISHED
            and snapshot.corpus_id == query.corpus_id
            and snapshot.corpus_version == query.corpus_version
            and snapshot.index_version == query.index_version
            and snapshot.embedding_version == query.embedding_version
            and snapshot.embedding_dimension == self._embedding.dimension
            and set(snapshot.required_roles).issubset(scope.role_codes)
            and all(
                snapshot.metadata.get(key) == value
                for key, value in query.required_metadata.items()
            )
        )
        rows = [(snapshot, record) for snapshot in snapshots for record in snapshot.records]
        query_tokens = tokenize(query.text)
        query_vector = self._embedding.embed((query.text,))[0]
        lexical_scores = _bm25(query_tokens, tuple(record.tokens for _, record in rows))
        vector_scores = tuple(_cosine(query_vector, record.vector) for _, record in rows)
        lexical_ranks = _positive_ranks(lexical_scores, rows)
        vector_ranks = _positive_ranks(vector_scores, rows)
        scored = []
        for index, row in enumerate(rows):
            lexical_rank = lexical_ranks.get(index)
            vector_rank = vector_ranks.get(index)
            if lexical_rank is None and vector_rank is None:
                continue
            reciprocal = (1 / (60 + lexical_rank) if lexical_rank else 0.0) + (
                1 / (60 + vector_rank) if vector_rank else 0.0
            )
            rerank = _deterministic_rerank(query_tokens, row[1])
            scored.append((reciprocal + rerank, row, lexical_rank, vector_rank))
        scored.sort(key=lambda item: (-item[0], item[1][1].chunk_id, item[1][0].snapshot_id))
        candidates = scored[: query.candidate_limit]
        hits = tuple(
            _hit(score, row, lexical_rank, vector_rank)
            for score, row, lexical_rank, vector_rank in candidates[: query.top_k]
        )
        return RetrievalResult(
            query_sha256=hashlib.sha256(query.text.encode()).hexdigest(),
            authorized_snapshot_count=len(snapshots),
            candidate_count=len(candidates),
            hits=hits,
        )


def _metadata(values: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in sorted(values.items()):
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", key) or not value or len(value) > 2_000:
            raise ValueError("INDEX_METADATA_INVALID")
        normalized[key] = value
    return normalized


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _bm25(query: tuple[str, ...], documents: tuple[tuple[str, ...], ...]) -> tuple[float, ...]:
    if not documents or not query:
        return tuple(0.0 for _ in documents)
    average_length = sum(len(document) for document in documents) / len(documents)
    document_frequency = Counter(token for token in set(query) for doc in documents if token in doc)
    scores: list[float] = []
    for document in documents:
        counts = Counter(document)
        score = 0.0
        for token in set(query):
            frequency = counts[token]
            if not frequency:
                continue
            inverse = math.log(
                1
                + (len(documents) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            denominator = frequency + 1.2 * (
                1 - 0.75 + 0.75 * len(document) / max(average_length, 1)
            )
            score += inverse * frequency * 2.2 / denominator
        scores.append(score)
    return tuple(scores)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("RETRIEVAL_VECTOR_DIMENSION_INVALID")
    similarity = sum(a * b for a, b in zip(left, right, strict=True))
    return max(0.0, similarity)


def _positive_ranks(
    scores: tuple[float, ...], rows: list[tuple[IndexSnapshot, IndexRecord]]
) -> dict[int, int]:
    ranked = sorted(
        (index for index, score in enumerate(scores) if score > 0),
        key=lambda index: (-scores[index], rows[index][1].chunk_id, rows[index][0].snapshot_id),
    )
    return {index: rank for rank, index in enumerate(ranked, start=1)}


def _deterministic_rerank(query_tokens: tuple[str, ...], record: IndexRecord) -> float:
    query_set = set(query_tokens)
    if not query_set:
        return 0.0
    record_set = set(record.tokens)
    overlap = len(query_set & record_set) / len(query_set)
    exact_phrase = 0.02 if " ".join(query_tokens) in record.text.casefold() else 0.0
    return overlap * 0.05 + exact_phrase


def _hit(
    score: float,
    row: tuple[IndexSnapshot, IndexRecord],
    lexical_rank: int | None,
    vector_rank: int | None,
) -> RetrievalHit:
    snapshot, record = row
    citation = RetrievalCitation(
        artifact_id=record.artifact_id,
        artifact_version=record.artifact_version,
        source_sha256=record.source_sha256,
        source_title=record.source_title,
        source_media_type=record.source_media_type,
        parser_name=record.parser_name,
        parser_version=record.parser_version,
        normalizer_version=record.normalizer_version,
        document_id=record.document_id,
        document_sha256=record.document_sha256,
        chunk_id=record.chunk_id,
        content_sha256=record.content_sha256,
        page_index=record.page_index,
        section_path=record.section_path,
        locator_type=record.locator_type,
        locator=record.locator,
    )
    return RetrievalHit(
        snapshot_id=snapshot.snapshot_id,
        chunk_id=record.chunk_id,
        text=record.text,
        score=score,
        lexical_rank=lexical_rank,
        vector_rank=vector_rank,
        citation=citation,
    )
