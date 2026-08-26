"""S5-02 provider-neutral Function Calling gateway tests."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any, cast
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
    FunctionCatalog,
    FunctionGateway,
    FunctionGatewayError,
    FunctionGatewayPolicy,
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolDataDestination,
    ToolDataScope,
    ToolDefinition,
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
    role_codes=("FUNCTION_USER",),
    permission_version="permissions-1",
)
TASK_ID = UUID("00000000-0000-4000-8000-000000000511")
RUN_ID = UUID("00000000-0000-4000-8000-000000000512")
NOW = datetime(2026, 8, 25, 5, 0, tzinfo=UTC)


def definition(
    name: str = "fixture.echo",
    *,
    version: str = "1.0.0",
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY,
    approval_required: bool = False,
    timeout_ms: int = 100,
) -> ToolDefinition:
    if side_effect is SideEffectClass.READ_ONLY:
        idempotency = IdempotencyPolicy.NONE
        recovery = ToolRecoveryPolicy.RETRY_READ_ONLY
        max_attempts = 2
        max_concurrency = 3
    else:
        idempotency = IdempotencyPolicy.REQUIRED
        recovery = (
            ToolRecoveryPolicy.HUMAN_REVIEW if approval_required else ToolRecoveryPolicy.RECONCILE
        )
        max_attempts = 1
        max_concurrency = 1
    return ToolDefinition(
        name=name,
        version=version,
        purpose="Return one validated fixture value.",
        kind=ToolKind.FUNCTION,
        transport=ToolTransport.FUNCTION,
        data_scope=ToolDataScope.TASK,
        data_destination=ToolDataDestination.LOCAL,
        side_effect=side_effect,
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"value": {"type": "string", "maxLength": 200}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"echo": {"type": "string"}},
            "required": ["echo"],
            "additionalProperties": False,
        },
        required_permissions=frozenset({"function.invoke"}),
        timeout_ms=timeout_ms,
        max_attempts=max_attempts,
        max_concurrency=max_concurrency,
        max_input_bytes=2_000,
        max_output_bytes=2_000,
        max_tokens=0,
        idempotency=idempotency,
        network=NetworkPolicy.NONE,
        approval_required=approval_required,
        declared_error_codes=frozenset({"FIXTURE_FAILED"}),
        recovery_policy=recovery,
        audit_owner="function-runtime",
        test_owner="function-runtime",
        test_groups=frozenset({"INT-FUNCTION", "SEC-TOOLS"}),
    )


class EchoAdapter:
    def __init__(self, *, delay: float = 0, bad_hash: bool = False) -> None:
        self.calls = 0
        self.delay = delay
        self.bad_hash = bad_hash

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        output = {"echo": invocation.arguments["value"]}
        return ToolResult(
            call_id=invocation.call_id,
            task_id=invocation.context.task_id,
            run_id=invocation.context.run_id,
            scope=invocation.context.scope,
            tool_name=invocation.definition.name,
            tool_version=invocation.definition.version,
            status=ToolStatus.SUCCESS,
            output=output,
            exit_code=0,
            stdout="",
            stderr="",
            encoding="utf-8",
            truncated=False,
            artifacts=(),
            idempotency_key=invocation.idempotency_key,
            input_sha256=invocation.input_sha256,
            output_sha256="0" * 64 if self.bad_hash else canonical_sha256(output),
            error_code=None,
            retryable=False,
            duration_ms=1,
            completed_at=NOW,
        )


class Runtime:
    def __init__(
        self,
        definitions: tuple[ToolDefinition, ...] | None = None,
        adapters: tuple[EchoAdapter, ...] | None = None,
    ) -> None:
        self.definitions = definitions or (definition(),)
        self.adapters = adapters or tuple(EchoAdapter() for _ in self.definitions)
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="function-gateway-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.repository = InMemoryAuditRepository()
        self.audit = AuditService(self.repository, self.traces)
        self.registry = ToolRegistry(
            self.definitions,
            {
                item.key: adapter
                for item, adapter in zip(self.definitions, self.adapters, strict=True)
            },
            audit=self.audit,
            clock=lambda: NOW,
        )
        self.gateway = FunctionGateway(
            self.registry,
            audit=self.audit,
            traces=self.traces,
            clock=lambda: NOW,
            attestation_key=b"f" * 32,
        )

    def context(self, **updates: Any) -> ToolInvocationContext:
        values: dict[str, Any] = {
            "task_id": TASK_ID,
            "run_id": RUN_ID,
            "scope": SCOPE,
            "request_id": "function-request-1",
            "policy_version": "function-policy-1",
            "expected_registry_version": self.registry.version,
            "allowed_tools": frozenset(item.key for item in self.definitions),
            "granted_permissions": frozenset({"function.invoke"}),
            "allowed_data_destinations": frozenset({ToolDataDestination.LOCAL}),
        }
        values.update(updates)
        return ToolInvocationContext(**values)

    def catalog(
        self,
        context: ToolInvocationContext | None = None,
        *,
        exposure_policy: ToolExposurePolicy | None = None,
    ) -> FunctionCatalog:
        return self.gateway.load_catalog(
            context or self.context(),
            exposure_policy=exposure_policy,
        )

    @staticmethod
    def raw_call(
        catalog: FunctionCatalog,
        value: str = "ok",
        *,
        call_id: str = "provider-call-1",
    ) -> str:
        return json.dumps(
            {
                "call_id": call_id,
                "name": catalog.model_schemas()[0].name,
                "arguments": {"value": value},
            },
            separators=(",", ":"),
        )

    def close(self) -> None:
        self.traces.shutdown()


def physical_calls(budget: BudgetGuard) -> int:
    return budget.telemetry().counters.physical_tool_calls


def test_catalog_is_authorized_deterministic_and_model_surface_is_minimal() -> None:
    tools = (
        definition("fixture.echo"),
        definition("fixture.echo-long-name-with.punctuation", version="2.3.4"),
    )
    runtime = Runtime(tools)
    try:
        first = runtime.catalog()
        second = runtime.catalog()
        assert first == second
        assert [
            f"{binding.tool_name}@{binding.tool_version}" for binding in first.bindings
        ] == sorted(item.key for item in tools)
        schemas = first.model_schemas()
        assert all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item.name) for item in schemas)
        assert len({item.name for item in schemas}) == 2
        assert all(item.strict for item in schemas)
        visible = json.dumps([item.model_dump(mode="json") for item in schemas])
        for hidden in (
            "tool_name",
            "tool_version",
            "registry_version",
            "output_schema",
            "secret_purposes",
            "gateway_attestation",
        ):
            assert hidden not in visible
        assert sum(adapter.calls for adapter in runtime.adapters) == 0
        events = runtime.repository.list(SCOPE)
        assert len(events) == 2
        assert all(event.action == "tool.expose" for event in events)
    finally:
        runtime.close()


def test_catalog_load_uses_registry_permission_and_exposure_limits() -> None:
    runtime = Runtime()
    many = Runtime(tuple(definition(f"fixture.tool{index}") for index in range(7)))
    try:
        with pytest.raises(ToolRegistryError) as denied:
            runtime.catalog(runtime.context(granted_permissions=frozenset()))
        assert denied.value.code == "TOOL_PERMISSION_DENIED"
        with pytest.raises(ToolRegistryError) as limited:
            many.catalog()
        assert limited.value.code == "TOOL_EXPOSURE_LIMIT"
        assert all(adapter.calls == 0 for adapter in (*runtime.adapters, *many.adapters))
    finally:
        runtime.close()
        many.close()


@pytest.mark.parametrize(
    "reference",
    ["https://untrusted.example/schema.json", "#/$defs/missing", "#named-anchor"],
)
def test_catalog_rejects_external_or_unresolved_schema_references(reference: str) -> None:
    payload = definition().model_dump()
    input_schema = cast(dict[str, Any], payload["input_schema"])
    input_schema["properties"]["value"] = {"$ref": reference}
    tool = ToolDefinition.model_validate(payload)
    runtime = Runtime((tool,))
    try:
        with pytest.raises(FunctionGatewayError) as captured:
            runtime.catalog()
        assert captured.value.code == "FUNCTION_SCHEMA_INVALID"
        assert runtime.adapters[0].calls == 0
        events = runtime.repository.list(SCOPE)
        assert [event.action for event in events] == ["tool.expose", "function.deny"]
    finally:
        runtime.close()


def test_catalog_accepts_resolvable_local_json_pointer_reference() -> None:
    payload = definition().model_dump()
    input_schema = cast(dict[str, Any], payload["input_schema"])
    input_schema["$defs"] = {"text": {"type": "string", "maxLength": 200}}
    input_schema["properties"]["value"] = {"$ref": "#/$defs/text"}
    tool = ToolDefinition.model_validate(payload)
    runtime = Runtime((tool,))
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        context = runtime.context()
        catalog = runtime.catalog(context)
        result = asyncio.run(
            runtime.gateway.invoke(
                runtime.raw_call(catalog, "local-ref"),
                catalog=catalog,
                context=context,
                budget=budget,
                observation_sha256="f" * 64,
            )
        )
        assert result.output == {"echo": "local-ref"}
        assert runtime.adapters[0].calls == 1
        assert physical_calls(budget) == 1
    finally:
        runtime.close()


def test_bare_allowed_tool_names_are_normalized_to_exact_deterministic_order() -> None:
    tools = (
        definition("fixture.echo"),
        definition("fixture.echo-long"),
    )
    runtime = Runtime(tools)
    try:
        context = runtime.context(allowed_tools=frozenset(item.name for item in tools))
        catalog = runtime.catalog(context)
        assert [
            f"{binding.tool_name}@{binding.tool_version}" for binding in catalog.bindings
        ] == sorted(item.key for item in tools)
        assert all(adapter.calls == 0 for adapter in runtime.adapters)
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("payload", "expected_code", "policy"),
    [
        ("{", "FUNCTION_JSON_INVALID", None),
        (
            '{"call_id":"a","call_id":"b","name":"valid_name","arguments":{}}',
            "FUNCTION_JSON_DUPLICATE_KEY",
            None,
        ),
        (
            '{"call_id":"a","name":"valid_name","arguments":{"value":NaN}}',
            "FUNCTION_JSON_NON_FINITE",
            None,
        ),
        (
            '{"call_id":"a","name":"valid_name","arguments":{},"retry":true}',
            "FUNCTION_ENVELOPE_INVALID",
            None,
        ),
        (
            '{"call_id":1,"name":"valid_name","arguments":{}}',
            "FUNCTION_ENVELOPE_INVALID",
            None,
        ),
        (
            '{"call_id":"a","name":"valid_name","arguments":[]}',
            "FUNCTION_ENVELOPE_INVALID",
            None,
        ),
        (b"\xff", "FUNCTION_ENCODING_INVALID", None),
        (
            '{"call_id":"a","name":"valid_name","arguments":{}}',
            "FUNCTION_PAYLOAD_TOO_LARGE",
            FunctionGatewayPolicy(max_call_bytes=8),
        ),
        (
            '{"call_id":"a","name":"valid_name","arguments":{"value":' + "1" * 5_000 + "}}",
            "FUNCTION_JSON_INVALID",
            None,
        ),
    ],
)
def test_invalid_json_envelopes_are_audited_before_budget_or_execution(
    payload: str | bytes,
    expected_code: str,
    policy: FunctionGatewayPolicy | None,
) -> None:
    runtime = Runtime()
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        catalog = runtime.catalog()
        with pytest.raises(FunctionGatewayError) as captured:
            asyncio.run(
                runtime.gateway.invoke(
                    payload,
                    catalog=catalog,
                    context=runtime.context(),
                    budget=budget,
                    observation_sha256="1" * 64,
                    policy=policy,
                )
            )
        assert captured.value.code == expected_code
        assert runtime.adapters[0].calls == 0
        assert physical_calls(budget) == 0
        event = runtime.repository.list(SCOPE)[-1]
        assert event.action == "function.deny"
        assert event.decision == expected_code
        assert "value" not in event.model_dump_json()
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("call", "expected_code"),
    [
        (
            {
                "call_id": "provider-call-1",
                "name": "unknown_function",
                "arguments": {"value": "ok"},
            },
            "FUNCTION_UNAVAILABLE",
        ),
        (
            {
                "call_id": "provider-call-1",
                "name": "__CURRENT__",
                "arguments": {"value": 1},
            },
            "FUNCTION_ARGUMENTS_INVALID",
        ),
        (
            {
                "call_id": "provider-call-1",
                "name": "__CURRENT__",
                "arguments": {"value": "ok", "approval": True},
            },
            "FUNCTION_ARGUMENTS_INVALID",
        ),
    ],
)
def test_unknown_function_and_invalid_arguments_are_zero_call(
    call: dict[str, Any], expected_code: str
) -> None:
    runtime = Runtime()
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        catalog = runtime.catalog()
        if call["name"] == "__CURRENT__":
            call["name"] = catalog.model_schemas()[0].name
        with pytest.raises(FunctionGatewayError) as captured:
            asyncio.run(
                runtime.gateway.invoke(
                    json.dumps(call),
                    catalog=catalog,
                    context=runtime.context(),
                    budget=budget,
                    observation_sha256="2" * 64,
                )
            )
        assert captured.value.code == expected_code
        assert runtime.adapters[0].calls == 0
        assert physical_calls(budget) == 0
    finally:
        runtime.close()


def test_catalog_attestation_staleness_and_context_binding_fail_closed() -> None:
    runtime = Runtime()
    changed = Runtime((definition(version="1.0.1"),))
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        context = runtime.context()
        catalog = runtime.catalog(context)
        raw = runtime.raw_call(catalog)
        untrusted = catalog.model_copy(update={"gateway_attestation_sha256": "0" * 64})
        with pytest.raises(FunctionGatewayError) as forged:
            asyncio.run(
                runtime.gateway.invoke(
                    raw,
                    catalog=untrusted,
                    context=context,
                    budget=budget,
                    observation_sha256="3" * 64,
                )
            )
        assert forged.value.code == "FUNCTION_CATALOG_UNTRUSTED"

        broken_binding = catalog.bindings[0].model_copy(update={"schema_sha256": "0" * 64})
        invalid = catalog.model_copy(update={"bindings": (broken_binding,)})
        with pytest.raises(FunctionGatewayError) as tampered:
            asyncio.run(
                runtime.gateway.invoke(
                    raw,
                    catalog=invalid,
                    context=context,
                    budget=budget,
                    observation_sha256="3" * 64,
                )
            )
        assert tampered.value.code == "FUNCTION_CATALOG_INVALID"

        with pytest.raises(FunctionGatewayError) as scope_changed:
            asyncio.run(
                runtime.gateway.invoke(
                    raw,
                    catalog=catalog,
                    context=runtime.context(request_id="function-request-2"),
                    budget=budget,
                    observation_sha256="4" * 64,
                )
            )
        assert scope_changed.value.code == "FUNCTION_CONTEXT_MISMATCH"

        with pytest.raises(FunctionGatewayError) as stale:
            asyncio.run(
                changed.gateway.invoke(
                    raw,
                    catalog=catalog,
                    context=changed.context(),
                    budget=budget,
                    observation_sha256="5" * 64,
                )
            )
        assert stale.value.code == "FUNCTION_CATALOG_STALE"
        assert runtime.adapters[0].calls == changed.adapters[0].calls == 0
        assert physical_calls(budget) == 0
    finally:
        runtime.close()
        changed.close()


def test_valid_call_returns_exact_tool_result_and_counts_one_physical_call() -> None:
    tools = (
        definition("fixture.echo", version="1.0.0"),
        definition("fixture.echo", version="2.0.0"),
    )
    runtime = Runtime(tools)
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        context = runtime.context(allowed_tools=frozenset({tools[1].key}))
        catalog = runtime.catalog(context)
        result = asyncio.run(
            runtime.gateway.invoke(
                runtime.raw_call(catalog, "selected"),
                catalog=catalog,
                context=context,
                budget=budget,
                observation_sha256="6" * 64,
            )
        )
        assert isinstance(result, ToolResult)
        assert result.tool_version == "2.0.0"
        assert result.output == {"echo": "selected"}
        assert runtime.adapters[0].calls == 0
        assert runtime.adapters[1].calls == 1
        assert physical_calls(budget) == 1
        events = runtime.repository.list(SCOPE)
        assert [event.action for event in events] == [
            "tool.expose",
            "tool.execute",
            "function.execute",
        ]
        assert "selected" not in json.dumps([event.model_dump(mode="json") for event in events])
    finally:
        runtime.close()


def test_side_effect_idempotency_is_orchestration_controlled_and_duplicate_free() -> None:
    tool = definition("fixture.write", side_effect=SideEffectClass.REVERSIBLE)
    runtime = Runtime((tool,))
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        context = runtime.context()
        catalog = runtime.catalog(
            context,
            exposure_policy=ToolExposurePolicy(allow_side_effects=True),
        )
        raw = runtime.raw_call(catalog, "once")
        first = asyncio.run(
            runtime.gateway.invoke(
                raw,
                catalog=catalog,
                context=context,
                budget=budget,
                observation_sha256="7" * 64,
                idempotency_key="write-once-1",
            )
        )
        second = asyncio.run(
            runtime.gateway.invoke(
                raw,
                catalog=catalog,
                context=context,
                budget=budget,
                observation_sha256="8" * 64,
                idempotency_key="write-once-1",
            )
        )
        assert first == second
        assert runtime.adapters[0].calls == 1
        assert physical_calls(budget) == 1
        assert any(event.action == "tool.replay" for event in runtime.repository.list(SCOPE))
    finally:
        runtime.close()


def test_approval_binding_requires_catalog_reload_after_context_change() -> None:
    tool = definition(
        "fixture.release",
        side_effect=SideEffectClass.IRREVERSIBLE,
        approval_required=True,
    )
    runtime = Runtime((tool,))
    budget = BudgetGuard(default_budget_policy("G0"))
    exposure = ToolExposurePolicy(allow_side_effects=True, allow_approval_required=True)
    try:
        context = runtime.context()
        catalog = runtime.catalog(context, exposure_policy=exposure)
        raw = runtime.raw_call(catalog, "approved")
        with pytest.raises(ToolRegistryError) as missing:
            asyncio.run(
                runtime.gateway.invoke(
                    raw,
                    catalog=catalog,
                    context=context,
                    budget=budget,
                    observation_sha256="9" * 64,
                    idempotency_key="release-1",
                )
            )
        assert missing.value.code == "TOOL_APPROVAL_REQUIRED"
        arguments = {"value": "approved"}
        binding = tool_approval_binding_sha256(
            context,
            tool,
            canonical_sha256(arguments),
        )
        approved = context.model_copy(update={"approved_call_sha256s": frozenset({binding})})
        with pytest.raises(FunctionGatewayError) as changed:
            asyncio.run(
                runtime.gateway.invoke(
                    raw,
                    catalog=catalog,
                    context=approved,
                    budget=budget,
                    observation_sha256="a" * 64,
                    idempotency_key="release-1",
                )
            )
        assert changed.value.code == "FUNCTION_CONTEXT_MISMATCH"
        approved_catalog = runtime.catalog(approved, exposure_policy=exposure)
        result = asyncio.run(
            runtime.gateway.invoke(
                runtime.raw_call(approved_catalog, "approved"),
                catalog=approved_catalog,
                context=approved,
                budget=budget,
                observation_sha256="b" * 64,
                idempotency_key="release-1",
            )
        )
        assert result.status is ToolStatus.SUCCESS
        assert runtime.adapters[0].calls == 1
        assert physical_calls(budget) == 1
    finally:
        runtime.close()


def test_timeout_returns_typed_result_without_hidden_retry() -> None:
    adapter = EchoAdapter(delay=0.03)
    runtime = Runtime((definition(timeout_ms=5),), (adapter,))
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        context = runtime.context()
        catalog = runtime.catalog(context)
        result = asyncio.run(
            runtime.gateway.invoke(
                runtime.raw_call(catalog),
                catalog=catalog,
                context=context,
                budget=budget,
                observation_sha256="c" * 64,
            )
        )
        assert result.status is ToolStatus.TIMEOUT
        assert result.error_code == "TOOL_TIMEOUT"
        assert result.retryable
        assert adapter.calls == 1
        assert physical_calls(budget) == 1
    finally:
        runtime.close()


def test_malformed_adapter_result_is_typed_and_not_returned() -> None:
    adapter = EchoAdapter(bad_hash=True)
    runtime = Runtime((definition(),), (adapter,))
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        context = runtime.context()
        catalog = runtime.catalog(context)
        with pytest.raises(ToolRegistryError) as captured:
            asyncio.run(
                runtime.gateway.invoke(
                    runtime.raw_call(catalog),
                    catalog=catalog,
                    context=context,
                    budget=budget,
                    observation_sha256="d" * 64,
                )
            )
        assert captured.value.code == "TOOL_RESULT_HASH_INVALID"
        assert adapter.calls == 1
        assert physical_calls(budget) == 1
        assert runtime.repository.list(SCOPE)[-1].action == "tool.deny"
    finally:
        runtime.close()


def test_gateway_policy_hard_limit_and_non_text_runtime_input_fail_closed() -> None:
    with pytest.raises(PydanticValidationError):
        FunctionGatewayPolicy(max_call_bytes=1_000_001)
    runtime = Runtime()
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        catalog = runtime.catalog()
        with pytest.raises(FunctionGatewayError) as captured:
            asyncio.run(
                runtime.gateway.invoke(
                    cast(Any, {"name": "not-raw-json"}),
                    catalog=catalog,
                    context=runtime.context(),
                    budget=budget,
                    observation_sha256="e" * 64,
                )
            )
        assert captured.value.code == "FUNCTION_PAYLOAD_TYPE_INVALID"
        assert runtime.adapters[0].calls == 0
        assert physical_calls(budget) == 0
    finally:
        runtime.close()


def test_gateway_rejects_explicit_short_attestation_key() -> None:
    runtime = Runtime()
    try:
        with pytest.raises(ValueError, match="at least 32 bytes"):
            FunctionGateway(
                runtime.registry,
                audit=runtime.audit,
                traces=runtime.traces,
                attestation_key=b"",
            )
    finally:
        runtime.close()
