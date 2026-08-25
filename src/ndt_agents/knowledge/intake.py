"""S3-03 immutable source intake, signature inspection, and UTF-8 normalization."""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import ArtifactRef, StrictModel, TenantScope
from ndt_agents.tools.file_gateway import ControlledFileGateway, FileGatewayError

INTAKE_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_BATCH_BYTES = 2 * 1024 * 1024 * 1024
MAX_BATCH_FILES = 50
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 1_000.0
_TEXT_TYPES = frozenset({"text/plain", "text/markdown"})
_EXECUTABLE_SUFFIXES = frozenset(
    {".bat", ".cmd", ".com", ".dll", ".exe", ".jar", ".msi", ".ps1", ".scr", ".sh"}
)
_SUPPORTED_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/bmp",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "text/markdown",
        "text/plain",
    }
)


class IntakeStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECTED = "REJECTED"


class EncodingHint(StrEnum):
    AUTO = "auto"
    UTF8 = "utf-8"
    GB18030 = "gb18030"
    GBK = "gbk"
    UTF16LE = "utf-16le"
    UTF16BE = "utf-16be"


class IntakeRequest(StrictModel):
    schema_version: Literal["1.0.0"] = INTAKE_VERSION
    artifact: ArtifactRef
    relative_path: str = Field(min_length=1, max_length=4096)
    encoding_hint: EncodingHint = EncodingHint.AUTO


class EncodingDecision(StrictModel):
    source_encoding: str = Field(min_length=1, max_length=64)
    normalized_encoding: Literal["utf-8"] = "utf-8"
    confidence: float = Field(ge=0, le=1)
    detection_method: str = Field(min_length=1, max_length=128)
    lossy: Literal[False] = False
    bom_removed: bool = False


class ContainerInspection(StrictModel):
    format: Literal["OOXML"]
    entry_count: int = Field(ge=1, le=MAX_ZIP_ENTRIES)
    compressed_bytes: int = Field(ge=0)
    expanded_bytes: int = Field(ge=0, le=MAX_ZIP_EXPANDED_BYTES)
    maximum_compression_ratio: float = Field(ge=0, le=MAX_ZIP_COMPRESSION_RATIO)


class IntakeRecord(StrictModel):
    schema_version: Literal["1.0.0"] = INTAKE_VERSION
    artifact_id: str = Field(min_length=36, max_length=36)
    relative_path: str = Field(min_length=1, max_length=4096)
    declared_media_type: str = Field(min_length=1, max_length=255)
    detected_media_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0, le=MAX_FILE_BYTES)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    encoding: EncodingDecision | None = None
    container: ContainerInspection | None = None
    source_immutable: Literal[True] = True


class IntakeResult(StrictModel):
    schema_version: Literal["1.0.0"] = INTAKE_VERSION
    status: IntakeStatus
    record: IntakeRecord | None = None
    normalized_text: str | None = Field(default=None, max_length=200_000_000)
    code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.status is IntakeStatus.ACCEPTED:
            if self.record is None or self.code is not None or self.next_action is not None:
                raise ValueError("accepted intake requires only a record")
        elif self.code is None or self.next_action is None:
            raise ValueError("non-accepted intake requires code and next action")
        return self


class _IntakeFailure(RuntimeError):
    def __init__(self, code: str, next_action: str, *, manual: bool = False) -> None:
        self.code = code
        self.next_action = next_action
        self.manual = manual
        super().__init__(code)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_executable(raw: bytes) -> bool:
    signatures = (
        b"MZ",
        b"\x7fELF",
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xce\xfa\xed\xfe",
        b"\xcf\xfa\xed\xfe",
    )
    return any(raw.startswith(signature) for signature in signatures)


