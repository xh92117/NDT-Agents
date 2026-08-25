"""S3-05 deterministic quality gate and bounded parser fallback pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal, Protocol, Self

from pydantic import Field, ValidationError, model_validator

from ndt_agents.contracts.v1 import StrictModel, TenantScope
from ndt_agents.knowledge.parsing import (
    BoundingBox,
    MinerUMethod,
    MinerUParseRequest,
    ParsedBlock,
    ParsedDocument,
    ParsedPage,
    ParseResult,
    ParseStatus,
)
from ndt_agents.tools.file_gateway import ControlledFileGateway, FileGatewayError

FALLBACK_VERSION: Literal["1.0.0"] = "1.0.0"
MIN_PAGE_COVERAGE = 0.95
MIN_MEANINGFUL_CHARACTERS = 50
MAX_CORRUPTED_CHARACTER_RATIO = 0.01
MIN_EXPECTED_BLOCK_COVERAGE = 0.95


class QualityStatus(StrEnum):
    PASS = "PASS"
    FALLBACK_REQUIRED = "FALLBACK_REQUIRED"


class FallbackStage(StrEnum):
    PRIMARY = "PRIMARY"
    MINERU_OCR = "MINERU_OCR"
    INDEPENDENT_OCR = "INDEPENDENT_OCR"


class FallbackStatus(StrEnum):
    READY = "READY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class QualityExpectation(StrictModel):
    schema_version: Literal["1.0.0"] = FALLBACK_VERSION
    expected_page_count: int = Field(ge=1, le=2_000)
    drawing_pages: tuple[int, ...] = Field(default=(), max_length=2_000)
    expected_table_pages: tuple[int, ...] = Field(default=(), max_length=2_000)
    expected_formula_pages: tuple[int, ...] = Field(default=(), max_length=2_000)
    minimum_meaningful_characters: int = Field(default=MIN_MEANINGFUL_CHARACTERS, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_pages(self) -> Self:
        groups = (self.drawing_pages, self.expected_table_pages, self.expected_formula_pages)
        for values in groups:
            if len(set(values)) != len(values) or any(
                value < 0 or value >= self.expected_page_count for value in values
            ):
                raise ValueError("quality expectation pages must be unique and in range")
        return self


class PageQuality(StrictModel):
    page_index: int = Field(ge=0, lt=2_000)
    present: bool
    drawing: bool
    meaningful_characters: int = Field(ge=0)
    corrupted_character_ratio: float = Field(ge=0, le=1)
    table_present: bool
    formula_present: bool
    reason_codes: tuple[str, ...]


class QualityDecision(StrictModel):
    schema_version: Literal["1.0.0"] = FALLBACK_VERSION
    status: QualityStatus
    page_coverage: float = Field(ge=0, le=1)
    table_coverage: float = Field(ge=0, le=1)
    formula_coverage: float = Field(ge=0, le=1)
    failed_pages: tuple[int, ...]
    reason_codes: tuple[str, ...]
    pages: tuple[PageQuality, ...]


class ParserAttempt(StrictModel):
    sequence: int = Field(ge=1, le=3)
    stage: FallbackStage
    status: Literal["PARSED", "FAILED"]
    parser_name: str | None = Field(default=None, max_length=128)
    parser_version: str | None = Field(default=None, max_length=128)
    method: str | None = Field(default=None, max_length=64)
    document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    quality: QualityDecision | None = None
    error_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if self.status == "PARSED":
            if (
                self.parser_name is None
                or self.parser_version is None
                or self.method is None
                or self.document_sha256 is None
                or self.quality is None
                or self.error_code is not None
            ):
                raise ValueError("parsed attempt requires parser and quality evidence")
        elif self.error_code is None or any(
            value is not None
            for value in (
                self.parser_name,
                self.parser_version,
                self.method,
                self.document_sha256,
                self.quality,
            )
        ):
            raise ValueError("failed attempt requires only an error code")
        return self


class FallbackResult(StrictModel):
    schema_version: Literal["1.0.0"] = FALLBACK_VERSION
    status: FallbackStatus
    selected_stage: FallbackStage | None
    document: ParsedDocument | None
    final_quality: QualityDecision | None
    attempts: tuple[ParserAttempt, ...] = Field(min_length=1, max_length=3)
    physical_tool_calls: int = Field(ge=0, le=3)
    code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        stages = [attempt.stage for attempt in self.attempts]
        if len(set(stages)) != len(stages):
            raise ValueError("fallback stages cannot repeat")
        if self.status is FallbackStatus.READY:
            if (
                self.selected_stage is None
                or self.document is None
                or self.final_quality is None
                or self.final_quality.status is not QualityStatus.PASS
                or self.code is not None
                or self.next_action is not None
            ):
                raise ValueError("ready fallback requires a selected document")
        elif (
            self.selected_stage is not None
            or self.document is not None
            or self.final_quality is not None
            or self.code is None
            or self.next_action is None
        ):
            raise ValueError("manual review requires only attempts and next action")
        return self


class ParserAdapter(Protocol):
    async def parse(self, scope: TenantScope, request: MinerUParseRequest) -> ParseResult: ...


class IndependentOcrPage(StrictModel):
    page_index: int = Field(ge=0, lt=2_000)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=5_000_000)


class IndependentOcrOutput(StrictModel):
    engine_name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    engine_version: str = Field(min_length=1, max_length=128)
    pages: tuple[IndependentOcrPage, ...] = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_page_order(self) -> Self:
        indexes = [page.page_index for page in self.pages]
        if indexes != list(range(len(indexes))):
            raise ValueError("independent OCR pages must be contiguous and zero based")
        return self


class IndependentOcrEngine(Protocol):
    async def recognize(
        self,
        scope: TenantScope,
        source_path: str,
        *,
        run_id: str,
        source_sha256: str,
    ) -> IndependentOcrOutput: ...


class IndependentOcrError(RuntimeError):
    def __init__(self, code: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(code)


class IndependentOcrAdapter:
    """Validate one independently registered OCR engine result."""

    def __init__(self, gateway: ControlledFileGateway, engine: IndependentOcrEngine) -> None:
        self._gateway = gateway
        self._engine = engine

    async def parse(self, scope: TenantScope, request: MinerUParseRequest) -> ParseResult:
        if request.artifact.scope != scope:
            return _parse_failure("OCR_SCOPE_DENIED", "Use the exact artifact owner scope.")
        try:
            snapshot = self._gateway.read_source_bytes(
                scope,
                request.relative_path,
                hard_limit_bytes=request.artifact.size_bytes + 1,
            )
            if (
                snapshot.size_bytes != request.artifact.size_bytes
                or snapshot.sha256 != request.artifact.sha256
            ):
                raise IndependentOcrError(
                    "OCR_SOURCE_CHANGED",
                    "Freeze and intake a new immutable artifact version before OCR.",
                )
            source = self._gateway.application_source_path(scope, request.relative_path)
            output = await self._engine.recognize(
                scope,
                str(source),
                run_id=request.run_id,
                source_sha256=request.artifact.sha256,
            )
            document = _independent_document(scope, request, output)
        except (FileGatewayError, IndependentOcrError) as exc:
            return _parse_failure(exc.code, exc.next_action)
        except (TimeoutError, ValidationError):
            return _parse_failure(
                "OCR_OUTPUT_INVALID",
                "Route the source to manual review with the preserved OCR diagnostics.",
            )
        return ParseResult(status=ParseStatus.PARSED, document=document)


def _independent_document(
    scope: TenantScope,
    request: MinerUParseRequest,
    output: IndependentOcrOutput,
) -> ParsedDocument:
    pages = tuple(
        ParsedPage(page_index=page.page_index, width=page.width, height=page.height)
        for page in output.pages
    )
    blocks = tuple(
        ParsedBlock(
            order=index,
            page_index=page.page_index,
            block_type="text",
            bbox=BoundingBox(coordinates=(0, 0, 1000, 1000)),
            text=page.text,
            text_level=0,
        )
        for index, page in enumerate(output.pages)
    )
    markdown = "\n\n".join(page.text for page in output.pages)
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    return ParsedDocument(
        scope=scope,
        artifact_id=request.artifact.artifact_id,
        source_sha256=request.artifact.sha256,
        source_media_type=request.artifact.media_type,
        parser_name="independent-ocr",
        parser_version=f"{output.engine_name}:{output.engine_version}",
        backend="independent-ocr",
        method="independent-ocr",
        markdown=markdown,
        pages=pages,
        blocks=blocks,
        output_sha256={"independent_ocr": digest},
        physical_tool_calls=1,
    )


class ParserQualityGate:
    def evaluate(
        self,
        document: ParsedDocument,
        expectation: QualityExpectation,
    ) -> QualityDecision:
        pages = {page.page_index: page for page in document.pages}
        blocks_by_page: dict[int, list[ParsedBlock]] = {
            index: [] for index in range(expectation.expected_page_count)
        }
        for block in document.blocks:
            blocks_by_page.setdefault(block.page_index, []).append(block)
        page_quality: list[PageQuality] = []
        failed: set[int] = set()
        all_reasons: set[str] = set()
        drawing_pages = set(expectation.drawing_pages)
        table_pages = set(expectation.expected_table_pages)
        formula_pages = set(expectation.expected_formula_pages)
        for index in range(expectation.expected_page_count):
            blocks = blocks_by_page.get(index, [])
            text = "".join(block.text or "" for block in blocks)
            meaningful = sum(1 for char in text if char.isalnum())
            corrupted = text.count("\ufffd")
            ratio = corrupted / max(1, len(text))
            table_present = any(block.block_type == "table" for block in blocks)
            formula_present = any(block.block_type == "equation" for block in blocks)
            reasons: list[str] = []
            if index not in pages:
                reasons.append("QUALITY_PAGE_MISSING")
            if (
                index not in drawing_pages
                and index in pages
                and meaningful < expectation.minimum_meaningful_characters
            ):
                reasons.append("QUALITY_TEXT_TOO_SPARSE")
            if ratio > MAX_CORRUPTED_CHARACTER_RATIO:
                reasons.append("QUALITY_CORRUPTED_TEXT")
            if index in table_pages and not table_present:
                reasons.append("QUALITY_TABLE_MISSING")
            if index in formula_pages and not formula_present:
                reasons.append("QUALITY_FORMULA_MISSING")
            if reasons:
                failed.add(index)
                all_reasons.update(reasons)
            page_quality.append(
                PageQuality(
                    page_index=index,
                    present=index in pages,
                    drawing=index in drawing_pages,
                    meaningful_characters=meaningful,
                    corrupted_character_ratio=ratio,
                    table_present=table_present,
                    formula_present=formula_present,
                    reason_codes=tuple(sorted(reasons)),
                )
            )
        page_coverage = len(set(pages) & set(range(expectation.expected_page_count))) / (
            expectation.expected_page_count
        )
        table_coverage = _coverage(table_pages, blocks_by_page, "table")
        formula_coverage = _coverage(formula_pages, blocks_by_page, "equation")
        if page_coverage < MIN_PAGE_COVERAGE:
            all_reasons.add("QUALITY_PAGE_COVERAGE_LOW")
        if table_coverage < MIN_EXPECTED_BLOCK_COVERAGE:
            all_reasons.add("QUALITY_TABLE_COVERAGE_LOW")
        if formula_coverage < MIN_EXPECTED_BLOCK_COVERAGE:
            all_reasons.add("QUALITY_FORMULA_COVERAGE_LOW")
        return QualityDecision(
            status=QualityStatus.FALLBACK_REQUIRED if all_reasons else QualityStatus.PASS,
            page_coverage=page_coverage,
            table_coverage=table_coverage,
            formula_coverage=formula_coverage,
            failed_pages=tuple(sorted(failed)),
            reason_codes=tuple(sorted(all_reasons)),
            pages=tuple(page_quality),
        )


def _coverage(
    expected_pages: set[int],
    blocks_by_page: dict[int, list[ParsedBlock]],
    block_type: str,
) -> float:
    if not expected_pages:
        return 1.0
    present = sum(
        1
        for page in expected_pages
        if any(block.block_type == block_type for block in blocks_by_page.get(page, []))
    )
    return present / len(expected_pages)


def _document_sha256(document: ParsedDocument) -> str:
    value = document.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _attempt(
    sequence: int,
    stage: FallbackStage,
    result: ParseResult,
    gate: ParserQualityGate,
    expectation: QualityExpectation,
) -> tuple[ParserAttempt, ParsedDocument | None, QualityDecision | None]:
    if result.status is ParseStatus.FAILED or result.document is None:
        return (
            ParserAttempt(
                sequence=sequence,
                stage=stage,
                status="FAILED",
                error_code=result.code or "PARSER_FAILED",
            ),
            None,
            None,
        )
    quality = gate.evaluate(result.document, expectation)
    return (
        ParserAttempt(
            sequence=sequence,
            stage=stage,
            status="PARSED",
            parser_name=result.document.parser_name,
            parser_version=result.document.parser_version,
            method=result.document.method,
            document_sha256=_document_sha256(result.document),
            quality=quality,
        ),
        result.document,
        quality,
    )


def _merge_documents(
    earlier: ParsedDocument,
    fallback: ParsedDocument,
    failed_pages: Sequence[int],
) -> ParsedDocument:
    if (
        earlier.scope != fallback.scope
        or earlier.artifact_id != fallback.artifact_id
        or earlier.source_sha256 != fallback.source_sha256
        or earlier.source_media_type != fallback.source_media_type
    ):
        raise ValueError("fallback documents must share exact source identity")
    replaced = set(failed_pages)
    pages = {page.page_index: page for page in earlier.pages if page.page_index not in replaced}
    pages.update({page.page_index: page for page in fallback.pages if page.page_index in replaced})
    blocks = [block for block in earlier.blocks if block.page_index not in replaced]
    blocks.extend(block for block in fallback.blocks if block.page_index in replaced)
    blocks.sort(key=lambda block: (block.page_index, block.order))
    normalized_blocks = tuple(
        block.model_copy(update={"order": order}) for order, block in enumerate(blocks)
    )
    markdown = "\n\n".join(block.text or "" for block in normalized_blocks if block.text)
    lineage = {
        "earlier": _document_sha256(earlier),
        "fallback": _document_sha256(fallback),
        "replaced_pages": sorted(replaced),
    }
    lineage_hash = hashlib.sha256(
        json.dumps(lineage, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ParsedDocument(
        scope=earlier.scope,
        artifact_id=earlier.artifact_id,
        source_sha256=earlier.source_sha256,
        source_media_type=earlier.source_media_type,
        parser_name="fallback-merge",
        parser_version=FALLBACK_VERSION,
        backend="mixed",
        method="mixed",
        markdown=markdown,
        pages=tuple(pages[index] for index in sorted(pages)),
        blocks=normalized_blocks,
        output_sha256={"merge_lineage": lineage_hash},
        physical_tool_calls=min(3, earlier.physical_tool_calls + fallback.physical_tool_calls),
    )


class ParserFallbackPipeline:
    """Primary -> MinerU OCR -> independent OCR, each at most once."""

    def __init__(
        self,
        mineru: ParserAdapter,
        independent_ocr: ParserAdapter,
        *,
        gate: ParserQualityGate | None = None,
    ) -> None:
        self._mineru = mineru
        self._independent_ocr = independent_ocr
        self._gate = gate or ParserQualityGate()

    async def run(
        self,
        scope: TenantScope,
        request: MinerUParseRequest,
        expectation: QualityExpectation,
    ) -> FallbackResult:
        if request.artifact.scope != scope:
            return FallbackResult(
                status=FallbackStatus.MANUAL_REVIEW,
                selected_stage=None,
                document=None,
                final_quality=None,
                attempts=(
                    ParserAttempt(
                        sequence=1,
                        stage=FallbackStage.PRIMARY,
                        status="FAILED",
                        error_code="PARSER_SCOPE_DENIED",
                    ),
                ),
                physical_tool_calls=0,
                code="PARSER_SCOPE_DENIED",
                next_action="Use the exact artifact owner scope.",
            )
        attempts: list[ParserAttempt] = []
        calls = 0
        current: ParsedDocument | None = None
        current_quality: QualityDecision | None = None
        primary_request = request.model_copy(
            update={"run_id": _stage_run_id(request.run_id, "primary"), "method": MinerUMethod.TEXT}
        )
        primary_result = await self._mineru.parse(scope, primary_request)
        calls += _physical_calls(primary_result)
        attempt, current, current_quality = _attempt(
            1, FallbackStage.PRIMARY, primary_result, self._gate, expectation
        )
        attempts.append(attempt)
        if current is not None and current_quality is not None:
            if current_quality.status is QualityStatus.PASS:
                return _ready(FallbackStage.PRIMARY, current, current_quality, attempts, calls)

        ocr_request = request.model_copy(
            update={"run_id": _stage_run_id(request.run_id, "ocr"), "method": MinerUMethod.OCR}
        )
        ocr_result = await self._mineru.parse(scope, ocr_request)
        calls += _physical_calls(ocr_result)
        ocr_attempt, ocr_document, ocr_quality = _attempt(
            2, FallbackStage.MINERU_OCR, ocr_result, self._gate, expectation
        )
        attempts.append(ocr_attempt)
        if ocr_document is not None and ocr_quality is not None:
            if current is not None and current_quality is not None and current_quality.failed_pages:
                current = _merge_documents(current, ocr_document, current_quality.failed_pages)
                current_quality = self._gate.evaluate(current, expectation)
            else:
                current, current_quality = ocr_document, ocr_quality
            if current_quality.status is QualityStatus.PASS:
                return _ready(FallbackStage.MINERU_OCR, current, current_quality, attempts, calls)

        independent_request = request.model_copy(
            update={
                "run_id": _stage_run_id(request.run_id, "independent"),
                "method": MinerUMethod.OCR,
            }
        )
        independent_result = await self._independent_ocr.parse(scope, independent_request)
        calls += _physical_calls(independent_result)
        independent_attempt, independent_document, independent_quality = _attempt(
            3,
            FallbackStage.INDEPENDENT_OCR,
            independent_result,
            self._gate,
            expectation,
        )
        attempts.append(independent_attempt)
        if independent_document is not None and independent_quality is not None:
            if current is not None and current_quality is not None and current_quality.failed_pages:
                current = _merge_documents(
                    current, independent_document, current_quality.failed_pages
                )
                current_quality = self._gate.evaluate(current, expectation)
            else:
                current, current_quality = independent_document, independent_quality
            if current_quality.status is QualityStatus.PASS:
                return _ready(
                    FallbackStage.INDEPENDENT_OCR,
                    current,
                    current_quality,
                    attempts,
                    calls,
                )
        return FallbackResult(
            status=FallbackStatus.MANUAL_REVIEW,
            selected_stage=None,
            document=None,
            final_quality=None,
            attempts=tuple(attempts),
            physical_tool_calls=min(3, calls),
            code="PARSER_FALLBACK_EXHAUSTED",
            next_action="Review the preserved source and all bounded parser attempts manually.",
        )


def _physical_calls(result: ParseResult) -> int:
    if result.document is not None:
        return result.document.physical_tool_calls
    return 1


def _stage_run_id(base: str, suffix: str) -> str:
    digest = hashlib.sha256(f"{base}:{suffix}".encode()).hexdigest()[:12]
    return f"{suffix[:16]}-{digest}"


def _ready(
    stage: FallbackStage,
    document: ParsedDocument,
    quality: QualityDecision,
    attempts: Sequence[ParserAttempt],
    calls: int,
) -> FallbackResult:
    return FallbackResult(
        status=FallbackStatus.READY,
        selected_stage=stage,
        document=document,
        final_quality=quality,
        attempts=tuple(attempts),
        physical_tool_calls=min(3, calls),
    )


def _parse_failure(code: str, next_action: str) -> ParseResult:
    return ParseResult(status=ParseStatus.FAILED, code=code, next_action=next_action)
