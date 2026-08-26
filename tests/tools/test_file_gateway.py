"""S3-02 controlled Bash file gateway integration and security tests."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ndt_agents.contracts.v1 import TenantScope, ToolStatus
from ndt_agents.observability import (
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.tools import (
    ControlledFileGateway,
    ExecutableIdentity,
    ExecutionTemplate,
    FileRootPolicy,
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolDataDestination,
    ToolDataScope,
    ToolInvocationContext,
    ToolKind,
    ToolRecoveryPolicy,
    ToolRegistry,
    ToolRegistryError,
    ToolTransport,
)

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("FILE_USER",),
    permission_version="permissions-1",
)
OTHER_SCOPE = SCOPE.model_copy(update={"project_id": UUID("00000000-0000-4000-8000-000000000999")})
TASK_ID = UUID("00000000-0000-4000-8000-000000000201")
RUN_ID = UUID("00000000-0000-4000-8000-000000000202")
PERMISSIONS = frozenset(
    {"file.list", "file.search", "file.read", "file.write", "file.edit", "file.execute"}
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class Runtime:
    def __init__(
        self,
        root: Path,
        *,
        scope: TenantScope = SCOPE,
        max_read_bytes: int = 1_000_000,
        max_output_bytes: int = 200_000,
        executables: dict[str, ExecutableIdentity] | None = None,
        templates: tuple[ExecutionTemplate, ...] = (),
    ) -> None:
        self.root = root
        self.gateway = ControlledFileGateway(
            FileRootPolicy(
                root=root,
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                max_read_bytes=max_read_bytes,
                max_output_bytes=max_output_bytes,
            ),
            executables=executables,
            execution_templates=templates,
            clock=lambda: datetime(2026, 8, 24, 7, 0, tzinfo=UTC),
        )
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="file-gateway-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.repository = InMemoryAuditRepository()
        self.registry = ToolRegistry(
            self.gateway.definitions,
            self.gateway.adapters,
            audit=AuditService(self.repository, self.traces),
            clock=lambda: datetime(2026, 8, 24, 7, 0, tzinfo=UTC),
        )

    def context(
        self,
        *,
        scope: TenantScope = SCOPE,
        permissions: frozenset[str] = PERMISSIONS,
    ) -> ToolInvocationContext:
        return ToolInvocationContext(
            task_id=TASK_ID,
            run_id=RUN_ID,
            scope=scope,
            request_id="file-request-1",
            policy_version="file-policy-1",
            expected_registry_version=self.registry.version,
            allowed_tools=frozenset(item.key for item in self.gateway.definitions),
            granted_permissions=permissions,
            allowed_data_destinations=frozenset({ToolDataDestination.LOCAL}),
            allow_network=False,
        )

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: ToolInvocationContext | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        with self.traces.start_span("file.invoke"):
            return await self.registry.invoke(
                name=name,
                version="1.0.0",
                arguments=arguments,
                context=context or self.context(),
                budget=BudgetGuard(default_budget_policy("P1")),
                observation_sha256=sha256(f"{name}:{arguments}".encode()),
                idempotency_key=idempotency_key,
            )

    def close(self) -> None:
        self.traces.shutdown()


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[Runtime]:
    active = Runtime(tmp_path)
    yield active
    active.close()


def test_definitions_are_fixed_scope_bound_and_network_free(runtime: Runtime) -> None:
    definitions = {item.name: item for item in runtime.gateway.definitions}
    assert set(definitions) == {
        "file.list",
        "file.search",
        "file.read",
        "file.write",
        "file.edit",
        "file.rollback",
        "file.execute",
    }
    assert all(item.network is NetworkPolicy.NONE for item in definitions.values())
    assert all(item.kind is ToolKind.BASH for item in definitions.values())
    assert all(item.transport is ToolTransport.BASH for item in definitions.values())
    assert all(item.data_scope is ToolDataScope.TASK for item in definitions.values())
    assert all(item.data_destination is ToolDataDestination.LOCAL for item in definitions.values())
    assert all(
        item.require_tenant_scope and item.require_project_scope for item in definitions.values()
    )
    assert all(item.test_owner == "file-tool-runtime" for item in definitions.values())
    assert definitions["file.list"].max_concurrency == 3
    assert definitions["file.list"].recovery_policy is ToolRecoveryPolicy.NO_RETRY
    assert definitions["file.write"].side_effect is SideEffectClass.REVERSIBLE
    assert definitions["file.write"].idempotency is IdempotencyPolicy.REQUIRED
    assert definitions["file.write"].recovery_policy is ToolRecoveryPolicy.RECONCILE


def test_list_preserves_chinese_spaces_brackets_and_leading_dash(runtime: Runtime) -> None:
    names = ("中文 文件.txt", "[point].txt", "-leading.txt")
    for name in names:
        (runtime.root / name).write_text("value", encoding="utf-8")
    result = asyncio.run(runtime.invoke("file.list", {"path": "."}))
    assert result.status is ToolStatus.SUCCESS
    assert set(result.output["items"]) == set(names)
    assert result.output["command_id"] == "bash.find"
    assert len(result.output["executable_sha256"]) == 64


def test_nul_delimited_list_denies_control_character_filename(runtime: Runtime) -> None:
    path = runtime.root / "bad\nname.txt"
    try:
        path.write_text("value", encoding="utf-8")
    except OSError:
        pytest.skip("control-character filenames are unavailable on this file system")
    result = asyncio.run(runtime.invoke("file.list", {"path": "."}))
    assert result.status is ToolStatus.DENIED
    assert result.error_code == "FILE_PATH_DENIED"


def test_fixed_string_search_returns_chinese_lines_and_no_match(runtime: Runtime) -> None:
    (runtime.root / "数据.txt").write_text("第一行\n裂缝位置\n最后一行\n", encoding="utf-8")
    found = asyncio.run(runtime.invoke("file.search", {"path": "数据.txt", "pattern": "裂缝"}))
    missing = asyncio.run(runtime.invoke("file.search", {"path": "数据.txt", "pattern": "不存在"}))
    assert found.output["matches"] == [{"line": 2, "text": "裂缝位置"}]
    assert missing.status is ToolStatus.SUCCESS and missing.output["matches"] == []


@pytest.mark.parametrize(
    ("raw", "requested", "label", "text"),
    [
        ("中文".encode(), "auto", "utf-8", "中文"),
        (b"\xef\xbb\xbf" + "中文".encode(), "auto", "utf-8-bom", "中文"),
        ("中文".encode("gbk"), "auto", "gbk", "中文"),
        ("中文".encode("gb18030"), "gb18030", "gb18030", "中文"),
        (b"\xff\xfe" + "中文".encode("utf-16le"), "auto", "utf-16le-bom", "中文"),
        (b"\xfe\xff" + "中文".encode("utf-16be"), "auto", "utf-16be-bom", "中文"),
    ],
)
def test_read_detects_and_normalizes_supported_encodings(
    runtime: Runtime,
    raw: bytes,
    requested: str,
    label: str,
    text: str,
) -> None:
    (runtime.root / "encoded.txt").write_bytes(raw)
    result = asyncio.run(
        runtime.invoke("file.read", {"path": "encoded.txt", "encoding": requested})
    )
    assert result.status is ToolStatus.SUCCESS
    assert result.output["content"] == text
    assert result.output["source_encoding"] == label
    assert result.output["normalized_encoding"] == "utf-8"
    assert result.output["source_sha256"] == sha256(raw)


def test_invalid_encoding_is_denied_without_lossy_output(runtime: Runtime) -> None:
    (runtime.root / "invalid.txt").write_bytes(b"\x81\x30\x81")
    result = asyncio.run(runtime.invoke("file.read", {"path": "invalid.txt"}))
    assert result.status is ToolStatus.DENIED
    assert result.error_code == "FILE_ENCODING_UNCERTAIN"
    assert result.stdout == "" and "replacement" not in str(result.output)


def test_safe_write_edit_and_rollback_round_trip(runtime: Runtime) -> None:
    written = asyncio.run(
        runtime.invoke(
            "file.write",
            {"path": "working.txt", "content": "one\ntwo\n"},
            idempotency_key="write-1",
        )
    )
    assert written.status is ToolStatus.SUCCESS
    first_hash = written.output["output_sha256"]
    edited = asyncio.run(
        runtime.invoke(
            "file.edit",
            {
                "path": "working.txt",
                "expected_sha256": first_hash,
                "start_line": 2,
                "end_line": 2,
                "replacement": "二",
            },
            idempotency_key="edit-1",
        )
    )
    assert (runtime.root / "working.txt").read_text(encoding="utf-8") == "one\n二\n"
    rolled_back = asyncio.run(
        runtime.invoke(
            "file.rollback",
            {
                "path": "working.txt",
                "expected_sha256": edited.output["output_sha256"],
                "version_id": edited.output["version_id"],
            },
            idempotency_key="rollback-1",
        )
    )
    assert rolled_back.status is ToolStatus.SUCCESS
    assert (runtime.root / "working.txt").read_bytes() == b"one\ntwo\n"


def test_edit_preserves_crlf_line_endings(runtime: Runtime) -> None:
    path = runtime.root / "windows.txt"
    path.write_bytes(b"one\r\ntwo\r\n")
    result = asyncio.run(
        runtime.invoke(
            "file.edit",
            {
                "path": "windows.txt",
                "expected_sha256": sha256(path.read_bytes()),
                "start_line": 2,
                "end_line": 2,
                "replacement": "changed",
            },
            idempotency_key="edit-crlf-1",
        )
    )
    assert result.status is ToolStatus.SUCCESS
    assert path.read_bytes() == b"one\r\nchanged\r\n"


def test_safe_write_denies_overwrite_and_internal_version_access(runtime: Runtime) -> None:
    (runtime.root / "existing.txt").write_text("old", encoding="utf-8")
    overwrite = asyncio.run(
        runtime.invoke(
            "file.write",
            {"path": "existing.txt", "content": "new"},
            idempotency_key="overwrite-1",
        )
    )
    internal = asyncio.run(runtime.invoke("file.list", {"path": ".ndt-versions"}))
    assert overwrite.error_code == "FILE_OVERWRITE_DENIED"
    assert overwrite.output["next_action"]
    assert internal.error_code == "FILE_PATH_DENIED"
    assert (runtime.root / "existing.txt").read_text(encoding="utf-8") == "old"


@pytest.mark.parametrize(
    "path",
    ["../escape.txt", "bad\nname.txt", "*.txt", "name;touch.txt", "name|pipe.txt"],
)
def test_malicious_paths_are_denied(runtime: Runtime, path: str) -> None:
    result = asyncio.run(runtime.invoke("file.read", {"path": path}))
    assert result.status is ToolStatus.DENIED
    assert result.error_code == "FILE_PATH_DENIED"


def test_absolute_and_cross_scope_paths_are_denied(runtime: Runtime) -> None:
    (runtime.root / "safe.txt").write_text("safe", encoding="utf-8")
    absolute = asyncio.run(
        runtime.invoke("file.read", {"path": str((runtime.root / "safe.txt").resolve())})
    )
    cross_scope = asyncio.run(
        runtime.invoke(
            "file.read",
            {"path": "safe.txt"},
            context=runtime.context(scope=OTHER_SCOPE),
        )
    )
    assert absolute.error_code == "FILE_PATH_DENIED"
    assert cross_scope.error_code == "FILE_SCOPE_DENIED"


def test_immutable_zones_and_version_conflicts_block_mutation(runtime: Runtime) -> None:
    (runtime.root / "raw").mkdir()
    raw_path = runtime.root / "raw" / "source.txt"
    raw_path.write_text("source", encoding="utf-8")
    immutable = asyncio.run(
        runtime.invoke(
            "file.edit",
            {
                "path": "raw/source.txt",
                "expected_sha256": sha256(b"source"),
                "start_line": 1,
                "end_line": 1,
                "replacement": "changed",
            },
            idempotency_key="immutable-1",
        )
    )
    conflict_path = runtime.root / "working.txt"
    conflict_path.write_text("current", encoding="utf-8")
    conflict = asyncio.run(
        runtime.invoke(
            "file.edit",
            {
                "path": "working.txt",
                "expected_sha256": "0" * 64,
                "start_line": 1,
                "end_line": 1,
                "replacement": "changed",
            },
            idempotency_key="conflict-1",
        )
    )
    assert immutable.error_code == "FILE_IMMUTABLE"
    assert conflict.error_code == "FILE_VERSION_CONFLICT"
    assert raw_path.read_text(encoding="utf-8") == "source"
    assert conflict_path.read_text(encoding="utf-8") == "current"


def test_symlink_escape_is_denied_when_supported(runtime: Runtime, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-file-gateway.txt"
    outside.write_text("outside", encoding="utf-8")
    link = runtime.root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable for this Windows account")
    result = asyncio.run(runtime.invoke("file.read", {"path": "link.txt"}))
    assert result.error_code == "FILE_PATH_DENIED"


def test_executable_hash_change_is_denied_before_process_start(tmp_path: Path) -> None:
    defaults = ControlledFileGateway._discover_default_executables()
    defaults["find"] = ExecutableIdentity(
        command_id=defaults["find"].command_id,
        path=defaults["find"].path,
        sha256="0" * 64,
    )
    runtime = Runtime(tmp_path, executables=defaults)
    try:
        result = asyncio.run(runtime.invoke("file.list", {"path": "."}))
        assert result.error_code == "FILE_EXECUTABLE_CHANGED"
    finally:
        runtime.close()


def test_registered_execute_template_and_unknown_command(tmp_path: Path) -> None:
    executable = ExecutableIdentity.discover("bash.sha256sum", "sha256sum")
    template = ExecutionTemplate(command_id="hash.file", executable=executable)
    runtime = Runtime(tmp_path, templates=(template,))
    try:
        (tmp_path / "value.txt").write_text("value", encoding="utf-8")
        allowed = asyncio.run(
            runtime.invoke("file.execute", {"command_id": "hash.file", "paths": ["value.txt"]})
        )
        denied = asyncio.run(
            runtime.invoke("file.execute", {"command_id": "shell.dynamic", "paths": ["value.txt"]})
        )
        assert allowed.status is ToolStatus.SUCCESS
        assert sha256(b"value") in allowed.output["content"]
        assert denied.error_code == "FILE_COMMAND_DENIED"
    finally:
        runtime.close()


def test_permission_denial_and_adapter_denial_are_audited(runtime: Runtime) -> None:
    (runtime.root / "safe.txt").write_text("safe", encoding="utf-8")
    with pytest.raises(ToolRegistryError) as denied:
        asyncio.run(
            runtime.invoke(
                "file.read",
                {"path": "safe.txt"},
                context=runtime.context(permissions=frozenset()),
            )
        )
    traversal = asyncio.run(runtime.invoke("file.read", {"path": "../safe.txt"}))
    events = runtime.repository.list(SCOPE)
    assert denied.value.code == "TOOL_PERMISSION_DENIED"
    assert traversal.error_code == "FILE_PATH_DENIED"
    assert traversal.output["error_code"] == "FILE_PATH_DENIED"
    assert len(events) == 2
    assert all(event.target_type == "tool" for event in events)
    assert events[-1].decision == "FILE_PATH_DENIED"


def test_byte_limits_fail_closed(runtime: Runtime, tmp_path: Path) -> None:
    runtime.close()
    limited = Runtime(tmp_path, max_read_bytes=2, max_output_bytes=2)
    try:
        (tmp_path / "large.txt").write_text("larger", encoding="utf-8")
        read = asyncio.run(limited.invoke("file.read", {"path": "large.txt"}))
        listing = asyncio.run(limited.invoke("file.list", {"path": "."}))
        assert read.error_code == "FILE_INPUT_TOO_LARGE"
        assert listing.error_code == "FILE_OUTPUT_TOO_LARGE"
    finally:
        limited.close()
