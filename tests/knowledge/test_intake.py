"""S3-03 INT-BASH, SEC-BASH, and secure intake coverage."""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ndt_agents.contracts.v1 import ArtifactRef, DataClassification, TenantScope
from ndt_agents.knowledge.intake import (
    MAX_BATCH_BYTES,
    MAX_FILE_BYTES,
    EncodingHint,
    IntakeRequest,
    IntakeStatus,
    KnowledgeIntakeService,
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


def service(root: Path) -> KnowledgeIntakeService:
    gateway = ControlledFileGateway(
        FileRootPolicy(root=root, tenant_id=TENANT, project_id=PROJECT),
        executables={name: _executable(name) for name in ("find", "grep", "cat")},
    )
    return KnowledgeIntakeService(gateway)


def request(
    root: Path,
    name: str,
    raw: bytes,
    media_type: str,
    *,
    encoding_hint: EncodingHint = EncodingHint.AUTO,
    immutable: bool = True,
    artifact_scope: TenantScope | None = None,
    artifact_size: int | None = None,
    artifact_hash: str | None = None,
) -> IntakeRequest:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    owner = artifact_scope or scope()
    return IntakeRequest(
        artifact=ArtifactRef(
            artifact_id=uuid4(),
            scope=owner,
            artifact_version="1",
            uri=f"artifact://{name}",
            media_type=media_type,
            size_bytes=len(raw) if artifact_size is None else artifact_size,
            sha256=artifact_hash or hashlib.sha256(raw).hexdigest(),
            classification=DataClassification.INTERNAL,
            immutable=immutable,
        ),
        relative_path=name,
        encoding_hint=encoding_hint,
    )


def test_utf8_chinese_source_is_hash_bound_and_normalized_without_mutation(tmp_path: Path) -> None:
    raw = "桥梁检测\n无损检测".encode()
    item = request(tmp_path, "raw/中文 资料.md", raw, "text/markdown")
    before = (tmp_path / item.relative_path).read_bytes()

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.ACCEPTED
    assert result.normalized_text == "桥梁检测\n无损检测"
    assert result.record is not None
    assert result.record.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.record.normalized_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.record.encoding is not None
    assert result.record.encoding.source_encoding == "utf-8"
    assert result.record.encoding.lossy is False
    assert (tmp_path / item.relative_path).read_bytes() == before


def test_utf8_bom_is_removed_only_from_normalized_text(tmp_path: Path) -> None:
    raw = b"\xef\xbb\xbf" + "检测".encode()
    item = request(tmp_path, "raw/bom.txt", raw, "text/plain")

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.ACCEPTED
    assert result.normalized_text == "检测"
    assert result.record is not None and result.record.encoding is not None
    assert result.record.encoding.bom_removed is True
    assert result.record.source_sha256 != result.record.normalized_sha256


@pytest.mark.parametrize(
    ("hint", "codec", "text"),
    [
        (EncodingHint.GBK, "gbk", "桥梁检测"),
        (EncodingHint.GB18030, "gb18030", "扩展字符𠀀"),
        (EncodingHint.UTF16LE, "utf-16le", "桥梁检测"),
        (EncodingHint.UTF16BE, "utf-16be", "桥梁检测"),
    ],
)
def test_explicit_legacy_encoding_round_trips_without_loss(
    tmp_path: Path,
    hint: EncodingHint,
    codec: str,
    text: str,
) -> None:
    raw = text.encode(codec)
    item = request(tmp_path, f"raw/{codec}.txt", raw, "text/plain", encoding_hint=hint)

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.ACCEPTED
    assert result.normalized_text == text
    assert result.record is not None and result.record.encoding is not None
    assert result.record.encoding.source_encoding == codec
    assert result.record.encoding.lossy is False


def test_legacy_auto_detection_requires_confirmation(tmp_path: Path) -> None:
    raw = "桥梁检测".encode("gbk")
    item = request(tmp_path, "raw/legacy.txt", raw, "text/plain")

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.MANUAL_REVIEW
    assert result.code == "INTAKE_ENCODING_LOW_CONFIDENCE"
    assert result.record is not None


def test_invalid_declared_text_never_uses_replacement_decoding(tmp_path: Path) -> None:
    item = request(tmp_path, "raw/invalid.txt", b"\x81", "text/plain")

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.MANUAL_REVIEW
    assert result.code == "INTAKE_ENCODING_UNCERTAIN"
    assert result.normalized_text is None


@pytest.mark.parametrize(
    ("name", "raw", "media_type"),
    [
        ("source.pdf", b"%PDF-1.7\n%%EOF", "application/pdf"),
        ("image.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        ("image.jpg", b"\xff\xd8\xffcontent", "image/jpeg"),
        ("image.tiff", b"II*\x00content", "image/tiff"),
        ("image.bmp", b"BMcontent", "image/bmp"),
    ],
)
def test_signature_first_binary_mime_detection(
    tmp_path: Path,
    name: str,
    raw: bytes,
    media_type: str,
) -> None:
    item = request(tmp_path, f"raw/{name}", raw, media_type)

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.ACCEPTED
    assert result.record is not None
    assert result.record.detected_media_type == media_type
    assert result.normalized_text is None


def _ooxml(path: Path, root: str, *, unsafe_name: str | None = None) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(f"{root}/document.xml", "<document>检测</document>")
        if unsafe_name:
            archive.writestr(unsafe_name, "unsafe")
    return path.read_bytes()


@pytest.mark.parametrize(
    ("root_name", "suffix", "media_type"),
    [
        ("word", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("xl", "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (
            "ppt",
            "pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ],
)
def test_office_container_is_inspected_without_extraction(
    tmp_path: Path,
    root_name: str,
    suffix: str,
    media_type: str,
) -> None:
    relative = f"raw/source.{suffix}"
    raw = _ooxml(tmp_path / relative, root_name)
    item = request(tmp_path, relative, raw, media_type)

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.ACCEPTED
    assert result.record is not None and result.record.container is not None
    assert result.record.container.entry_count == 2
    assert not any(path.name == "document.xml" for path in tmp_path.rglob("document.xml"))


def test_office_container_traversal_and_executable_entries_are_denied(tmp_path: Path) -> None:
    relative = "raw/unsafe.docx"
    raw = _ooxml(tmp_path / relative, "word", unsafe_name="../payload.exe")
    item = request(
        tmp_path,
        relative,
        raw,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.REJECTED
    assert result.code == "INTAKE_ARCHIVE_PATH_DENIED"


def test_office_container_extreme_compression_ratio_is_denied(tmp_path: Path) -> None:
    relative = "raw/bomb.docx"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "A" * 5_000_000)
    raw = path.read_bytes()
    item = request(
        tmp_path,
        relative,
        raw,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.REJECTED
    assert result.code == "INTAKE_ARCHIVE_EXPANSION_DENIED"


@pytest.mark.parametrize(
    ("suffix", "media_type"),
    [
        ("doc", "application/msword"),
        ("xls", "application/vnd.ms-excel"),
        ("ppt", "application/vnd.ms-powerpoint"),
    ],
)
def test_legacy_office_compound_signature_uses_bounded_suffix_disambiguation(
    tmp_path: Path,
    suffix: str,
    media_type: str,
) -> None:
    raw = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy-office"
    item = request(tmp_path, f"raw/source.{suffix}", raw, media_type)

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.ACCEPTED
    assert result.record is not None
    assert result.record.detected_media_type == media_type


def test_declared_mime_mismatch_requires_review(tmp_path: Path) -> None:
    item = request(tmp_path, "raw/not-a-pdf.pdf", "检测".encode(), "application/pdf")

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.MANUAL_REVIEW
    assert result.code == "INTAKE_MIME_MISMATCH"
    assert result.record is not None
    assert result.record.detected_media_type == "text/plain"


@pytest.mark.parametrize(
    ("name", "raw"),
    [("payload.exe", b"MZpayload"), ("payload", b"\x7fELFpayload")],
)
def test_executable_content_is_denied(tmp_path: Path, name: str, raw: bytes) -> None:
    item = request(tmp_path, f"raw/{name}", raw, "application/pdf")

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.REJECTED
    assert result.code == "INTAKE_EXECUTABLE_DENIED"


def test_scope_mutability_hash_size_and_file_limits_fail_closed(tmp_path: Path) -> None:
    raw = "检测".encode()
    wrong_scope = request(
        tmp_path,
        "raw/wrong-scope.txt",
        raw,
        "text/plain",
        artifact_scope=scope(project_id=uuid4()),
    )
    mutable = request(tmp_path, "raw/mutable.txt", raw, "text/plain", immutable=False)
    wrong_hash = request(tmp_path, "raw/hash.txt", raw, "text/plain", artifact_hash="0" * 64)
    wrong_size = request(tmp_path, "raw/size.txt", raw, "text/plain", artifact_size=len(raw) + 1)
    too_large = request(
        tmp_path,
        "raw/large.txt",
        raw,
        "text/plain",
        artifact_size=MAX_FILE_BYTES + 1,
    )

    intake = service(tmp_path)

    assert intake.intake(scope(), wrong_scope).code == "INTAKE_SCOPE_DENIED"
    assert intake.intake(scope(), mutable).code == "INTAKE_SOURCE_MUTABLE"
    assert intake.intake(scope(), wrong_hash).code == "INTAKE_SOURCE_ATTESTATION_FAILED"
    assert intake.intake(scope(), wrong_size).code == "INTAKE_SOURCE_ATTESTATION_FAILED"
    assert intake.intake(scope(), too_large).code == "INTAKE_FILE_TOO_LARGE"


@pytest.mark.parametrize("relative_path", ["../escape.txt", "C:/escape.txt", "raw/*.txt"])
def test_gateway_path_policy_is_reused_for_intake(tmp_path: Path, relative_path: str) -> None:
    raw = b"safe"
    artifact = ArtifactRef(
        artifact_id=uuid4(),
        scope=scope(),
        artifact_version="1",
        uri="artifact://escape",
        media_type="text/plain",
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        classification=DataClassification.INTERNAL,
        immutable=True,
    )
    item = IntakeRequest(artifact=artifact, relative_path=relative_path)

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.REJECTED
    assert result.code == "FILE_PATH_DENIED"


def test_symlink_source_is_denied_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "raw/target.txt"
    target.parent.mkdir()
    target.write_bytes(b"safe")
    link = tmp_path / "raw/link.txt"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("platform does not allow symlink creation")
    item = request(tmp_path, "raw/link.txt", b"safe", "text/plain")
    link.unlink()
    os.symlink(target, link)

    result = service(tmp_path).intake(scope(), item)

    assert result.status is IntakeStatus.REJECTED
    assert result.code == "FILE_PATH_DENIED"


def test_batch_limits_uniqueness_and_duplicate_content_are_explicit(tmp_path: Path) -> None:
    first = request(tmp_path, "raw/first.txt", b"same", "text/plain")
    second = request(tmp_path, "raw/second.txt", b"same", "text/plain")
    intake = service(tmp_path)

    results = intake.intake_batch(scope(), (first, second))

    assert results[0].status is IntakeStatus.ACCEPTED
    assert results[1].code == "INTAKE_DUPLICATE_CONTENT"
    with pytest.raises(ValueError, match="paths and artifact IDs"):
        intake.intake_batch(scope(), (first, first))
    oversized = first.model_copy(
        update={"artifact": first.artifact.model_copy(update={"size_bytes": MAX_BATCH_BYTES})}
    )
    with pytest.raises(ValueError, match="2 GB"):
        intake.intake_batch(scope(), (oversized, second))
