"""S3-04 INT-MINERU and parser-boundary tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest

from ndt_agents.contracts.v1 import ArtifactRef, DataClassification, TenantScope
from ndt_agents.knowledge.intake import IntakeRequest, IntakeStatus, KnowledgeIntakeService
from ndt_agents.knowledge.parsing import (
    MinerUAdapter,
    MinerUCliRunner,
    MinerUMethod,
    MinerUParseRequest,
    ParseStatus,
    ProcessExecutor,
    ProcessOutcome,
)
from ndt_agents.tools.file_gateway import (
    ControlledFileGateway,
    ExecutableIdentity,
    FileRootPolicy,
)

TENANT = UUID("00000000-0000-4000-8000-000000000101")
PROJECT = UUID("00000000-0000-4000-8000-000000000201")
USER = UUID("00000000-0000-4000-8000-000000000301")
PARSER_VERSION = "mineru-test-3.0.0"
FakeMode = Literal[
    "valid",
    "failure",
    "timeout",
    "missing",
    "duplicate-json",
    "wrong-version",
    "bad-page",
    "invalid-bbox",
    "escaped-asset",
]


def scope(*, project_id: UUID = PROJECT) -> TenantScope:
    return TenantScope(
        tenant_id=TENANT,
        project_id=project_id,
        user_id=USER,
        role_codes=("knowledge-owner",),
        permission_version="permissions-1",
    )


def executable(name: str) -> ExecutableIdentity:
    path = Path(sys.executable).resolve()
    return ExecutableIdentity(
        command_id=f"test.{name}",
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def gateway(root: Path) -> ControlledFileGateway:
    return ControlledFileGateway(
        FileRootPolicy(root=root, tenant_id=TENANT, project_id=PROJECT),
        executables={name: executable(name) for name in ("find", "grep", "cat")},
    )


def accepted_request(
    root: Path,
    *,
    name: str = "raw/source.pdf",
    raw: bytes = b"%PDF-1.7\nsource",
    media_type: str = "application/pdf",
    owner: TenantScope | None = None,
) -> tuple[ControlledFileGateway, MinerUParseRequest]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    artifact = ArtifactRef(
        artifact_id=uuid4(),
        scope=owner or scope(),
        artifact_version="1",
        uri=f"artifact://{name}",
        media_type=media_type,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        classification=DataClassification.INTERNAL,
        immutable=True,
    )
    file_gateway = gateway(root)
    intake = KnowledgeIntakeService(file_gateway).intake(
        artifact.scope,
        IntakeRequest(artifact=artifact, relative_path=name),
    )
    assert intake.status is IntakeStatus.ACCEPTED
    return file_gateway, MinerUParseRequest(
        artifact=artifact,
        intake=intake,
        relative_path=name,
        run_id="parse-run-1",
    )


class FakeProcess(ProcessExecutor):
    def __init__(
        self,
        *,
        mode: FakeMode = "valid",
    ) -> None:
        self.mode = mode
        self.calls = 0
        self.arguments: tuple[str, ...] = ()
        self.environment: Mapping[str, str] = {}

    async def execute(
        self,
        executable_path: Path,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: int,
    ) -> ProcessOutcome:
        self.calls += 1
        self.arguments = tuple(arguments)
        self.environment = dict(environment)
        assert executable_path == Path(sys.executable).resolve()
        assert cwd.is_dir()
        assert timeout_seconds == 900
        assert "MINERU_TOOLS_CONFIG_JSON" in environment
        if self.mode == "timeout":
            raise TimeoutError
        if self.mode == "failure":
            return ProcessOutcome(
                returncode=2, stdout=b"", stderr=b"bounded failure", duration_ms=1
            )
        output = Path(arguments[arguments.index("-o") + 1]) / "source" / "pipeline"
        output.mkdir(parents=True)
        if self.mode == "missing":
            (output / "source.md").write_text("# Result", encoding="utf-8")
            return ProcessOutcome(returncode=0, stdout=b"", stderr=b"", duration_ms=1)
        content: list[dict[str, object]] = [
            {
                "type": "title",
                "text": "Bridge inspection",
                "text_level": 1,
                "bbox": [10, 20, 900, 100],
                "page_idx": 0,
            },
            {
                "type": "table",
                "table_body": "| Item | Value |\n|---|---|\n| Crack | 1 mm |",
                "bbox": [20, 120, 950, 700],
                "page_idx": 0,
            },
        ]
        if self.mode == "invalid-bbox":
            content[0]["bbox"] = [10, 20, 1100, 100]
        if self.mode == "escaped-asset":
            content.append(
                {
                    "type": "image",
                    "img_path": "../escape.png",
                    "bbox": [20, 710, 500, 990],
                    "page_idx": 0,
                }
            )
        middle = {
            "_backend": "pipeline",
            "_version_name": "wrong" if self.mode == "wrong-version" else PARSER_VERSION,
            "pdf_info": [
                {"page_idx": 1 if self.mode == "bad-page" else 0, "page_size": [1000, 1400]}
            ],
        }
        (output / "source.md").write_text("# Bridge inspection\n\nResult", encoding="utf-8")
        if self.mode == "duplicate-json":
            (output / "source_content_list.json").write_text(
                '[{"type":"text","type":"title","text":"x","bbox":[0,0,1,1],"page_idx":0}]',
                encoding="utf-8",
            )
        else:
            (output / "source_content_list.json").write_text(json.dumps(content), encoding="utf-8")
        (output / "source_middle.json").write_text(json.dumps(middle), encoding="utf-8")
        return ProcessOutcome(returncode=0, stdout=b"ok", stderr=b"", duration_ms=5)


def adapter(
    root: Path,
    file_gateway: ControlledFileGateway,
    process: FakeProcess,
) -> MinerUAdapter:
    output_root = root / "working/mineru"
    output_root.mkdir(parents=True, exist_ok=True)
    config = root / "working/mineru.json"
    config.write_text("{}", encoding="utf-8")
    runner = MinerUCliRunner(
        executable=executable("mineru"),
        parser_version=PARSER_VERSION,
        root=root,
        output_root=output_root,
        config_path=config,
        tenant_id=TENANT,
        project_id=PROJECT,
        process=process,
    )
    return MinerUAdapter(file_gateway, runner)


def test_pinned_cli_arguments_and_structured_outputs_are_traceable(tmp_path: Path) -> None:
    file_gateway, parse_request = accepted_request(tmp_path)
    process = FakeProcess()

    result = asyncio.run(adapter(tmp_path, file_gateway, process).parse(scope(), parse_request))

    assert result.status is ParseStatus.PARSED
    assert result.document is not None
    assert result.document.parser_name == "mineru"
    assert result.document.parser_version == PARSER_VERSION
    assert result.document.backend == "pipeline"
    assert result.document.method == "txt"
    assert result.document.physical_tool_calls == 1
    assert len(result.document.pages) == 1
    assert [block.block_type for block in result.document.blocks] == ["title", "table"]
    assert all(block.page_index == 0 for block in result.document.blocks)
    assert set(result.document.output_sha256) == {"markdown", "content_list", "middle"}
    assert process.arguments[0:2] == ("-p", str((tmp_path / "raw/source.pdf").resolve()))
    assert process.arguments[4:] == (
        "-m",
        "txt",
        "-b",
        "pipeline",
        "-l",
        "ch",
        "-f",
        "true",
        "-t",
        "true",
    )
    assert "--api-url" not in process.arguments
    assert "--url" not in process.arguments


def test_ocr_method_changes_only_the_pinned_method_argument(tmp_path: Path) -> None:
    file_gateway, parse_request = accepted_request(tmp_path)
    parse_request = parse_request.model_copy(update={"method": MinerUMethod.OCR})
    process = FakeProcess()

    result = asyncio.run(adapter(tmp_path, file_gateway, process).parse(scope(), parse_request))

    assert result.status is ParseStatus.PARSED
    assert result.document is not None and result.document.method == "ocr"
    assert process.arguments[process.arguments.index("-m") + 1] == "ocr"


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("failure", "MINERU_PROCESS_FAILED"),
        ("timeout", "MINERU_TIMEOUT"),
        ("missing", "MINERU_OUTPUT_INCOMPLETE"),
        ("duplicate-json", "MINERU_OUTPUT_INVALID"),
        ("wrong-version", "MINERU_VERSION_MISMATCH"),
        ("bad-page", "MINERU_OUTPUT_INVALID"),
        ("invalid-bbox", "MINERU_OUTPUT_INVALID"),
        ("escaped-asset", "MINERU_OUTPUT_PATH_DENIED"),
    ],
)
def test_process_and_output_failures_are_typed(
    tmp_path: Path,
    mode: FakeMode,
    code: str,
) -> None:
    file_gateway, parse_request = accepted_request(tmp_path)
    process = FakeProcess(mode=mode)

    result = asyncio.run(adapter(tmp_path, file_gateway, process).parse(scope(), parse_request))

    assert result.status is ParseStatus.FAILED
    assert result.code == code
    assert result.document is None


def test_text_and_markdown_passthrough_use_zero_physical_calls(tmp_path: Path) -> None:
    file_gateway, parse_request = accepted_request(
        tmp_path,
        name="raw/source.md",
        raw="桥梁检测".encode(),
        media_type="text/markdown",
    )
    process = FakeProcess()

    result = asyncio.run(adapter(tmp_path, file_gateway, process).parse(scope(), parse_request))

    assert result.status is ParseStatus.PARSED
    assert result.document is not None
    assert result.document.parser_name == "text-reader"
    assert result.document.physical_tool_calls == 0
    assert result.document.markdown == "桥梁检测"
    assert process.calls == 0


def test_legacy_office_requires_registered_conversion(tmp_path: Path) -> None:
    file_gateway, parse_request = accepted_request(
        tmp_path,
        name="raw/source.doc",
        raw=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy",
        media_type="application/msword",
    )
    process = FakeProcess()

    result = asyncio.run(adapter(tmp_path, file_gateway, process).parse(scope(), parse_request))

    assert result.status is ParseStatus.FAILED
    assert result.code == "MINERU_CONVERSION_REQUIRED"
    assert process.calls == 0


def test_scope_and_source_path_tampering_fail_before_process(tmp_path: Path) -> None:
    file_gateway, parse_request = accepted_request(tmp_path)
    process = FakeProcess()
    parser = adapter(tmp_path, file_gateway, process)

    wrong_scope = asyncio.run(parser.parse(scope(project_id=uuid4()), parse_request))
    (tmp_path / parse_request.relative_path).write_bytes(b"changed")
    changed = asyncio.run(
        parser.parse(scope(), parse_request.model_copy(update={"run_id": "run-2"}))
    )

    assert wrong_scope.code == "MINERU_SCOPE_DENIED"
    assert changed.code == "MINERU_SOURCE_CHANGED"
    assert process.calls == 0


def test_request_contract_rejects_intake_and_artifact_mismatch(tmp_path: Path) -> None:
    _file_gateway, parse_request = accepted_request(tmp_path)
    altered_artifact = parse_request.artifact.model_copy(update={"sha256": "0" * 64})

    with pytest.raises(ValueError, match="does not match"):
        MinerUParseRequest(
            artifact=altered_artifact,
            intake=parse_request.intake,
            relative_path=parse_request.relative_path,
            run_id="mismatch",
        )
