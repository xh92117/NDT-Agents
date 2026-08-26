"""Strict application-owned prompt catalog and immutable instruction loading."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

import yaml
from pydantic import Field, ValidationError, model_validator
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken

from ndt_agents.contracts.v1 import StrictModel
from ndt_agents.models.instructions import ApplicationInstruction, build_application_instruction
from ndt_agents.models.registry import canonical_sha256

PROMPT_CATALOG_VERSION: Literal["1.0.0"] = "1.0.0"
_MAX_CATALOG_BYTES = 128 * 1024
_MAX_PROMPT_BYTES = 100 * 1024


class PromptRegistryError(RuntimeError):
    """Stable prompt-catalog failure that exposes no prompt content."""

    def __init__(self, code: str, message: str, *, next_action: str) -> None:
        self.code = code
        self.retryable = False
        self.next_action = next_action
        super().__init__(message)


class PromptCatalogEntry(StrictModel):
    prompt_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    path: str = Field(min_length=4, max_length=512)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        if "\\" in self.path or "\x00" in self.path or "\r" in self.path or "\n" in self.path:
            raise ValueError("prompt paths must use bounded POSIX-relative syntax")
        candidate = PurePosixPath(self.path)
        if (
            candidate.is_absolute()
            or candidate.suffix.lower() != ".md"
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or ":" in self.path
        ):
            raise ValueError("prompt paths must remain relative Markdown paths")
        return self


class PromptCatalogDocument(StrictModel):
    schema_version: Literal["1.0.0"] = PROMPT_CATALOG_VERSION
    catalog_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    prompts: tuple[PromptCatalogEntry, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_unique_entries(self) -> Self:
        identities = [(entry.prompt_id, entry.version) for entry in self.prompts]
        paths = [entry.path for entry in self.prompts]
        prompt_ids = [entry.prompt_id for entry in self.prompts]
        if len(set(identities)) != len(identities):
            raise ValueError("prompt identities must be unique")
        if len(set(paths)) != len(paths):
            raise ValueError("prompt paths must be unique")
        if len(set(prompt_ids)) != len(prompt_ids):
            raise ValueError("one active version per prompt ID is required")
        return self


class ResolvedPrompt(StrictModel):
    schema_version: Literal["1.0.0"] = PROMPT_CATALOG_VERSION
    prompt_id: str
    version: str
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    instruction: ApplicationInstruction

    @model_validator(mode="after")
    def validate_instruction(self) -> Self:
        if (
            self.instruction.instruction_id != self.prompt_id
            or self.instruction.instruction_version != self.version
            or self.instruction.instruction_sha256 != self.sha256
        ):
            raise ValueError("resolved prompt instruction identity is inconsistent")
        return self


@dataclass(frozen=True, slots=True)
class PromptRegistry:
    source_path: Path
    document: PromptCatalogDocument
    prompts: tuple[ResolvedPrompt, ...]
    catalog_sha256: str

    def resolve(self, prompt_id: str) -> ResolvedPrompt:
        for prompt in self.prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        raise PromptRegistryError(
            "PROMPT_NOT_FOUND",
            "The requested prompt is not in the active catalog.",
            next_action="Use an exact prompt ID from the active prompt catalog.",
        )


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found a duplicate key",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _error(code: str, message: str, next_action: str) -> PromptRegistryError:
    return PromptRegistryError(code, message, next_action=next_action)


def _read_catalog(path: Path) -> PromptCatalogDocument:
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise _error(
            "PROMPT_CATALOG_EXTENSION_INVALID",
            "The prompt catalog must use a YAML filename.",
            "Select an explicit .yaml or .yml prompt catalog.",
        )
    try:
        raw = path.read_bytes()
    except OSError:
        raise _error(
            "PROMPT_CATALOG_NOT_FOUND",
            "The prompt catalog could not be read.",
            "Verify the explicit catalog path and local read permission.",
        ) from None
    if len(raw) > _MAX_CATALOG_BYTES:
        raise _error(
            "PROMPT_CATALOG_TOO_LARGE",
            "The prompt catalog exceeds its byte limit.",
            "Reduce the catalog to the documented bounded size.",
        )
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _error(
            "PROMPT_CATALOG_ENCODING_INVALID",
            "The prompt catalog uses a forbidden byte-order mark.",
            "Save the catalog as UTF-8 without BOM.",
        )
    try:
        text = raw.decode("utf-8")
        if any(isinstance(token, (AliasToken, AnchorToken)) for token in yaml.scan(text)):
            raise ValueError("YAML aliases and anchors are forbidden")
        payload: Any = yaml.load(text, Loader=_UniqueKeyLoader)
        return PromptCatalogDocument.model_validate(payload)
    except (
        ConstructorError,
        UnicodeDecodeError,
        TypeError,
        ValueError,
        ValidationError,
        yaml.YAMLError,
    ):
        raise _error(
            "PROMPT_CATALOG_INVALID",
            "The prompt catalog is malformed or violates its strict schema.",
            "Correct the application-owned catalog and retry.",
        ) from None


def _has_symlink_component(root: Path, relative: PurePosixPath) -> bool:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _load_prompt(root: Path, entry: PromptCatalogEntry) -> ResolvedPrompt:
    relative = PurePosixPath(entry.path)
    unresolved = root.joinpath(*relative.parts)
    if _has_symlink_component(root, relative):
        raise _error(
            "PROMPT_PATH_DENIED",
            "A prompt path uses a symbolic-link component.",
            "Use an application-owned regular file within the prompt catalog directory.",
        )
    try:
        resolved = unresolved.resolve(strict=True)
    except OSError:
        raise _error(
            "PROMPT_NOT_FOUND",
            "A catalog prompt file could not be read.",
            "Restore the exact prompt file referenced by the active catalog.",
        ) from None
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise _error(
            "PROMPT_PATH_DENIED",
            "A prompt path escapes the application-owned catalog directory.",
            "Use a regular relative Markdown file within the prompt catalog directory.",
        )
    try:
        raw = resolved.read_bytes()
    except OSError:
        raise _error(
            "PROMPT_NOT_FOUND",
            "A catalog prompt file could not be read.",
            "Verify the exact prompt file and local read permission.",
        ) from None
    if not raw or len(raw) > _MAX_PROMPT_BYTES:
        raise _error(
            "PROMPT_CONTENT_INVALID",
            "A prompt file is empty or exceeds its byte limit.",
            "Provide one bounded non-empty application-owned prompt.",
        )
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _error(
            "PROMPT_ENCODING_INVALID",
            "A prompt file uses a forbidden byte-order mark.",
            "Save the prompt as UTF-8 without BOM.",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _error(
            "PROMPT_ENCODING_INVALID",
            "A prompt file is not valid UTF-8.",
            "Save the prompt as validated UTF-8 without lossy replacement.",
        ) from None
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry.sha256:
        raise _error(
            "PROMPT_HASH_MISMATCH",
            "A prompt file does not match its catalog hash.",
            "Review the prompt change and publish a new exact catalog hash.",
        )
    instruction = build_application_instruction(
        instruction_id=entry.prompt_id,
        instruction_version=entry.version,
        text=text,
    )
    return ResolvedPrompt(
        prompt_id=entry.prompt_id,
        version=entry.version,
        relative_path=entry.path,
        sha256=digest,
        instruction=instruction,
    )


def load_prompt_registry(catalog_path: str | Path) -> PromptRegistry:
    """Load one strict prompt catalog and verify every exact local prompt file."""

    raw_path = str(catalog_path)
    if any(value in raw_path for value in ("\x00", "\r", "\n")):
        raise _error(
            "PROMPT_CATALOG_PATH_DENIED",
            "The prompt catalog path contains forbidden characters.",
            "Use one explicit local YAML path.",
        )
    source_path = Path(catalog_path).expanduser().resolve()
    document = _read_catalog(source_path)
    root = source_path.parent.resolve()
    prompts = tuple(
        sorted(
            (_load_prompt(root, entry) for entry in document.prompts),
            key=lambda prompt: prompt.prompt_id,
        )
    )
    catalog_sha256 = canonical_sha256(
        {
            "document": document.model_dump(mode="json"),
            "resolved": [
                {
                    "prompt_id": prompt.prompt_id,
                    "version": prompt.version,
                    "relative_path": prompt.relative_path,
                    "sha256": prompt.sha256,
                }
                for prompt in prompts
            ],
        }
    )
    return PromptRegistry(
        source_path=source_path,
        document=document,
        prompts=prompts,
        catalog_sha256=catalog_sha256,
    )