def _safe_text(text: str) -> bool:
    if "\x00" in text:
        return False
    controls = sum(1 for char in text if ord(char) < 32 and char not in "\t\r\n\f")
    return controls <= max(1, len(text) // 100)


def _decode_with(raw: bytes, codec: str, label: str, method: str) -> tuple[str, EncodingDecision]:
    try:
        text = raw.decode(codec, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise _IntakeFailure(
            "INTAKE_ENCODING_INVALID",
            "Select the correct encoding or route the immutable source to manual review.",
            manual=True,
        ) from exc
    text = text.removeprefix("\ufeff")
    if not _safe_text(text):
        raise _IntakeFailure(
            "INTAKE_TEXT_INVALID",
            "Review the source as binary or choose a correct text encoding.",
            manual=True,
        )
    return text, EncodingDecision(
        source_encoding=label,
        confidence=1.0,
        detection_method=method,
        bom_removed=raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")),
    )


def _detect_text(raw: bytes, hint: EncodingHint) -> tuple[str, EncodingDecision]:
    if hint is not EncodingHint.AUTO:
        return _decode_with(raw, hint.value, hint.value, "explicit-user-selection")
    bom_options = (
        (b"\xef\xbb\xbf", "utf-8-sig", "utf-8-bom"),
        (b"\xff\xfe", "utf-16", "utf-16le-bom"),
        (b"\xfe\xff", "utf-16", "utf-16be-bom"),
    )
    for prefix, codec, label in bom_options:
        if raw.startswith(prefix):
            return _decode_with(raw, codec, label, "bom")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        text = ""
    if text and _safe_text(text):
        return text, EncodingDecision(
            source_encoding="utf-8",
            confidence=1.0,
            detection_method="strict-utf-8",
        )
    if not raw:
        return "", EncodingDecision(
            source_encoding="utf-8",
            confidence=1.0,
            detection_method="empty-text-default",
        )
    if len(raw) % 2 == 0:
        even_nuls = raw[0::2].count(0) / max(1, len(raw[0::2]))
        odd_nuls = raw[1::2].count(0) / max(1, len(raw[1::2]))
        if max(even_nuls, odd_nuls) >= 0.3:
            codec = "utf-16be" if even_nuls > odd_nuls else "utf-16le"
            text, decision = _decode_with(raw, codec, codec, "utf16-null-pattern")
            return text, decision.model_copy(update={"confidence": 0.75})
    decoded: list[tuple[str, str]] = []
    for codec in ("gb18030", "gbk"):
        try:
            candidate = raw.decode(codec, errors="strict")
        except UnicodeDecodeError:
            continue
        if _safe_text(candidate):
            decoded.append((codec, candidate))
    if decoded:
        label, candidate = decoded[0]
        confidence = 0.78 if len(decoded) == 1 else 0.65
        return candidate, EncodingDecision(
            source_encoding=label,
            confidence=confidence,
            detection_method="legacy-candidate",
        )
    raise _IntakeFailure(
        "INTAKE_ENCODING_UNCERTAIN",
        "Select a supported encoding or route the immutable source to manual review.",
        manual=True,
    )


def _inspect_ooxml(raw: bytes) -> tuple[str, ContainerInspection]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_ZIP_ENTRIES:
                raise _IntakeFailure(
                    "INTAKE_ARCHIVE_ENTRY_LIMIT",
                    "Use an Office container within the configured entry limit.",
                )
            expanded = 0
            compressed = 0
            maximum_ratio = 0.0
            names: set[str] = set()
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name.replace("\\", "/"))
                if (
                    name.startswith(("/", "\\"))
                    or any(part in {"", ".."} for part in path.parts)
                    or any(ord(char) < 32 for char in name)
                    or ":" in name
                    or Path(name).suffix.lower() in _EXECUTABLE_SUFFIXES
                ):
                    raise _IntakeFailure(
                        "INTAKE_ARCHIVE_PATH_DENIED",
                        "Remove unsafe archive entries and create a new immutable Office source.",
                    )
                expanded += entry.file_size
                compressed += entry.compress_size
                ratio = entry.file_size / max(1, entry.compress_size)
                maximum_ratio = max(maximum_ratio, ratio)
                if expanded > MAX_ZIP_EXPANDED_BYTES or ratio > MAX_ZIP_COMPRESSION_RATIO:
                    raise _IntakeFailure(
                        "INTAKE_ARCHIVE_EXPANSION_DENIED",
                        "Reduce the expanded size or compression ratio before intake.",
                    )
                names.add(name)
    except zipfile.BadZipFile as exc:
        raise _IntakeFailure(
            "INTAKE_ARCHIVE_INVALID",
            "Provide a valid immutable Office Open XML source.",
        ) from exc
    if "[Content_Types].xml" not in names:
        raise _IntakeFailure(
            "INTAKE_ARCHIVE_UNSUPPORTED",
            "Only supported Office Open XML containers may enter this pipeline.",
        )
    if any(name.startswith("word/") for name in names):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif any(name.startswith("xl/") for name in names):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif any(name.startswith("ppt/") for name in names):
        media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    else:
        raise _IntakeFailure(
            "INTAKE_ARCHIVE_UNSUPPORTED",
            "The Office Open XML package has no supported document root.",
        )
    return media_type, ContainerInspection(
        format="OOXML",
        entry_count=len(entries),
        compressed_bytes=compressed,
        expanded_bytes=expanded,
        maximum_compression_ratio=maximum_ratio,
    )


def _binary_media_type(raw: bytes, suffix: str) -> tuple[str, ContainerInspection | None] | None:
    if raw.startswith(b"%PDF-"):
        return "application/pdf", None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", None
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", None
    if raw.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff", None
    if raw.startswith(b"BM"):
        return "image/bmp", None
    if raw.startswith(b"PK\x03\x04"):
        return _inspect_ooxml(raw)
    if raw.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        legacy = {
            ".doc": "application/msword",
            ".xls": "application/vnd.ms-excel",
            ".ppt": "application/vnd.ms-powerpoint",
        }
        media_type = legacy.get(suffix)
        if media_type:
            return media_type, None
    return None


class KnowledgeIntakeService:
    """Validate immutable sources without modifying or publishing them."""

    def __init__(self, gateway: ControlledFileGateway) -> None:
        self._gateway = gateway

    def intake(self, scope: TenantScope, request: IntakeRequest) -> IntakeResult:
        artifact = request.artifact
        if artifact.scope != scope:
            return self._failure("INTAKE_SCOPE_DENIED", "Use the exact artifact owner scope.")
        if not artifact.immutable:
            return self._failure(
                "INTAKE_SOURCE_MUTABLE",
                "Freeze an immutable source artifact version before intake.",
            )
        if artifact.size_bytes > MAX_FILE_BYTES:
            return self._failure(
                "INTAKE_FILE_TOO_LARGE",
                "Split the source so one immutable file is within the 500 MB hard limit.",
            )
        try:
            snapshot = self._gateway.read_source_bytes(
                scope,
                request.relative_path,
                hard_limit_bytes=MAX_FILE_BYTES,
            )
            return self._inspect(request, snapshot.content, snapshot.size_bytes, snapshot.sha256)
        except FileGatewayError as exc:
            return self._failure(exc.code, exc.next_action)
        except _IntakeFailure as exc:
            return self._failure(
                exc.code,
                exc.next_action,
                manual=exc.manual,
            )

    def intake_batch(
        self,
        scope: TenantScope,
        requests: Iterable[IntakeRequest],
    ) -> tuple[IntakeResult, ...]:
        items = tuple(requests)
        if not items or len(items) > MAX_BATCH_FILES:
            raise ValueError("knowledge intake batch must contain between 1 and 50 files")
        if sum(item.artifact.size_bytes for item in items) > MAX_BATCH_BYTES:
            raise ValueError("knowledge intake batch exceeds the 2 GB hard limit")
        paths = [item.relative_path for item in items]
        artifacts = [item.artifact.artifact_id for item in items]
        if len(set(paths)) != len(paths) or len(set(artifacts)) != len(artifacts):
            raise ValueError("knowledge intake batch paths and artifact IDs must be unique")
        results = tuple(self.intake(scope, item) for item in items)
        accepted_hashes: set[str] = set()
        normalized: list[IntakeResult] = []
        for result in results:
            if result.record is None or result.status is not IntakeStatus.ACCEPTED:
                normalized.append(result)
                continue
            if result.record.source_sha256 in accepted_hashes:
                normalized.append(
                    self._failure(
                        "INTAKE_DUPLICATE_CONTENT",
                        "Reference the already accepted immutable source instead of importing "
                        "it twice.",
                    )
                )
                continue
            accepted_hashes.add(result.record.source_sha256)
            normalized.append(result)
        return tuple(normalized)

    def _inspect(
        self,
        request: IntakeRequest,
        raw: bytes,
        source_size: int,
        source_hash: str,
    ) -> IntakeResult:
        artifact = request.artifact
        if source_size != artifact.size_bytes or source_hash != artifact.sha256:
            return self._failure(
                "INTAKE_SOURCE_ATTESTATION_FAILED",
                "Register a new immutable artifact version with the exact size and SHA-256.",
            )
        if (
            _is_executable(raw)
            or Path(request.relative_path).suffix.lower() in _EXECUTABLE_SUFFIXES
        ):
            return self._failure(
                "INTAKE_EXECUTABLE_DENIED",
                "Executable content cannot enter the knowledge source pipeline.",
            )
        suffix = Path(request.relative_path).suffix.lower()
        detected = _binary_media_type(raw, suffix)
        text: str | None = None
        encoding: EncodingDecision | None = None
        container: ContainerInspection | None = None
        if detected is None:
            try:
                text, encoding = _detect_text(raw, request.encoding_hint)
            except _IntakeFailure:
                if artifact.media_type in _TEXT_TYPES:
                    raise
                return self._failure(
                    "INTAKE_MEDIA_UNSUPPORTED",
                    "Provide a supported document, image, or text source.",
                )
            media_type = "text/markdown" if suffix in {".md", ".markdown"} else "text/plain"
        else:
            media_type, container = detected
        if media_type not in _SUPPORTED_MEDIA_TYPES:
            return self._failure(
                "INTAKE_MEDIA_UNSUPPORTED",
                "Provide a supported V1 source type.",
            )
        normalized_hash = _sha256(text.encode("utf-8")) if text is not None else None
        record = IntakeRecord(
            artifact_id=str(artifact.artifact_id),
            relative_path=request.relative_path,
            declared_media_type=artifact.media_type,
            detected_media_type=media_type,
            size_bytes=source_size,
            source_sha256=source_hash,
            normalized_sha256=normalized_hash,
            encoding=encoding,
            container=container,
        )
        if artifact.media_type != media_type:
            return IntakeResult(
                status=IntakeStatus.MANUAL_REVIEW,
                record=record,
                normalized_text=text,
                code="INTAKE_MIME_MISMATCH",
                next_action="Review the declared and detected MIME values before parsing.",
            )
        if encoding is not None and encoding.confidence < 0.8:
            return IntakeResult(
                status=IntakeStatus.MANUAL_REVIEW,
                record=record,
                normalized_text=text,
                code="INTAKE_ENCODING_LOW_CONFIDENCE",
                next_action="Confirm the source encoding before parsing.",
            )
        return IntakeResult(status=IntakeStatus.ACCEPTED, record=record, normalized_text=text)

    @staticmethod
    def _failure(code: str, next_action: str, *, manual: bool = False) -> IntakeResult:
        return IntakeResult(
            status=IntakeStatus.MANUAL_REVIEW if manual else IntakeStatus.REJECTED,
            code=code,
            next_action=next_action,
        )
