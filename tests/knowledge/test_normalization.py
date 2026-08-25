"""S3-06 canonical element and chunk normalization regression tests."""

from __future__ import annotations

from uuid import UUID, uuid4

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.knowledge.fallback import (
    FallbackResult,
    FallbackStage,
    FallbackStatus,
    PageQuality,
    ParserAttempt,
    QualityDecision,
    QualityStatus,
)
from ndt_agents.knowledge.normalization import (
    ElementKind,
    KnowledgeNormalizer,
    NormalizationRequest,
    NormalizationStatus,
)
from ndt_agents.knowledge.parsing import (
    BoundingBox,
    ParsedBlock,
    ParsedDocument,
    ParsedPage,
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


def block(
    order: int,
    block_type: str,
    text: str | None,
    *,
    page: int = 0,
    level: int | None = None,
    asset: str | None = None,
) -> ParsedBlock:
    return ParsedBlock(
        order=order,
        page_index=page,
        block_type=block_type,
        bbox=BoundingBox(coordinates=(10, 20 + order, 900, 100 + order)),
        text=text,
        text_level=level,
        asset_path=asset,
    )


def parsed_document(blocks: tuple[ParsedBlock, ...]) -> ParsedDocument:
    page_indexes = sorted({item.page_index for item in blocks})
    return ParsedDocument(
        scope=scope(),
        artifact_id=uuid4(),
        source_sha256="1" * 64,
        source_media_type="application/pdf",
        parser_name="mineru",
        parser_version="mineru-3.0.0",
        backend="pipeline",
        method="txt",
        markdown="source markdown",
        pages=tuple(
            ParsedPage(page_index=index, width=1000, height=1400) for index in page_indexes
        ),
        blocks=blocks,
        output_sha256={"markdown": "2" * 64},
        physical_tool_calls=1,
    )


def ready(document: ParsedDocument) -> FallbackResult:
    pages = tuple(
        PageQuality(
            page_index=page.page_index,
            present=True,
            drawing=False,
            meaningful_characters=100,
            corrupted_character_ratio=0,
            table_present=True,
            formula_present=True,
            reason_codes=(),
        )
        for page in document.pages
    )
    quality = QualityDecision(
        status=QualityStatus.PASS,
        page_coverage=1,
        table_coverage=1,
        formula_coverage=1,
        failed_pages=(),
        reason_codes=(),
        pages=pages,
    )
    attempt = ParserAttempt(
        sequence=1,
        stage=FallbackStage.PRIMARY,
        status="PARSED",
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        method=document.method,
        document_sha256="3" * 64,
        quality=quality,
    )
    return FallbackResult(
        status=FallbackStatus.READY,
        selected_stage=FallbackStage.PRIMARY,
        document=document,
        final_quality=quality,
        attempts=(attempt,),
        physical_tool_calls=1,
    )


def request(document: ParsedDocument, **metadata: str) -> NormalizationRequest:
    return NormalizationRequest(
        fallback=ready(document),
        artifact_version="source-v1",
        source_title="Bridge inspection standard",
        language="zh-CN",
        metadata=metadata,
    )


def all_blocks() -> tuple[ParsedBlock, ...]:
    return (
        block(0, "title", "桥梁检测标准", level=1),
        block(1, "title", "适用范围", level=2),
        block(2, "text", "1.1 本标准规定裂缝宽度为 1.0 mm。"),
        block(3, "text", "检测结果应保持可追溯。"),
        block(4, "table", "| 项目 | 数值 |\n|---|---|\n| 裂缝 | 1.0 mm |"),
        block(5, "equation", "v = s / t"),
        block(6, "image", "图 1 构件位置", asset="images/figure-1.png"),
        block(7, "list", "- 超声检测\n- 磁粉检测"),
        block(8, "code", "result = measure(signal)"),
        block(9, "header", "项目文档页眉"),
    )


def test_every_block_type_is_mapped_once_with_traceability() -> None:
    source = parsed_document(all_blocks())

    result = KnowledgeNormalizer().normalize(scope(), request(source, source_type="standard"))

    assert result.status is NormalizationStatus.NORMALIZED
    assert result.document is not None
    document = result.document
    assert [element.kind for element in document.elements] == [
        ElementKind.HEADING,
        ElementKind.HEADING,
        ElementKind.CLAUSE,
        ElementKind.PARAGRAPH,
        ElementKind.TABLE,
        ElementKind.FORMULA,
        ElementKind.FIGURE,
        ElementKind.LIST,
        ElementKind.CODE,
        ElementKind.AUXILIARY,
    ]
    assert [
        order for element in document.elements for order in element.source_block_orders
    ] == list(range(10))
    clause = document.elements[2]
    assert clause.clause_identifier == "1.1"
    assert clause.section_path == ("桥梁检测标准", "适用范围")
    assert clause.page_index == 0
    assert clause.bbox.coordinates == (10, 22, 900, 102)
    assert document.physical_calls == 0


def test_markdown_and_simple_html_tables_become_rectangular_rows() -> None:
    markdown = parsed_document((block(0, "table", "| A | B |\n|---|---|\n| 1 | 2 |"),))
    html = parsed_document(
        (
            block(
                0,
                "table",
                "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>",
            ),
        )
    )

    markdown_result = KnowledgeNormalizer().normalize(scope(), request(markdown))
    html_result = KnowledgeNormalizer().normalize(scope(), request(html))

    assert markdown_result.document is not None
    assert html_result.document is not None
    expected = (("A", "B"), ("1", "2"))
    assert markdown_result.document.elements[0].table_rows == expected
    assert html_result.document.elements[0].table_rows == expected


def test_formula_figure_and_chinese_numeric_content_are_preserved() -> None:
    source = parsed_document(all_blocks())

    result = KnowledgeNormalizer().normalize(scope(), request(source))

    assert result.document is not None
    formula = next(item for item in result.document.elements if item.kind is ElementKind.FORMULA)
    figure = next(item for item in result.document.elements if item.kind is ElementKind.FIGURE)
    table = next(item for item in result.document.elements if item.kind is ElementKind.TABLE)
    assert formula.formula == "v = s / t"
    assert figure.asset_path == "images/figure-1.png"
    assert "1.0 mm" in table.content
    assert "裂缝" in table.content


def test_identical_input_is_stable_and_metadata_change_changes_document_hash() -> None:
    source = parsed_document(all_blocks())
    normalizer = KnowledgeNormalizer()

    first = normalizer.normalize(scope(), request(source, region="CN"))
    second = normalizer.normalize(scope(), request(source, region="CN"))
    changed = normalizer.normalize(scope(), request(source, region="EU"))

    assert (
        first.document is not None and second.document is not None and changed.document is not None
    )
    assert first.document == second.document
    assert first.document.document_sha256 == second.document.document_sha256
    assert first.document.document_sha256 != changed.document.document_sha256
    assert first.document.document_id == changed.document.document_id


def test_long_element_chunks_reconstruct_exact_numbers_units_and_text() -> None:
    long_text = ("裂缝宽度 1.25 mm；" * 200) + "END"
    source = parsed_document((block(0, "text", long_text),))

    result = KnowledgeNormalizer().normalize(scope(), request(source))

    assert result.document is not None
    chunks = result.document.chunks
    assert len(chunks) > 1
    assert "".join(chunk.text for chunk in chunks) == long_text
    assert all(len(chunk.text) <= 1_200 for chunk in chunks)
    assert {chunk.element_id for chunk in chunks} == {result.document.elements[0].element_id}


def test_non_ready_and_cross_scope_inputs_fail_closed() -> None:
    source = parsed_document((block(0, "text", "valid source text"),))
    ready_request = request(source)
    manual = ready_request.fallback.model_copy(
        update={
            "status": FallbackStatus.MANUAL_REVIEW,
            "selected_stage": None,
            "document": None,
            "final_quality": None,
            "code": "manual",
            "next_action": "review",
        }
    )

    non_ready = KnowledgeNormalizer().normalize(
        scope(), ready_request.model_copy(update={"fallback": manual})
    )
    denied = KnowledgeNormalizer().normalize(scope(project_id=uuid4()), ready_request)

    assert non_ready.code == "NORMALIZATION_INPUT_NOT_READY"
    assert denied.code == "NORMALIZATION_SCOPE_DENIED"


def test_duplicate_or_non_contiguous_block_order_is_rejected() -> None:
    source = parsed_document(
        (
            block(0, "text", "first paragraph"),
            block(2, "text", "third paragraph"),
        )
    )

    result = KnowledgeNormalizer().normalize(scope(), request(source))

    assert result.status is NormalizationStatus.FAILED
    assert result.code == "NORMALIZATION_BLOCK_ORDER_INVALID"


def test_malformed_table_and_invalid_metadata_are_typed_failures() -> None:
    malformed = parsed_document((block(0, "table", "| A | B |\n| 1 |"),))
    valid = parsed_document((block(0, "text", "normal paragraph"),))

    malformed_result = KnowledgeNormalizer().normalize(scope(), request(malformed))
    metadata_result = KnowledgeNormalizer().normalize(
        scope(), request(valid, **{"Bad Key": "value"})
    )

    assert malformed_result.code == "NORMALIZATION_TABLE_INVALID"
    assert metadata_result.code == "NORMALIZATION_METADATA_INVALID"
