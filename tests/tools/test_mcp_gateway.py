"""S5-04 MCP registration, authorization, async state, and recovery tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr
from pydantic import ValidationError as PydanticValidationError

from ndt_agents.contracts.v1 import (
    ArtifactRef,
    DataClassification,
    TenantScope,
    ToolStatus,
)
from ndt_agents.observability import (
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.tools import (
    IdempotencyPolicy,
    InMemoryMcpStateRepository,
    McpAsyncState,
    McpCapabilityRegistration,
    McpChunk,
    McpCredentialLease,
    McpCredentialRequest,
    McpDeployment,
    McpDiscoveredCapability,
    McpGateway,
    McpGatewayOutput,
    McpOperation,
    McpServerRegistration,
    McpTransportError,
    McpTransportReply,
    McpTransportRequest,
    McpTransportStatus,
    NetworkPolicy,
    SideEffectClass,
    ToolDataDestination,
    ToolInvocationContext,
    ToolKind,
    ToolRecoveryPolicy,
    ToolRegistry,
    ToolTransport,
    mcp_capability_registration_sha256,
    mcp_server_registration_sha256,
)
from ndt_agents.tools.registry import canonical_sha256

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000701"),
    project_id=UUID("00000000-0000-4000-8000-000000000702"),
    user_id=UUID("00000000-0000-4000-8000-000000000703"),
    role_codes=("MCP_USER",),
    permission_version="permissions-1",
)
TASK_ID = UUID("00000000-0000-4000-8000-000000000711")
RUN_ID = UUID("00000000-0000-4000-8000-000000000712")
NOW = datetime(2026, 8, 25, 7, 0, tzinfo=UTC)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"echo": {"type": "string"}},
    "required": ["echo"],
    "additionalProperties": False,
}


def server(*, deployment: McpDeployment = McpDeployment.REMOTE, **updates: Any) -> Any:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "server_id": "fixture-mcp",
        "server_version": "1.0.0",
        "namespace": "fixture.mcp",
        "deployment": deployment,
        "endpoint": (
            "https://mcp.example.test/v1"
            if deployment is McpDeployment.REMOTE
            else "mcp+local://fixture-mcp/v1"
        ),
        "audience": "fixture-mcp",
        "policy_version": "mcp-policy-1",
        "discovery_permission": "mcp.discover",
        "secret_purpose": "mcp.fixture" if deployment is McpDeployment.REMOTE else None,
    }
    values.update(updates)
    draft = McpServerRegistration.model_construct(**values, registration_sha256="0" * 64)
    values["registration_sha256"] = mcp_server_registration_sha256(draft)
    return McpServerRegistration.model_validate(values)


def capability(**updates: Any) -> Any:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "name": "echo",
        "version": "1.0.0",
        "purpose": "Echo one bounded fixture value.",
        "permission": "mcp.echo",
        "side_effect": SideEffectClass.READ_ONLY,
        "approval_required": False,
        "data_destination": ToolDataDestination.APPROVED_EXTERNAL,
        "input_schema": INPUT_SCHEMA,
        "output_schema": OUTPUT_SCHEMA,
        "timeout_ms": 100,
        "supports_streaming": False,
        "supports_async": False,
        "max_chunks": 32,
        "max_stream_bytes": 100_000,
        "max_inline_bytes": 32_000,
    }
    values.update(updates)
    draft = McpCapabilityRegistration.model_construct(**values, capability_sha256="0" * 64)
    values["capability_sha256"] = mcp_capability_registration_sha256(draft)
    return McpCapabilityRegistration.model_validate(values)


def discovered(item: McpCapabilityRegistration) -> McpDiscoveredCapability:
    return McpDiscoveredCapability(
        name=item.name,
        version=item.version,
        input_schema_sha256=canonical_sha256(item.input_schema),
        output_schema_sha256=canonical_sha256(item.output_schema),
        side_effect=item.side_effect,
        supports_streaming=item.supports_streaming,
        supports_async=item.supports_async,
    )


def discovery_reply(item: McpCapabilityRegistration) -> McpTransportReply:
    return McpTransportReply(
        status=McpTransportStatus.DISCOVERED,
        server_id="fixture-mcp",
        server_version="1.0.0",
        capabilities=(discovered(item),),
        summary="Discovered one fixture capability.",
    )


def completed_reply(
    *,
    value: str = "ok",
    chunks: tuple[McpChunk, ...] = (),
    artifacts: tuple[ArtifactRef, ...] = (),
) -> McpTransportReply:
    return McpTransportReply(
        status=McpTransportStatus.COMPLETED,
        server_id="fixture-mcp",
        server_version="1.0.0",
        output={"echo": value},
        summary="Fixture capability completed.",
        chunks=chunks,
        artifacts=artifacts,
    )


class FakeCredentialBroker:
    def __init__(self, **lease_updates: Any) -> None:
        self.calls: list[McpCredentialRequest] = []
        self.lease_updates = lease_updates

    def issue(self, request: McpCredentialRequest) -> McpCredentialLease:
        self.calls.append(request)
        values: dict[str, Any] = {
            "scope": request.scope,
            "task_id": request.task_id,
            "run_id": request.run_id,
            "server_id": request.server_id,
            "audience": request.audience,
            "permission": request.permission,
            "secret_purpose": request.secret_purpose,
            "policy_version": request.policy_version,
            "issued_at": NOW,
            "expires_at": NOW + timedelta(seconds=60),
            "value": SecretStr("raw-mcp-token-must-not-serialize"),
        }
        values.update(self.lease_updates)
        return McpCredentialLease(**values)


class FakeTransport:
    def __init__(self, replies: list[Any] | None = None, *, delay: float = 0) -> None:
        self.replies = replies or []
        self.delay = delay
        self.requests: list[McpTransportRequest] = []
        self.credentials: list[McpCredentialLease | None] = []

    async def exchange(
        self,
        request: McpTransportRequest,
        credential: McpCredentialLease | None,
    ) -> Any:
        self.requests.append(request)
        self.credentials.append(credential)
        if self.delay:
            await asyncio.sleep(self.delay)
        if not self.replies:
            raise RuntimeError("fixture response missing")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Runtime:
    def __init__(
        self,
        selected_capability: McpCapabilityRegistration,
        transport: FakeTransport,
        *,
        selected_server: McpServerRegistration | None = None,
        broker: FakeCredentialBroker | None = None,
    ) -> None:
        self.server = selected_server or server()
        self.capability = selected_capability
        self.transport = transport
        self.now = NOW
        self.broker = broker or (
            FakeCredentialBroker() if self.server.deployment is McpDeployment.REMOTE else None
        )
        self.state = InMemoryMcpStateRepository()
        self.gateway = McpGateway(
            self.server,
            (self.capability,),
            transport,
            credential_broker=self.broker,
            state_repository=self.state,
            clock=lambda: self.now,
            handle_factory=lambda: UUID("00000000-0000-4000-8000-000000000799"),
        )
        self.bindings = self.gateway.bindings()
        definitions = tuple(item.definition for item in self.bindings)
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="mcp-gateway-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.repository = InMemoryAuditRepository()
        self.registry = ToolRegistry(
            definitions,
            self.gateway.adapters(),
            audit=AuditService(self.repository, self.traces),
            clock=lambda: self.now,
        )

    def definition(self, operation: McpOperation) -> Any:
        return next(item.definition for item in self.bindings if item.operation is operation)

    def context(self, **updates: Any) -> ToolInvocationContext:
        values: dict[str, Any] = {
            "task_id": TASK_ID,
            "run_id": RUN_ID,
            "scope": SCOPE,
            "request_id": "mcp-request-1",
            "policy_version": "tool-policy-1",
            "expected_registry_version": self.registry.version,
            "allowed_tools": frozenset(item.definition.key for item in self.bindings),
            "granted_permissions": frozenset({"mcp.discover", "mcp.echo"}),
            "allowed_secret_purposes": (
                frozenset({"mcp.fixture"})
                if self.server.deployment is McpDeployment.REMOTE
                else frozenset()
            ),
            "allowed_data_destinations": frozenset(
                {
                    ToolDataDestination.APPROVED_EXTERNAL
                    if self.server.deployment is McpDeployment.REMOTE
                    else ToolDataDestination.LOCAL
                }
            ),
            "allow_network": self.server.deployment is McpDeployment.REMOTE,
        }
        values.update(updates)
        return ToolInvocationContext(**values)

    async def invoke(
        self,
        operation: McpOperation,
        arguments: dict[str, Any],
        *,
        context: ToolInvocationContext | None = None,
        budget: BudgetGuard | None = None,
        observation: str = "1" * 64,
        idempotency_key: str | None = None,
    ) -> tuple[Any, McpGatewayOutput | None, BudgetGuard]:
        definition = self.definition(operation)
        selected_budget = budget or BudgetGuard(default_budget_policy("P1"))
        with self.traces.start_span("mcp.invoke"):
            result = await self.registry.invoke(
                name=definition.name,
                version=definition.version,
                arguments=arguments,
                context=context or self.context(),
                budget=selected_budget,
                observation_sha256=observation,
                idempotency_key=idempotency_key,
            )
        output = (
            None
            if result.status is ToolStatus.TIMEOUT
            else McpGatewayOutput.model_validate(result.output)
        )
        return result, output, selected_budget

    async def discover(self, *, observation: str = "1" * 64) -> Any:
        return await self.invoke(McpOperation.DISCOVER, {}, observation=observation)

    def close(self) -> None:
        self.traces.shutdown()


def artifact(
    *,
    scope: TenantScope = SCOPE,
    immutable: bool = True,
    value: str = "ok",
) -> ArtifactRef:
    inline = {
        "result": {"echo": value},
        "stream": {
            "chunk_count": 0,
            "size_bytes": 0,
            "media_type": None,
            "content": "",
            "sha256": canonical_sha256({"content": ""}),
        },
    }
    encoded = json.dumps(
        inline,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return ArtifactRef(
        artifact_id=UUID("00000000-0000-4000-8000-000000000790"),
        scope=scope,
        artifact_version="1",
        uri="artifact://mcp/result-1",
        media_type="application/json",
        size_bytes=len(encoded),
        sha256=hashlib.sha256(encoded).hexdigest(),
        classification=DataClassification.INTERNAL,
        immutable=immutable,
    )


@pytest.mark.parametrize(
    ("deployment", "endpoint"),
    [
        (McpDeployment.REMOTE, "http://mcp.example.test/v1"),
        (McpDeployment.REMOTE, "https://user:pass@mcp.example.test/v1"),
        (McpDeployment.REMOTE, "https://127.0.0.1/v1"),
        (McpDeployment.REMOTE, "https://mcp.example.test/v1#fragment"),
        (McpDeployment.REMOTE, "https://bad..example.test/v1"),
        (McpDeployment.LOCAL, "https://mcp.example.test/v1"),
        (McpDeployment.LOCAL, "mcp+local://fixture-mcp:443/v1"),
    ],
)
def test_server_registration_rejects_unsafe_or_mismatched_endpoints(
    deployment: McpDeployment, endpoint: str
) -> None:
    with pytest.raises((PydanticValidationError, ValueError)):
        server(deployment=deployment, endpoint=endpoint)


def test_registration_and_capability_hashes_reject_tamper() -> None:
    registered = server()
    allowed = capability()
    with pytest.raises(PydanticValidationError, match="registration hash"):
        McpServerRegistration.model_validate({**registered.model_dump(), "server_version": "1.0.1"})
    with pytest.raises(PydanticValidationError, match="registration hash"):
        McpCapabilityRegistration.model_validate(
            {**allowed.model_dump(), "permission": "mcp.changed"}
        )


def test_capability_rejects_plaintext_token_and_unsafe_side_effect() -> None:
    secret_schema = {
        "type": "object",
        "properties": {"token": {"type": "string"}},
        "required": ["token"],
        "additionalProperties": False,
    }
    with pytest.raises(PydanticValidationError, match="credential"):
        capability(input_schema=secret_schema)
    with pytest.raises(PydanticValidationError, match="require approval"):
        capability(side_effect=SideEffectClass.IRREVERSIBLE)


def test_bindings_are_separate_registered_mcp_operations() -> None:
    selected = capability(supports_async=True)
    runtime = Runtime(selected, FakeTransport())
    try:
        assert {item.operation for item in runtime.bindings} == set(McpOperation)
        for item in runtime.bindings:
            definition = item.definition
            assert definition.kind is ToolKind.MCP
            assert definition.transport is ToolTransport.MCP
            assert definition.namespace == "fixture.mcp"
            assert definition.network is NetworkPolicy.RESTRICTED
            assert {"INT-MCP", "SEC-TOOLS", "RES-ALL"} <= definition.test_groups
        assert runtime.definition(McpOperation.CANCEL).idempotency is IdempotencyPolicy.REQUIRED
        assert (
            runtime.definition(McpOperation.CANCEL).recovery_policy is ToolRecoveryPolicy.RECONCILE
        )
        assert not runtime.transport.requests
    finally:
        runtime.close()


def test_registry_version_binds_server_and_capability_registrations() -> None:
    selected = capability()
    first = Runtime(selected, FakeTransport())
    moved = Runtime(
        selected,
        FakeTransport(),
        selected_server=server(endpoint="https://mcp-alt.example.test/v1"),
    )
    changed = Runtime(capability(version="1.0.1"), FakeTransport())
    try:
        assert first.registry.version != moved.registry.version
        assert first.registry.version != changed.registry.version
    finally:
        first.close()
        moved.close()
        changed.close()


@pytest.mark.parametrize(
    "updates",
    [
        {"granted_permissions": frozenset({"mcp.echo"})},
        {"allowed_secret_purposes": frozenset()},
        {"allow_network": False},
        {"allowed_data_destinations": frozenset({ToolDataDestination.LOCAL})},
    ],
)
def test_registry_preflight_denial_makes_zero_credential_and_transport_calls(
    updates: dict[str, Any],
) -> None:
    selected = capability()
    transport = FakeTransport([discovery_reply(selected)])
    runtime = Runtime(selected, transport)
    try:
        with pytest.raises(Exception) as captured:
            asyncio.run(
                runtime.invoke(
                    McpOperation.DISCOVER,
                    {},
                    context=runtime.context(**updates),
                )
            )
        assert getattr(captured.value, "code", "").startswith("TOOL_")
        assert not transport.requests
        assert runtime.broker is not None and not runtime.broker.calls
    finally:
        runtime.close()


def test_discovery_is_exact_metered_and_credentials_never_serialize() -> None:
    selected = capability()
    transport = FakeTransport([discovery_reply(selected)])
    runtime = Runtime(selected, transport)
    try:
        result, output, budget = asyncio.run(runtime.discover())
        assert result.status is ToolStatus.SUCCESS
        assert output is not None and output.state == "DISCOVERED"
        assert output.trust == "UNTRUSTED"
        assert output.content == {"capability_count": 1}
        assert budget.telemetry().counters.physical_tool_calls == 1
        assert len(transport.requests) == 1
        assert runtime.broker is not None and len(runtime.broker.calls) == 1
        lease = transport.credentials[0]
        assert lease is not None
        serialized = lease.model_dump_json()
        assert "raw-mcp-token" not in serialized and "value" not in serialized
        assert "raw-mcp-token" not in result.model_dump_json()
        assert "raw-mcp-token" not in runtime.repository.list(SCOPE)[0].model_dump_json()
    finally:
        runtime.close()


def test_discovery_rejects_added_or_changed_capability() -> None:
    selected = capability()
    changed = discovered(capability(version="1.0.1"))
    reply = discovery_reply(selected).model_copy(update={"capabilities": (changed,)})
    runtime = Runtime(selected, FakeTransport([reply]))
    try:
        result, output, _ = asyncio.run(runtime.discover())
        assert result.status is ToolStatus.BLOCKED
        assert result.error_code == "MCP_SCHEMA_CHANGED"
        assert output is not None and output.content == {}
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "reply",
    [
        discovery_reply(capability()).model_copy(update={"server_version": "1.0.1"}),
        RuntimeError("provider internals must not cross the boundary"),
    ],
)
def test_wrong_server_identity_and_generic_provider_failure_are_typed(reply: Any) -> None:
    selected = capability()
    runtime = Runtime(selected, FakeTransport([reply]))
    try:
        result, output, _ = asyncio.run(runtime.discover())
        assert result.error_code in {"MCP_RESPONSE_INVALID", "MCP_PROVIDER_FAILED"}
        assert output is not None and output.content == {}
        assert "provider internals" not in result.model_dump_json()
    finally:
        runtime.close()


def test_invocation_requires_scoped_discovery_before_credentials_or_transport() -> None:
    selected = capability()
    transport = FakeTransport([completed_reply()])
    runtime = Runtime(selected, transport)
    try:
        result, _, budget = asyncio.run(runtime.invoke(McpOperation.INVOKE, {"value": "x"}))
        assert result.status is ToolStatus.BLOCKED
        assert result.error_code == "MCP_DISCOVERY_REQUIRED"
        assert not transport.requests
        assert runtime.broker is not None and not runtime.broker.calls
        assert budget.telemetry().counters.physical_tool_calls == 1
    finally:
        runtime.close()


def test_expired_discovery_blocks_new_invocation_before_credentials_or_transport() -> None:
    selected = capability()
    runtime = Runtime(selected, FakeTransport([discovery_reply(selected)]))
    try:
        asyncio.run(runtime.discover())
        runtime.now = NOW + timedelta(seconds=301)
        prior_transport = len(runtime.transport.requests)
        prior_broker = len(runtime.broker.calls) if runtime.broker is not None else 0
        result, _, _ = asyncio.run(
            runtime.invoke(McpOperation.INVOKE, {"value": "x"}, observation="2" * 64)
        )
        assert result.error_code == "MCP_DISCOVERY_REQUIRED"
        assert len(runtime.transport.requests) == prior_transport
        assert runtime.broker is not None and len(runtime.broker.calls) == prior_broker
    finally:
        runtime.close()


def test_synchronous_invocation_validates_output_and_bounded_stream() -> None:
    selected = capability(supports_streaming=True)
    chunks = (
        McpChunk(index=0, media_type="text/plain", content="a"),
        McpChunk(index=1, media_type="text/plain", content="b"),
    )
    transport = FakeTransport([discovery_reply(selected), completed_reply(chunks=chunks)])
    runtime = Runtime(selected, transport)
    try:
        asyncio.run(runtime.discover())
        result, output, _ = asyncio.run(
            runtime.invoke(
                McpOperation.INVOKE,
                {"value": "x"},
                observation="2" * 64,
                idempotency_key="invoke-1",
            )
        )
        assert result.status is ToolStatus.SUCCESS
        assert output is not None and output.state == McpAsyncState.COMPLETED
        assert output.content["result"] == {"echo": "ok"}
        assert output.content["stream"]["content"] == "ab"
        assert output.content["stream"]["chunk_count"] == 2
        assert len(transport.requests) == 2
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "chunks",
    [
        (McpChunk(index=1, media_type="text/plain", content="gap"),),
        (
            McpChunk(index=0, media_type="text/plain", content="a"),
            McpChunk(index=1, media_type="application/json", content="b"),
        ),
    ],
)
def test_invalid_stream_is_typed(chunks: tuple[McpChunk, ...]) -> None:
    selected = capability(supports_streaming=True)
    runtime = Runtime(
        selected,
        FakeTransport([discovery_reply(selected), completed_reply(chunks=chunks)]),
    )
    try:
        asyncio.run(runtime.discover())
        result, _, _ = asyncio.run(
            runtime.invoke(McpOperation.INVOKE, {"value": "x"}, observation="2" * 64)
        )
        assert result.error_code == "MCP_STREAM_INVALID"
    finally:
        runtime.close()


def test_output_schema_and_malformed_reply_fail_closed() -> None:
    selected = capability()
    invalid_output = completed_reply().model_copy(update={"output": {"wrong": "field"}})
    runtime = Runtime(
        selected,
        FakeTransport([discovery_reply(selected), invalid_output]),
    )
    try:
        asyncio.run(runtime.discover())
        result, output, _ = asyncio.run(
            runtime.invoke(
                McpOperation.INVOKE,
                {"value": "x"},
                observation="2" * 64,
                idempotency_key="invoke-1",
            )
        )
        assert result.status is ToolStatus.FAILED
        assert result.error_code == "MCP_RESPONSE_INVALID"
        assert output is not None and output.content == {}
    finally:
        runtime.close()


def test_async_handle_binds_state_without_exposing_remote_task_id() -> None:
    selected = capability(supports_async=True)
    accepted = McpTransportReply(
        status=McpTransportStatus.ACCEPTED,
        server_id="fixture-mcp",
        server_version="1.0.0",
        summary="Fixture task accepted.",
        remote_task_id="remote-secret-handle-1",
    )
    runtime = Runtime(selected, FakeTransport([discovery_reply(selected), accepted]))
    try:
        asyncio.run(runtime.discover())
        result, output, _ = asyncio.run(
            runtime.invoke(
                McpOperation.INVOKE,
                {"value": "x"},
                observation="2" * 64,
                idempotency_key="invoke-1",
            )
        )
        assert result.status is ToolStatus.SUCCESS
        assert output is not None and output.handle == ("mcp-task-00000000000040008000000000000799")
        assert "remote-secret-handle-1" not in result.model_dump_json()
        record = runtime.state.get(output.handle)
        assert record is not None and record.state is McpAsyncState.PENDING
        assert record.task_id == TASK_ID and record.run_id == RUN_ID and record.scope == SCOPE
    finally:
        runtime.close()


def test_async_poll_pending_then_completed_is_monotonic() -> None:
    selected = capability(supports_async=True)
    accepted = McpTransportReply(
        status=McpTransportStatus.ACCEPTED,
        server_id="fixture-mcp",
        server_version="1.0.0",
        summary="Accepted.",
        remote_task_id="remote-1",
    )
    pending = McpTransportReply(
        status=McpTransportStatus.PENDING,
        server_id="fixture-mcp",
        server_version="1.0.0",
        summary="Still running.",
        remote_task_id="remote-1",
    )
    runtime = Runtime(
        selected,
        FakeTransport([discovery_reply(selected), accepted, pending, completed_reply()]),
    )
    budget = BudgetGuard(default_budget_policy("P1"))
    try:
        asyncio.run(runtime.discover(observation="1" * 64))
        _, started, _ = asyncio.run(
            runtime.invoke(
                McpOperation.INVOKE,
                {"value": "x"},
                budget=budget,
                observation="2" * 64,
                idempotency_key="invoke-1",
            )
        )
        assert started is not None and started.handle is not None
        _, waiting, _ = asyncio.run(
            runtime.invoke(
                McpOperation.POLL,
                {"handle": started.handle},
                budget=budget,
                observation="3" * 64,
            )
        )
        assert waiting is not None and waiting.state == "PENDING"
        _, completed, _ = asyncio.run(
            runtime.invoke(
                McpOperation.POLL,
                {"handle": started.handle},
                budget=budget,
                observation="4" * 64,
            )
        )
        assert completed is not None and completed.state == "COMPLETED"
        record = runtime.state.get(started.handle)
        assert record is not None and record.state is McpAsyncState.COMPLETED
    finally:
        runtime.close()


def test_discovery_refresh_does_not_orphan_existing_async_handle() -> None:
    selected = capability(supports_async=True)
    accepted = McpTransportReply(
        status=McpTransportStatus.ACCEPTED,
        server_id="fixture-mcp",
        server_version="1.0.0",
        summary="Accepted.",
        remote_task_id="remote-1",
    )
    runtime = Runtime(
        selected,
        FakeTransport(
            [
                discovery_reply(selected),
                accepted,
                discovery_reply(selected),
                completed_reply(),
            ]
        ),
    )
    try:
        asyncio.run(runtime.discover())
        _, started, _ = asyncio.run(
            runtime.invoke(
                McpOperation.INVOKE,
                {"value": "x"},
                observation="2" * 64,
                idempotency_key="invoke-1",
            )
        )
        assert started is not None and started.handle is not None
        original = runtime.state.get(started.handle)
        assert original is not None
        runtime.now = NOW + timedelta(seconds=1)
        asyncio.run(runtime.discover(observation="3" * 64))
        completed, _, _ = asyncio.run(
            runtime.invoke(
                McpOperation.POLL,
                {"handle": started.handle},
                observation="4" * 64,
            )
        )
        assert completed.status is ToolStatus.SUCCESS
        current = runtime.state.get(started.handle)
        assert current is not None and current.state is McpAsyncState.COMPLETED
        assert current.discovery_manifest_sha256 == original.discovery_manifest_sha256
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "context_updates",
    [
        {
            "scope": SCOPE.model_copy(
                update={"user_id": UUID("00000000-0000-4000-8000-000000000704")}
            )
        },
        {"task_id": UUID("00000000-0000-4000-8000-000000000713")},
        {"run_id": UUID("00000000-0000-4000-8000-000000000714")},
    ],
)
def test_wrong_binding_poll_fails_before_credential_and_transport(
    context_updates: dict[str, Any],
) -> None:
    selected = capability(supports_async=True)
    accepted = McpTransportReply(
        status=McpTransportStatus.ACCEPTED,
        server_id="fixture-mcp",
        server_version="1.0.0",
        summary="Accepted.",
        remote_task_id="remote-1",
    )
    runtime = Runtime(selected, FakeTransport([discovery_reply(selected), accepted]))
    try:
        asyncio.run(runtime.discover())
        _, started, _ = asyncio.run(
            runtime.invoke(
                McpOperation.INVOKE,
                {"value": "x"},
                observation="2" * 64,
                idempotency_key="invoke-1",
            )
        )
        assert started is not None and started.handle is not None
        prior_transport = len(runtime.transport.requests)
        prior_broker = len(runtime.broker.calls) if runtime.broker is not None else 0
        result, _, _ = asyncio.run(
            runtime.invoke(
                McpOperation.POLL,
                {"handle": started.handle},
                context=runtime.context(**context_updates),
                observation="3" * 64,
            )
        )
        assert result.status is ToolStatus.DENIED
        assert result.error_code == "MCP_SCOPE_DENIED"
        assert len(runtime.transport.requests) == prior_transport
        assert runtime.broker is not None and len(runtime.broker.calls) == prior_broker
    finally:
        runtime.close()


def test_cancel_is_registry_idempotent_and_terminal_replay_is_denied() -> None:
    selected = capability(supports_async=True)
    accepted = McpTransportReply(
        status=McpTransportStatus.ACCEPTED,
        server_id="fixture-mcp",
        server_version="1.0.0",
        summary="Accepted.",
        remote_task_id="remote-1",
    )
    cancelled = McpTransportReply(
        status=McpTransportStatus.CANCELLED,
        server_id="fixture-mcp",
        server_version="1.0.0",
        summary="Cancelled.",
        remote_task_id="remote-1",
    )
    runtime = Runtime(
        selected,
        FakeTransport([discovery_reply(selected), accepted, cancelled]),
    )
    try:
        asyncio.run(runtime.discover())
        _, started, _ = asyncio.run(
            runtime.invoke(
                McpOperation.INVOKE,
                {"value": "x"},
                observation="2" * 64,
                idempotency_key="invoke-1",
            )
        )
        assert started is not None and started.handle is not None
        first, output, _ = asyncio.run(
            runtime.invoke(
                McpOperation.CANCEL,
                {"handle": started.handle},
                observation="3" * 64,
                idempotency_key="cancel-1",
            )
        )
        assert output is not None and output.state == "CANCELLED"
        calls = len(runtime.transport.requests)
        second, _, _ = asyncio.run(
            runtime.invoke(
                McpOperation.CANCEL,
                {"handle": started.handle},
                observation="4" * 64,
                idempotency_key="cancel-1",
            )
        )
        assert second == first and len(runtime.transport.requests) == calls
        terminal, _, _ = asyncio.run(
            runtime.invoke(
                McpOperation.CANCEL,
                {"handle": started.handle},
                observation="5" * 64,
                idempotency_key="cancel-2",
            )
        )
        assert terminal.error_code == "MCP_STATE_INVALID"
        assert len(runtime.transport.requests) == calls
    finally:
        runtime.close()


def test_disconnect_preserves_pending_state_and_allows_later_poll() -> None:
    selected = capability(supports_async=True)
    accepted = McpTransportReply(
        status=McpTransportStatus.ACCEPTED,
        server_id="fixture-mcp",
        server_version="1.0.0",
        summary="Accepted.",
        remote_task_id="remote-1",
    )
    runtime = Runtime(
        selected,
        FakeTransport(
            [
                discovery_reply(selected),
                accepted,
                McpTransportError("MCP_DISCONNECTED"),
                completed_reply(),
            ]
        ),
    )
    try:
        asyncio.run(runtime.discover())
        _, started, _ = asyncio.run(
            runtime.invoke(
                McpOperation.INVOKE,
                {"value": "x"},
                observation="2" * 64,
                idempotency_key="invoke-1",
            )
        )
        assert started is not None and started.handle is not None
        failed, _, _ = asyncio.run(
            runtime.invoke(
                McpOperation.POLL,
                {"handle": started.handle},
                observation="3" * 64,
            )
        )
        assert failed.error_code == "MCP_DISCONNECTED" and failed.retryable
        record = runtime.state.get(started.handle)
        assert record is not None and record.state is McpAsyncState.PENDING
        completed, _, _ = asyncio.run(
            runtime.invoke(
                McpOperation.POLL,
                {"handle": started.handle},
                observation="4" * 64,
            )
        )
        assert completed.status is ToolStatus.SUCCESS
    finally:
        runtime.close()


def test_large_result_requires_immutable_same_scope_artifact() -> None:
    selected = capability(max_inline_bytes=256)
    large = "x" * 300
    for artifacts, expected in (
        ((), "MCP_ARTIFACT_INVALID"),
        ((artifact(immutable=False, value=large),), "MCP_ARTIFACT_INVALID"),
        (
            (
                artifact(
                    scope=SCOPE.model_copy(
                        update={"project_id": UUID("00000000-0000-4000-8000-000000000705")}
                    ),
                    value=large,
                ),
            ),
            "MCP_ARTIFACT_INVALID",
        ),
        ((artifact(value=large),), None),
    ):
        runtime = Runtime(
            selected,
            FakeTransport(
                [discovery_reply(selected), completed_reply(value=large, artifacts=artifacts)]
            ),
        )
        try:
            asyncio.run(runtime.discover())
            result, output, _ = asyncio.run(
                runtime.invoke(McpOperation.INVOKE, {"value": "x"}, observation="2" * 64)
            )
            assert result.error_code == expected
            if expected is None:
                assert output is not None and output.content["artifact_only"] is True
                assert "x" * 100 not in result.model_dump_json()
        finally:
            runtime.close()


def test_invalid_or_expired_credential_is_typed_before_transport() -> None:
    selected = capability()
    broker = FakeCredentialBroker(audience="wrong-audience")
    runtime = Runtime(
        selected,
        FakeTransport([discovery_reply(selected)]),
        broker=broker,
    )
    try:
        result, _, _ = asyncio.run(runtime.discover())
        assert result.error_code == "MCP_CREDENTIAL_FAILED"
        assert not runtime.transport.requests
    finally:
        runtime.close()


def test_local_gateway_uses_no_network_or_credentials() -> None:
    selected = capability(data_destination=ToolDataDestination.LOCAL)
    local_server = server(deployment=McpDeployment.LOCAL)
    transport = FakeTransport([discovery_reply(selected), completed_reply()])
    runtime = Runtime(selected, transport, selected_server=local_server)
    try:
        assert runtime.definition(McpOperation.DISCOVER).network is NetworkPolicy.NONE
        asyncio.run(runtime.discover())
        result, _, _ = asyncio.run(
            runtime.invoke(McpOperation.INVOKE, {"value": "x"}, observation="2" * 64)
        )
        assert result.status is ToolStatus.SUCCESS
        assert runtime.broker is None and transport.credentials == [None, None]
    finally:
        runtime.close()


def test_registry_timeout_is_typed_without_hidden_retry() -> None:
    selected = capability(timeout_ms=1)
    transport = FakeTransport([discovery_reply(selected), completed_reply()])
    runtime = Runtime(selected, transport)
    try:
        asyncio.run(runtime.discover())
        transport.delay = 0.02
        result, output, budget = asyncio.run(
            runtime.invoke(McpOperation.INVOKE, {"value": "x"}, observation="2" * 64)
        )
        assert result.status is ToolStatus.TIMEOUT and result.error_code == "TOOL_TIMEOUT"
        assert output is None
        assert len(transport.requests) == 2
        assert budget.telemetry().counters.physical_tool_calls == 1
    finally:
        runtime.close()
