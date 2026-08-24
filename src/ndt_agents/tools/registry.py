"""Immutable shared Tool Registry with one validated execution path."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, Self
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, ValidationError
from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel, TenantScope, ToolResult, ToolStatus
from ndt_agents.observability.audit import AuditKind, AuditOutcome, AuditRecord, AuditService
from ndt_agents.orchestration.budget import BudgetExceeded, BudgetGuard

TOOL_REGISTRY_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"


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


class ToolDefinition(StrictModel):
    schema_version: Literal["1.0.0"] = TOOL_REGISTRY_CONTRACT_VERSION
    origin: DefinitionOrigin = DefinitionOrigin.APPLICATION
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    purpose: str = Field(min_length=1, max_length=1000)
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
    audit_owner: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    test_groups: frozenset[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.origin is not DefinitionOrigin.APPLICATION:
            raise ValueError("only application-owned tool definitions are publishable")
        if self.side_effect is not SideEffectClass.READ_ONLY:
            if self.idempotency is not IdempotencyPolicy.REQUIRED:
                raise ValueError("side-effecting tools require idempotency")
            if self.max_concurrency != 1:
                raise ValueError("side-effecting tools must be serial")
        for schema in (self.input_schema, self.output_schema):
            Draft202012Validator.check_schema(schema)
            if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
                raise ValueError("tool schemas must be strict object schemas")
        return self

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"


class ToolInvocationContext(StrictModel):
    schema_version: Literal["1.0.0"] = TOOL_REGISTRY_CONTRACT_VERSION
    task_id: UUID
    run_id: UUID
    scope: TenantScope
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    policy_version: str = Field(min_length=1, max_length=128)
    expected_registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_tools: frozenset[str] = Field(min_length=1)
    granted_permissions: frozenset[str] = frozenset()
    allowed_secret_purposes: frozenset[str] = frozenset()
    allow_network: bool = False


class ToolInvocation(StrictModel):
    schema_version: Literal["1.0.0"] = TOOL_REGISTRY_CONTRACT_VERSION
    call_id: UUID
    context: ToolInvocationContext
    definition: ToolDefinition
    arguments: dict[str, Any]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
    )


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
    ) -> ToolResult:
        started = time.monotonic()
        call_id = uuid4()
        encoded_arguments = dict(arguments)
        input_sha256 = canonical_sha256(encoded_arguments)
        definition: ToolDefinition | None = None
        reservation_id: UUID | None = None
        try:
            definition = self.resolve(name, version)
            self._preflight(definition, encoded_arguments, context, idempotency_key)
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
                result.status.value,
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
        idempotency_key: str | None,
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
        if definition.idempotency is IdempotencyPolicy.REQUIRED and idempotency_key is None:
            self._deny("TOOL_IDEMPOTENCY_REQUIRED", "The side effect requires an idempotency key.")
        input_bytes = len(
            json.dumps(arguments, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if input_bytes > definition.max_input_bytes:
            self._deny("TOOL_INPUT_TOO_LARGE", "The tool input exceeds its byte budget.")
        Draft202012Validator(definition.input_schema).validate(arguments)

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
            retryable=invocation.definition.side_effect is SideEffectClass.READ_ONLY,
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
    def _deny(code: str, message: str) -> None:
        raise ToolRegistryError(
            code,
            message,
            retryable=False,
            next_action="Correct the tool request and retry through the current registry.",
        )
