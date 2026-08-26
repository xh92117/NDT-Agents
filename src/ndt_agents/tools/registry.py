"""Immutable shared Tool Registry with one validated execution path."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, NoReturn, Protocol, Self
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, ValidationError
from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel, TenantScope, ToolResult, ToolStatus
from ndt_agents.observability.audit import AuditKind, AuditOutcome, AuditRecord, AuditService
from ndt_agents.orchestration.budget import BudgetExceeded, BudgetGuard
from ndt_agents.tools.schema_policy import plaintext_secret_fields

TOOL_REGISTRY_CONTRACT_VERSION: Literal["1.1.0"] = "1.1.0"
DEFAULT_EXPOSED_TOOLS = 6
HARD_EXPOSED_TOOLS = 12
DEFAULT_MCP_NAMESPACES = 1
HARD_MCP_NAMESPACES = 2

_ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_REGISTRY_RESULT_ERROR_CODES = frozenset({"TOOL_TIMEOUT"})


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


class DefinitionOrigin(StrEnum):
    APPLICATION = "APPLICATION"
    UNTRUSTED = "UNTRUSTED"


class SideEffectClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    REVERSIBLE = "REVERSIBLE"
    IRREVERSIBLE = "IRREVERSIBLE"


class IdempotencyPolicy(StrEnum):
    NONE = "NONE"
    REQUIRED = "REQUIRED"


class NetworkPolicy(StrEnum):
    NONE = "NONE"
    RESTRICTED = "RESTRICTED"


class ToolKind(StrEnum):
    INTERNAL = "INTERNAL"
    BASH = "BASH"
    FUNCTION = "FUNCTION"
    WEB_SEARCH = "WEB_SEARCH"
    MCP = "MCP"
    INSTRUMENT = "INSTRUMENT"
    AI_MODEL = "AI_MODEL"


class ToolTransport(StrEnum):
    INTERNAL = "INTERNAL"
    BASH = "BASH"
    FUNCTION = "FUNCTION"
    HTTP_API = "HTTP_API"
    SDK = "SDK"
    DLL = "DLL"
    FILE_EXCHANGE = "FILE_EXCHANGE"
    MCP = "MCP"
    SIMULATOR = "SIMULATOR"


class ToolDataScope(StrEnum):
    TASK = "TASK"
    PROJECT = "PROJECT"
    TENANT = "TENANT"


class ToolDataDestination(StrEnum):
    LOCAL = "LOCAL"
    TENANT_MANAGED = "TENANT_MANAGED"
    APPROVED_EXTERNAL = "APPROVED_EXTERNAL"


class ToolRecoveryPolicy(StrEnum):
    NO_RETRY = "NO_RETRY"
    RETRY_READ_ONLY = "RETRY_READ_ONLY"
    RECONCILE = "RECONCILE"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class ToolDefinition(StrictModel):
    schema_version: Literal["1.1.0"] = TOOL_REGISTRY_CONTRACT_VERSION
    origin: DefinitionOrigin = DefinitionOrigin.APPLICATION
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    purpose: str = Field(min_length=1, max_length=1000)
    kind: ToolKind
    transport: ToolTransport
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    data_scope: ToolDataScope
    data_destination: ToolDataDestination
    side_effect: SideEffectClass
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permissions: frozenset[str] = frozenset()
    require_tenant_scope: bool = True
    require_project_scope: bool = True
    timeout_ms: int = Field(ge=1, le=3_600_000)
    max_attempts: int = Field(ge=1, le=3)
    max_concurrency: int = Field(ge=1, le=16)
    max_input_bytes: int = Field(ge=1, le=10_000_000)
    max_output_bytes: int = Field(ge=1, le=100_000_000)
    max_tokens: int = Field(ge=0, le=1_000_000)
    idempotency: IdempotencyPolicy
    secret_purposes: frozenset[str] = frozenset()
    network: NetworkPolicy = NetworkPolicy.NONE
    approval_required: bool = False
    declared_error_codes: frozenset[str] = Field(min_length=1, max_length=128)
    recovery_policy: ToolRecoveryPolicy
    audit_owner: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    test_owner: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    test_groups: frozenset[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.origin is not DefinitionOrigin.APPLICATION:
            raise ValueError("only application-owned tool definitions are publishable")
        if self.data_scope in {ToolDataScope.TASK, ToolDataScope.PROJECT} and not (
            self.require_tenant_scope and self.require_project_scope
        ):
            raise ValueError("task and project data scopes require tenant and project scope")
        if self.data_scope is ToolDataScope.TENANT and not self.require_tenant_scope:
            raise ValueError("tenant data scope requires tenant scope")
        if self.side_effect is not SideEffectClass.READ_ONLY:
            if self.idempotency is not IdempotencyPolicy.REQUIRED:
                raise ValueError("side-effecting tools require idempotency")
            if self.max_concurrency != 1:
                raise ValueError("side-effecting tools must be serial")
        if self.side_effect is SideEffectClass.IRREVERSIBLE and not self.approval_required:
            raise ValueError("irreversible tools require approval")
        if self.max_attempts > 1 and self.recovery_policy is not ToolRecoveryPolicy.RETRY_READ_ONLY:
            raise ValueError("multiple attempts require read-only retry recovery")
        if self.recovery_policy is ToolRecoveryPolicy.RETRY_READ_ONLY:
            if self.side_effect is not SideEffectClass.READ_ONLY or self.max_attempts < 2:
                raise ValueError("automatic retry requires a read-only tool and multiple attempts")
        if self.recovery_policy is ToolRecoveryPolicy.RECONCILE:
            if self.side_effect is SideEffectClass.READ_ONLY:
                raise ValueError("reconciliation is reserved for side-effecting tools")
        if self.recovery_policy is ToolRecoveryPolicy.HUMAN_REVIEW and not self.approval_required:
            raise ValueError("human-review recovery requires approval")
        if self.side_effect is not SideEffectClass.READ_ONLY and self.recovery_policy not in {
            ToolRecoveryPolicy.RECONCILE,
            ToolRecoveryPolicy.HUMAN_REVIEW,
        }:
            raise ValueError("side-effecting tools require reconciliation or human review")
        if self.data_destination is ToolDataDestination.APPROVED_EXTERNAL:
            if self.network is not NetworkPolicy.RESTRICTED:
                raise ValueError("external data destinations require restricted network policy")
        if self.kind is ToolKind.INTERNAL and self.transport is not ToolTransport.INTERNAL:
            raise ValueError("internal tools require the internal transport")
        if self.kind is ToolKind.BASH:
            if (
                self.transport is not ToolTransport.BASH
                or self.data_destination is not ToolDataDestination.LOCAL
                or self.network is not NetworkPolicy.NONE
            ):
                raise ValueError("Bash tools require local, network-free Bash transport")
        if self.kind is ToolKind.FUNCTION and self.transport is not ToolTransport.FUNCTION:
            raise ValueError("Function Calling tools require the function transport")
        if self.kind is ToolKind.WEB_SEARCH:
            if (
                self.transport is not ToolTransport.HTTP_API
                or self.side_effect is not SideEffectClass.READ_ONLY
                or self.network is not NetworkPolicy.RESTRICTED
                or self.data_destination is not ToolDataDestination.APPROVED_EXTERNAL
            ):
                raise ValueError("Web Search tools require read-only approved external HTTP access")
        if self.kind is ToolKind.MCP and self.transport is not ToolTransport.MCP:
            raise ValueError("MCP tools require MCP transport")
        if self.transport is ToolTransport.MCP and self.namespace is None:
            raise ValueError("MCP transport requires one namespace")
        if self.transport is not ToolTransport.MCP and self.namespace is not None:
            raise ValueError("only MCP transport may declare an MCP namespace")
        if self.kind is ToolKind.INSTRUMENT and self.transport not in {
            ToolTransport.BASH,
            ToolTransport.HTTP_API,
            ToolTransport.SDK,
            ToolTransport.DLL,
            ToolTransport.FILE_EXCHANGE,
            ToolTransport.MCP,
            ToolTransport.SIMULATOR,
        }:
            raise ValueError("instrument tools require a registered adapter transport")
        if self.kind is ToolKind.AI_MODEL:
            if (
                self.transport
                not in {
                    ToolTransport.BASH,
                    ToolTransport.HTTP_API,
                    ToolTransport.SDK,
                    ToolTransport.MCP,
                    ToolTransport.SIMULATOR,
                }
                or self.max_tokens < 1
            ):
                raise ValueError("AI-model tools require a model transport and token budget")
        for code in self.declared_error_codes:
            if _ERROR_CODE_PATTERN.fullmatch(code) is None:
                raise ValueError("declared tool error codes must be stable uppercase identifiers")
        for schema in (self.input_schema, self.output_schema):
            Draft202012Validator.check_schema(schema)
            if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
                raise ValueError("tool schemas must be strict object schemas")
        if plaintext_secret_fields(self.input_schema):
            raise ValueError("tool input schemas must use secret references, not plaintext fields")
        required_groups = {
            ToolKind.BASH: frozenset({"INT-BASH", "SEC-BASH", "SEC-TOOLS"}),
            ToolKind.FUNCTION: frozenset({"INT-FUNCTION", "SEC-TOOLS"}),
            ToolKind.WEB_SEARCH: frozenset({"INT-WEB", "SEC-TOOLS"}),
            ToolKind.MCP: frozenset({"INT-MCP", "SEC-TOOLS"}),
            ToolKind.INSTRUMENT: frozenset({"INT-INSTRUMENT", "SEC-TOOLS"}),
            ToolKind.AI_MODEL: frozenset({"UNIT-MODELREG", "INT-INSTRUMENT", "SEC-TOOLS"}),
        }.get(self.kind, frozenset())
        if not required_groups <= self.test_groups:
            raise ValueError("tool test groups do not cover the declared capability family")
        return self

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"


class ToolInvocationContext(StrictModel):
    schema_version: Literal["1.1.0"] = TOOL_REGISTRY_CONTRACT_VERSION
    task_id: UUID
    run_id: UUID
    scope: TenantScope
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    policy_version: str = Field(min_length=1, max_length=128)
    expected_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_tools: frozenset[str] = Field(min_length=1, max_length=HARD_EXPOSED_TOOLS)
    granted_permissions: frozenset[str] = frozenset()
    allowed_secret_purposes: frozenset[str] = frozenset()
    allowed_data_destinations: frozenset[ToolDataDestination] = Field(
        min_length=1, max_length=len(ToolDataDestination)
    )
    approved_call_sha256s: frozenset[str] = Field(
        default=frozenset(), max_length=HARD_EXPOSED_TOOLS
    )
    allow_network: bool = False

    @model_validator(mode="after")
    def validate_approval_bindings(self) -> Self:
        if any(not _is_sha256(value) for value in self.approved_call_sha256s):
            raise ValueError("approval bindings must be SHA-256 values")
        return self


class ToolInvocation(StrictModel):
    schema_version: Literal["1.1.0"] = TOOL_REGISTRY_CONTRACT_VERSION
    call_id: UUID
    context: ToolInvocationContext
    definition: ToolDefinition
    arguments: dict[str, Any]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt_number: int = Field(ge=1, le=3)
    idempotency_key: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
    )


class ToolExposurePolicy(StrictModel):
    schema_version: Literal["1.1.0"] = TOOL_REGISTRY_CONTRACT_VERSION
    max_tools: int = Field(default=DEFAULT_EXPOSED_TOOLS, ge=1, le=HARD_EXPOSED_TOOLS)
    max_mcp_namespaces: int = Field(default=DEFAULT_MCP_NAMESPACES, ge=1, le=HARD_MCP_NAMESPACES)
    allow_side_effects: bool = False
    allow_approval_required: bool = False


class ExposedTool(StrictModel):
    schema_version: Literal["1.1.0"] = TOOL_REGISTRY_CONTRACT_VERSION
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    kind: ToolKind
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    purpose: str = Field(min_length=1, max_length=1000)
    side_effect: SideEffectClass
    approval_required: bool
    input_schema: dict[str, Any]


class ToolExposureManifest(StrictModel):
    schema_version: Literal["1.1.0"] = TOOL_REGISTRY_CONTRACT_VERSION
    registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    tools: tuple[ExposedTool, ...] = Field(max_length=HARD_EXPOSED_TOOLS)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if len({f"{tool.name}@{tool.version}" for tool in self.tools}) != len(self.tools):
            raise ValueError("exposed tools must be unique")
        payload = {
            "registry_version": self.registry_version,
            "tools": [tool.model_dump(mode="json") for tool in self.tools],
        }
        if self.manifest_sha256 != canonical_sha256(payload):
            raise ValueError("tool exposure manifest hash is invalid")
        return self


class ToolAdapter(Protocol):
    async def execute(self, invocation: ToolInvocation) -> ToolResult: ...


class ToolRegistryError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool, next_action: str) -> None:
        self.code = code
        self.retryable = retryable
        self.next_action = next_action
        super().__init__(message)


def canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ToolRegistryError(
            "TOOL_PAYLOAD_INVALID",
            "The tool payload is not canonical JSON.",
            retryable=False,
            next_action="Provide a JSON-compatible payload.",
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def tool_approval_binding_sha256(
    context: ToolInvocationContext,
    definition: ToolDefinition,
    input_sha256: str,
) -> str:
    """Bind an upstream approval decision to one exact scoped tool input."""

    if not _is_sha256(input_sha256):
        raise ToolRegistryError(
            "TOOL_APPROVAL_BINDING_INVALID",
            "The approval binding input hash is invalid.",
            retryable=False,
            next_action="Bind approval to the canonical tool input SHA-256.",
        )
    return canonical_sha256(
        {
            "schema_version": TOOL_REGISTRY_CONTRACT_VERSION,
            "task_id": str(context.task_id),
            "run_id": str(context.run_id),
            "scope": context.scope.model_dump(mode="json"),
            "policy_version": context.policy_version,
            "registry_version": context.expected_registry_version,
            "tool_key": definition.key,
            "input_sha256": input_sha256,
        }
    )


def _scope_key(scope: TenantScope) -> tuple[UUID, UUID, UUID, tuple[str, ...], str]:
    return (
        scope.tenant_id,
        scope.project_id,
        scope.user_id,
        scope.role_codes,
        scope.permission_version,
    )


class ToolRegistry:
    """Published definitions plus the only supported adapter execution gateway."""

    def __init__(
        self,
        definitions: Sequence[ToolDefinition],
        adapters: Mapping[str, ToolAdapter],
        *,
        audit: AuditService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        by_key: dict[str, ToolDefinition] = {}
        for definition in definitions:
            if definition.origin is not DefinitionOrigin.APPLICATION or definition.key in by_key:
                raise ToolRegistryError(
                    "TOOL_DEFINITION_REJECTED",
                    "The tool definition is untrusted or duplicated.",
                    retryable=False,
                    next_action="Publish one application-owned definition per name and version.",
                )
            by_key[definition.key] = definition
        if set(adapters) != set(by_key):
            raise ToolRegistryError(
                "TOOL_ADAPTER_BINDING_INVALID",
                "Every published definition requires exactly one registered adapter.",
                retryable=False,
                next_action="Align adapter keys with the published definitions.",
            )
        manifest = [by_key[key].model_dump(mode="json") for key in sorted(by_key)]
        self._definitions = by_key
        self._adapters = dict(adapters)
        self._version = canonical_sha256(manifest)
        self._audit = audit
        self._clock = clock
        self._journal: dict[
            tuple[tuple[UUID, UUID, UUID, tuple[str, ...], str], str, str],
            tuple[str, ToolResult | None],
        ] = {}
        self._semaphores = {
            key: asyncio.Semaphore(definition.max_concurrency) for key, definition in by_key.items()
        }

    @property
    def version(self) -> str:
        return self._version

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def resolve(self, name: str, version: str) -> ToolDefinition:
        definition = self._definitions.get(f"{name}@{version}")
        if definition is None:
            raise ToolRegistryError(
                "TOOL_UNREGISTERED",
                "The requested tool definition is not published.",
                retryable=False,
                next_action="Use a tool and version from the current registry snapshot.",
            )
        return definition

    def expose(
        self,
        context: ToolInvocationContext,
        *,
        policy: ToolExposurePolicy | None = None,
    ) -> ToolExposureManifest:
        """Return the minimal authorized function surface for one child context."""

        selected_policy = policy or ToolExposurePolicy()
        input_sha256 = canonical_sha256(
            {
                "registry_version": context.expected_registry_version,
                "allowed_tools": sorted(context.allowed_tools),
                "granted_permissions": sorted(context.granted_permissions),
                "allowed_secret_purposes": sorted(context.allowed_secret_purposes),
                "allowed_data_destinations": sorted(context.allowed_data_destinations),
                "allow_network": context.allow_network,
                "policy": selected_policy.model_dump(mode="json"),
            }
        )
        try:
            if context.expected_registry_version != self.version:
                self._deny("TOOL_REGISTRY_STALE", "The caller uses a stale registry version.")
            definitions = tuple(
                self._definition_for_allowed_token(token) for token in sorted(context.allowed_tools)
            )
            if len({definition.key for definition in definitions}) != len(definitions):
                self._deny(
                    "TOOL_EXPOSURE_DUPLICATE",
                    "The requested tool exposure contains duplicate definitions.",
                )
            if len(definitions) > selected_policy.max_tools:
                self._deny(
                    "TOOL_EXPOSURE_LIMIT",
                    "The requested tool exposure exceeds the active function limit.",
                )
            namespaces = {
                definition.namespace
                for definition in definitions
                if definition.transport is ToolTransport.MCP and definition.namespace is not None
            }
            if len(namespaces) > selected_policy.max_mcp_namespaces:
                self._deny(
                    "TOOL_MCP_NAMESPACE_LIMIT",
                    "The requested exposure exceeds the active MCP namespace limit.",
                )
            tools: list[ExposedTool] = []
            for definition in definitions:
                self._authorize_definition(definition, context)
                if (
                    definition.side_effect is not SideEffectClass.READ_ONLY
                    and not selected_policy.allow_side_effects
                ):
                    self._deny(
                        "TOOL_EXPOSURE_SIDE_EFFECT_DENIED",
                        "The exposure policy does not allow side-effecting tools.",
                    )
                if definition.approval_required and not selected_policy.allow_approval_required:
                    self._deny(
                        "TOOL_EXPOSURE_APPROVAL_DENIED",
                        "The exposure policy does not allow approval-gated tools.",
                    )
                tools.append(
                    ExposedTool(
                        name=definition.name,
                        version=definition.version,
                        kind=definition.kind,
                        namespace=definition.namespace,
                        purpose=definition.purpose,
                        side_effect=definition.side_effect,
                        approval_required=definition.approval_required,
                        input_schema=definition.input_schema,
                    )
                )
            payload = {
                "registry_version": self.version,
                "tools": [tool.model_dump(mode="json") for tool in tools],
            }
            manifest = ToolExposureManifest(
                registry_version=self.version,
                tools=tuple(tools),
                manifest_sha256=canonical_sha256(payload),
            )
            self._record_target(
                context,
                target_id=self.version,
                action="tool.expose",
                decision="AUTHORIZED",
                outcome=AuditOutcome.SUCCESS,
                input_sha256=input_sha256,
                output_sha256=manifest.manifest_sha256,
            )
            return manifest
        except ToolRegistryError as error:
            self._record_target(
                context,
                target_id=self.version,
                action="tool.expose",
                decision=error.code,
                outcome=AuditOutcome.DENIED,
                input_sha256=input_sha256,
                output_sha256=canonical_sha256({"error_code": error.code}),
            )
            raise

    async def invoke(
        self,
        *,
        name: str,
        version: str,
        arguments: Mapping[str, Any],
        context: ToolInvocationContext,
        budget: BudgetGuard,
        observation_sha256: str,
        idempotency_key: str | None = None,
        retry: bool = False,
        attempt_number: int = 1,
    ) -> ToolResult:
        started = time.monotonic()
        call_id = uuid4()
        encoded_arguments = dict(arguments)
        input_sha256 = canonical_sha256(encoded_arguments)
        definition: ToolDefinition | None = None
        reservation_id: UUID | None = None
        try:
            definition = self.resolve(name, version)
            self._preflight(
                definition,
                encoded_arguments,
                context,
                input_sha256,
                idempotency_key,
                retry,
                attempt_number,
            )
            journal_key = self._journal_key(context.scope, definition.key, idempotency_key)
            if journal_key is not None:
                existing = self._journal.get(journal_key)
                if existing is not None:
                    if existing[0] != input_sha256:
                        self._deny(
                            "TOOL_IDEMPOTENCY_CONFLICT",
                            "The idempotency key is bound to different input.",
                        )
                    if existing[1] is None:
                        self._deny(
                            "TOOL_RECONCILIATION_REQUIRED",
                            "A prior side effect has no committed result.",
                        )
                    committed = existing[1]
                    assert committed is not None
                    self._record(
                        context,
                        definition,
                        "tool.replay",
                        "REUSED",
                        AuditOutcome.SUCCESS,
                        input_sha256,
                        committed.output_sha256 or canonical_sha256({}),
                    )
                    return committed
            reservation_id = budget.begin_tool_call(
                tool_name=name,
                tool_version=version,
                arguments=encoded_arguments,
                observation_sha256=observation_sha256,
                retry=retry,
            )
            invocation = ToolInvocation(
                call_id=call_id,
                context=context,
                definition=definition,
                arguments=encoded_arguments,
                input_sha256=input_sha256,
                attempt_number=attempt_number,
                idempotency_key=idempotency_key,
            )
            if journal_key is not None:
                self._journal[journal_key] = (input_sha256, None)
            async with self._semaphores[definition.key]:
                try:
                    async with asyncio.timeout(definition.timeout_ms / 1000):
                        result = await self._adapters[definition.key].execute(invocation)
                except TimeoutError:
                    result = self._timeout_result(invocation, started)
            self._validate_result(invocation, result)
            budget.complete_tool_call(reservation_id, success=result.status is ToolStatus.SUCCESS)
            reservation_id = None
            if journal_key is not None and result.status is ToolStatus.SUCCESS:
                self._journal[journal_key] = (input_sha256, result)
            outcome = (
                AuditOutcome.SUCCESS if result.status is ToolStatus.SUCCESS else AuditOutcome.FAILED
            )
            self._record(
                context,
                definition,
                "tool.execute",
                result.error_code or result.status.value,
                outcome,
                input_sha256,
                result.output_sha256 or canonical_sha256({}),
            )
            return result
        except (ToolRegistryError, BudgetExceeded, ValidationError) as error:
            if reservation_id is not None:
                budget.complete_tool_call(reservation_id, success=False)
            code = getattr(error, "code", "TOOL_SCHEMA_INVALID")
            if definition is not None:
                self._record(
                    context,
                    definition,
                    "tool.deny",
                    code,
                    AuditOutcome.DENIED,
                    input_sha256,
                    canonical_sha256({"error_code": code}),
                )
            else:
                self._record_target(
                    context,
                    target_id=f"{name}:{version}",
                    action="tool.deny",
                    decision=code,
                    outcome=AuditOutcome.DENIED,
                    input_sha256=input_sha256,
                    output_sha256=canonical_sha256({"error_code": code}),
                )
            if isinstance(error, ToolRegistryError):
                raise
            raise ToolRegistryError(
                code,
                "The tool invocation was denied before a valid result was available.",
                retryable=False,
                next_action="Correct the request or budget state before retrying.",
            ) from error

    def _preflight(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
        input_sha256: str,
        idempotency_key: str | None,
        retry: bool,
        attempt_number: int,
    ) -> None:
        self._authorize_definition(definition, context)
        if definition.kind is ToolKind.AI_MODEL:
            self._deny(
                "TOOL_MODEL_GATEWAY_REQUIRED",
                "AI-model capabilities require the separately metered model gateway.",
            )
        if attempt_number > definition.max_attempts:
            self._deny("TOOL_ATTEMPT_LIMIT", "The declared tool attempt limit was exceeded.")
        if retry != (attempt_number > 1):
            self._deny(
                "TOOL_RETRY_STATE_INVALID",
                "Retry state and attempt number do not match.",
            )
        if retry and definition.recovery_policy is not ToolRecoveryPolicy.RETRY_READ_ONLY:
            self._deny("TOOL_RETRY_DENIED", "The tool does not permit automatic retry.")
        if definition.approval_required:
            binding = tool_approval_binding_sha256(context, definition, input_sha256)
            if binding not in context.approved_call_sha256s:
                self._deny(
                    "TOOL_APPROVAL_REQUIRED",
                    "The exact scoped tool input lacks an approval binding.",
                )
        if definition.idempotency is IdempotencyPolicy.REQUIRED and idempotency_key is None:
            self._deny("TOOL_IDEMPOTENCY_REQUIRED", "The side effect requires an idempotency key.")
        input_bytes = len(
            json.dumps(arguments, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if input_bytes > definition.max_input_bytes:
            self._deny("TOOL_INPUT_TOO_LARGE", "The tool input exceeds its byte budget.")
        Draft202012Validator(definition.input_schema).validate(arguments)

    def _authorize_definition(
        self,
        definition: ToolDefinition,
        context: ToolInvocationContext,
    ) -> None:
        if context.expected_registry_version != self.version:
            self._deny("TOOL_REGISTRY_STALE", "The caller is bound to a stale registry version.")
        if (
            definition.key not in context.allowed_tools
            and definition.name not in context.allowed_tools
        ):
            self._deny("TOOL_NOT_ALLOWED", "The tool is outside the task allowlist.")
        if not definition.required_permissions <= context.granted_permissions:
            self._deny("TOOL_PERMISSION_DENIED", "The task lacks a required tool permission.")
        if not definition.secret_purposes <= context.allowed_secret_purposes:
            self._deny("TOOL_SECRET_PURPOSE_DENIED", "The task lacks a required secret purpose.")
        if definition.network is not NetworkPolicy.NONE and not context.allow_network:
            self._deny("TOOL_NETWORK_DENIED", "The task does not permit network access.")
        if definition.data_destination not in context.allowed_data_destinations:
            self._deny(
                "TOOL_DATA_DESTINATION_DENIED",
                "The task does not allow the tool data destination.",
            )

    def _definition_for_allowed_token(self, token: str) -> ToolDefinition:
        if "@" in token:
            definition = self._definitions.get(token)
            if definition is None:
                self._deny(
                    "TOOL_EXPOSURE_TOOL_INVALID",
                    "The exposure references an unpublished tool version.",
                )
            return definition
        matches = [item for item in self._definitions.values() if item.name == token]
        if len(matches) != 1:
            self._deny(
                "TOOL_EXPOSURE_TOOL_INVALID",
                "The exposure tool name is missing or version-ambiguous.",
            )
        return matches[0]

    def _validate_result(self, invocation: ToolInvocation, result: ToolResult) -> None:
        expected = invocation.context
        if (
            result.call_id != invocation.call_id
            or result.task_id != expected.task_id
            or result.run_id != expected.run_id
            or result.scope != expected.scope
            or result.tool_name != invocation.definition.name
            or result.tool_version != invocation.definition.version
            or result.input_sha256 != invocation.input_sha256
            or result.idempotency_key != invocation.idempotency_key
        ):
            self._deny(
                "TOOL_RESULT_IDENTITY_INVALID",
                "The ToolResult identity does not match the invocation.",
            )
        output_hash = canonical_sha256(result.output)
        if result.output_sha256 != output_hash:
            self._deny("TOOL_RESULT_HASH_INVALID", "The ToolResult output hash is invalid.")
        output_bytes = len(
            json.dumps(result.output, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if output_bytes > invocation.definition.max_output_bytes:
            self._deny("TOOL_OUTPUT_TOO_LARGE", "The ToolResult exceeds its byte budget.")
        if result.status is ToolStatus.SUCCESS and result.error_code is not None:
            self._deny(
                "TOOL_RESULT_ERROR_UNEXPECTED",
                "A successful ToolResult cannot declare an error code.",
            )
        if result.status is not ToolStatus.SUCCESS:
            if result.error_code is None:
                self._deny(
                    "TOOL_RESULT_ERROR_MISSING",
                    "A non-success ToolResult requires an error code.",
                )
            if result.error_code not in (
                invocation.definition.declared_error_codes | _REGISTRY_RESULT_ERROR_CODES
            ):
                self._deny(
                    "TOOL_RESULT_ERROR_UNDECLARED",
                    "The ToolResult returned an undeclared error code.",
                )
        if result.retryable and (
            invocation.definition.side_effect is not SideEffectClass.READ_ONLY
            or invocation.definition.recovery_policy is not ToolRecoveryPolicy.RETRY_READ_ONLY
        ):
            self._deny(
                "TOOL_RESULT_RETRY_INVALID",
                "The ToolResult retry flag conflicts with the declared recovery policy.",
            )
        if result.status is not ToolStatus.TIMEOUT:
            Draft202012Validator(invocation.definition.output_schema).validate(result.output)

    def _timeout_result(self, invocation: ToolInvocation, started: float) -> ToolResult:
        output: dict[str, Any] = {}
        return ToolResult(
            call_id=invocation.call_id,
            task_id=invocation.context.task_id,
            run_id=invocation.context.run_id,
            scope=invocation.context.scope,
            tool_name=invocation.definition.name,
            tool_version=invocation.definition.version,
            status=ToolStatus.TIMEOUT,
            output=output,
            exit_code=None,
            stdout="",
            stderr="",
            encoding=None,
            truncated=False,
            artifacts=(),
            idempotency_key=invocation.idempotency_key,
            input_sha256=invocation.input_sha256,
            output_sha256=canonical_sha256(output),
            error_code="TOOL_TIMEOUT",
            retryable=(invocation.definition.recovery_policy is ToolRecoveryPolicy.RETRY_READ_ONLY),
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            completed_at=self._clock(),
        )

    def _record(
        self,
        context: ToolInvocationContext,
        definition: ToolDefinition,
        action: str,
        decision: str,
        outcome: AuditOutcome,
        input_sha256: str,
        output_sha256: str,
    ) -> None:
        self._record_target(
            context,
            target_id=f"{definition.name}:{definition.version}",
            action=action,
            decision=decision,
            outcome=outcome,
            input_sha256=input_sha256,
            output_sha256=output_sha256,
        )

    def _record_target(
        self,
        context: ToolInvocationContext,
        *,
        target_id: str,
        action: str,
        decision: str,
        outcome: AuditOutcome,
        input_sha256: str,
        output_sha256: str,
    ) -> None:
        self._audit.record(
            AuditRecord(
                event_id=uuid4(),
                scope=context.scope,
                kind=AuditKind.TOOL,
                action=action,
                target_type="tool",
                target_id=target_id,
                task_id=context.task_id,
                policy_version=context.policy_version,
                decision=decision,
                outcome=outcome,
                input_sha256=input_sha256,
                output_sha256=output_sha256,
                request_id=context.request_id,
                occurred_at=self._clock(),
            )
        )

    @staticmethod
    def _journal_key(
        scope: TenantScope, tool_key: str, idempotency_key: str | None
    ) -> tuple[tuple[UUID, UUID, UUID, tuple[str, ...], str], str, str] | None:
        if idempotency_key is None:
            return None
        return _scope_key(scope), tool_key, idempotency_key

    @staticmethod
    def _deny(code: str, message: str) -> NoReturn:
        raise ToolRegistryError(
            code,
            message,
            retryable=False,
            next_action="Correct the tool request and retry through the current registry.",
        )
