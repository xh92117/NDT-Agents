"""S3-05 INT-OCR deterministic quality and bounded fallback tests."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from uuid import UUID, uuid4

from ndt_agents.contracts.v1 import ArtifactRef, DataClassification, TenantScope
from ndt_agents.knowledge.fallback import (
    FallbackStage,
    FallbackStatus,
    IndependentOcrAdapter,
    IndependentOcrOutput,
    IndependentOcrPage,
    ParserAdapter,
    ParserFallbackPipeline,
    ParserQualityGate,
    QualityExpectation,
    QualityStatus,
)
from ndt_agents.knowledge.intake import IntakeRequest, IntakeStatus, KnowledgeIntakeService
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
from ndt_agents.tools.file_gateway import (
    ControlledFileGateway,
    ExecutableIdentity,
    FileRootPolicy,
)

TENANT = UUID("00000000-0000-4000-8000-000000000101")
PROJECT = UUID("00000000-0000-4000-8000-000000000201")
USER = UUID("00000000-0000-4000-8000-000000000301")


def scope(*, project_id: UUID = PROJECT) -> TenantScope:
    return TenantScope(
        tenant_id=TENANT,
        project_id=project_id,
        user_id=USER,
        role_codes=("knowledge-owner",),
        permission_version="permissions-1",
    )


def _executable(name: str) -> ExecutableIdentity:
    path = Path(sys.executable).resolve()
    return ExecutableIdentity(
        command_id=f"test.{name}",
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def accepted_request(root: Path) -> tuple[ControlledFileGateway, MinerUParseRequest]:
    raw = b"%PDF-1.7\nsource"
    relative = "raw/source.pdf"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    artifact = ArtifactRef(
        artifact_id=uuid4(),
        scope=scope(),
        artifact_version="1",
        uri="artifact://source.pdf",
        media_type="application/pdf",
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        classification=DataClassification.INTERNAL,
        immutable=True,
    )
    gateway = ControlledFileGateway(
        FileRootPolicy(root=root, tenant_id=TENANT, project_id=PROJECT),
        executables={name: _executable(name) for name in ("find", "grep", "cat")},
    )
    intake = KnowledgeIntakeService(gateway).intake(
        scope(), IntakeRequest(artifact=artifact, relative_path=relative)
    )
    assert intake.status is IntakeStatus.ACCEPTED
    return gateway, MinerUParseRequest(
        artifact=artifact,
        intake=intake,
        relative_path=relative,
        run_id="fallback-root",
    )


def document(
    request: MinerUParseRequest,
    texts: dict[int, str],
    *,
    parser_name: str = "mineru",
    method: str = "txt",
    tables: tuple[int, ...] = (),
    formulas: tuple[int, ...] = (),
) -> ParsedDocument:
    pages = tuple(ParsedPage(page_index=index, width=1000, height=1400) for index in sorted(texts))
    blocks: list[ParsedBlock] = []
    for page_index, text in sorted(texts.items()):
        blocks.append(
            ParsedBlock(
                order=len(blocks),
                page_index=page_index,
                block_type="text",
                bbox=BoundingBox(coordinates=(0, 0, 1000, 1000)),
                text=text,
                text_level=0,
            )
        )
        if page_index in tables:
            blocks.append(
                ParsedBlock(
                    order=len(blocks),
                    page_index=page_index,
                    block_type="table",
                    bbox=BoundingBox(coordinates=(0, 0, 1000, 1000)),
                    text="|A|B|",
                )
            )
        if page_index in formulas:
            blocks.append(
                ParsedBlock(
                    order=len(blocks),
                    page_index=page_index,
                    block_type="equation",
                    bbox=BoundingBox(coordinates=(0, 0, 1000, 1000)),
                    text="x^2+y^2",
                )
            )
    parser_literal = parser_name
    backend = "independent-ocr" if parser_name == "independent-ocr" else "pipeline"
    return ParsedDocument.model_validate(
        {
            "scope": scope(),
            "artifact_id": request.artifact.artifact_id,
            "source_sha256": request.artifact.sha256,
            "source_media_type": request.artifact.media_type,
            "parser_name": parser_literal,
            "parser_version": f"{parser_name}-1",
            "backend": backend,
            "method": method,
            "markdown": "\n\n".join(texts.values()),
            "pages": pages,
            "blocks": tuple(blocks),
            "output_sha256": {"output": "1" * 64},
            "physical_tool_calls": 1,
        }
    )


def parsed(value: ParsedDocument) -> ParseResult:
    return ParseResult(status=ParseStatus.PARSED, document=value)


def failed(code: str) -> ParseResult:
    return ParseResult(status=ParseStatus.FAILED, code=code, next_action="review")


class SequenceParser(ParserAdapter):
    def __init__(self, responses: dict[MinerUMethod, ParseResult]) -> None:
        self.responses = responses
        self.calls: list[MinerUParseRequest] = []

    async def parse(self, requested_scope: TenantScope, request: MinerUParseRequest) -> ParseResult:
        assert requested_scope == scope()
        self.calls.append(request)
        return self.responses[request.method]


class OneParser(ParserAdapter):
    def __init__(self, response: ParseResult) -> None:
        self.response = response
        self.calls: list[MinerUParseRequest] = []

    async def parse(self, requested_scope: TenantScope, request: MinerUParseRequest) -> ParseResult:
        assert requested_scope == scope()
        self.calls.append(request)
        return self.response


def expectation(page_count: int = 1, **updates: object) -> QualityExpectation:
    return QualityExpectation(expected_page_count=page_count).model_copy(update=updates)


def good_text(label: str) -> str:
    return (label + " bridge inspection result ") * 8


def test_quality_gate_passes_good_pages_and_excludes_classified_drawings(
    tmp_path: Path,
) -> None:
    _gateway, request = accepted_request(tmp_path)
    doc = document(request, {0: good_text("page"), 1: "x"})

    decision = ParserQualityGate().evaluate(doc, expectation(2, drawing_pages=(1,)))

    assert decision.status is QualityStatus.PASS
    assert decision.failed_pages == ()
    assert decision.pages[1].drawing is True


def test_quality_gate_reports_page_text_corruption_table_and_formula_reasons(
    tmp_path: Path,
) -> None:
    _gateway, request = accepted_request(tmp_path)
    doc = document(request, {0: "\ufffd\ufffd" + "a" * 60})

    decision = ParserQualityGate().evaluate(
        doc,
        expectation(2, expected_table_pages=(0,), expected_formula_pages=(0,)),
    )

    assert decision.status is QualityStatus.FALLBACK_REQUIRED
    assert decision.failed_pages == (0, 1)
    assert {
        "QUALITY_CORRUPTED_TEXT",
        "QUALITY_TABLE_MISSING",
        "QUALITY_FORMULA_MISSING",
        "QUALITY_PAGE_MISSING",
        "QUALITY_PAGE_COVERAGE_LOW",
    } <= set(decision.reason_codes)


def test_primary_quality_pass_stops_without_spending_fallback_calls(tmp_path: Path) -> None:
    _gateway, request = accepted_request(tmp_path)
    primary_doc = document(request, {0: good_text("primary")})
    mineru = SequenceParser(
        {MinerUMethod.TEXT: parsed(primary_doc), MinerUMethod.OCR: failed("unused")}
    )
    independent = OneParser(failed("unused"))

    result = asyncio.run(
        ParserFallbackPipeline(mineru, independent).run(scope(), request, expectation())
    )

    assert result.status is FallbackStatus.READY
    assert result.selected_stage is FallbackStage.PRIMARY
    assert result.physical_tool_calls == 1
    assert len(result.attempts) == 1
    assert len(mineru.calls) == 1
    assert independent.calls == []


def test_mineru_ocr_replaces_only_failed_pages_and_preserves_good_primary_pages(
    tmp_path: Path,
) -> None:
    _gateway, request = accepted_request(tmp_path)
    primary_page = good_text("primary-page-zero")
    ocr_page = good_text("ocr-page-one")
    primary_doc = document(request, {0: primary_page, 1: "short"})
    ocr_doc = document(
        request,
        {0: good_text("ocr-page-zero-should-not-win"), 1: ocr_page},
        method="ocr",
    )
    mineru = SequenceParser(
        {MinerUMethod.TEXT: parsed(primary_doc), MinerUMethod.OCR: parsed(ocr_doc)}
    )
    independent = OneParser(failed("unused"))

    result = asyncio.run(
        ParserFallbackPipeline(mineru, independent).run(scope(), request, expectation(2))
    )

    assert result.status is FallbackStatus.READY
    assert result.selected_stage is FallbackStage.MINERU_OCR
    assert result.document is not None
    merged = {block.page_index: block.text for block in result.document.blocks}
    assert merged[0] == primary_page
    assert merged[1] == ocr_page
    assert result.document.parser_name == "fallback-merge"
    assert result.physical_tool_calls == 2
    assert len(result.attempts) == 2


def test_independent_ocr_is_the_third_and_final_stage(tmp_path: Path) -> None:
    _gateway, request = accepted_request(tmp_path)
    sparse = document(request, {0: "short"})
    independent_doc = document(
        request,
        {0: good_text("independent")},
        parser_name="independent-ocr",
        method="independent-ocr",
    )
    mineru = SequenceParser({MinerUMethod.TEXT: parsed(sparse), MinerUMethod.OCR: parsed(sparse)})
    independent = OneParser(parsed(independent_doc))

    result = asyncio.run(
        ParserFallbackPipeline(mineru, independent).run(scope(), request, expectation())
    )

    assert result.status is FallbackStatus.READY
    assert result.selected_stage is FallbackStage.INDEPENDENT_OCR
    assert result.physical_tool_calls == 3
    assert [attempt.stage for attempt in result.attempts] == list(FallbackStage)
    assert len(mineru.calls) == 2
    assert len(independent.calls) == 1


def test_all_low_quality_or_failed_stages_enter_manual_review_without_retry(
    tmp_path: Path,
) -> None:
    _gateway, request = accepted_request(tmp_path)
    sparse = document(request, {0: "short"})
    mineru = SequenceParser(
        {MinerUMethod.TEXT: parsed(sparse), MinerUMethod.OCR: failed("OCR_TIMEOUT")}
    )
    independent = OneParser(parsed(sparse))

    result = asyncio.run(
        ParserFallbackPipeline(mineru, independent).run(scope(), request, expectation())
    )

    assert result.status is FallbackStatus.MANUAL_REVIEW
    assert result.code == "PARSER_FALLBACK_EXHAUSTED"
    assert result.physical_tool_calls == 3
    assert len(result.attempts) == 3
    assert len({attempt.stage for attempt in result.attempts}) == 3
    assert result.document is None


def test_scope_mismatch_stops_before_any_parser_call(tmp_path: Path) -> None:
    _gateway, request = accepted_request(tmp_path)
    parser = SequenceParser(
        {MinerUMethod.TEXT: failed("unused"), MinerUMethod.OCR: failed("unused")}
    )
    independent = OneParser(failed("unused"))

    result = asyncio.run(
        ParserFallbackPipeline(parser, independent).run(
            scope(project_id=uuid4()), request, expectation()
        )
    )

    assert result.status is FallbackStatus.MANUAL_REVIEW
    assert result.code == "PARSER_SCOPE_DENIED"
    assert result.physical_tool_calls == 0
    assert parser.calls == []
    assert independent.calls == []


class FakeIndependentEngine:
    def __init__(self, *, invalid_order: bool = False, timeout: bool = False) -> None:
        self.invalid_order = invalid_order
        self.timeout = timeout
        self.calls = 0

    async def recognize(
        self,
        requested_scope: TenantScope,
        source_path: str,
        *,
        run_id: str,
        source_sha256: str,
    ) -> IndependentOcrOutput:
        self.calls += 1
        assert requested_scope == scope()
        assert Path(source_path).is_file()
        assert run_id
        assert len(source_sha256) == 64
        if self.timeout:
            raise TimeoutError
        indexes = (1,) if self.invalid_order else (0,)
        return IndependentOcrOutput(
            engine_name="independent-test",
            engine_version="1.0.0",
            pages=tuple(
                IndependentOcrPage(
                    page_index=index,
                    width=1000,
                    height=1400,
                    text=good_text("engine"),
                )
                for index in indexes
            ),
        )


def test_independent_ocr_adapter_binds_source_and_returns_typed_document(tmp_path: Path) -> None:
    gateway, request = accepted_request(tmp_path)
    engine = FakeIndependentEngine()

    result = asyncio.run(IndependentOcrAdapter(gateway, engine).parse(scope(), request))

    assert result.status is ParseStatus.PARSED
    assert result.document is not None
    assert result.document.parser_name == "independent-ocr"
    assert result.document.physical_tool_calls == 1
    assert result.document.source_sha256 == request.artifact.sha256
    assert engine.calls == 1


def test_independent_ocr_timeout_is_typed_and_source_change_is_denied(tmp_path: Path) -> None:
    gateway, request = accepted_request(tmp_path)
    timeout_engine = FakeIndependentEngine(timeout=True)

    timeout_result = asyncio.run(
        IndependentOcrAdapter(gateway, timeout_engine).parse(scope(), request)
    )
    (tmp_path / request.relative_path).write_bytes(b"changed")
    changed_result = asyncio.run(
        IndependentOcrAdapter(gateway, FakeIndependentEngine()).parse(scope(), request)
    )

    assert timeout_result.code == "OCR_OUTPUT_INVALID"
    assert changed_result.code in {"OCR_SOURCE_CHANGED", "FILE_INPUT_TOO_LARGE"}


def test_independent_ocr_malformed_page_order_is_typed(tmp_path: Path) -> None:
    gateway, request = accepted_request(tmp_path)

    result = asyncio.run(
        IndependentOcrAdapter(gateway, FakeIndependentEngine(invalid_order=True)).parse(
            scope(), request
        )
    )

    assert result.status is ParseStatus.FAILED
    assert result.code == "OCR_OUTPUT_INVALID"
