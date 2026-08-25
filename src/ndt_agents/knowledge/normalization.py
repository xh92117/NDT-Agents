"""S3-06 deterministic canonical document and traceable chunk normalization."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from html.parser import HTMLParser
from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator

from ndt_agents.contracts.v1 import StrictModel, TenantScope
from ndt_agents.knowledge.fallback import (
    FallbackResult,
    FallbackStatus,
    QualityStatus,
)
from ndt_agents.knowledge.parsing import BoundingBox, ParsedBlock, ParsedDocument

NORMALIZER_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_CHUNK_CHARACTERS = 1_200
_CLAUSE = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:[.)]|\s)\s*(.+)$", re.DOTALL)
_METADATA_KEY = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class ElementKind(StrEnum):
    HEADING = "HEADING"
    CLAUSE = "CLAUSE"
    PARAGRAPH = "PARAGRAPH"
    TABLE = "TABLE"
    FORMULA = "FORMULA"
    FIGURE = "FIGURE"
    LIST = "LIST"
    CODE = "CODE"
    AUXILIARY = "AUXILIARY"


class LocatorType(StrEnum):
    PAGE = "PAGE"
    SECTION = "SECTION"
    CLAUSE = "CLAUSE"
    TABLE = "TABLE"
    FIGURE = "FIGURE"


class CanonicalElement(StrictModel):
    element_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    sequence: int = Field(ge=0)
    kind: ElementKind
    page_index: int = Field(ge=0, lt=2_000)
    bbox: BoundingBox
    section_path: tuple[str, ...] = Field(default=(), max_length=10)
    locator_type: LocatorType
    locator: str = Field(min_length=1, max_length=512)
    source_block_orders: tuple[int, ...] = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=10_000_000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    clause_identifier: str | None = Field(default=None, max_length=128)
    table_rows: tuple[tuple[str, ...], ...] = Field(default=(), max_length=100_000)
    formula: str | None = Field(default=None, max_length=2_000_000)
    asset_path: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_kind_payload(self) -> Self:
        if self.kind is ElementKind.CLAUSE and self.clause_identifier is None:
            raise ValueError("clause element requires an identifier")
        if self.kind is ElementKind.TABLE and not self.table_rows:
            raise ValueError("table element requires canonical rows")
        if self.kind is ElementKind.FORMULA and self.formula is None:
            raise ValueError("formula element requires formula text")
        if self.kind is ElementKind.FIGURE and self.asset_path is None:
            raise ValueError("figure element requires a safe asset path")
        return self


class KnowledgeChunk(StrictModel):
    chunk_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    index: int = Field(ge=0)
    element_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    part_index: int = Field(ge=0)
    part_count: int = Field(ge=1)
    page_index: int = Field(ge=0, lt=2_000)
    section_path: tuple[str, ...]
    locator_type: LocatorType
    locator: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=1, max_length=MAX_CHUNK_CHARACTERS)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CanonicalDocument(StrictModel):
    schema_version: Literal["1.0.0"] = NORMALIZER_VERSION
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: TenantScope
    artifact_id: str = Field(min_length=36, max_length=36)
    artifact_version: str = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_media_type: str = Field(min_length=1, max_length=255)
    source_title: str = Field(min_length=1, max_length=1000)
    language: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    parser_name: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    normalizer_version: Literal["1.0.0"] = NORMALIZER_VERSION
    metadata: dict[str, str] = Field(max_length=64)
    source_block_count: int = Field(ge=1)
    elements: tuple[CanonicalElement, ...] = Field(min_length=1, max_length=200_000)
    chunks: tuple[KnowledgeChunk, ...] = Field(min_length=1, max_length=400_000)
    physical_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        orders = [order for element in self.elements for order in element.source_block_orders]
        if sorted(orders) != list(range(self.source_block_count)):
            raise ValueError("canonical elements must cover every source block exactly once")
        element_ids = [element.element_id for element in self.elements]
        if len(set(element_ids)) != len(element_ids):
            raise ValueError("canonical element IDs must be unique")
        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("knowledge chunk IDs must be unique")
        chunks_by_element = {chunk.element_id for chunk in self.chunks}
        if chunks_by_element != set(element_ids):
            raise ValueError("every canonical element must have traceable chunks")
        return self


class NormalizationRequest(StrictModel):
    schema_version: Literal["1.0.0"] = NORMALIZER_VERSION
    fallback: FallbackResult
    artifact_version: str = Field(min_length=1, max_length=64)
    source_title: str = Field(min_length=1, max_length=1000)
    language: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    metadata: dict[str, str] = Field(default_factory=dict, max_length=64)


class NormalizationStatus(StrEnum):
    NORMALIZED = "NORMALIZED"
    FAILED = "FAILED"


class NormalizationResult(StrictModel):
    schema_version: Literal["1.0.0"] = NORMALIZER_VERSION
    status: NormalizationStatus
    document: CanonicalDocument | None = None
    code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.status is NormalizationStatus.NORMALIZED:
            if self.document is None or self.code is not None or self.next_action is not None:
                raise ValueError("normalized result requires only a document")
        elif self.document is not None or self.code is None or self.next_action is None:
            raise ValueError("failed normalization requires code and next action")
        return self


class NormalizationError(RuntimeError):
    def __init__(self, code: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(code)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _table_rows(content: str) -> tuple[tuple[str, ...], ...]:
    stripped = content.strip()
    if stripped.lower().startswith("<table"):
        parser = _TableParser()
        try:
            parser.feed(stripped)
            parser.close()
        except Exception as exc:
            raise NormalizationError(
                "NORMALIZATION_TABLE_INVALID", "Repair the bounded table markup before retrying."
            ) from exc
        rows = parser.rows
    else:
        rows = []
        for line in stripped.splitlines():
            if "|" not in line:
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            rows.append(cells)
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise NormalizationError(
            "NORMALIZATION_TABLE_INVALID",
            "Provide a rectangular Markdown or simple HTML table.",
        )
    return tuple(tuple(cell for cell in row) for row in rows)


def _metadata(values: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in sorted(values.items()):
        if (
            not _METADATA_KEY.fullmatch(key)
            or not value
            or len(value) > 2_000
            or any(ord(char) < 32 and char not in "\t\r\n" for char in value)
        ):
            raise NormalizationError(
                "NORMALIZATION_METADATA_INVALID",
                "Use bounded lowercase metadata keys and non-control text values.",
            )
        normalized[key] = value
    return normalized


def _element_kind(block: ParsedBlock) -> tuple[ElementKind, str | None]:
    if block.block_type == "title" or (block.block_type == "text" and (block.text_level or 0) > 0):
        return ElementKind.HEADING, None
    if block.block_type == "text":
        match = _CLAUSE.match(block.text or "")
        return (ElementKind.CLAUSE, match.group(1)) if match else (ElementKind.PARAGRAPH, None)
    mapping = {
        "table": ElementKind.TABLE,
        "equation": ElementKind.FORMULA,
        "image": ElementKind.FIGURE,
        "chart": ElementKind.FIGURE,
        "list": ElementKind.LIST,
        "code": ElementKind.CODE,
    }
    return mapping.get(block.block_type, ElementKind.AUXILIARY), None


def _locator(
    kind: ElementKind, page: int, clause: str | None, sequence: int
) -> tuple[LocatorType, str]:
    if kind is ElementKind.CLAUSE:
        return LocatorType.CLAUSE, clause or ""
    if kind is ElementKind.TABLE:
        return LocatorType.TABLE, f"page:{page + 1}:table:{sequence + 1}"
    if kind is ElementKind.FIGURE:
        return LocatorType.FIGURE, f"page:{page + 1}:figure:{sequence + 1}"
    if kind is ElementKind.HEADING:
        return LocatorType.SECTION, f"page:{page + 1}:section:{sequence + 1}"
    return LocatorType.PAGE, f"page:{page + 1}"


class KnowledgeNormalizer:
    def normalize(
        self,
        scope: TenantScope,
        request: NormalizationRequest,
    ) -> NormalizationResult:
        fallback = request.fallback
        if (
            fallback.status is not FallbackStatus.READY
            or fallback.document is None
            or fallback.final_quality is None
            or fallback.final_quality.status is not QualityStatus.PASS
        ):
            return self._failure(
                "NORMALIZATION_INPUT_NOT_READY",
                "Complete parser quality validation before normalization.",
            )
        document = fallback.document
        if document.scope != scope:
            return self._failure(
                "NORMALIZATION_SCOPE_DENIED", "Use the exact parsed-document owner scope."
            )
        try:
            metadata = _metadata(request.metadata)
            elements = self._elements(document)
            chunks = self._chunks(document, elements)
            canonical = self._document(request, document, metadata, elements, chunks)
        except (NormalizationError, ValidationError) as exc:
            if isinstance(exc, NormalizationError):
                return self._failure(exc.code, exc.next_action)
            return self._failure(
                "NORMALIZATION_OUTPUT_INVALID",
                "Repair the typed source blocks and rerun deterministic normalization.",
            )
        return NormalizationResult(status=NormalizationStatus.NORMALIZED, document=canonical)

    @staticmethod
    def _elements(document: ParsedDocument) -> tuple[CanonicalElement, ...]:
        blocks = sorted(document.blocks, key=lambda block: block.order)
        if [block.order for block in blocks] != list(range(len(blocks))):
            raise NormalizationError(
                "NORMALIZATION_BLOCK_ORDER_INVALID",
                "Return unique contiguous parsed block orders.",
            )
        headings: list[str] = []
        elements: list[CanonicalElement] = []
        for sequence, block in enumerate(blocks):
            content = block.text or block.asset_path or ""
            if not content:
                raise NormalizationError(
                    "NORMALIZATION_BLOCK_EMPTY",
                    "Provide text or a safe asset path for every parsed block.",
                )
            kind, clause = _element_kind(block)
            if kind is ElementKind.HEADING:
                level = max(1, min(10, block.text_level or 1))
                headings = headings[: level - 1]
                while len(headings) < level - 1:
                    headings.append("[untitled]")
                headings.append(content)
                section_path = tuple(headings)
            else:
                section_path = tuple(headings)
            rows = _table_rows(content) if kind is ElementKind.TABLE else ()
            formula = content if kind is ElementKind.FORMULA else None
            asset = block.asset_path if kind is ElementKind.FIGURE else None
            locator_type, locator = _locator(kind, block.page_index, clause, sequence)
            identity = {
                "normalizer": NORMALIZER_VERSION,
                "source": document.source_sha256,
                "order": block.order,
                "kind": kind.value,
                "page": block.page_index,
                "bbox": block.bbox.coordinates,
                "section": section_path,
                "locator": locator,
                "content": content,
            }
            elements.append(
                CanonicalElement(
                    element_id=_canonical_hash(identity),
                    sequence=sequence,
                    kind=kind,
                    page_index=block.page_index,
                    bbox=block.bbox,
                    section_path=section_path,
                    locator_type=locator_type,
                    locator=locator,
                    source_block_orders=(block.order,),
                    content=content,
                    content_sha256=_hash_text(content),
                    clause_identifier=clause,
                    table_rows=rows,
                    formula=formula,
                    asset_path=asset,
                )
            )
        return tuple(elements)

    @staticmethod
    def _chunks(
        document: ParsedDocument,
        elements: tuple[CanonicalElement, ...],
    ) -> tuple[KnowledgeChunk, ...]:
        chunks: list[KnowledgeChunk] = []
        for element in elements:
            parts = tuple(
                element.content[index : index + MAX_CHUNK_CHARACTERS]
                for index in range(0, len(element.content), MAX_CHUNK_CHARACTERS)
            )
            for part_index, text in enumerate(parts):
                identity = {
                    "normalizer": NORMALIZER_VERSION,
                    "source": document.source_sha256,
                    "element": element.element_id,
                    "part": part_index,
                    "count": len(parts),
                    "text": text,
                }
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=_canonical_hash(identity),
                        index=len(chunks),
                        element_id=element.element_id,
                        part_index=part_index,
                        part_count=len(parts),
                        page_index=element.page_index,
                        section_path=element.section_path,
                        locator_type=element.locator_type,
                        locator=element.locator,
                        text=text,
                        content_sha256=_hash_text(text),
                    )
                )
        return tuple(chunks)

    @staticmethod
    def _document(
        request: NormalizationRequest,
        parsed: ParsedDocument,
        metadata: dict[str, str],
        elements: tuple[CanonicalElement, ...],
        chunks: tuple[KnowledgeChunk, ...],
    ) -> CanonicalDocument:
        identity = {
            "scope": parsed.scope.model_dump(mode="json"),
            "artifact": str(parsed.artifact_id),
            "artifact_version": request.artifact_version,
            "source": parsed.source_sha256,
            "media": parsed.source_media_type,
            "parser": [parsed.parser_name, parsed.parser_version],
            "normalizer": NORMALIZER_VERSION,
            "title": request.source_title,
            "language": request.language,
            "metadata": metadata,
            "elements": [element.model_dump(mode="json") for element in elements],
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
        }
        document_hash = _canonical_hash(identity)
        document_id = _canonical_hash(
            {
                "scope": parsed.scope.model_dump(mode="json"),
                "artifact": str(parsed.artifact_id),
                "artifact_version": request.artifact_version,
                "normalizer": NORMALIZER_VERSION,
            }
        )
        return CanonicalDocument(
            document_id=document_id,
            document_sha256=document_hash,
            scope=parsed.scope,
            artifact_id=str(parsed.artifact_id),
            artifact_version=request.artifact_version,
            source_sha256=parsed.source_sha256,
            source_media_type=parsed.source_media_type,
            source_title=request.source_title,
            language=request.language,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            metadata=metadata,
            source_block_count=len(parsed.blocks),
            elements=elements,
            chunks=chunks,
        )

    @staticmethod
    def _failure(code: str, next_action: str) -> NormalizationResult:
        return NormalizationResult(
            status=NormalizationStatus.FAILED,
            code=code,
            next_action=next_action,
        )
