"""Strict versioned agent runtime configuration inspired by DeerFlow's layout."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import Field, ValidationError, model_validator
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken

from ndt_agents.contracts.v1 import StrictModel
from ndt_agents.models.config import ConfiguredModelRuntime
from ndt_agents.models.instructions import ApplicationInstruction
from ndt_agents.models.registry import canonical_sha256
from ndt_agents.orchestration.child_models import AgentDefinition, ChildAgentKind
from ndt_agents.orchestration.prompt_registry import PromptRegistry, PromptRegistryError
from ndt_agents.orchestration.registry import AgentRegistry

AGENT_RUNTIME_CONFIG_VERSION: Literal["1.1.0"] = "1.1.0"
_MAX_CONFIG_BYTES = 256 * 1024
_TOOL_REFERENCE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}@[0-9]+\.[0-9]+\.[0-9]+$")


class AgentRuntimeConfigurationError(RuntimeError):
    """Stable non-disclosing agent configuration failure."""

    def __init__(self, code: str, message: str, *, next_action: str) -> None:
        self.code = code
        self.retryable = False
        self.next_action = next_action
        super().__init__(message)


class AgentModelConfiguration(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,127}$")
    display_name: str = Field(min_length=1, max_length=128)
    binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    binding_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    max_input_tokens: int = Field(ge=1, le=1_000_000)
    max_output_tokens: int = Field(ge=1, le=1_000_000)


class AgentProfileConfiguration(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,127}$")
    kind: ChildAgentKind
    description: str = Field(min_length=1, max_length=1000)
    model: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,127}$")
    prompt: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    skill_version: str = Field(min_length=1, max_length=128)
    graph_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    allowed_tools: tuple[str, ...] = Field(default=(), max_length=12)
    max_turns: int | None = Field(default=None, ge=1, le=32)
    timeout_ms: int | None = Field(default=None, ge=1, le=3_600_000)

    @model_validator(mode="after")
    def validate_tools(self) -> Self:
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("agent tool references must be unique")
        if any(_TOOL_REFERENCE.fullmatch(value) is None for value in self.allowed_tools):
            raise ValueError("agent tools require exact name@semantic-version references")
        return self


class SubagentConfiguration(StrictModel):
    default_max_turns: int = Field(ge=1, le=32)
    hard_max_turns: int = Field(ge=1, le=32)
    default_timeout_ms: int = Field(ge=1, le=3_600_000)
    hard_timeout_ms: int = Field(ge=1, le=3_600_000)
    max_concurrent: int = Field(ge=1, le=4)
    hard_max_concurrent: int = Field(ge=1, le=4)
    max_total_per_run: int = Field(ge=1, le=32)
    hard_max_total_per_run: int = Field(ge=1, le=32)
    agents: tuple[AgentProfileConfiguration, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_limits_and_agents(self) -> Self:
        if (
            self.default_max_turns > self.hard_max_turns
            or self.default_timeout_ms > self.hard_timeout_ms
            or self.max_concurrent > self.hard_max_concurrent
            or self.max_total_per_run > self.hard_max_total_per_run
        ):
            raise ValueError("active subagent limits cannot exceed hard limits")
        names = [agent.name for agent in self.agents]
        if len(set(names)) != len(names):
            raise ValueError("agent names must be unique")
        general = [agent for agent in self.agents if agent.kind is ChildAgentKind.GENERAL]
        if len(general) != 1 or general[0].name != "general":
            raise ValueError("exactly one General Agent must be configured")
        for agent in self.agents:
            if agent.max_turns is not None and agent.max_turns > self.hard_max_turns:
                raise ValueError("agent turn limit exceeds the configured hard limit")
            if agent.timeout_ms is not None and agent.timeout_ms > self.hard_timeout_ms:
                raise ValueError("agent timeout exceeds the configured hard limit")
        return self


class AgentRuntimeConfigurationDocument(StrictModel):
    schema_version: Literal["1.1.0"] = AGENT_RUNTIME_CONFIG_VERSION
    config_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    models: tuple[AgentModelConfiguration, ...] = Field(min_length=1, max_length=32)
    subagents: SubagentConfiguration

    @model_validator(mode="after")
    def validate_model_names(self) -> Self:
        names = [model.name for model in self.models]
        if len(set(names)) != len(names):
            raise ValueError("model names must be unique")
        return self


class ResolvedAgentProfile(StrictModel):
    schema_version: Literal["1.1.0"] = AGENT_RUNTIME_CONFIG_VERSION
    name: str
    kind: ChildAgentKind
    description: str
    model_name: str
    binding_id: str
    binding_version: str
    model_id: str
    prompt_name: str
    prompt_version: str
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    skill_version: str
    graph_version: str
    allowed_tools: tuple[str, ...]
    max_turns: int
    timeout_ms: int


class AgentRuntimeStatus(StrictModel):
    schema_version: Literal["1.1.0"] = AGENT_RUNTIME_CONFIG_VERSION
    state: Literal["CONFIGURED"] = "CONFIGURED"
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    models: int = Field(ge=1)
    prompts: int = Field(ge=1)
    agents: int = Field(ge=1)
    general_agents: Literal[1] = 1


@dataclass(frozen=True, slots=True)
class ConfiguredAgentRuntime:
    source_path: Path
    document: AgentRuntimeConfigurationDocument
    prompt_registry: PromptRegistry
    profiles: tuple[ResolvedAgentProfile, ...]
    configuration_sha256: str
    status: AgentRuntimeStatus

    def build_agent_registry(self) -> AgentRegistry:
        """Materialize the existing application-owned child registry contract."""

        definitions = tuple(
            AgentDefinition(
                agent_type=profile.name,
                kind=profile.kind,
                agent_configuration_sha256=self.configuration_sha256,
                allowed_tools=frozenset(profile.allowed_tools),
                skill_version=profile.skill_version,
                prompt_version=profile.prompt_version,
                model_version=profile.model_name,
            )
            for profile in self.profiles
        )
        return AgentRegistry(definitions)

    def profile(self, name: str) -> ResolvedAgentProfile:
        for profile in self.profiles:
            if profile.name == name:
                return profile
        raise AgentRuntimeConfigurationError(
            "AGENT_PROFILE_NOT_FOUND",
            "The selected child-agent profile is not configured.",
            next_action="Select a profile from the current agent runtime configuration.",
        )

    def prompt_instruction(self, profile_name: str) -> ApplicationInstruction:
        profile = self.profile(profile_name)
        prompt = self.prompt_registry.resolve(profile.prompt_name)
        if prompt.version != profile.prompt_version or prompt.sha256 != profile.prompt_sha256:
            raise AgentRuntimeConfigurationError(
                "AGENT_PROMPT_STALE",
                "The selected agent prompt does not match the resolved profile.",
                next_action="Reload the exact prompt catalog and agent configuration together.",
            )
        return prompt.instruction


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


def _error(code: str, message: str, next_action: str) -> AgentRuntimeConfigurationError:
    return AgentRuntimeConfigurationError(code, message, next_action=next_action)


def _read_document(path: Path) -> AgentRuntimeConfigurationDocument:
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise _error(
            "AGENT_CONFIG_EXTENSION_INVALID",
            "The agent configuration must use a YAML filename.",
            "Select an explicit .yaml or .yml agent configuration file.",
        )
    try:
        raw = path.read_bytes()
    except OSError:
        raise _error(
            "AGENT_CONFIG_NOT_FOUND",
            "The agent configuration file could not be read.",
            "Verify the explicit path and local read permission.",
        ) from None
    if len(raw) > _MAX_CONFIG_BYTES:
        raise _error(
            "AGENT_CONFIG_TOO_LARGE",
            "The agent configuration exceeds its byte limit.",
            "Reduce the file to the documented bounded configuration size.",
        )
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _error(
            "AGENT_CONFIG_ENCODING_INVALID",
            "The agent configuration uses a forbidden byte-order mark.",
            "Save the file as UTF-8 without BOM.",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _error(
            "AGENT_CONFIG_ENCODING_INVALID",
            "The agent configuration is not valid UTF-8.",
            "Save the file as validated UTF-8 without lossy replacement.",
        ) from None
    try:
        if any(isinstance(token, (AliasToken, AnchorToken)) for token in yaml.scan(text)):
            raise ValueError("YAML aliases and anchors are forbidden")
        payload: Any = yaml.load(text, Loader=_UniqueKeyLoader)
        return AgentRuntimeConfigurationDocument.model_validate(payload)
    except (ConstructorError, TypeError, ValueError, ValidationError, yaml.YAMLError):
        raise _error(
            "AGENT_CONFIG_INVALID",
            "The agent YAML is malformed or violates its strict schema.",
            "Correct the non-secret YAML using the versioned example and retry.",
        ) from None


def _resolve_profiles(
    document: AgentRuntimeConfigurationDocument,
    model_runtime: ConfiguredModelRuntime,
    prompt_registry: PromptRegistry,
    known_tool_references: frozenset[str],
) -> tuple[ResolvedAgentProfile, ...]:
    model_by_name = {model.name: model for model in document.models}
    resolved_models: dict[str, AgentModelConfiguration] = {}
    for model in document.models:
        binding = next(
            (
                candidate
                for candidate in model_runtime.bindings
                if candidate.binding_id == model.binding_id
                and candidate.version == model.binding_version
            ),
            None,
        )
        definition = next(
            (
                candidate
                for candidate in model_runtime.catalog.models
                if binding is not None
                and candidate.provider_id == binding.provider_id
                and candidate.model_id == model.model_id
            ),
            None,
        )
        if (
            binding is None
            or definition is None
            or model.model_id not in binding.allowed_model_ids
            or model.max_input_tokens > binding.max_input_tokens
            or model.max_input_tokens > definition.context_window_tokens
            or model.max_output_tokens > binding.max_output_tokens
            or model.max_output_tokens > definition.max_output_tokens
        ):
            raise _error(
                "AGENT_CONFIG_REFERENCE_INVALID",
                "An agent model entry does not resolve within the published model runtime.",
                "Use an exact allowed binding, version, model, and bounded token limits.",
            )
        resolved_models[model.name] = model

    profiles: list[ResolvedAgentProfile] = []
    for agent in document.subagents.agents:
        if agent.model not in model_by_name:
            raise _error(
                "AGENT_CONFIG_REFERENCE_INVALID",
                "An agent references a model name that is not configured.",
                "Use a model name from the current agent configuration.",
            )
        unresolved_tools = set(agent.allowed_tools).difference(known_tool_references)
        if unresolved_tools:
            raise _error(
                "AGENT_CONFIG_REFERENCE_INVALID",
                "An agent tool entry is not in the supplied Tool Registry snapshot.",
                "Use exact published tool name and version references.",
            )
        try:
            prompt = prompt_registry.resolve(agent.prompt)
        except PromptRegistryError:
            raise _error(
                "AGENT_CONFIG_REFERENCE_INVALID",
                "An agent references a prompt that is not in the active catalog.",
                "Use an exact prompt ID from the current prompt catalog.",
            ) from None
        model = resolved_models[agent.model]
        profiles.append(
            ResolvedAgentProfile(
                name=agent.name,
                kind=agent.kind,
                description=agent.description,
                model_name=model.name,
                binding_id=model.binding_id,
                binding_version=model.binding_version,
                model_id=model.model_id,
                prompt_name=prompt.prompt_id,
                prompt_version=prompt.version,
                prompt_sha256=prompt.sha256,
                skill_version=agent.skill_version,
                graph_version=agent.graph_version,
                allowed_tools=tuple(sorted(agent.allowed_tools)),
                max_turns=agent.max_turns or document.subagents.default_max_turns,
                timeout_ms=agent.timeout_ms or document.subagents.default_timeout_ms,
            )
        )
    return tuple(sorted(profiles, key=lambda profile: profile.name))


def load_agent_runtime_configuration(
    config_path: str | Path,
    *,
    model_runtime: ConfiguredModelRuntime,
    prompt_registry: PromptRegistry,
    known_tool_references: frozenset[str] = frozenset(),
) -> ConfiguredAgentRuntime:
    """Load and resolve one strict, non-secret, offline agent configuration."""

    raw_path = str(config_path)
    if any(value in raw_path for value in ("\x00", "\r", "\n")):
        raise _error(
            "AGENT_CONFIG_PATH_DENIED",
            "The agent configuration path contains forbidden characters.",
            "Use one explicit local YAML path.",
        )
    source_path = Path(config_path).expanduser().resolve()
    document = _read_document(source_path)
    profiles = _resolve_profiles(
        document,
        model_runtime,
        prompt_registry,
        known_tool_references,
    )
    configuration_sha256 = canonical_sha256(
        {
            "document": document.model_dump(mode="json"),
            "model_registry_version": model_runtime.registry_version,
            "prompt_catalog_sha256": prompt_registry.catalog_sha256,
            "known_tool_references": sorted(known_tool_references),
        }
    )
    status = AgentRuntimeStatus(
        configuration_sha256=configuration_sha256,
        model_registry_version=model_runtime.registry_version,
        prompt_catalog_sha256=prompt_registry.catalog_sha256,
        models=len(document.models),
        prompts=len(prompt_registry.prompts),
        agents=len(profiles),
        general_agents=1,
    )
    return ConfiguredAgentRuntime(
        source_path=source_path,
        document=document,
        prompt_registry=prompt_registry,
        profiles=profiles,
        configuration_sha256=configuration_sha256,
        status=status,
    )
