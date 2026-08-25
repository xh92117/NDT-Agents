"""S3-04 pinned MinerU CLI adapter and strict structured-output validation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, Self, cast
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from ndt_agents.contracts.v1 import ArtifactRef, StrictModel, TenantScope
from ndt_agents.knowledge.intake import IntakeResult, IntakeStatus
from ndt_agents.tools.file_gateway import (
    ControlledFileGateway,
    ExecutableIdentity,
    FileGatewayError,
)

MINERU_ADAPTER_VERSION: Literal["1.0.0"] = "1.0.0"
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_MINERU_MEDIA = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/bmp",
        "image/jpeg",
        "image/png",
        "image/tiff",
    }
)
_LEGACY_OFFICE_MEDIA = frozenset(
    {"application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint"}
)
_TEXT_MEDIA = frozenset({"text/markdown", "text/plain"})
_BLOCK_TYPES = frozenset(
    {
        "aside_text",
        "chart",
        "code",
        "equation",
        "footer",
        "header",
        "image",
        "list",
        "page_footnote",
        "page_number",
        "table",
        "text",
        "title",
    }
)
_MAX_MARKDOWN_BYTES = 50 * 1024 * 1024
_MAX_CONTENT_LIST_BYTES = 100 * 1024 * 1024
_MAX_MIDDLE_BYTES = 200 * 1024 * 1024
_MAX_BLOCKS = 200_000
_MAX_PAGES = 2_000


class MinerUMethod(StrEnum):
    TEXT = "txt"
    OCR = "ocr"


class ParseStatus(StrEnum):
    PARSED = "PARSED"
    FAILED = "FAILED"


class BoundingBox(StrictModel):
    coordinates: tuple[float, float, float, float]

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        x0, y0, x1, y1 = self.coordinates
        if not (0 <= x0 <= x1 <= 1000 and 0 <= y0 <= y1 <= 1000):
            raise ValueError("MinerU coordinates must be ordered in the 0-1000 range")
        return self


class ParsedPage(StrictModel):
    page_index: int = Field(ge=0, lt=_MAX_PAGES)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class ParsedBlock(StrictModel):
    order: int = Field(ge=0, lt=_MAX_BLOCKS)
    page_index: int = Field(ge=0, lt=_MAX_PAGES)
    block_type: str = Field(min_length=1, max_length=64)
    bbox: BoundingBox
    text: str | None = Field(default=None, max_length=2_000_000)
    text_level: int | None = Field(default=None, ge=0, le=10)
    asset_path: str | None = Field(default=None, max_length=2048)


class ParsedDocument(StrictModel):
    schema_version: Literal["1.0.0"] = MINERU_ADAPTER_VERSION
    scope: TenantScope
    artifact_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_media_type: str = Field(min_length=1, max_length=255)
    parser_name: Literal["mineru", "text-reader"]
    parser_version: str = Field(min_length=1, max_length=128)
    backend: Literal["pipeline", "text"]
    method: Literal["txt", "ocr", "passthrough"]
    markdown: str = Field(max_length=50_000_000)
    pages: tuple[ParsedPage, ...] = Field(min_length=1, max_length=_MAX_PAGES)
    blocks: tuple[ParsedBlock, ...] = Field(min_length=1, max_length=_MAX_BLOCKS)
    output_sha256: Mapping[str, str]
    physical_tool_calls: int = Field(ge=0, le=1)


class MinerUParseRequest(StrictModel):
    schema_version: Literal["1.0.0"] = MINERU_ADAPTER_VERSION
    artifact: ArtifactRef
    intake: IntakeResult
    relative_path: str = Field(min_length=1, max_length=4096)
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    method: MinerUMethod = MinerUMethod.TEXT

    @model_validator(mode="after")
    def validate_intake_binding(self) -> Self:
        if self.intake.status is not IntakeStatus.ACCEPTED or self.intake.record is None:
            raise ValueError("MinerU requires an accepted intake result")
        record = self.intake.record
        if (
            record.artifact_id != str(self.artifact.artifact_id)
            or record.relative_path != self.relative_path
            or record.source_sha256 != self.artifact.sha256
            or record.size_bytes != self.artifact.size_bytes
            or record.detected_media_type != self.artifact.media_type
        ):
            raise ValueError("MinerU request does not match the accepted immutable source")
        return self


class ParseResult(StrictModel):
    schema_version: Literal["1.0.0"] = MINERU_ADAPTER_VERSION
    status: ParseStatus
    document: ParsedDocument | None = None
    code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.status is ParseStatus.PARSED:
            if self.document is None or self.code is not None or self.next_action is not None:
                raise ValueError("parsed result requires only a document")
        elif self.document is not None or self.code is None or self.next_action is None:
            raise ValueError("failed parse requires code and next action")
        return self


class ProcessOutcome(StrictModel):
    returncode: int
    stdout: bytes = Field(max_length=1_000_000)
    stderr: bytes = Field(max_length=1_000_000)
    duration_ms: int = Field(ge=0)


class ProcessExecutor(Protocol):
    async def execute(
        self,
        executable: Path,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: int,
    ) -> ProcessOutcome: ...


class AsyncSubprocessExecutor:
    async def execute(
        self,
        executable: Path,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: int,
    ) -> ProcessOutcome:
        started = asyncio.get_running_loop().time()
        process = await asyncio.create_subprocess_exec(
            str(executable),
            *arguments,
            cwd=cwd,
            env=dict(environment),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        elapsed = int((asyncio.get_running_loop().time() - started) * 1000)
        return ProcessOutcome(
            returncode=cast(int, process.returncode),
            stdout=stdout[:1_000_000],
            stderr=stderr[:1_000_000],
            duration_ms=elapsed,
        )


class MinerURawOutput(StrictModel):
    parser_version: str = Field(min_length=1, max_length=128)
    method: MinerUMethod
    markdown: bytes = Field(max_length=_MAX_MARKDOWN_BYTES)
    content_list_json: bytes = Field(max_length=_MAX_CONTENT_LIST_BYTES)
    middle_json: bytes = Field(max_length=_MAX_MIDDLE_BYTES)
    process: ProcessOutcome


class MinerURunner(Protocol):
    async def run(
        self,
        scope: TenantScope,
        source_path: Path,
        *,
        run_id: str,
        method: MinerUMethod,
    ) -> MinerURawOutput: ...


class MinerUAdapterError(RuntimeError):
    def __init__(self, code: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(code)


class MinerUCliRunner:
    """Run one pinned local MinerU pipeline command and collect exact required outputs."""

    def __init__(
        self,
        *,
        executable: ExecutableIdentity,
        parser_version: str,
        root: Path,
        output_root: Path,
        config_path: Path,
        tenant_id: UUID,
        project_id: UUID,
        process: ProcessExecutor | None = None,
        timeout_seconds: int = 900,
    ) -> None:
        resolved_root = root.resolve()
        resolved_output = output_root.resolve()
        resolved_config = config_path.resolve()
        if (
            not resolved_root.is_dir()
            or not resolved_output.is_dir()
            or not resolved_output.is_relative_to(resolved_root)
            or not resolved_config.is_file()
            or not resolved_config.is_relative_to(resolved_root)
            or not 1 <= timeout_seconds <= 900
        ):
            raise ValueError("MinerU roots, config, and timeout must be bounded and authorized")
        self._executable = executable
        self._parser_version = parser_version
        self._root = resolved_root
        self._output_root = resolved_output
        self._config_path = resolved_config
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._process = process or AsyncSubprocessExecutor()
        self._timeout_seconds = timeout_seconds

    async def run(
        self,
        scope: TenantScope,
        source_path: Path,
        *,
        run_id: str,
        method: MinerUMethod,
    ) -> MinerURawOutput:
        if scope.tenant_id != self._tenant_id or scope.project_id != self._project_id:
            raise MinerUAdapterError(
                "MINERU_SCOPE_DENIED", "Use the exact tenant and project parser worker."
            )
        source = source_path.resolve()
        if (
            not _RUN_ID.fullmatch(run_id)
            or not source.is_file()
            or not source.is_relative_to(self._root)
            or source_path.is_symlink()
        ):
            raise MinerUAdapterError(
                "MINERU_PATH_DENIED", "Use one accepted source and application-owned run ID."
            )
        output_dir = self._output_root / run_id
        if output_dir.exists():
            raise MinerUAdapterError("MINERU_RUN_CONFLICT", "Use a new idempotent parse run ID.")
        output_dir.mkdir(mode=0o700)
        arguments = (
            "-p",
            str(source),
            "-o",
            str(output_dir),
            "-m",
            method.value,
            "-b",
            "pipeline",
            "-l",
            "ch",
            "-f",
            "true",
            "-t",
            "true",
        )
        self._executable.verify()
        try:
            outcome = await self._process.execute(
                self._executable.path,
                arguments,
                cwd=self._root,
                environment={
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PATH": str(self._executable.path.parent),
                    "MINERU_TOOLS_CONFIG_JSON": str(self._config_path),
                },
                timeout_seconds=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise MinerUAdapterError(
                "MINERU_TIMEOUT", "Route the source to bounded retry or manual review."
            ) from exc
        if outcome.returncode != 0:
            raise MinerUAdapterError(
                "MINERU_PROCESS_FAILED",
                "Inspect the bounded parser diagnostics and route to fallback or manual review.",
            )
        files = self._collect(output_dir)
        return MinerURawOutput(
            parser_version=self._parser_version,
            method=method,
            markdown=files["markdown"],
            content_list_json=files["content_list"],
            middle_json=files["middle"],
            process=outcome,
        )

    @staticmethod
    def _collect(output_dir: Path) -> dict[str, bytes]:
        matches: dict[str, list[Path]] = {"markdown": [], "content_list": [], "middle": []}
        for path in output_dir.rglob("*"):
            if path.is_symlink() or not path.resolve().is_relative_to(output_dir.resolve()):
                raise MinerUAdapterError(
                    "MINERU_OUTPUT_PATH_DENIED",
                    "Remove output links or escaped paths and rerun the parser.",
                )
            if not path.is_file():
                continue
            if path.name.endswith("_content_list.json"):
                matches["content_list"].append(path)
            elif path.name.endswith("_middle.json"):
                matches["middle"].append(path)
            elif path.suffix.lower() == ".md":
                matches["markdown"].append(path)
        if any(len(paths) != 1 for paths in matches.values()):
            raise MinerUAdapterError(
                "MINERU_OUTPUT_INCOMPLETE",
                "Produce exactly one Markdown, content-list JSON, and middle JSON output.",
            )
        limits = {
            "markdown": _MAX_MARKDOWN_BYTES,
            "content_list": _MAX_CONTENT_LIST_BYTES,
            "middle": _MAX_MIDDLE_BYTES,
        }
        output: dict[str, bytes] = {}
        for key, paths in matches.items():
            path = paths[0]
            if path.stat().st_size > limits[key]:
                raise MinerUAdapterError(
                    "MINERU_OUTPUT_TOO_LARGE", "Reduce or split the source before parsing again."
                )
            output[key] = path.read_bytes()
        return output


def _strict_json(raw: bytes, *, expected: type[list[Any]] | type[dict[str, Any]]) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise MinerUAdapterError(
            "MINERU_OUTPUT_INVALID", "Regenerate strict UTF-8 JSON output."
        ) from exc
    if not isinstance(value, expected):
        raise MinerUAdapterError(
            "MINERU_OUTPUT_INVALID", "Regenerate output with the pinned MinerU schema."
        )
    return value


def _asset_path(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise MinerUAdapterError("MINERU_OUTPUT_INVALID", "Use one bounded relative asset path.")
    path = PurePosixPath(value.replace("\\", "/"))
    if value.startswith(("/", "\\")) or ".." in path.parts or ":" in value:
        raise MinerUAdapterError(
            "MINERU_OUTPUT_PATH_DENIED", "Keep all parser assets inside the run output."
        )
    return value


def _text_value(block: Mapping[str, Any]) -> str | None:
    for key in ("text", "table_body", "equation", "code_body", "content"):
        value = block.get(key)
        if isinstance(value, str):
            if len(value) > 2_000_000:
                raise MinerUAdapterError(
                    "MINERU_OUTPUT_TOO_LARGE", "Split an oversized content block."
                )
            return value
    return None


class MinerUAdapter:
    def __init__(
        self,
        gateway: ControlledFileGateway,
        runner: MinerURunner,
        *,
        text_parser_version: str = "text-reader-1.0.0",
    ) -> None:
        self._gateway = gateway
        self._runner = runner
        self._text_parser_version = text_parser_version

    async def parse(self, scope: TenantScope, request: MinerUParseRequest) -> ParseResult:
        if request.artifact.scope != scope:
            return self._failure("MINERU_SCOPE_DENIED", "Use the exact artifact owner scope.")
        media_type = request.artifact.media_type
        if media_type in _TEXT_MEDIA:
            return self._text_passthrough(scope, request)
        if media_type in _LEGACY_OFFICE_MEDIA:
            return self._failure(
                "MINERU_CONVERSION_REQUIRED",
                "Run one registered legacy Office conversion before MinerU parsing.",
            )
        if media_type not in _MINERU_MEDIA:
            return self._failure(
                "MINERU_MEDIA_UNSUPPORTED", "Use one supported MinerU source type."
            )
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
                raise MinerUAdapterError(
                    "MINERU_SOURCE_CHANGED",
                    "Freeze and intake a new immutable artifact version before parsing.",
                )
            source_path = self._gateway.application_source_path(scope, request.relative_path)
            raw = await self._runner.run(
                scope, source_path, run_id=request.run_id, method=request.method
            )
            document = self._validate_output(scope, request, raw)
        except (FileGatewayError, MinerUAdapterError) as exc:
            return self._failure(exc.code, exc.next_action)
        except ValidationError:
            return self._failure(
                "MINERU_OUTPUT_INVALID",
                "Regenerate output with valid bounded typed fields.",
            )
        return ParseResult(status=ParseStatus.PARSED, document=document)

    def _text_passthrough(self, scope: TenantScope, request: MinerUParseRequest) -> ParseResult:
        text = request.intake.normalized_text
        if text is None:
            return self._failure(
                "MINERU_TEXT_MISSING", "Repeat secure intake with a confirmed text encoding."
            )
        block_type = "title" if request.artifact.media_type == "text/markdown" else "text"
        document = ParsedDocument(
            scope=scope,
            artifact_id=request.artifact.artifact_id,
            source_sha256=request.artifact.sha256,
            source_media_type=request.artifact.media_type,
            parser_name="text-reader",
            parser_version=self._text_parser_version,
            backend="text",
            method="passthrough",
            markdown=text,
            pages=(ParsedPage(page_index=0, width=1, height=1),),
            blocks=(
                ParsedBlock(
                    order=0,
                    page_index=0,
                    block_type=block_type,
                    bbox=BoundingBox(coordinates=(0, 0, 1000, 1000)),
                    text=text,
                    text_level=1 if block_type == "title" else 0,
                ),
            ),
            output_sha256={"markdown": hashlib.sha256(text.encode()).hexdigest()},
            physical_tool_calls=0,
        )
        return ParseResult(status=ParseStatus.PARSED, document=document)

    @staticmethod
    def _validate_output(
        scope: TenantScope,
        request: MinerUParseRequest,
        raw: MinerURawOutput,
    ) -> ParsedDocument:
        try:
            markdown = raw.markdown.decode("utf-8", errors="strict").removeprefix("\ufeff")
        except UnicodeDecodeError as exc:
            raise MinerUAdapterError(
                "MINERU_OUTPUT_INVALID", "Regenerate Markdown as strict UTF-8."
            ) from exc
        if not markdown.strip():
            raise MinerUAdapterError(
                "MINERU_OUTPUT_EMPTY", "Route the source to quality fallback or manual review."
            )
        content = cast(list[Any], _strict_json(raw.content_list_json, expected=list))
        middle = cast(dict[str, Any], _strict_json(raw.middle_json, expected=dict))
        if (
            middle.get("_backend") != "pipeline"
            or middle.get("_version_name") != raw.parser_version
        ):
            raise MinerUAdapterError(
                "MINERU_VERSION_MISMATCH", "Use the pinned pipeline backend and parser version."
            )
        page_values = middle.get("pdf_info")
        if not isinstance(page_values, list) or not 1 <= len(page_values) <= _MAX_PAGES:
            raise MinerUAdapterError(
                "MINERU_OUTPUT_INVALID", "Return one bounded page list from MinerU."
            )
        pages: list[ParsedPage] = []
        page_indexes: set[int] = set()
        for page in page_values:
            if not isinstance(page, dict):
                raise MinerUAdapterError("MINERU_OUTPUT_INVALID", "Return structured page objects.")
            index = page.get("page_idx")
            size = page.get("page_size")
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index in page_indexes
                or not isinstance(size, list)
                or len(size) != 2
                or not all(isinstance(value, (int, float)) and value > 0 for value in size)
            ):
                raise MinerUAdapterError(
                    "MINERU_OUTPUT_INVALID", "Return unique pages with positive page sizes."
                )
            pages.append(ParsedPage(page_index=index, width=size[0], height=size[1]))
            page_indexes.add(index)
        if page_indexes != set(range(len(pages))):
            raise MinerUAdapterError(
                "MINERU_OUTPUT_INVALID", "Return contiguous zero-based page indexes."
            )
        if not 1 <= len(content) <= _MAX_BLOCKS:
            raise MinerUAdapterError(
                "MINERU_OUTPUT_INVALID", "Return one bounded non-empty content list."
            )
        blocks: list[ParsedBlock] = []
        for order, item in enumerate(content):
            if not isinstance(item, dict):
                raise MinerUAdapterError(
                    "MINERU_OUTPUT_INVALID", "Return structured content-list objects."
                )
            block = cast(dict[str, Any], item)
            block_type = block.get("type")
            page_index = block.get("page_idx")
            bbox = block.get("bbox")
            if (
                not isinstance(block_type, str)
                or block_type not in _BLOCK_TYPES
                or not isinstance(page_index, int)
                or isinstance(page_index, bool)
                or page_index not in page_indexes
                or not isinstance(bbox, list)
                or len(bbox) != 4
                or not all(isinstance(value, (int, float)) for value in bbox)
            ):
                raise MinerUAdapterError(
                    "MINERU_OUTPUT_INVALID",
                    "Return traceable blocks with valid type, page, and bbox.",
                )
            blocks.append(
                ParsedBlock(
                    order=order,
                    page_index=page_index,
                    block_type=block_type,
                    bbox=BoundingBox(
                        coordinates=cast(tuple[float, float, float, float], tuple(bbox))
                    ),
                    text=_text_value(block),
                    text_level=block.get("text_level"),
                    asset_path=_asset_path(block.get("img_path")),
                )
            )
        hashes = {
            "markdown": hashlib.sha256(raw.markdown).hexdigest(),
            "content_list": hashlib.sha256(raw.content_list_json).hexdigest(),
            "middle": hashlib.sha256(raw.middle_json).hexdigest(),
        }
        return ParsedDocument(
            scope=scope,
            artifact_id=request.artifact.artifact_id,
            source_sha256=request.artifact.sha256,
            source_media_type=request.artifact.media_type,
            parser_name="mineru",
            parser_version=raw.parser_version,
            backend="pipeline",
            method=raw.method.value,
            markdown=markdown,
            pages=tuple(pages),
            blocks=tuple(blocks),
            output_sha256=hashes,
            physical_tool_calls=1,
        )

    @staticmethod
    def _failure(code: str, next_action: str) -> ParseResult:
        return ParseResult(status=ParseStatus.FAILED, code=code, next_action=next_action)
