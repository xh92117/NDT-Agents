"""S5-01 unified capability publication, exposure, and security tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from ndt_agents.contracts.v1 import TenantScope, ToolResult, ToolStatus
from ndt_agents.observability import (
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.tools import (
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolDataDestination,
    ToolDataScope,
    ToolDefinition,
    ToolExposureManifest,
    ToolExposurePolicy,
    ToolInvocation,
    ToolInvocationContext,
    ToolKind,
    ToolRecoveryPolicy,
    ToolRegistry,
    ToolRegistryError,
    ToolTransport,
    tool_approval_binding_sha256,
)
from ndt_agents.tools.registry import canonical_sha256

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000501"),
    project_id=UUID("00000000-0000-4000-8000-000000000502"),
    user_id=UUID("00000000-0000-4000-8000-000000000503"),
    role_codes=("TOOL_USER",),
    permission_version="permissions-s5-1",
)
TASK_ID = UUID("00000000-0000-4000-8000-000000000511")
RUN_ID = UUID("00000000-0000-4000-8000-000000000512")

_TRANSPORTS = {
    ToolKind.INTERNAL: ToolTransport.INTERNAL,
    ToolKind.BASH: ToolTransport.BASH,
    ToolKind.FUNCTION: ToolTransport.FUNCTION,
    ToolKind.WEB_SEARCH: ToolTransport.HTTP_API,
    ToolKind.MCP: ToolTransport.MCP,
    ToolKind.INSTRUMENT: ToolTransport.SIMULATOR,
    ToolKind.AI_MODEL: ToolTransport.SIMULATOR,
}
_TEST_GROUPS = {
    ToolKind.INTERNAL: frozenset({"UNIT-TOOLREG"}),
    ToolKind.BASH: frozenset({"INT-BASH", "SEC-BASH", "SEC-TOOLS"}),
    ToolKind.FUNCTION: frozenset({"INT-FUNCTION", "SEC-TOOLS"}),
    ToolKind.WEB_SEARCH: frozenset({"INT-WEB", "SEC-TOOLS"}),
    ToolKind.MCP: frozenset({"INT-MCP", "SEC-TOOLS"}),
    ToolKind.INSTRUMENT: frozenset({"INT-INSTRUMENT", "SEC-TOOLS"}),
    ToolKind.AI_MODEL: frozenset({"UNIT-MODELREG", "INT-INSTRUMENT", "SEC-TOOLS"}),
}


def definition(
    name: str,
    kind: ToolKind = ToolKind.INTERNAL,
    *,
    version: str = "1.0.0",
    transport: ToolTransport | None = None,
    namespace: str | None = None,
    destination: ToolDataDestination | None = None,
    network: NetworkPolicy | None = None,
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY,
    approval_required: bool = False,
    max_attempts: int = 1,
    recovery_policy: ToolRecoveryPolicy | None = None,
    max_tokens: int | None = None,
    test_groups: frozenset[str] | None = None,
    input_schema: dict[str, Any] | None = None,
) -> ToolDefinition:
    selected_destination = destination or (
        ToolDataDestination.APPROVED_EXTERNAL
        if kind is ToolKind.WEB_SEARCH
        else ToolDataDestination.LOCAL
    )
    selected_network = network or (
        NetworkPolicy.RESTRICTED
        if selected_destination is ToolDataDestination.APPROVED_EXTERNAL
        else NetworkPolicy.NONE
    )
    selected_recovery = recovery_policy or (
        ToolRecoveryPolicy.RETRY_READ_ONLY
        if max_attempts > 1
        else (
            ToolRecoveryPolicy.RECONCILE
            if side_effect is not SideEffectClass.READ_ONLY
            else ToolRecoveryPolicy.NO_RETRY
        )
    )
    if side_effect is SideEffectClass.IRREVERSIBLE and approval_required:
        selected_recovery = recovery_policy or ToolRecoveryPolicy.HUMAN_REVIEW
    return ToolDefinition(
        name=name,
        version=version,
        purpose=f"Exercise {kind.value} registration.",
        kind=kind,
        transport=transport or _TRANSPORTS[kind],
        namespace=namespace or ("fixture.server" if kind is ToolKind.MCP else None),
        data_scope=ToolDataScope.TASK,
        data_destination=selected_destination,
        side_effect=side_effect,
        input_schema=input_schema
        or {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"echo": {"type": "string"}},
            "required": ["echo"],
            "additionalProperties": False,
        },
        required_permissions=frozenset({f"permission.{name}"}),
        timeout_ms=100,
        max_attempts=max_attempts,
        max_concurrency=1 if side_effect is not SideEffectClass.READ_ONLY else 2,
        max_input_bytes=1000,
        max_output_bytes=1000,
        max_tokens=max_tokens
        if max_tokens is not None
        else (1000 if kind is ToolKind.AI_MODEL else 0),
        idempotency=(
            IdempotencyPolicy.REQUIRED
            if side_effect is not SideEffectClass.READ_ONLY
            else IdempotencyPolicy.NONE
        ),
        secret_purposes=(
            frozenset({"fixture.provider"})
            if selected_network is NetworkPolicy.RESTRICTED
            else frozenset()
        ),
        network=selected_network,
        approval_required=approval_required,
        declared_error_codes=frozenset({"FIXTURE_FAILURE"}),
        recovery_policy=selected_recovery,
        audit_owner="tool-runtime",
        test_owner="tool-runtime",
        test_groups=test_groups or _TEST_GROUPS[kind],
    )


class Adapter:
    def __init__(
        self,
        *,
        status: ToolStatus = ToolStatus.SUCCESS,
        error_code: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.calls = 0
        self.status = status
        self.error_code = error_code
        self.retryable = retryable

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        self.calls += 1
        output = {"echo": invocation.arguments["value"]}
        return ToolResult(
            call_id=invocation.call_id,
            task_id=invocation.context.task_id,
            run_id=invocation.context.run_id,
            scope=invocation.context.scope,
            tool_name=invocation.definition.name,
            tool_version=invocation.definition.version,
            status=self.status,
            output=output,
            exit_code=0 if self.status is ToolStatus.SUCCESS else None,
            stdout="",
            stderr="",
            encoding="utf-8",
            truncated=False,
            artifacts=(),
            idempotency_key=invocation.idempotency_key,
            input_sha256=invocation.input_sha256,
            output_sha256=canonical_sha256(output),
            error_code=self.error_code,
            retryable=self.retryable,
            duration_ms=1,
            completed_at=datetime(2026, 8, 25, 4, 0, tzinfo=UTC),
        )


class Runtime:
    def __init__(
        self,
        definitions: tuple[ToolDefinition, ...],
        adapters: tuple[Adapter, ...] | None = None,
    ) -> None:
        self.definitions = definitions
        self.adapters = adapters or tuple(Adapter() for _ in definitions)
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="unified-tool-registry-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.repository = InMemoryAuditRepository()
        self.registry = ToolRegistry(
            definitions,
            {item.key: adapter for item, adapter in zip(definitions, self.adapters, strict=True)},
            audit=AuditService(self.repository, self.traces),
            clock=lambda: datetime(2026, 8, 25, 4, 0, tzinfo=UTC),
        )

    def context(
        self,
        *,
        allowed_tools: frozenset[str] | None = None,
        permissions: frozenset[str] | None = None,
        destinations: frozenset[ToolDataDestination] | None = None,
        secret_purposes: frozenset[str] | None = None,
        allow_network: bool = True,
        approved_call_sha256s: frozenset[str] = frozenset(),
    ) -> ToolInvocationContext:
        return ToolInvocationContext(
            task_id=TASK_ID,
            run_id=RUN_ID,
            scope=SCOPE,
            request_id="s5-tool-request-1",
            policy_version="s5-tool-policy-1",
            expected_registry_version=self.registry.version,
            allowed_tools=allowed_tools or frozenset(item.key for item in self.definitions),
            granted_permissions=permissions
            or frozenset(
                permission for item in self.definitions for permission in item.required_permissions
            ),
            allowed_secret_purposes=secret_purposes
            or frozenset(purpose for item in self.definitions for purpose in item.secret_purposes),
            allowed_data_destinations=destinations
            or frozenset(item.data_destination for item in self.definitions),
            approved_call_sha256s=approved_call_sha256s,
            allow_network=allow_network,
        )

    def close(self) -> None:
        self.traces.shutdown()

    def expose(
        self,
        context: ToolInvocationContext,
        *,
        policy: ToolExposurePolicy | None = None,
    ) -> ToolExposureManifest:
        with self.traces.start_span("tool.expose"):
            return self.registry.expose(context, policy=policy)

    async def invoke(self, **arguments: Any) -> ToolResult:
        with self.traces.start_span("tool.invoke"):
            return await self.registry.invoke(**arguments)


def test_all_capability_families_publish_with_explicit_contracts() -> None:
    definitions = tuple(definition(f"fixture.{kind.value.lower()}", kind) for kind in ToolKind)
    runtime = Runtime(definitions)
    duplicate = Runtime(definitions)
    changed_definitions = definitions[:-1] + (
        definition("fixture.ai_model", ToolKind.AI_MODEL, version="1.0.1"),
    )
    changed = Runtime(changed_definitions)
    try:
        assert {item.kind for item in runtime.registry.definitions} == set(ToolKind)
        assert all(item.test_owner and item.declared_error_codes for item in definitions)
        assert runtime.registry.version == duplicate.registry.version
        assert runtime.registry.version != changed.registry.version
    finally:
        runtime.close()
        duplicate.close()
        changed.close()


@pytest.mark.parametrize(
    "updates",
    [
        {"network": NetworkPolicy.NONE},
        {"transport": ToolTransport.INTERNAL},
        {"data_destination": ToolDataDestination.LOCAL},
        {"test_groups": frozenset({"INT-WEB"})},
    ],
)
def test_web_family_rejects_unsafe_contract_combinations(updates: dict[str, Any]) -> None:
    base = definition("fixture.web", ToolKind.WEB_SEARCH).model_dump()
    with pytest.raises(PydanticValidationError):
        ToolDefinition.model_validate({**base, **updates})


def test_family_contracts_reject_missing_namespace_transport_token_and_approval() -> None:
    invalid = (
        {
            **definition("fixture.mcp", ToolKind.MCP).model_dump(),
            "namespace": None,
        },
        {
            **definition("fixture.instrument", ToolKind.INSTRUMENT).model_dump(),
            "transport": ToolTransport.INTERNAL,
        },
        {
            **definition("fixture.model", ToolKind.AI_MODEL).model_dump(),
            "max_tokens": 0,
        },
        {
            **definition("fixture.effect").model_dump(),
            "side_effect": SideEffectClass.IRREVERSIBLE,
            "idempotency": IdempotencyPolicy.REQUIRED,
            "max_concurrency": 1,
            "recovery_policy": ToolRecoveryPolicy.HUMAN_REVIEW,
            "approval_required": False,
        },
    )
    for payload in invalid:
        with pytest.raises(PydanticValidationError):
            ToolDefinition.model_validate(payload)

    instrument_over_mcp = definition(
        "fixture.instrument_mcp",
        ToolKind.INSTRUMENT,
        transport=ToolTransport.MCP,
        namespace="fixture.device",
    )
    assert instrument_over_mcp.namespace == "fixture.device"
    with pytest.raises(PydanticValidationError, match="namespace"):
        definition(
            "fixture.instrument_mcp_invalid",
            ToolKind.INSTRUMENT,
            transport=ToolTransport.MCP,
        )


def test_plaintext_secret_fields_and_invalid_recovery_are_rejected() -> None:
    secret_schema = {
        "type": "object",
        "properties": {"api_key": {"type": "string"}},
        "required": ["api_key"],
        "additionalProperties": False,
    }
    with pytest.raises(PydanticValidationError, match="secret references"):
        definition("fixture.secret", input_schema=secret_schema)
    with pytest.raises(PydanticValidationError, match="multiple attempts"):
        ToolDefinition.model_validate(
            {
                **definition("fixture.retry").model_dump(),
                "max_attempts": 2,
                "recovery_policy": ToolRecoveryPolicy.NO_RETRY,
            }
        )


@pytest.mark.parametrize(
    "field_name",
    (
        "access_key",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "password",
        "private-key",
        "secret",
        "token",
    ),
)
def test_plaintext_secret_schema_policy_is_consistent_across_tool_boundaries(
    field_name: str,
) -> None:
    from tests.tools.test_adapter_sdk import registration
    from tests.tools.test_mcp_gateway import capability

    nested_secret_schema = {
        "type": "object",
        "properties": {
            "request": {
                "type": "object",
                "properties": {field_name: {"type": "string"}},
                "required": [field_name],
                "additionalProperties": False,
            }
        },
        "required": ["request"],
        "additionalProperties": False,
    }
    with pytest.raises(PydanticValidationError, match="secret references"):
        definition(
            f"fixture.secret.{field_name.replace('_', '-')}", input_schema=nested_secret_schema
        )
    with pytest.raises(PydanticValidationError, match="credential"):
        registration(input_schema=nested_secret_schema)
    with pytest.raises(PydanticValidationError, match="credential"):
        capability(input_schema=nested_secret_schema)


def test_authorized_exposure_is_deterministic_minimal_and_zero_call() -> None:
    definitions = (
        definition("fixture.internal"),
        definition("fixture.function", ToolKind.FUNCTION),
        definition("fixture.web", ToolKind.WEB_SEARCH),
    )
    runtime = Runtime(definitions)
    try:
        first = runtime.expose(runtime.context())
        second = runtime.expose(runtime.context())
        serialized = first.model_dump_json()
        assert first == second
        assert [item.name for item in first.tools] == sorted(item.name for item in definitions)
        assert "fixture.provider" not in serialized
        assert "output_schema" not in serialized
        assert "transport" not in serialized
        assert sum(adapter.calls for adapter in runtime.adapters) == 0
        with pytest.raises(PydanticValidationError, match="manifest hash"):
            type(first).model_validate({**first.model_dump(), "manifest_sha256": "0" * 64})
        events = runtime.repository.list(SCOPE)
        assert len(events) == 2
        assert all(
            event.action == "tool.expose" and event.decision == "AUTHORIZED" for event in events
        )
    finally:
        runtime.close()


def test_exposure_enforces_default_and_hard_tool_limits() -> None:
    definitions = tuple(
        definition(f"fixture.function{index}", ToolKind.FUNCTION) for index in range(7)
    )
    runtime = Runtime(definitions)
    try:
        with pytest.raises(ToolRegistryError) as captured:
            runtime.expose(runtime.context())
        assert captured.value.code == "TOOL_EXPOSURE_LIMIT"
        manifest = runtime.expose(runtime.context(), policy=ToolExposurePolicy(max_tools=7))
        assert len(manifest.tools) == 7
        with pytest.raises(PydanticValidationError):
            ToolExposurePolicy(max_tools=13)
        assert sum(adapter.calls for adapter in runtime.adapters) == 0
    finally:
        runtime.close()


def test_exposure_enforces_default_and_hard_mcp_namespace_limits() -> None:
    definitions = (
        definition("fixture.mcp_a", ToolKind.MCP, namespace="fixture.alpha"),
        definition(
            "fixture.instrument_mcp",
            ToolKind.INSTRUMENT,
            transport=ToolTransport.MCP,
            namespace="fixture.beta",
        ),
    )
    runtime = Runtime(definitions)
    try:
        with pytest.raises(ToolRegistryError) as captured:
            runtime.expose(runtime.context())
        assert captured.value.code == "TOOL_MCP_NAMESPACE_LIMIT"
        manifest = runtime.expose(
            runtime.context(), policy=ToolExposurePolicy(max_mcp_namespaces=2)
        )
        assert {item.namespace for item in manifest.tools} == {"fixture.alpha", "fixture.beta"}
        with pytest.raises(PydanticValidationError):
            ToolExposurePolicy(max_mcp_namespaces=3)
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("context_updates", "code"),
    [
        ({"permissions": frozenset({"unrelated"})}, "TOOL_PERMISSION_DENIED"),
        ({"secret_purposes": frozenset({"unrelated"})}, "TOOL_SECRET_PURPOSE_DENIED"),
        ({"allow_network": False}, "TOOL_NETWORK_DENIED"),
        (
            {"destinations": frozenset({ToolDataDestination.LOCAL})},
            "TOOL_DATA_DESTINATION_DENIED",
        ),
        (
            {"allowed_tools": frozenset({"fixture.missing@1.0.0"})},
            "TOOL_EXPOSURE_TOOL_INVALID",
        ),
    ],
)
def test_exposure_denials_are_audited_and_zero_call(
    context_updates: dict[str, Any], code: str
) -> None:
    runtime = Runtime((definition("fixture.web", ToolKind.WEB_SEARCH),))
    try:
        with pytest.raises(ToolRegistryError) as captured:
            runtime.expose(runtime.context(**context_updates))
        assert captured.value.code == code
        assert runtime.adapters[0].calls == 0
        event = runtime.repository.list(SCOPE)[0]
        assert event.action == "tool.expose" and event.decision == code
    finally:
        runtime.close()


def test_high_impact_invocation_requires_exact_approval_binding() -> None:
    tool = definition(
        "fixture.instrument",
        ToolKind.INSTRUMENT,
        side_effect=SideEffectClass.IRREVERSIBLE,
        approval_required=True,
        recovery_policy=ToolRecoveryPolicy.HUMAN_REVIEW,
    )
    runtime = Runtime((tool,))
    arguments = {"value": "approved"}
    base_context = runtime.context()
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        exposure = runtime.expose(
            base_context,
            policy=ToolExposurePolicy(
                allow_side_effects=True,
                allow_approval_required=True,
            ),
        )
        assert exposure.tools[0].approval_required
        with pytest.raises(ToolRegistryError) as missing:
            asyncio.run(
                runtime.invoke(
                    name=tool.name,
                    version=tool.version,
                    arguments=arguments,
                    context=base_context,
                    budget=budget,
                    observation_sha256="1" * 64,
                    idempotency_key="instrument-action-1",
                )
            )
        assert missing.value.code == "TOOL_APPROVAL_REQUIRED"
        assert runtime.adapters[0].calls == 0

        binding = tool_approval_binding_sha256(
            base_context,
            tool,
            canonical_sha256(arguments),
        )
        approved_context = base_context.model_copy(
            update={"approved_call_sha256s": frozenset({binding})}
        )
        result = asyncio.run(
            runtime.invoke(
                name=tool.name,
                version=tool.version,
                arguments=arguments,
                context=approved_context,
                budget=budget,
                observation_sha256="2" * 64,
                idempotency_key="instrument-action-1",
            )
        )
        assert result.status is ToolStatus.SUCCESS
        assert runtime.adapters[0].calls == 1
        with pytest.raises(ToolRegistryError) as stale:
            asyncio.run(
                runtime.invoke(
                    name=tool.name,
                    version=tool.version,
                    arguments={"value": "changed"},
                    context=approved_context,
                    budget=budget,
                    observation_sha256="3" * 64,
                    idempotency_key="instrument-action-1",
                )
            )
        assert stale.value.code == "TOOL_APPROVAL_REQUIRED"
        assert runtime.adapters[0].calls == 1
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("adapter", "code"),
    [
        (
            Adapter(status=ToolStatus.FAILED, error_code="UNDECLARED_FAILURE"),
            "TOOL_RESULT_ERROR_UNDECLARED",
        ),
        (
            Adapter(
                status=ToolStatus.FAILED,
                error_code="FIXTURE_FAILURE",
                retryable=True,
            ),
            "TOOL_RESULT_RETRY_INVALID",
        ),
    ],
)
def test_invalid_adapter_failure_contracts_are_rejected_after_one_call(
    adapter: Adapter, code: str
) -> None:
    runtime = Runtime((definition("fixture.internal"),), (adapter,))
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        with pytest.raises(ToolRegistryError) as captured:
            asyncio.run(
                runtime.invoke(
                    name="fixture.internal",
                    version="1.0.0",
                    arguments={"value": "x"},
                    context=runtime.context(),
                    budget=budget,
                    observation_sha256="4" * 64,
                )
            )
        assert captured.value.code == code
        assert adapter.calls == 1
        assert budget.telemetry().counters.physical_tool_calls == 1
    finally:
        runtime.close()


def test_retry_attempt_state_is_bounded_before_execution() -> None:
    tool = definition(
        "fixture.function",
        ToolKind.FUNCTION,
        max_attempts=2,
        recovery_policy=ToolRecoveryPolicy.RETRY_READ_ONLY,
    )
    runtime = Runtime((tool,))
    try:
        for attempt_number, retry, code in (
            (2, False, "TOOL_RETRY_STATE_INVALID"),
            (3, True, "TOOL_ATTEMPT_LIMIT"),
        ):
            with pytest.raises(ToolRegistryError) as captured:
                asyncio.run(
                    runtime.invoke(
                        name=tool.name,
                        version=tool.version,
                        arguments={"value": "retry"},
                        context=runtime.context(),
                        budget=BudgetGuard(default_budget_policy("G0")),
                        observation_sha256=str(attempt_number) * 64,
                        retry=retry,
                        attempt_number=attempt_number,
                    )
                )
            assert captured.value.code == code
        budget = BudgetGuard(default_budget_policy("G0"))
        result = asyncio.run(
            runtime.invoke(
                name=tool.name,
                version=tool.version,
                arguments={"value": "retry"},
                context=runtime.context(),
                budget=budget,
                observation_sha256="5" * 64,
                retry=True,
                attempt_number=2,
            )
        )
        assert result.status is ToolStatus.SUCCESS
        assert runtime.adapters[0].calls == 1
        assert budget.telemetry().counters.retries == 1
    finally:
        runtime.close()


def test_ai_model_invocation_requires_separately_metered_gateway() -> None:
    tool = definition("fixture.model", ToolKind.AI_MODEL)
    runtime = Runtime((tool,))
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        with pytest.raises(ToolRegistryError) as captured:
            asyncio.run(
                runtime.invoke(
                    name=tool.name,
                    version=tool.version,
                    arguments={"value": "prompt-reference"},
                    context=runtime.context(),
                    budget=budget,
                    observation_sha256="6" * 64,
                )
            )
        assert captured.value.code == "TOOL_MODEL_GATEWAY_REQUIRED"
        assert runtime.adapters[0].calls == 0
        counters = budget.telemetry().counters
        assert counters.physical_tool_calls == 0
        assert counters.physical_llm_calls == 0
    finally:
        runtime.close()
