"""Policy-bound MCP gateway with exact discovery and scoped async state."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Any, Literal, Protocol, Self
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from ndt_agents.contracts.v1 import ArtifactRef, StrictModel, TenantScope, ToolResult, ToolStatus
from ndt_agents.tools.registry import (
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolDataDestination,
    ToolDataScope,
    ToolDefinition,
    ToolInvocation,
    ToolKind,
    ToolRecoveryPolicy,
    ToolTransport,
    canonical_sha256,
)
from ndt_agents.tools.schema_policy import plaintext_secret_fields

MCP_GATEWAY_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_MCP_CREDENTIAL_SECONDS = 300
MAX_MCP_DISCOVERY_SECONDS = 3_600
MAX_MCP_CAPABILITIES = 32
MAX_MCP_CHUNKS = 128
MAX_MCP_STREAM_BYTES = 1_000_000

_IDENTIFIER = r"^[a-z][a-z0-9_.-]{0,127}$"
_CAPABILITY = r"^[a-z][a-z0-9_-]{0,63}$"
_SEMVER = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_HANDLE = r"^mcp-task-[0-9a-f]{32}$"
_REMOTE_TASK = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
_MCP_ERRORS = frozenset(
    {
        "MCP_ARTIFACT_INVALID",
        "MCP_CANCELLED",
        "MCP_CREDENTIAL_FAILED",
        "MCP_DISCOVERY_REQUIRED",
        "MCP_DISCONNECTED",
        "MCP_PROVIDER_FAILED",
        "MCP_RESPONSE_INVALID",
        "MCP_SCHEMA_CHANGED",
        "MCP_SCOPE_DENIED",
        "MCP_STATE_INVALID",
        "MCP_STREAM_INVALID",
    }
)


class McpDeployment(StrEnum):
    LOCAL = "LOCAL"
    REMOTE = "REMOTE"


class McpOperation(StrEnum):
    DISCOVER = "DISCOVER"
    INVOKE = "INVOKE"
    POLL = "POLL"
    CANCEL = "CANCEL"


class McpTransportStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    COMPLETED = "COMPLETED"
    ACCEPTED = "ACCEPTED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"


class McpAsyncState(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class McpServerRegistration(StrictModel):
    schema_version: Literal["1.0.0"] = MCP_GATEWAY_CONTRACT_VERSION
    server_id: str = Field(pattern=_IDENTIFIER)
    server_version: str = Field(pattern=_SEMVER)
    namespace: str = Field(pattern=_IDENTIFIER)
    deployment: McpDeployment
    endpoint: str = Field(min_length=1, max_length=2048)
    audience: str = Field(pattern=_IDENTIFIER)
    policy_version: str = Field(pattern=_IDENTIFIER)
    discovery_permission: str = Field(pattern=_IDENTIFIER)
    discovery_ttl_seconds: int = Field(default=300, ge=30, le=MAX_MCP_DISCOVERY_SECONDS)
    secret_purpose: str | None = Field(default=None, pattern=_IDENTIFIER)
    registration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("endpoint", mode="before")
    @classmethod
    def canonicalize_endpoint(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return _canonical_mcp_endpoint(value)

    @model_validator(mode="after")
    def validate_registration(self) -> Self:
        scheme = urlsplit(self.endpoint).scheme
        if self.deployment is McpDeployment.REMOTE:
            if scheme != "https" or self.secret_purpose is None:
                raise ValueError("remote MCP servers require HTTPS and a secret purpose")
        elif scheme != "mcp+local" or self.secret_purpose is not None:
            raise ValueError("local MCP servers require credential-free mcp+local endpoints")
        if self.registration_sha256 != mcp_server_registration_sha256(self):
            raise ValueError("MCP server registration hash is invalid")
        return self


class McpCapabilityRegistration(StrictModel):
    schema_version: Literal["1.0.0"] = MCP_GATEWAY_CONTRACT_VERSION
    name: str = Field(pattern=_CAPABILITY)
    version: str = Field(pattern=_SEMVER)
    purpose: str = Field(min_length=1, max_length=1000)
    permission: str = Field(pattern=_IDENTIFIER)
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY
    approval_required: bool = False
    data_destination: ToolDataDestination
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    timeout_ms: int = Field(ge=1, le=3_600_000)
    supports_streaming: bool = False
    supports_async: bool = False
    max_chunks: int = Field(default=32, ge=1, le=MAX_MCP_CHUNKS)
    max_stream_bytes: int = Field(default=100_000, ge=1, le=MAX_MCP_STREAM_BYTES)
    max_inline_bytes: int = Field(default=32_000, ge=256, le=1_000_000)
    capability_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_capability(self) -> Self:
        for schema in (self.input_schema, self.output_schema):
            Draft202012Validator.check_schema(schema)
            if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
                raise ValueError("MCP capability schemas must be strict objects")
        if plaintext_secret_fields(self.input_schema):
            raise ValueError("MCP input schemas cannot accept plaintext credential fields")
        if self.side_effect is SideEffectClass.IRREVERSIBLE and not self.approval_required:
            raise ValueError("irreversible MCP capabilities require approval")
        if self.capability_sha256 != mcp_capability_registration_sha256(self):
            raise ValueError("MCP capability registration hash is invalid")
        return self


class McpDiscoveredCapability(StrictModel):
    name: str = Field(pattern=_CAPABILITY)
    version: str = Field(pattern=_SEMVER)
    input_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    side_effect: SideEffectClass
    supports_streaming: bool
    supports_async: bool


class McpDiscoveryManifest(StrictModel):
    schema_version: Literal["1.0.0"] = MCP_GATEWAY_CONTRACT_VERSION
    server_id: str = Field(pattern=_IDENTIFIER)
    server_version: str = Field(pattern=_SEMVER)
    namespace: str = Field(pattern=_IDENTIFIER)
    registration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capabilities: tuple[McpDiscoveredCapability, ...] = Field(
        min_length=1, max_length=MAX_MCP_CAPABILITIES
    )
    discovered_at: datetime
    expires_at: datetime
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        _require_utc(self.discovered_at, "MCP discovery time")
        _require_utc(self.expires_at, "MCP discovery expiry time")
        if not self.discovered_at < self.expires_at:
            raise ValueError("MCP discovery expiry must follow discovery time")
        if self.expires_at - self.discovered_at > timedelta(seconds=MAX_MCP_DISCOVERY_SECONDS):
            raise ValueError("MCP discovery manifest exceeds the hard lifetime")
        names = tuple(item.name for item in self.capabilities)
        if names != tuple(sorted(set(names))):
            raise ValueError("discovered MCP capabilities must be sorted and unique")
        if self.manifest_sha256 != mcp_discovery_manifest_sha256(self):
            raise ValueError("MCP discovery manifest hash is invalid")
        return self


class McpCredentialRequest(StrictModel):
    schema_version: Literal["1.0.0"] = MCP_GATEWAY_CONTRACT_VERSION
    scope: TenantScope
    task_id: UUID
    run_id: UUID
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    server_id: str = Field(pattern=_IDENTIFIER)
    audience: str = Field(pattern=_IDENTIFIER)
    permission: str = Field(pattern=_IDENTIFIER)
    secret_purpose: str = Field(pattern=_IDENTIFIER)
    policy_version: str = Field(pattern=_IDENTIFIER)
    requested_expires_at: datetime

    @model_validator(mode="after")
    def validate_expiry(self) -> Self:
        _require_utc(self.requested_expires_at, "MCP credential request expiry")
        return self


class McpCredentialLease(StrictModel):
    schema_version: Literal["1.0.0"] = MCP_GATEWAY_CONTRACT_VERSION
    scope: TenantScope
    task_id: UUID
    run_id: UUID
    server_id: str = Field(pattern=_IDENTIFIER)
    audience: str = Field(pattern=_IDENTIFIER)
    permission: str = Field(pattern=_IDENTIFIER)
    secret_purpose: str = Field(pattern=_IDENTIFIER)
    policy_version: str = Field(pattern=_IDENTIFIER)
    issued_at: datetime
    expires_at: datetime
    value: SecretStr = Field(exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        _require_utc(self.issued_at, "MCP credential issue time")
        _require_utc(self.expires_at, "MCP credential expiry time")
        if not self.issued_at < self.expires_at:
            raise ValueError("MCP credential lease expiry must follow issue time")
        if self.expires_at - self.issued_at > timedelta(seconds=MAX_MCP_CREDENTIAL_SECONDS):
            raise ValueError("MCP credential lease exceeds the hard lifetime")
        return self


class McpChunk(StrictModel):
    index: int = Field(ge=0, le=MAX_MCP_CHUNKS - 1)
    media_type: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=MAX_MCP_STREAM_BYTES)


class McpTransportRequest(StrictModel):
    schema_version: Literal["1.0.0"] = MCP_GATEWAY_CONTRACT_VERSION
    operation: McpOperation
    server_id: str = Field(pattern=_IDENTIFIER)
    server_version: str = Field(pattern=_SEMVER)
    endpoint: str = Field(min_length=1, max_length=2048)
    namespace: str = Field(pattern=_IDENTIFIER)
    capability_name: str | None = Field(default=None, pattern=_CAPABILITY)
    capability_version: str | None = Field(default=None, pattern=_SEMVER)
    arguments: dict[str, Any]
    remote_task_id: str | None = Field(default=None, pattern=_REMOTE_TASK)
    discovery_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class McpTransportReply(StrictModel):
    schema_version: Literal["1.0.0"] = MCP_GATEWAY_CONTRACT_VERSION
    status: McpTransportStatus
    server_id: str = Field(pattern=_IDENTIFIER)
    server_version: str = Field(pattern=_SEMVER)
    capabilities: tuple[McpDiscoveredCapability, ...] = Field(
        default=(), max_length=MAX_MCP_CAPABILITIES
    )
    output: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(min_length=1, max_length=4000)
    remote_task_id: str | None = Field(default=None, pattern=_REMOTE_TASK)
    chunks: tuple[McpChunk, ...] = Field(default=(), max_length=MAX_MCP_CHUNKS)
    artifacts: tuple[ArtifactRef, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_reply(self) -> Self:
        if self.status is McpTransportStatus.DISCOVERED:
            if (
                not self.capabilities
                or self.remote_task_id is not None
                or self.output
                or self.chunks
            ):
                raise ValueError("MCP discovery response fields are inconsistent")
        elif self.status in {McpTransportStatus.ACCEPTED, McpTransportStatus.PENDING}:
            if self.remote_task_id is None or self.capabilities or self.output or self.chunks:
                raise ValueError("MCP pending response fields are inconsistent")
        elif self.status is McpTransportStatus.CANCELLED:
            if self.remote_task_id is None or self.capabilities or self.output or self.chunks:
                raise ValueError("MCP cancellation response fields are inconsistent")
        elif self.capabilities or self.remote_task_id is not None:
            raise ValueError("MCP completed response fields are inconsistent")
        return self


class McpGatewayOutput(StrictModel):
    schema_version: Literal["1.0.0"] = MCP_GATEWAY_CONTRACT_VERSION
    operation: McpOperation
    trust: Literal["UNTRUSTED"] = "UNTRUSTED"
    state: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    summary: str = Field(min_length=1, max_length=4000)
    handle: str | None = Field(default=None, pattern=_HANDLE)
    content: dict[str, Any]
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    record_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class McpAsyncRecord(StrictModel):
    schema_version: Literal["1.0.0"] = MCP_GATEWAY_CONTRACT_VERSION
    handle: str = Field(pattern=_HANDLE)
    scope: TenantScope
    task_id: UUID
    run_id: UUID
    server_id: str = Field(pattern=_IDENTIFIER)
    server_version: str = Field(pattern=_SEMVER)
    capability_name: str = Field(pattern=_CAPABILITY)
    capability_version: str = Field(pattern=_SEMVER)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    discovery_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    remote_task_id: str = Field(pattern=_REMOTE_TASK)
    state: McpAsyncState
    summary: str = Field(min_length=1, max_length=4000)
    artifacts: tuple[ArtifactRef, ...] = Field(default=(), max_length=32)
    updated_at: datetime
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        _require_utc(self.updated_at, "MCP async update time")
        if self.record_sha256 != mcp_async_record_sha256(self):
            raise ValueError("MCP async record hash is invalid")
        return self


class McpToolBinding(StrictModel):
    definition: ToolDefinition
    operation: McpOperation
    capability_name: str | None = Field(default=None, pattern=_CAPABILITY)


class McpGatewayError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("The MCP operation did not produce an authorized usable result.")


class McpTransportError(RuntimeError):
    def __init__(
        self,
        code: Literal["MCP_DISCONNECTED", "MCP_PROVIDER_FAILED", "MCP_CANCELLED"],
    ) -> None:
        self.code = code
        super().__init__("The MCP transport did not complete the requested exchange.")


class McpCredentialBroker(Protocol):
    def issue(self, request: McpCredentialRequest) -> McpCredentialLease: ...


class McpTransport(Protocol):
    async def exchange(
        self,
        request: McpTransportRequest,
        credential: McpCredentialLease | None,
    ) -> McpTransportReply | Mapping[str, Any]: ...


class McpStateRepository(Protocol):
    def get(self, handle: str) -> McpAsyncRecord | None: ...

    def put(self, record: McpAsyncRecord) -> None: ...


class InMemoryMcpStateRepository:
    """Deterministic scoped state store for local tests; not a durable queue."""

    def __init__(self) -> None:
        self._records: dict[str, McpAsyncRecord] = {}
        self._lock = RLock()

    def get(self, handle: str) -> McpAsyncRecord | None:
        with self._lock:
            return self._records.get(handle)

    def put(self, record: McpAsyncRecord) -> None:
        with self._lock:
            current = self._records.get(record.handle)
            if current is not None:
                if current.record_sha256 == record.record_sha256:
                    return
                if current.state is not McpAsyncState.PENDING:
                    raise McpGatewayError("MCP_STATE_INVALID")
                if record.state not in {
                    McpAsyncState.PENDING,
                    McpAsyncState.COMPLETED,
                    McpAsyncState.CANCELLED,
                    McpAsyncState.FAILED,
                }:
                    raise McpGatewayError("MCP_STATE_INVALID")
            self._records[record.handle] = record


class McpGateway:
    """Build exact MCP tool bindings around an injected transport and broker."""

    def __init__(
        self,
        server: McpServerRegistration,
        capabilities: Sequence[McpCapabilityRegistration],
        transport: McpTransport,
        *,
        credential_broker: McpCredentialBroker | None = None,
        state_repository: McpStateRepository | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        handle_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        ordered = tuple(sorted(capabilities, key=lambda item: item.name))
        if not ordered or len(ordered) > MAX_MCP_CAPABILITIES:
            raise ValueError("MCP gateway requires a bounded capability allowlist")
        if len({item.name for item in ordered}) != len(ordered):
            raise ValueError("MCP capability names must be unique")
        for item in ordered:
            expected_destination = (
                ToolDataDestination.LOCAL
                if server.deployment is McpDeployment.LOCAL
                else ToolDataDestination.APPROVED_EXTERNAL
            )
            if item.data_destination is not expected_destination:
                raise ValueError("MCP capability destination conflicts with server deployment")
        if server.deployment is McpDeployment.REMOTE and credential_broker is None:
            raise ValueError("remote MCP gateways require a credential broker")
        if server.deployment is McpDeployment.LOCAL and credential_broker is not None:
            raise ValueError("local MCP gateways cannot receive a credential broker")
        self.server = server
        self.capabilities = ordered
        self._by_name = {item.name: item for item in ordered}
        self._transport = transport
        self._broker = credential_broker
        self._state = state_repository or InMemoryMcpStateRepository()
        self._clock = clock
        self._handle_factory = handle_factory
        self._discoveries: dict[tuple[object, ...], McpDiscoveryManifest] = {}
        self._discovery_history: dict[tuple[object, ...], McpDiscoveryManifest] = {}

    def bindings(self) -> tuple[McpToolBinding, ...]:
        bindings = [
            McpToolBinding(
                definition=self._definition(McpOperation.DISCOVER, None),
                operation=McpOperation.DISCOVER,
            )
        ]
        for capability in self.capabilities:
            for operation in (McpOperation.INVOKE, McpOperation.POLL, McpOperation.CANCEL):
                if operation in {McpOperation.POLL, McpOperation.CANCEL} and not (
                    capability.supports_async
                ):
                    continue
                bindings.append(
                    McpToolBinding(
                        definition=self._definition(operation, capability),
                        operation=operation,
                        capability_name=capability.name,
                    )
                )
        return tuple(bindings)

    def adapters(self) -> dict[str, McpOperationAdapter]:
        return {
            binding.definition.key: McpOperationAdapter(
                self,
                binding.operation,
                self._by_name.get(binding.capability_name or ""),
            )
            for binding in self.bindings()
        }

    def _definition(
        self,
        operation: McpOperation,
        capability: McpCapabilityRegistration | None,
    ) -> ToolDefinition:
        remote = self.server.deployment is McpDeployment.REMOTE
        permission = (
            self.server.discovery_permission if capability is None else capability.permission
        )
        if operation is McpOperation.DISCOVER:
            input_schema = _empty_input_schema()
            side_effect = SideEffectClass.READ_ONLY
            approval_required = False
        elif operation is McpOperation.INVOKE:
            assert capability is not None
            input_schema = capability.input_schema
            side_effect = (
                SideEffectClass.REVERSIBLE
                if capability.supports_async and capability.side_effect is SideEffectClass.READ_ONLY
                else capability.side_effect
            )
            approval_required = capability.approval_required
        else:
            input_schema = _handle_input_schema()
            side_effect = (
                SideEffectClass.READ_ONLY
                if operation is McpOperation.POLL
                else SideEffectClass.REVERSIBLE
            )
            approval_required = False
        read_only = side_effect is SideEffectClass.READ_ONLY
        return ToolDefinition(
            name=self._tool_name(operation, capability),
            version="1.0.0",
            purpose=self._purpose(operation, capability),
            kind=ToolKind.MCP,
            transport=ToolTransport.MCP,
            namespace=self.server.namespace,
            data_scope=ToolDataScope.TASK,
            data_destination=(
                ToolDataDestination.APPROVED_EXTERNAL if remote else ToolDataDestination.LOCAL
            ),
            side_effect=side_effect,
            input_schema=input_schema,
            output_schema=_gateway_output_schema(
                canonical_sha256(
                    {
                        "operation": operation.value,
                        "server_registration_sha256": self.server.registration_sha256,
                        "capability_registration_sha256": (
                            capability.capability_sha256 if capability is not None else None
                        ),
                    }
                )
            ),
            required_permissions=frozenset({permission}),
            timeout_ms=(capability.timeout_ms if capability is not None else 10_000),
            max_attempts=2 if read_only else 1,
            max_concurrency=3 if read_only else 1,
            max_input_bytes=100_000,
            max_output_bytes=1_100_000,
            max_tokens=0,
            idempotency=(IdempotencyPolicy.NONE if read_only else IdempotencyPolicy.REQUIRED),
            secret_purposes=(
                frozenset({self.server.secret_purpose})
                if self.server.secret_purpose is not None
                else frozenset()
            ),
            network=NetworkPolicy.RESTRICTED if remote else NetworkPolicy.NONE,
            approval_required=approval_required,
            declared_error_codes=_MCP_ERRORS,
            recovery_policy=(
                ToolRecoveryPolicy.RETRY_READ_ONLY
                if read_only
                else ToolRecoveryPolicy.HUMAN_REVIEW
                if approval_required
                else ToolRecoveryPolicy.RECONCILE
            ),
            audit_owner="mcp-runtime",
            test_owner="mcp-runtime",
            test_groups=frozenset({"INT-MCP", "SEC-TOOLS", "RES-ALL"}),
        )

    def _tool_name(
        self,
        operation: McpOperation,
        capability: McpCapabilityRegistration | None,
    ) -> str:
        prefix = f"mcp.{self.server.namespace}"
        if operation is McpOperation.DISCOVER:
            return f"{prefix}.discover"
        assert capability is not None
        suffix = capability.name
        if operation is not McpOperation.INVOKE:
            suffix = f"{suffix}.{operation.value.lower()}"
        return f"{prefix}.{suffix}"

    @staticmethod
    def _purpose(
        operation: McpOperation,
        capability: McpCapabilityRegistration | None,
    ) -> str:
        if operation is McpOperation.DISCOVER:
            return "Validate the MCP server capability manifest against the static allowlist."
        assert capability is not None
        if operation is McpOperation.INVOKE:
            return capability.purpose
        return f"{operation.value.title()} one bound asynchronous {capability.name} task."

    def _discovery_key(self, invocation: ToolInvocation) -> tuple[object, ...]:
        scope = invocation.context.scope
        return (
            scope.tenant_id,
            scope.project_id,
            scope.user_id,
            scope.role_codes,
            scope.permission_version,
            invocation.context.task_id,
            invocation.context.run_id,
            invocation.context.policy_version,
            self.server.registration_sha256,
        )


class McpOperationAdapter:
    """One operation-specific ToolAdapter created by McpGateway."""

    def __init__(
        self,
        gateway: McpGateway,
        operation: McpOperation,
        capability: McpCapabilityRegistration | None,
    ) -> None:
        self._gateway = gateway
        self._operation = operation
        self._capability = capability

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        started = time.monotonic()
        handle: str | None = None
        try:
            if self._operation is McpOperation.DISCOVER:
                output, artifacts = await self._discover(invocation)
            elif self._operation is McpOperation.INVOKE:
                output, artifacts = await self._invoke(invocation)
            else:
                handle = _validated_handle(invocation.arguments)
                output, artifacts = await self._continue(invocation, handle)
            return self._result(
                invocation,
                output,
                artifacts=artifacts,
                status=ToolStatus.SUCCESS,
                error_code=None,
                retryable=False,
                started=started,
            )
        except McpTransportError as error:
            return self._failure_result(invocation, error.code, handle, started)
        except McpGatewayError as error:
            return self._failure_result(invocation, error.code, handle, started)
        except (PydanticValidationError, JsonSchemaValidationError, TypeError, ValueError):
            return self._failure_result(invocation, "MCP_RESPONSE_INVALID", handle, started)
        except Exception:
            return self._failure_result(invocation, "MCP_PROVIDER_FAILED", handle, started)

    async def _discover(
        self, invocation: ToolInvocation
    ) -> tuple[McpGatewayOutput, tuple[ArtifactRef, ...]]:
        credential = self._credential(invocation, self._gateway.server.discovery_permission)
        reply = await self._exchange(
            McpTransportRequest(
                operation=McpOperation.DISCOVER,
                server_id=self._gateway.server.server_id,
                server_version=self._gateway.server.server_version,
                endpoint=self._gateway.server.endpoint,
                namespace=self._gateway.server.namespace,
                arguments={},
            ),
            credential,
        )
        if reply.status is not McpTransportStatus.DISCOVERED:
            raise McpGatewayError("MCP_RESPONSE_INVALID")
        expected = tuple(_discovered(item) for item in self._gateway.capabilities)
        if reply.capabilities != expected:
            raise McpGatewayError("MCP_SCHEMA_CHANGED")
        discovered_at = self._gateway._clock()
        draft = McpDiscoveryManifest.model_construct(
            server_id=self._gateway.server.server_id,
            server_version=self._gateway.server.server_version,
            namespace=self._gateway.server.namespace,
            registration_sha256=self._gateway.server.registration_sha256,
            capabilities=expected,
            discovered_at=discovered_at,
            expires_at=discovered_at
            + timedelta(seconds=self._gateway.server.discovery_ttl_seconds),
            manifest_sha256="0" * 64,
        )
        payload = draft.model_dump(mode="json", exclude={"manifest_sha256"})
        manifest = McpDiscoveryManifest.model_validate(
            {**payload, "manifest_sha256": canonical_sha256(payload)}
        )
        discovery_key = self._gateway._discovery_key(invocation)
        self._gateway._discoveries[discovery_key] = manifest
        self._gateway._discovery_history[discovery_key + (manifest.manifest_sha256,)] = manifest
        return (
            McpGatewayOutput(
                operation=McpOperation.DISCOVER,
                state="DISCOVERED",
                summary="The MCP capability manifest matches the static application allowlist.",
                content={"capability_count": len(expected)},
                manifest_sha256=manifest.manifest_sha256,
            ),
            (),
        )

    async def _invoke(
        self, invocation: ToolInvocation
    ) -> tuple[McpGatewayOutput, tuple[ArtifactRef, ...]]:
        capability = self._require_capability()
        manifest = self._gateway._discoveries.get(self._gateway._discovery_key(invocation))
        if manifest is None:
            raise McpGatewayError("MCP_DISCOVERY_REQUIRED")
        if self._gateway._clock() >= manifest.expires_at:
            raise McpGatewayError("MCP_DISCOVERY_REQUIRED")
        if _discovered(capability) not in manifest.capabilities:
            raise McpGatewayError("MCP_SCHEMA_CHANGED")
        credential = self._credential(invocation, capability.permission)
        reply = await self._exchange(
            McpTransportRequest(
                operation=McpOperation.INVOKE,
                server_id=self._gateway.server.server_id,
                server_version=self._gateway.server.server_version,
                endpoint=self._gateway.server.endpoint,
                namespace=self._gateway.server.namespace,
                capability_name=capability.name,
                capability_version=capability.version,
                arguments=invocation.arguments,
                discovery_manifest_sha256=manifest.manifest_sha256,
            ),
            credential,
        )
        if reply.status is McpTransportStatus.COMPLETED:
            return self._completed_output(invocation, capability, manifest, reply, None)
        if reply.status is not McpTransportStatus.ACCEPTED or not capability.supports_async:
            raise McpGatewayError("MCP_RESPONSE_INVALID")
        assert reply.remote_task_id is not None
        handle = f"mcp-task-{self._gateway._handle_factory().hex}"
        record = _new_record(
            handle=handle,
            scope=invocation.context.scope,
            task_id=invocation.context.task_id,
            run_id=invocation.context.run_id,
            server_id=self._gateway.server.server_id,
            server_version=self._gateway.server.server_version,
            capability_name=capability.name,
            capability_version=capability.version,
            input_sha256=invocation.input_sha256,
            discovery_manifest_sha256=manifest.manifest_sha256,
            remote_task_id=reply.remote_task_id,
            state=McpAsyncState.PENDING,
            summary=reply.summary,
            artifacts=(),
            updated_at=self._gateway._clock(),
        )
        self._gateway._state.put(record)
        return (
            McpGatewayOutput(
                operation=McpOperation.INVOKE,
                state=McpAsyncState.PENDING.value,
                summary=reply.summary,
                handle=handle,
                content={},
                manifest_sha256=manifest.manifest_sha256,
                record_sha256=record.record_sha256,
            ),
            (),
        )

    async def _continue(
        self,
        invocation: ToolInvocation,
        handle: str,
    ) -> tuple[McpGatewayOutput, tuple[ArtifactRef, ...]]:
        capability = self._require_capability()
        record = self._gateway._state.get(handle)
        if record is None or not _record_matches(
            record, invocation, self._gateway.server, capability
        ):
            raise McpGatewayError("MCP_SCOPE_DENIED")
        if record.state is not McpAsyncState.PENDING:
            raise McpGatewayError("MCP_STATE_INVALID")
        manifest = self._gateway._discovery_history.get(
            self._gateway._discovery_key(invocation) + (record.discovery_manifest_sha256,)
        )
        if manifest is None:
            raise McpGatewayError("MCP_DISCOVERY_REQUIRED")
        credential = self._credential(invocation, capability.permission)
        reply = await self._exchange(
            McpTransportRequest(
                operation=self._operation,
                server_id=self._gateway.server.server_id,
                server_version=self._gateway.server.server_version,
                endpoint=self._gateway.server.endpoint,
                namespace=self._gateway.server.namespace,
                capability_name=capability.name,
                capability_version=capability.version,
                arguments={},
                remote_task_id=record.remote_task_id,
                discovery_manifest_sha256=record.discovery_manifest_sha256,
            ),
            credential,
        )
        if self._operation is McpOperation.CANCEL:
            if (
                reply.status is not McpTransportStatus.CANCELLED
                or reply.remote_task_id != record.remote_task_id
            ):
                raise McpGatewayError("MCP_RESPONSE_INVALID")
            updated = _updated_record(
                record,
                state=McpAsyncState.CANCELLED,
                summary=reply.summary,
                artifacts=(),
                updated_at=self._gateway._clock(),
            )
            self._gateway._state.put(updated)
            return (
                McpGatewayOutput(
                    operation=McpOperation.CANCEL,
                    state=McpAsyncState.CANCELLED.value,
                    summary=reply.summary,
                    handle=handle,
                    content={},
                    manifest_sha256=record.discovery_manifest_sha256,
                    record_sha256=updated.record_sha256,
                ),
                (),
            )
        if reply.status is McpTransportStatus.PENDING:
            if reply.remote_task_id != record.remote_task_id:
                raise McpGatewayError("MCP_RESPONSE_INVALID")
            updated = _updated_record(
                record,
                state=McpAsyncState.PENDING,
                summary=reply.summary,
                artifacts=(),
                updated_at=self._gateway._clock(),
            )
            self._gateway._state.put(updated)
            return (
                McpGatewayOutput(
                    operation=McpOperation.POLL,
                    state=McpAsyncState.PENDING.value,
                    summary=reply.summary,
                    handle=handle,
                    content={},
                    manifest_sha256=record.discovery_manifest_sha256,
                    record_sha256=updated.record_sha256,
                ),
                (),
            )
        if reply.status is not McpTransportStatus.COMPLETED:
            raise McpGatewayError("MCP_RESPONSE_INVALID")
        return self._completed_output(invocation, capability, manifest, reply, record)

    def _completed_output(
        self,
        invocation: ToolInvocation,
        capability: McpCapabilityRegistration,
        manifest: McpDiscoveryManifest,
        reply: McpTransportReply,
        record: McpAsyncRecord | None,
    ) -> tuple[McpGatewayOutput, tuple[ArtifactRef, ...]]:
        Draft202012Validator(capability.output_schema).validate(reply.output)
        stream = _stream_payload(capability, reply.chunks)
        inline: dict[str, Any] = {"result": reply.output, "stream": stream}
        encoded_inline = json.dumps(
            inline,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        artifacts = _validated_artifacts(
            invocation.context.scope,
            reply.artifacts,
            expected_sha256=hashlib.sha256(encoded_inline).hexdigest(),
            expected_size_bytes=len(encoded_inline),
        )
        if len(encoded_inline) > capability.max_inline_bytes:
            if not artifacts:
                raise McpGatewayError("MCP_ARTIFACT_INVALID")
            inline = {
                "artifact_only": True,
                "stream": {key: value for key, value in stream.items() if key != "content"},
            }
        updated: McpAsyncRecord | None = None
        handle: str | None = None
        operation = McpOperation.INVOKE
        if record is not None:
            handle = record.handle
            operation = McpOperation.POLL
            updated = _updated_record(
                record,
                state=McpAsyncState.COMPLETED,
                summary=reply.summary,
                artifacts=artifacts,
                updated_at=self._gateway._clock(),
            )
            self._gateway._state.put(updated)
        return (
            McpGatewayOutput(
                operation=operation,
                state=McpAsyncState.COMPLETED.value,
                summary=reply.summary,
                handle=handle,
                content=inline,
                manifest_sha256=manifest.manifest_sha256,
                record_sha256=updated.record_sha256 if updated is not None else None,
            ),
            artifacts,
        )

    async def _exchange(
        self,
        request: McpTransportRequest,
        credential: McpCredentialLease | None,
    ) -> McpTransportReply:
        raw = await self._gateway._transport.exchange(request, credential)
        reply = McpTransportReply.model_validate(raw, strict=True)
        server = self._gateway.server
        if reply.server_id != server.server_id or reply.server_version != server.server_version:
            raise McpGatewayError("MCP_RESPONSE_INVALID")
        return reply

    def _credential(
        self,
        invocation: ToolInvocation,
        permission: str,
    ) -> McpCredentialLease | None:
        server = self._gateway.server
        if server.deployment is McpDeployment.LOCAL:
            return None
        broker = self._gateway._broker
        assert broker is not None and server.secret_purpose is not None
        now = self._gateway._clock()
        request = McpCredentialRequest(
            scope=invocation.context.scope,
            task_id=invocation.context.task_id,
            run_id=invocation.context.run_id,
            request_id=invocation.context.request_id,
            server_id=server.server_id,
            audience=server.audience,
            permission=permission,
            secret_purpose=server.secret_purpose,
            policy_version=server.policy_version,
            requested_expires_at=now + timedelta(seconds=MAX_MCP_CREDENTIAL_SECONDS),
        )
        try:
            raw_lease = broker.issue(request)
            lease = McpCredentialLease.model_validate(raw_lease, strict=True)
        except Exception as error:
            raise McpGatewayError("MCP_CREDENTIAL_FAILED") from error
        expected = request.model_dump(exclude={"request_id", "requested_expires_at"})
        actual = lease.model_dump(exclude={"issued_at", "expires_at", "value"})
        if expected != actual or not lease.issued_at <= now < lease.expires_at:
            raise McpGatewayError("MCP_CREDENTIAL_FAILED")
        if lease.expires_at > request.requested_expires_at:
            raise McpGatewayError("MCP_CREDENTIAL_FAILED")
        return lease

    def _require_capability(self) -> McpCapabilityRegistration:
        if self._capability is None:
            raise McpGatewayError("MCP_RESPONSE_INVALID")
        return self._capability

    def _failure_result(
        self,
        invocation: ToolInvocation,
        code: str,
        handle: str | None,
        started: float,
    ) -> ToolResult:
        status = (
            ToolStatus.CANCELLED
            if code == "MCP_CANCELLED"
            else ToolStatus.BLOCKED
            if code in {"MCP_DISCOVERY_REQUIRED", "MCP_DISCONNECTED", "MCP_SCHEMA_CHANGED"}
            else ToolStatus.DENIED
            if code in {"MCP_SCOPE_DENIED", "MCP_STATE_INVALID"}
            else ToolStatus.FAILED
        )
        read_only = invocation.definition.side_effect is SideEffectClass.READ_ONLY
        retryable = code in {"MCP_DISCONNECTED", "MCP_PROVIDER_FAILED"} and read_only
        output = McpGatewayOutput(
            operation=self._operation,
            state="FAILED",
            summary="The MCP operation failed without producing trusted capability output.",
            handle=handle,
            content={},
        )
        return self._result(
            invocation,
            output,
            artifacts=(),
            status=status,
            error_code=code,
            retryable=retryable,
            started=started,
        )

    def _result(
        self,
        invocation: ToolInvocation,
        output: McpGatewayOutput,
        *,
        artifacts: tuple[ArtifactRef, ...],
        status: ToolStatus,
        error_code: str | None,
        retryable: bool,
        started: float,
    ) -> ToolResult:
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
            stdout="",
            stderr="",
            encoding="utf-8",
            truncated=False,
            artifacts=artifacts,
            idempotency_key=invocation.idempotency_key,
            input_sha256=invocation.input_sha256,
            output_sha256=canonical_sha256(payload),
            error_code=error_code,
            retryable=retryable,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            completed_at=self._gateway._clock(),
        )


def mcp_server_registration_sha256(registration: McpServerRegistration) -> str:
    return canonical_sha256(registration.model_dump(mode="json", exclude={"registration_sha256"}))


def mcp_capability_registration_sha256(capability: McpCapabilityRegistration) -> str:
    return canonical_sha256(capability.model_dump(mode="json", exclude={"capability_sha256"}))


def mcp_discovery_manifest_sha256(manifest: McpDiscoveryManifest) -> str:
    return canonical_sha256(manifest.model_dump(mode="json", exclude={"manifest_sha256"}))


def mcp_async_record_sha256(record: McpAsyncRecord) -> str:
    return canonical_sha256(record.model_dump(mode="json", exclude={"record_sha256"}))


def _canonical_mcp_endpoint(value: str) -> str:
    if value != value.strip() or any(ord(char) < 32 or char.isspace() for char in value):
        raise ValueError("MCP endpoint contains unsafe characters")
    parsed = urlsplit(value)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError("MCP endpoint contains forbidden components")
    if parsed.scheme not in {"https", "mcp+local"} or not parsed.hostname:
        raise ValueError("MCP endpoint scheme or host is invalid")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("MCP endpoint host must use an application-owned identifier")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("MCP endpoint cannot use a literal IP address")
    labels = host.split(".")
    if any(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None for label in labels
    ):
        raise ValueError("MCP endpoint host is invalid")
    if parsed.scheme == "mcp+local" and parsed.port is not None:
        raise ValueError("local MCP endpoints cannot declare a port")
    if parsed.scheme == "https" and parsed.port not in {None, 443}:
        raise ValueError("MCP endpoint uses an unapproved port")
    port = "" if parsed.port in {None, 443} else f":{parsed.port}"
    path = parsed.path or ""
    return urlunsplit((parsed.scheme, f"{host}{port}", path, "", ""))


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{label} must use UTC")


def _discovered(capability: McpCapabilityRegistration) -> McpDiscoveredCapability:
    return McpDiscoveredCapability(
        name=capability.name,
        version=capability.version,
        input_schema_sha256=canonical_sha256(capability.input_schema),
        output_schema_sha256=canonical_sha256(capability.output_schema),
        side_effect=capability.side_effect,
        supports_streaming=capability.supports_streaming,
        supports_async=capability.supports_async,
    )


def _validated_handle(arguments: Mapping[str, Any]) -> str:
    value = arguments.get("handle")
    if not isinstance(value, str) or re.fullmatch(_HANDLE, value) is None or len(arguments) != 1:
        raise McpGatewayError("MCP_SCOPE_DENIED")
    return value


def _record_matches(
    record: McpAsyncRecord,
    invocation: ToolInvocation,
    server: McpServerRegistration,
    capability: McpCapabilityRegistration,
) -> bool:
    return bool(
        record.scope == invocation.context.scope
        and record.task_id == invocation.context.task_id
        and record.run_id == invocation.context.run_id
        and record.server_id == server.server_id
        and record.server_version == server.server_version
        and record.capability_name == capability.name
        and record.capability_version == capability.version
    )


def _stream_payload(
    capability: McpCapabilityRegistration,
    chunks: tuple[McpChunk, ...],
) -> dict[str, Any]:
    if chunks and not capability.supports_streaming:
        raise McpGatewayError("MCP_STREAM_INVALID")
    if len(chunks) > capability.max_chunks:
        raise McpGatewayError("MCP_STREAM_INVALID")
    if tuple(item.index for item in chunks) != tuple(range(len(chunks))):
        raise McpGatewayError("MCP_STREAM_INVALID")
    media_types = {item.media_type for item in chunks}
    if len(media_types) > 1:
        raise McpGatewayError("MCP_STREAM_INVALID")
    joined = "".join(item.content for item in chunks)
    size = len(joined.encode("utf-8"))
    if size > capability.max_stream_bytes:
        raise McpGatewayError("MCP_STREAM_INVALID")
    return {
        "chunk_count": len(chunks),
        "size_bytes": size,
        "media_type": next(iter(media_types), None),
        "content": joined,
        "sha256": canonical_sha256({"content": joined}),
    }


def _validated_artifacts(
    scope: TenantScope,
    artifacts: tuple[ArtifactRef, ...],
    *,
    expected_sha256: str,
    expected_size_bytes: int,
) -> tuple[ArtifactRef, ...]:
    if any(not item.immutable or item.scope != scope for item in artifacts):
        raise McpGatewayError("MCP_ARTIFACT_INVALID")
    if len({item.artifact_id for item in artifacts}) != len(artifacts):
        raise McpGatewayError("MCP_ARTIFACT_INVALID")
    if artifacts and not any(
        item.sha256 == expected_sha256 and item.size_bytes == expected_size_bytes
        for item in artifacts
    ):
        raise McpGatewayError("MCP_ARTIFACT_INVALID")
    return artifacts


def _new_record(**payload: Any) -> McpAsyncRecord:
    draft = McpAsyncRecord.model_construct(**payload, record_sha256="0" * 64)
    encoded = draft.model_dump(mode="json", exclude={"record_sha256"})
    return McpAsyncRecord.model_validate({**encoded, "record_sha256": canonical_sha256(encoded)})


def _updated_record(
    record: McpAsyncRecord,
    *,
    state: McpAsyncState,
    summary: str,
    artifacts: tuple[ArtifactRef, ...],
    updated_at: datetime,
) -> McpAsyncRecord:
    draft = record.model_copy(
        update={
            "state": state,
            "summary": summary,
            "artifacts": artifacts,
            "updated_at": updated_at,
            "record_sha256": "0" * 64,
        }
    )
    payload = draft.model_dump(mode="json", exclude={"record_sha256"})
    return McpAsyncRecord.model_validate({**payload, "record_sha256": canonical_sha256(payload)})


def _empty_input_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "additionalProperties": False}


def _handle_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"handle": {"type": "string", "pattern": _HANDLE[1:-1]}},
        "required": ["handle"],
        "additionalProperties": False,
    }


def _gateway_output_schema(binding_sha256: str) -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    return {
        "$comment": f"MCP static binding SHA-256: {binding_sha256}",
        "type": "object",
        "properties": {
            "schema_version": {"const": MCP_GATEWAY_CONTRACT_VERSION},
            "operation": {"enum": [item.value for item in McpOperation]},
            "trust": {"const": "UNTRUSTED"},
            "state": {"type": "string"},
            "summary": {"type": "string"},
            "handle": nullable_string,
            "content": {"type": "object"},
            "manifest_sha256": nullable_string,
            "record_sha256": nullable_string,
        },
        "required": [
            "schema_version",
            "operation",
            "trust",
            "state",
            "summary",
            "handle",
            "content",
            "manifest_sha256",
            "record_sha256",
        ],
        "additionalProperties": False,
    }
