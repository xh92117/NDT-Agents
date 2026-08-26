"""Scope-bound local-file tools using fixed argv templates and safe mutation wrappers."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field

from ndt_agents.contracts.v1 import StrictModel, TenantScope, ToolResult, ToolStatus
from ndt_agents.tools.registry import (
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolAdapter,
    ToolDataDestination,
    ToolDataScope,
    ToolDefinition,
    ToolInvocation,
    ToolKind,
    ToolRecoveryPolicy,
    ToolTransport,
    canonical_sha256,
)

FILE_GATEWAY_VERSION: Literal["1.0.0"] = "1.0.0"
_FILE_ERROR_CODES = frozenset(
    {
        "FILE_COMMAND_DENIED",
        "FILE_COMMAND_DUPLICATE",
        "FILE_COMMAND_FAILED",
        "FILE_EDIT_RANGE_INVALID",
        "FILE_ENCODING_UNCERTAIN",
        "FILE_EXECUTABLE_BINDING_INVALID",
        "FILE_EXECUTABLE_CHANGED",
        "FILE_EXECUTABLE_NOT_FOUND",
        "FILE_IMMUTABLE",
        "FILE_INPUT_LIMIT_INVALID",
        "FILE_INPUT_TOO_LARGE",
        "FILE_IO_FAILED",
        "FILE_NOT_FOUND",
        "FILE_OUTPUT_TOO_LARGE",
        "FILE_OVERWRITE_DENIED",
        "FILE_PATH_DENIED",
        "FILE_PATTERN_DENIED",
        "FILE_ROOT_INVALID",
        "FILE_SCOPE_DENIED",
        "FILE_SOURCE_CHANGED",
        "FILE_SOURCE_NOT_REGULAR",
        "FILE_VERSION_CONFLICT",
        "FILE_VERSION_NOT_FOUND",
    }
)
FileOperation = Literal["LIST", "SEARCH", "READ", "WRITE", "EDIT", "ROLLBACK", "EXECUTE"]
_FORBIDDEN_PATH_CHARACTERS = frozenset("*?;&|`$><")
_INTERNAL_VERSION_ROOT = ".ndt-versions"
_OPERATIONS: Mapping[str, FileOperation] = {
    "file.list": "LIST",
    "file.search": "SEARCH",
    "file.read": "READ",
    "file.write": "WRITE",
    "file.edit": "EDIT",
    "file.rollback": "ROLLBACK",
    "file.execute": "EXECUTE",
}


class FileGatewayError(RuntimeError):
    """Typed, non-disclosing local-file policy failure."""

    def __init__(self, code: str, message: str, *, next_action: str) -> None:
        self.code = code
        self.retryable = False
        self.next_action = next_action
        super().__init__(message)


class ListInput(StrictModel):
    path: str = Field(min_length=1, max_length=4096)


class SearchInput(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    pattern: str = Field(min_length=1, max_length=4096)


class ReadInput(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    encoding: Literal["auto", "utf-8", "gbk", "gb18030", "utf-16le", "utf-16be"] = "auto"


class WriteInput(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=200_000)


class EditInput(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_line: int = Field(ge=1, le=1_000_000)
    end_line: int = Field(ge=1, le=1_000_000)
    replacement: str = Field(max_length=200_000)


class RollbackInput(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExecuteInput(StrictModel):
    command_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    paths: tuple[str, ...] = Field(min_length=1, max_length=16)


class SearchMatch(StrictModel):
    line: int = Field(ge=1)
    text: str = Field(max_length=10_000)


class FileToolOutput(StrictModel):
    operation: FileOperation
    command_id: str
    executable_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    path: str
    items: tuple[str, ...] = ()
    content: str = ""
    matches: tuple[SearchMatch, ...] = ()
    bytes_processed: int = Field(ge=0)
    lines: int = Field(ge=0)
    source_encoding: str | None = None
    normalized_encoding: str | None = None
    detector_confidence: float | None = Field(default=None, ge=0, le=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    version_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = Field(default=None, max_length=128)
    next_action: str | None = Field(default=None, max_length=500)


@dataclass(frozen=True, slots=True)
class ExecutableIdentity:
    command_id: str
    path: Path
    sha256: str

    @classmethod
    def discover(cls, command_id: str, executable_name: str) -> ExecutableIdentity:
        candidates: list[str | None] = []
        if os.name == "nt":
            candidates.extend(
                [
                    str(Path("C:/Program Files/Git/usr/bin") / f"{executable_name}.exe"),
                    str(Path("C:/Program Files/Git/bin") / f"{executable_name}.exe"),
                ]
            )
        candidates.append(shutil.which(executable_name))
        selected = next(
            (Path(value).resolve() for value in candidates if value and Path(value).is_file()),
            None,
        )
        if selected is None:
            raise FileGatewayError(
                "FILE_EXECUTABLE_NOT_FOUND",
                "A registered local-file executable is unavailable.",
                next_action="Install the approved UTF-8 Bash runtime or use the Linux worker.",
            )
        return cls(command_id=command_id, path=selected, sha256=_sha256_file(selected))

    def verify(self) -> None:
        if not self.path.is_file() or _sha256_file(self.path) != self.sha256:
            raise FileGatewayError(
                "FILE_EXECUTABLE_CHANGED",
                "A registered executable no longer matches its approved hash.",
                next_action="Revalidate and republish the executable identity before retrying.",
            )


@dataclass(frozen=True, slots=True)
class ExecutionTemplate:
    command_id: str
    executable: ExecutableIdentity
    fixed_arguments: tuple[str, ...] = ()
    max_paths: int = 1


@dataclass(frozen=True, slots=True)
class FileRootPolicy:
    root: Path
    tenant_id: UUID
    project_id: UUID
    immutable_prefixes: tuple[str, ...] = ("raw", "published")
    max_read_bytes: int = 1_000_000
    max_output_bytes: int = 200_000
    max_output_lines: int = 10_000


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    content: bytes
    size_bytes: int
    sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode(raw: bytes, requested: str = "auto") -> tuple[str, str, float]:
    codecs: list[tuple[str, str, float]]
    if requested != "auto":
        codecs = [(requested, requested, 1.0)]
    elif raw.startswith(b"\xef\xbb\xbf"):
        codecs = [("utf-8-sig", "utf-8-bom", 1.0)]
    elif raw.startswith(b"\xff\xfe"):
        codecs = [("utf-16", "utf-16le-bom", 1.0)]
    elif raw.startswith(b"\xfe\xff"):
        codecs = [("utf-16", "utf-16be-bom", 1.0)]
    else:
        codecs = [
            ("utf-8", "utf-8", 1.0),
            ("gbk", "gbk", 0.8),
            ("gb18030", "gb18030", 0.75),
        ]
    for codec, label, confidence in codecs:
        try:
            text = raw.decode(codec, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
        text = text.removeprefix("\ufeff")
        if "\x00" in text:
            continue
        return text, label, confidence
    raise FileGatewayError(
        "FILE_ENCODING_UNCERTAIN",
        "The file encoding cannot be decoded without loss.",
        next_action="Select a supported encoding or route the original file to manual review.",
    )


def _tool_definition(
    name: str,
    purpose: str,
    input_model: type[StrictModel],
    *,
    permission: str,
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version=FILE_GATEWAY_VERSION,
        purpose=purpose,
        kind=ToolKind.BASH,
        transport=ToolTransport.BASH,
        data_scope=ToolDataScope.TASK,
        data_destination=ToolDataDestination.LOCAL,
        side_effect=side_effect,
        input_schema=input_model.model_json_schema(),
        output_schema=FileToolOutput.model_json_schema(),
        required_permissions=frozenset({permission}),
        timeout_ms=30_000,
        max_attempts=1,
        max_concurrency=3 if side_effect is SideEffectClass.READ_ONLY else 1,
        max_input_bytes=500_000,
        max_output_bytes=500_000,
        max_tokens=0,
        idempotency=(
            IdempotencyPolicy.NONE
            if side_effect is SideEffectClass.READ_ONLY
            else IdempotencyPolicy.REQUIRED
        ),
        network=NetworkPolicy.NONE,
        declared_error_codes=_FILE_ERROR_CODES,
        recovery_policy=(
            ToolRecoveryPolicy.NO_RETRY
            if side_effect is SideEffectClass.READ_ONLY
            else ToolRecoveryPolicy.RECONCILE
        ),
        audit_owner="file-tool-runtime",
        test_owner="file-tool-runtime",
        test_groups=frozenset({"INT-BASH", "SEC-BASH", "SEC-TOOLS"}),
    )


class ControlledFileGateway:
    """Create fixed file-tool definitions and adapters for one tenant/project root."""

    def __init__(
        self,
        policy: FileRootPolicy,
        *,
        executables: Mapping[str, ExecutableIdentity] | None = None,
        execution_templates: Sequence[ExecutionTemplate] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        root = policy.root.resolve()
        if not root.is_dir():
            raise FileGatewayError(
                "FILE_ROOT_INVALID",
                "The configured file-tool root is unavailable.",
                next_action="Create and authorize the exact tenant/project working root.",
            )
        self._policy = FileRootPolicy(
            root=root,
            tenant_id=policy.tenant_id,
            project_id=policy.project_id,
            immutable_prefixes=policy.immutable_prefixes,
            max_read_bytes=policy.max_read_bytes,
            max_output_bytes=policy.max_output_bytes,
            max_output_lines=policy.max_output_lines,
        )
        self._executables = dict(executables or self._discover_default_executables())
        if not {"find", "grep", "cat"} <= set(self._executables):
            raise FileGatewayError(
                "FILE_EXECUTABLE_BINDING_INVALID",
                "The fixed local-file executable set is incomplete.",
                next_action="Bind exact identities for find, grep, and cat.",
            )
        self._execution_templates = {item.command_id: item for item in execution_templates}
        if len(self._execution_templates) != len(execution_templates):
            raise FileGatewayError(
                "FILE_COMMAND_DUPLICATE",
                "A registered execution command ID is duplicated.",
                next_action="Publish one exact template for each command ID.",
            )
        self._clock = clock
        self._versions: dict[str, Path] = {}

    @staticmethod
    def _discover_default_executables() -> dict[str, ExecutableIdentity]:
        return {
            name: ExecutableIdentity.discover(f"bash.{name}", name)
            for name in ("find", "grep", "cat")
        }

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (
            _tool_definition(
                "file.list", "List one authorized directory.", ListInput, permission="file.list"
            ),
            _tool_definition(
                "file.search",
                "Search one authorized UTF-8 file.",
                SearchInput,
                permission="file.search",
            ),
            _tool_definition(
                "file.read",
                "Read and normalize one authorized text file.",
                ReadInput,
                permission="file.read",
            ),
            _tool_definition(
                "file.write",
                "Create one authorized UTF-8 file atomically.",
                WriteInput,
                permission="file.write",
                side_effect=SideEffectClass.REVERSIBLE,
            ),
            _tool_definition(
                "file.edit",
                "Create one versioned UTF-8 file edit.",
                EditInput,
                permission="file.edit",
                side_effect=SideEffectClass.REVERSIBLE,
            ),
            _tool_definition(
                "file.rollback",
                "Restore one exact prior file version.",
                RollbackInput,
                permission="file.edit",
                side_effect=SideEffectClass.REVERSIBLE,
            ),
            _tool_definition(
                "file.execute",
                "Run one registered read-only local command template.",
                ExecuteInput,
                permission="file.execute",
            ),
        )

    @property
    def adapters(self) -> Mapping[str, ToolAdapter]:
        return {
            definition.key: _FileAdapter(self, definition.name) for definition in self.definitions
        }

    def _check_scope(self, scope: TenantScope) -> None:
        if scope.tenant_id != self._policy.tenant_id or scope.project_id != self._policy.project_id:
            raise FileGatewayError(
                "FILE_SCOPE_DENIED",
                "The invocation scope does not own the configured file root.",
                next_action="Use the exact authorized tenant and project file root.",
            )

    def read_source_bytes(
        self,
        scope: TenantScope,
        relative_path: str,
        *,
        hard_limit_bytes: int,
    ) -> SourceSnapshot:
        """Read one immutable intake source through the gateway path and scope policy.

        This application-owned adapter is not published as a model-callable tool. It exists for
        binary signature inspection and hashing, which cannot safely pass through text context.
        """

        self._check_scope(scope)
        if hard_limit_bytes <= 0:
            raise FileGatewayError(
                "FILE_INPUT_LIMIT_INVALID",
                "The source read limit is invalid.",
                next_action="Use the centrally configured positive intake limit.",
            )
        relative = Path(relative_path)
        lexical_path = self._policy.root / relative
        if lexical_path.is_symlink():
            raise self._path_error()
        path = self._path(relative_path, exists=True)
        if not path.is_file():
            raise FileGatewayError(
                "FILE_SOURCE_NOT_REGULAR",
                "The selected intake source is not a regular file.",
                next_action="Select one immutable regular source file.",
            )
        before = path.stat()
        if before.st_size > hard_limit_bytes:
            raise FileGatewayError(
                "FILE_INPUT_TOO_LARGE",
                "The selected file exceeds the intake hard limit.",
                next_action="Split the source or obtain an approved bounded exception.",
            )
        content = bytearray()
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > hard_limit_bytes:
                    raise FileGatewayError(
                        "FILE_INPUT_TOO_LARGE",
                        "The selected file exceeds the intake hard limit.",
                        next_action="Split the source or obtain an approved bounded exception.",
                    )
                digest.update(chunk)
                content.extend(chunk)
        after = path.stat()
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or total != after.st_size
        ):
            raise FileGatewayError(
                "FILE_SOURCE_CHANGED",
                "The source changed during intake inspection.",
                next_action="Freeze a new immutable artifact version and retry.",
            )
        return SourceSnapshot(content=bytes(content), size_bytes=total, sha256=digest.hexdigest())

    def application_source_path(self, scope: TenantScope, relative_path: str) -> Path:
        """Resolve one non-symlink source for an application-owned registered adapter."""

        self._check_scope(scope)
        relative = Path(relative_path)
        lexical_path = self._policy.root / relative
        if lexical_path.is_symlink():
            raise self._path_error()
        path = self._path(relative_path, exists=True)
        if not path.is_file():
            raise FileGatewayError(
                "FILE_SOURCE_NOT_REGULAR",
                "The selected adapter source is not a regular file.",
                next_action="Select one immutable regular source file.",
            )
        return path

    def _path(self, value: str, *, exists: bool, mutation: bool = False) -> Path:
        path_value = Path(value)
        if path_value.is_absolute() or path_value.drive or any(ord(char) < 32 for char in value):
            raise self._path_error()
        if any(char in _FORBIDDEN_PATH_CHARACTERS for char in value):
            raise self._path_error()
        relative = Path(value)
        if _INTERNAL_VERSION_ROOT in relative.parts or any(part == ".." for part in relative.parts):
            raise self._path_error()
        candidate = (self._policy.root / relative).resolve(strict=False)
        if not candidate.is_relative_to(self._policy.root):
            raise self._path_error()
        if exists and not candidate.exists():
            raise FileGatewayError(
                "FILE_NOT_FOUND",
                "The selected authorized path does not exist.",
                next_action="Select an existing path inside the task working root.",
            )
        if mutation:
            if relative.parts and relative.parts[0] in self._policy.immutable_prefixes:
                raise FileGatewayError(
                    "FILE_IMMUTABLE",
                    "The selected path is inside an immutable file zone.",
                    next_action="Create or edit a versioned working copy instead.",
                )
            if candidate.exists() and candidate.is_symlink():
                raise self._path_error()
            if not candidate.parent.resolve().is_relative_to(self._policy.root):
                raise self._path_error()
        return candidate

    @staticmethod
    def _path_error() -> FileGatewayError:
        return FileGatewayError(
            "FILE_PATH_DENIED",
            "The selected path violates the local-file policy.",
            next_action="Use a literal relative path inside the authorized working root.",
        )

    async def _command(
        self,
        executable: ExecutableIdentity,
        arguments: Sequence[str],
        *,
        allowed_returncodes: frozenset[int] = frozenset({0}),
    ) -> bytes:
        executable.verify()
        process = await asyncio.create_subprocess_exec(
            str(executable.path),
            *arguments,
            cwd=self._policy.root,
            env={
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": str(executable.path.parent),
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        if (
            len(stdout) > self._policy.max_output_bytes
            or len(stderr) > self._policy.max_output_bytes
        ):
            raise FileGatewayError(
                "FILE_OUTPUT_TOO_LARGE",
                "The local command output exceeds its configured byte limit.",
                next_action="Narrow the path or search pattern and retry.",
            )
        if process.returncode not in allowed_returncodes:
            raise FileGatewayError(
                "FILE_COMMAND_FAILED",
                "A registered local command returned a failure.",
                next_action=(
                    f"Verify the selected file and bounded command arguments; exit code "
                    f"{process.returncode}."
                ),
            )
        return stdout

    async def execute(self, operation: str, invocation: ToolInvocation) -> FileToolOutput:
        self._check_scope(invocation.context.scope)
        if operation == "file.list":
            list_input = ListInput.model_validate(invocation.arguments)
            path = self._path(list_input.path, exists=True)
            executable = self._executables["find"]
            raw = await self._command(
                executable,
                ("--", str(path), "-mindepth", "1", "-maxdepth", "1", "-print0"),
            )
            decoded_items = tuple(_decode(item)[0] for item in raw.split(b"\x00") if item)
            if any(any(ord(char) < 32 for char in item) for item in decoded_items):
                raise FileGatewayError(
                    "FILE_PATH_DENIED",
                    "A listed filename contains a forbidden control character.",
                    next_action="Rename the file before adding its name to agent context.",
                )
            items = tuple(Path(item).name for item in decoded_items)
            items = tuple(item for item in items if item != _INTERNAL_VERSION_ROOT)
            self._check_lines(items)
            return self._output(
                "LIST",
                executable,
                list_input.path,
                raw,
                items=items,
                content="\n".join(items),
                source_encoding="utf-8",
                confidence=1.0,
            )
        if operation == "file.search":
            search_input = SearchInput.model_validate(invocation.arguments)
            if any(ord(char) < 32 for char in search_input.pattern):
                raise FileGatewayError(
                    "FILE_PATTERN_DENIED",
                    "The search pattern contains control characters.",
                    next_action="Use a bounded literal search pattern.",
                )
            path = self._path(search_input.path, exists=True)
            executable = self._executables["grep"]
            raw = await self._command(
                executable,
                ("-n", "-F", "-e", search_input.pattern, "--", str(path)),
                allowed_returncodes=frozenset({0, 1}),
            )
            text, encoding, confidence = _decode(raw)
            matches = tuple(
                SearchMatch(line=int(line), text=value)
                for line, value in (item.split(":", 1) for item in text.splitlines())
            )
            self._check_lines(matches)
            return self._output(
                "SEARCH",
                executable,
                search_input.path,
                raw,
                matches=matches,
                content=text,
                source_encoding=encoding,
                confidence=confidence,
            )
        if operation == "file.read":
            read_input = ReadInput.model_validate(invocation.arguments)
            path = self._path(read_input.path, exists=True)
            if path.stat().st_size > self._policy.max_read_bytes:
                raise FileGatewayError(
                    "FILE_INPUT_TOO_LARGE",
                    "The selected file exceeds its read limit.",
                    next_action="Use a bounded range or smaller working copy.",
                )
            executable = self._executables["cat"]
            raw = await self._command(executable, ("--", str(path)))
            text, encoding, confidence = _decode(raw, read_input.encoding)
            self._check_lines(text.splitlines())
            return self._output(
                "READ",
                executable,
                read_input.path,
                raw,
                content=text,
                source_encoding=encoding,
                confidence=confidence,
                source_sha256=_sha256_file(path),
            )
        if operation == "file.write":
            write_input = WriteInput.model_validate(invocation.arguments)
            path = self._path(write_input.path, exists=False, mutation=True)
            if path.exists():
                raise FileGatewayError(
                    "FILE_OVERWRITE_DENIED",
                    "Safe write cannot overwrite an existing file.",
                    next_action="Use a versioned edit with the expected hash.",
                )
            raw = write_input.content.encode("utf-8")
            self._atomic_write(path, raw)
            return self._output(
                "WRITE",
                None,
                write_input.path,
                raw,
                source_encoding="utf-8",
                confidence=1.0,
                output_sha256=_sha256_file(path),
            )
        if operation == "file.edit":
            edit_input = EditInput.model_validate(invocation.arguments)
            path = self._path(edit_input.path, exists=True, mutation=True)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != edit_input.expected_sha256:
                raise FileGatewayError(
                    "FILE_VERSION_CONFLICT",
                    "The selected file changed before editing.",
                    next_action="Read the current version and submit its exact hash.",
                )
            text, encoding, confidence = _decode(raw)
            lines = text.splitlines(keepends=True)
            if edit_input.end_line < edit_input.start_line or edit_input.end_line > len(lines):
                raise FileGatewayError(
                    "FILE_EDIT_RANGE_INVALID",
                    "The edit line range is invalid.",
                    next_action="Use an existing inclusive line range.",
                )
            version_id = self._save_version(path, raw)
            replacement = edit_input.replacement
            newline = "\r\n" if "\r\n" in text else "\n"
            if replacement and not replacement.endswith(("\n", "\r")):
                replacement += newline
            updated = "".join(
                (
                    *lines[: edit_input.start_line - 1],
                    replacement,
                    *lines[edit_input.end_line :],
                )
            ).encode("utf-8")
            self._atomic_write(path, updated)
            return self._output(
                "EDIT",
                None,
                edit_input.path,
                updated,
                source_encoding=encoding,
                confidence=confidence,
                source_sha256=hashlib.sha256(raw).hexdigest(),
                output_sha256=_sha256_file(path),
                version_id=version_id,
            )
        if operation == "file.rollback":
            rollback_input = RollbackInput.model_validate(invocation.arguments)
            path = self._path(rollback_input.path, exists=True, mutation=True)
            if _sha256_file(path) != rollback_input.expected_sha256:
                raise FileGatewayError(
                    "FILE_VERSION_CONFLICT",
                    "The selected file changed before rollback.",
                    next_action="Read the current version and submit its exact hash.",
                )
            version = self._versions.get(rollback_input.version_id)
            if version is None or not version.is_file():
                raise FileGatewayError(
                    "FILE_VERSION_NOT_FOUND",
                    "The requested working-copy version is unavailable.",
                    next_action="Select a version recorded by this gateway runtime.",
                )
            raw = version.read_bytes()
            self._atomic_write(path, raw)
            text, encoding, confidence = _decode(raw)
            return self._output(
                "ROLLBACK",
                None,
                rollback_input.path,
                raw,
                source_encoding=encoding,
                confidence=confidence,
                output_sha256=_sha256_file(path),
                version_id=rollback_input.version_id,
            )
        execute_input = ExecuteInput.model_validate(invocation.arguments)
        template = self._execution_templates.get(execute_input.command_id)
        if template is None or len(execute_input.paths) > template.max_paths:
            raise FileGatewayError(
                "FILE_COMMAND_DENIED",
                "The requested execution template is not registered.",
                next_action="Use an application-owned command template and bounded path count.",
            )
        paths = tuple(str(self._path(value, exists=True)) for value in execute_input.paths)
        raw = await self._command(template.executable, (*template.fixed_arguments, "--", *paths))
        text, encoding, confidence = _decode(raw)
        self._check_lines(text.splitlines())
        return self._output(
            "EXECUTE",
            template.executable,
            ",".join(execute_input.paths),
            raw,
            content=text,
            items=tuple(text.splitlines()),
            source_encoding=encoding,
            confidence=confidence,
        )

    def _check_lines(self, values: Sequence[object]) -> None:
        if len(values) > self._policy.max_output_lines:
            raise FileGatewayError(
                "FILE_OUTPUT_TOO_LARGE",
                "The local command output exceeds its line limit.",
                next_action="Narrow the path or search pattern and retry.",
            )

    def _save_version(self, path: Path, raw: bytes) -> str:
        version_id = hashlib.sha256(raw).hexdigest()
        version_root = self._policy.root / _INTERNAL_VERSION_ROOT
        version_root.mkdir(mode=0o700, exist_ok=True)
        version_path = version_root / version_id
        if not version_path.exists():
            self._atomic_write(version_path, raw)
        self._versions[version_id] = version_path
        return version_id

    @staticmethod
    def _atomic_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=False, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".ndt-write-", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            if Path(temporary).exists():
                Path(temporary).unlink()
            raise

    def _output(
        self,
        operation: FileOperation,
        executable: ExecutableIdentity | None,
        path: str,
        raw: bytes,
        *,
        items: tuple[str, ...] = (),
        content: str = "",
        matches: tuple[SearchMatch, ...] = (),
        source_encoding: str | None = None,
        confidence: float | None = None,
        source_sha256: str | None = None,
        output_sha256: str | None = None,
        version_id: str | None = None,
    ) -> FileToolOutput:
        return FileToolOutput(
            operation=operation,
            command_id=executable.command_id if executable else f"safe-{operation.lower()}",
            executable_sha256=executable.sha256 if executable else None,
            path=path,
            items=items,
            content=content,
            matches=matches,
            bytes_processed=len(raw),
            lines=len(content.splitlines()) if content else len(items) or len(matches),
            source_encoding=source_encoding,
            normalized_encoding="utf-8" if source_encoding else None,
            detector_confidence=confidence,
            source_sha256=source_sha256,
            output_sha256=output_sha256,
            version_id=version_id,
        )


class _FileAdapter:
    def __init__(self, gateway: ControlledFileGateway, operation: str) -> None:
        self._gateway = gateway
        self._operation = operation

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        started = time.monotonic()
        try:
            output = await self._gateway.execute(self._operation, invocation)
            status = ToolStatus.SUCCESS
            error_code = None
            retryable = False
        except FileGatewayError as error:
            output = FileToolOutput(
                operation=_OPERATIONS[self._operation],
                command_id="denied",
                path="denied",
                bytes_processed=0,
                lines=0,
                error_code=error.code,
                next_action=error.next_action,
            )
            status = ToolStatus.DENIED
            error_code = error.code
            retryable = error.retryable
        except OSError:
            output = FileToolOutput(
                operation=_OPERATIONS[self._operation],
                command_id="failed",
                path="failed",
                bytes_processed=0,
                lines=0,
                error_code="FILE_IO_FAILED",
                next_action="Verify the authorized path and local file-system state.",
            )
            status = ToolStatus.FAILED
            error_code = "FILE_IO_FAILED"
            retryable = False
        payload = output.model_dump(mode="json")
        return ToolResult(
            call_id=invocation.call_id,
            task_id=invocation.context.task_id,
            run_id=invocation.context.run_id,
            scope=invocation.context.scope,
            tool_name=invocation.definition.name,
            tool_version=invocation.definition.version,
            status=status,
            output=payload,
            exit_code=0 if status is ToolStatus.SUCCESS else None,
            stdout=output.content,
            stderr="",
            encoding=output.normalized_encoding,
            truncated=False,
            artifacts=(),
            idempotency_key=invocation.idempotency_key,
            input_sha256=invocation.input_sha256,
            output_sha256=canonical_sha256(payload),
            error_code=error_code,
            retryable=retryable,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            completed_at=self._gateway._clock(),
        )
