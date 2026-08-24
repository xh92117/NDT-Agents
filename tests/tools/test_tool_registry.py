"""S1-12 shared Tool Registry contract and execution tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from ndt_agents.contracts.v1 import TenantScope, ToolResult, ToolStatus
from ndt_agents.observability import (
    AuditKind,
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.tools import (
    DefinitionOrigin,
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationContext,
    ToolRegistry,
    ToolRegistryError,
)
from ndt_agents.tools.registry import canonical_sha256

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("TOOL_USER",),
    permission_version="permissions-1",
)
TASK_ID = UUID("00000000-0000-4000-8000-000000000201")
RUN_ID = UUID("00000000-0000-4000-8000-000000000202")


def definition(
    *,
    version: str = "1.0.0",
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY,
    network: NetworkPolicy = NetworkPolicy.NONE,
    timeout_ms: int = 100,
) -> ToolDefinition:
    return ToolDefinition(
        name="fixture.echo",
        version=version,
        purpose="Return one validated fixture value.",
        side_effect=side_effect,
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"echo": {"type": "string"}},
            "additionalProperties": False,
        },
        required_permissions=frozenset({"tool.echo"}),
        timeout_ms=timeout_ms,
        max_attempts=2,
        max_concurrency=1 if side_effect is not SideEffectClass.READ_ONLY else 2,
        max_input_bytes=1000,
        max_output_bytes=1000,
        max_tokens=0,
        idempotency=(
            IdempotencyPolicy.NONE
            if side_effect is SideEffectClass.READ_ONLY
            else IdempotencyPolicy.REQUIRED
        ),
        secret_purposes=frozenset({"echo.token"})
        if network is NetworkPolicy.RESTRICTED
        else frozenset(),
        network=network,
        audit_owner="tool-runtime",
        test_groups=frozenset({"UNIT-TOOLREG"}),
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
            completed_at=datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
        )


class Runtime:
    def __init__(
        self, tool: ToolDefinition | None = None, adapter: EchoAdapter | None = None
    ) -> None:
        self.tool = tool or definition()
        self.adapter = adapter or EchoAdapter()
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="tool-registry-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.repository = InMemoryAuditRepository()
        self.registry = ToolRegistry(
            (self.tool,),
            {self.tool.key: self.adapter},
            audit=AuditService(self.repository, self.traces),
            clock=lambda: datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
        )

    def context(self, **updates: Any) -> ToolInvocationContext:
        values: dict[str, Any] = {
            "task_id": TASK_ID,
            "run_id": RUN_ID,
            "scope": SCOPE,
            "request_id": "tool-request-1",
            "policy_version": "tool-policy-1",
            "expected_registry_version": self.registry.version,
            "allowed_tools": frozenset({self.tool.key}),
            "granted_permissions": frozenset({"tool.echo"}),
            "allowed_secret_purposes": frozenset({"echo.token"}),
            "allow_network": True,
        }
        values.update(updates)
        return ToolInvocationContext(**values)

    async def invoke(self, **updates: Any) -> ToolResult:
        values: dict[str, Any] = {
            "name": self.tool.name,
            "version": self.tool.version,
            "arguments": {"value": "ok"},
            "context": self.context(),
            "budget": BudgetGuard(default_budget_policy("G0")),
            "observation_sha256": "1" * 64,
        }
        values.update(updates)
        with self.traces.start_span("tool.invoke"):
            return await self.registry.invoke(**values)

    def close(self) -> None:
        self.traces.shutdown()


def test_definition_rejects_untrusted_non_strict_and_unsafe_side_effects() -> None:
    base = definition().model_dump()
    with pytest.raises(PydanticValidationError):
        ToolDefinition.model_validate({**base, "origin": DefinitionOrigin.UNTRUSTED})
    with pytest.raises(PydanticValidationError):
        ToolDefinition.model_validate({**base, "input_schema": {"type": "object"}})
    with pytest.raises(PydanticValidationError):
        ToolDefinition.model_validate(
            {
                **base,
                "side_effect": SideEffectClass.IRREVERSIBLE,
                "idempotency": IdempotencyPolicy.NONE,
            }
        )


def test_publication_is_deterministic_and_version_change_is_visible() -> None:
    first = Runtime()
    second = Runtime()
    changed = Runtime(definition(version="1.0.1"))
    try:
        assert first.registry.version == second.registry.version
        assert first.registry.version != changed.registry.version
        assert first.registry.definitions == (first.tool,)
    finally:
        first.close()
        second.close()
        changed.close()


def test_duplicate_or_missing_adapter_is_rejected() -> None:
    runtime = Runtime()
    try:
        with pytest.raises(ToolRegistryError, match="duplicated"):
            ToolRegistry(
                (runtime.tool, runtime.tool),
                {runtime.tool.key: runtime.adapter},
                audit=AuditService(runtime.repository, runtime.traces),
            )
        with pytest.raises(ToolRegistryError, match="adapter"):
            ToolRegistry(
                (),
                {runtime.tool.key: runtime.adapter},
                audit=AuditService(runtime.repository, runtime.traces),
            )
    finally:
        runtime.close()


def test_success_validates_result_counts_budget_and_audits() -> None:
    runtime = Runtime()
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        result = asyncio.run(runtime.invoke(budget=budget))
        assert result.output == {"echo": "ok"}
        assert runtime.adapter.calls == 1
        assert budget.telemetry().counters.physical_tool_calls == 1
        events = runtime.repository.list(SCOPE)
        assert len(events) == 1 and events[0].kind is AuditKind.TOOL
        assert events[0].input_sha256 != canonical_sha256({"value": "secret"})
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"expected_registry_version": "0" * 64}, "TOOL_REGISTRY_STALE"),
        ({"allowed_tools": frozenset({"other@1.0.0"})}, "TOOL_NOT_ALLOWED"),
        ({"granted_permissions": frozenset()}, "TOOL_PERMISSION_DENIED"),
    ],
)
def test_preflight_denial_never_calls_adapter(updates: dict[str, Any], code: str) -> None:
    runtime = Runtime()
    try:
        with pytest.raises(ToolRegistryError) as captured:
            asyncio.run(runtime.invoke(context=runtime.context(**updates)))
        assert captured.value.code == code
        assert runtime.adapter.calls == 0
        assert runtime.repository.list(SCOPE)[0].outcome.value == "DENIED"
    finally:
        runtime.close()


def test_input_schema_denial_and_output_hash_denial() -> None:
    runtime = Runtime()
    invalid_output = Runtime(adapter=EchoAdapter(bad_hash=True))
    try:
        with pytest.raises(ToolRegistryError) as input_error:
            asyncio.run(runtime.invoke(arguments={"unknown": "x"}))
        assert input_error.value.code == "TOOL_SCHEMA_INVALID"
        assert runtime.adapter.calls == 0
        with pytest.raises(ToolRegistryError) as output_error:
            asyncio.run(invalid_output.invoke())
        assert output_error.value.code == "TOOL_RESULT_HASH_INVALID"
        assert invalid_output.adapter.calls == 1
    finally:
        runtime.close()
        invalid_output.close()


def test_network_and_secret_declarations_are_enforced() -> None:
    runtime = Runtime(definition(network=NetworkPolicy.RESTRICTED))
    try:
        with pytest.raises(ToolRegistryError) as secret_error:
            asyncio.run(
                runtime.invoke(context=runtime.context(allowed_secret_purposes=frozenset()))
            )
        assert secret_error.value.code == "TOOL_SECRET_PURPOSE_DENIED"
        with pytest.raises(ToolRegistryError) as network_error:
            asyncio.run(runtime.invoke(context=runtime.context(allow_network=False)))
        assert network_error.value.code == "TOOL_NETWORK_DENIED"
        assert runtime.adapter.calls == 0
    finally:
        runtime.close()


def test_side_effect_requires_key_replays_commit_and_rejects_conflict() -> None:
    runtime = Runtime(definition(side_effect=SideEffectClass.REVERSIBLE))
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        with pytest.raises(ToolRegistryError) as missing:
            asyncio.run(runtime.invoke(budget=budget))
        assert missing.value.code == "TOOL_IDEMPOTENCY_REQUIRED"
        first = asyncio.run(runtime.invoke(budget=budget, idempotency_key="effect-1"))
        replay = asyncio.run(runtime.invoke(budget=budget, idempotency_key="effect-1"))
        assert replay == first
        assert runtime.adapter.calls == 1
        with pytest.raises(ToolRegistryError) as conflict:
            asyncio.run(
                runtime.invoke(
                    budget=budget,
                    idempotency_key="effect-1",
                    arguments={"value": "changed"},
                )
            )
        assert conflict.value.code == "TOOL_IDEMPOTENCY_CONFLICT"
        assert runtime.adapter.calls == 1
    finally:
        runtime.close()


def test_timeout_is_typed_and_side_effect_requires_reconciliation() -> None:
    readonly = Runtime(definition(timeout_ms=1), EchoAdapter(delay=0.02))
    effect = Runtime(
        definition(side_effect=SideEffectClass.REVERSIBLE, timeout_ms=1),
        EchoAdapter(delay=0.02),
    )
    try:
        result = asyncio.run(readonly.invoke())
        assert result.status is ToolStatus.TIMEOUT
        assert result.error_code == "TOOL_TIMEOUT" and result.retryable
        asyncio.run(effect.invoke(idempotency_key="effect-timeout"))
        with pytest.raises(ToolRegistryError) as captured:
            asyncio.run(effect.invoke(idempotency_key="effect-timeout"))
        assert captured.value.code == "TOOL_RECONCILIATION_REQUIRED"
        assert effect.adapter.calls == 1
    finally:
        readonly.close()
        effect.close()


def test_budget_denial_prevents_physical_adapter_call() -> None:
    runtime = Runtime()
    budget = BudgetGuard(default_budget_policy("G0"))
    try:
        asyncio.run(runtime.invoke(budget=budget))
        with pytest.raises(ToolRegistryError) as captured:
            asyncio.run(runtime.invoke(budget=budget))
        assert captured.value.code == "BUDGET_IDENTICAL_TOOL_CALL"
        assert runtime.adapter.calls == 1
    finally:
        runtime.close()


def test_unregistered_tool_is_denied_and_audited_without_adapter_call() -> None:
    runtime = Runtime()
    try:
        with pytest.raises(ToolRegistryError) as captured:
            asyncio.run(runtime.invoke(name="missing.tool"))
        assert captured.value.code == "TOOL_UNREGISTERED"
        assert runtime.adapter.calls == 0
        event = runtime.repository.list(SCOPE)[0]
        assert event.target_id == "missing.tool:1.0.0"
        assert event.outcome.value == "DENIED"
    finally:
        runtime.close()
