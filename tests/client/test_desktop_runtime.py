"""S6-02 application-owned desktop session and Tool Registry bridge tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from ndt_agents.client.desktop import (
    DesktopBridgeError,
    DesktopBridgeErrorPayload,
    DesktopBridgeRequest,
    DesktopBridgeService,
    DesktopCancelRequest,
    DesktopSessionGrant,
    InMemoryDesktopSessionAuthority,
)
from ndt_agents.contracts.v1 import TenantScope, ToolStatus
from ndt_agents.observability import InMemorySpanExporter
from ndt_agents.observability.audit import AuditService, InMemoryAuditRepository
from ndt_agents.observability.tracing import TraceService
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.tools.reference_adapters import (
    DeterministicReferenceSimulatorProvider,
    ReferenceAdapterRegistry,
    ReferenceAdapterRuntime,
)
from ndt_agents.tools.registry import ToolDataDestination, ToolInvocationContext

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
DESKTOP_CONTRACT_ROOT = ROOT / "contracts" / "desktop" / "v1"
SESSION_HANDLE = "desktop-session-handle-000000000001"
TASK_ID = UUID("00000000-0000-4000-8000-000000000601")
RUN_ID = UUID("00000000-0000-4000-8000-000000000602")
SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000611"),
    project_id=UUID("00000000-0000-4000-8000-000000000612"),
    user_id=UUID("00000000-0000-4000-8000-000000000613"),
    role_codes=("REFERENCE_USER",),
    permission_version="permissions-1",
)


class Harness:
    def __init__(self, *, granted: bool = True) -> None:
        self.exporter = InMemorySpanExporter()
        self.traces = TraceService(
            service_name="desktop-runtime-test",
            service_version="1.0.0",
            exporter=self.exporter,
        )
        self.audit_repository = InMemoryAuditRepository()
        self.audit = AuditService(self.audit_repository, self.traces)
        self.reference_registry = ReferenceAdapterRegistry()
        self.runtime = ReferenceAdapterRuntime(
            self.reference_registry,
            self.audit,
            clock=lambda: NOW,
        )
        self.profile = next(
            profile for profile in self.reference_registry.profiles if profile.method_code == "UT"
        )
        self.definition = self.runtime.tool_registry.resolve(
            "adapter.reference.ut.acquire", "1.0.0"
        )
        self.context = ToolInvocationContext(
            task_id=TASK_ID,
            run_id=RUN_ID,
            scope=SCOPE,
            request_id="desktop-ut-request",
            policy_version="desktop-policy-1",
            expected_registry_version=self.runtime.tool_registry.version,
            allowed_tools=frozenset({self.definition.key}),
            granted_permissions=(
                self.profile.registration.required_permissions if granted else frozenset()
            ),
            allowed_data_destinations=frozenset({ToolDataDestination.LOCAL}),
            allow_network=False,
        )
        self.authority = InMemoryDesktopSessionAuthority(clock=lambda: NOW)
        self.authority.install(
            SESSION_HANDLE,
            DesktopSessionGrant(
                context=self.context,
                budget=BudgetGuard(default_budget_policy("P1")),
                observation_sha256="9" * 64,
                expires_at=NOW + timedelta(minutes=15),
            ),
        )
        self.service = DesktopBridgeService(
            authority=self.authority,
            registry=self.runtime.tool_registry,
            audit=self.audit,
            traces=self.traces,
            clock=lambda: NOW,
        )

    def request(self, **updates: object) -> DesktopBridgeRequest:
        values: dict[str, object] = {
            "session_handle": SESSION_HANDLE,
            "task_id": TASK_ID,
            "run_id": RUN_ID,
            "registry_version": self.runtime.tool_registry.version,
            "tool_name": self.definition.name,
            "tool_version": self.definition.version,
            "arguments": {"fixture_id": self.profile.fixture_id},
            "idempotency_key": "desktop-call-0001",
        }
        values.update(updates)
        return DesktopBridgeRequest.model_validate(values)

    def cancel_request(self, **updates: object) -> DesktopCancelRequest:
        values: dict[str, object] = {
            "session_handle": SESSION_HANDLE,
            "task_id": TASK_ID,
            "run_id": RUN_ID,
            "registry_version": self.runtime.tool_registry.version,
            "target_request_sha256": "b" * 64,
            "reason": "User requested cancellation.",
        }
        values.update(updates)
        return DesktopCancelRequest.model_validate(values)

    @property
    def provider(self) -> DeterministicReferenceSimulatorProvider:
        provider = self.runtime.providers["UT"]
        assert isinstance(provider, DeterministicReferenceSimulatorProvider)
        return provider

    def close(self) -> None:
        self.traces.shutdown()


def test_request_rejects_scope_permissions_and_unknown_client_authority() -> None:
    with pytest.raises(ValueError):
        DesktopBridgeRequest.model_validate(
            {
                "session_handle": SESSION_HANDLE,
                "task_id": TASK_ID,
                "run_id": RUN_ID,
                "registry_version": "a" * 64,
                "tool_name": "adapter.reference.ut.acquire",
                "tool_version": "1.0.0",
                "arguments": {"fixture_id": "reference-ut-baseline"},
                "idempotency_key": "desktop-call-0001",
                "granted_permissions": ["reference.ut.acquire"],
            }
        )


def test_shared_invoke_contract_uses_camel_case_and_canonical_hash() -> None:
    payload = json.loads((DESKTOP_CONTRACT_ROOT / "invoke.valid.json").read_text("utf-8"))
    request = DesktopBridgeRequest.model_validate(payload)

    assert request.model_dump(mode="json", by_alias=True) == payload
    assert request.request_sha256 == (
        "6b80c5f4f072a58352eec50c83b33d8fdf9b8d7933d81b544598c03fdf6b817b"
    )


def test_shared_cancel_contract_is_distinct_and_hash_bound() -> None:
    payload = json.loads((DESKTOP_CONTRACT_ROOT / "cancel.valid.json").read_text("utf-8"))
    request = DesktopCancelRequest.model_validate(payload)

    assert request.model_dump(mode="json", by_alias=True) == payload
    assert request.request_sha256 == (
        "0a07509deb3aa3920938a23bff93e4353949617eccda5bbd4ceba24f9684fd6e"
    )
    with pytest.raises(ValueError):
        DesktopBridgeRequest.model_validate(payload)


def test_cancel_reason_uses_the_same_utf8_byte_budget_as_rust() -> None:
    payload = json.loads((DESKTOP_CONTRACT_ROOT / "cancel.utf8-oversized.json").read_text("utf-8"))

    assert len(payload["reason"]) <= 512
    assert len(payload["reason"].encode("utf-8")) > 512
    with pytest.raises(ValueError, match="UTF-8 byte budget"):
        DesktopCancelRequest.model_validate(payload)


def test_shared_error_contract_round_trips_and_exception_maps_without_authority() -> None:
    payload = json.loads((DESKTOP_CONTRACT_ROOT / "error.valid.json").read_text("utf-8"))
    expected = DesktopBridgeErrorPayload.model_validate(payload)
    error = DesktopBridgeError(
        expected.code,
        expected.message,
        next_action=expected.next_action,
        retryable=expected.retryable,
    )

    assert error.to_payload().model_dump(mode="json", by_alias=True) == payload


def test_missing_session_denies_before_registry_or_provider() -> None:
    harness = Harness()
    try:
        harness.authority.revoke(SESSION_HANDLE)
        with pytest.raises(DesktopBridgeError) as captured:
            asyncio.run(harness.service.invoke(harness.request()))
        assert captured.value.code == "DESKTOP_SESSION_REQUIRED"
        assert harness.provider.calls == 0
        assert harness.audit_repository.list(SCOPE) == ()
    finally:
        harness.close()


def test_authoritative_session_invokes_only_the_registered_scoped_tool() -> None:
    harness = Harness()
    try:
        response = asyncio.run(harness.service.invoke(harness.request()))
        assert response.tool_result.status is ToolStatus.SUCCESS
        assert response.tool_result.scope == SCOPE
        assert response.tool_result.task_id == TASK_ID
        assert response.tool_result.run_id == RUN_ID
        assert response.request_sha256
        assert harness.provider.calls == 1
        events = harness.audit_repository.list(SCOPE)
        assert any(event.action == "tool.execute" for event in events)
    finally:
        harness.close()


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"task_id": UUID("00000000-0000-4000-8000-000000000699")}, "DESKTOP_SCOPE_MISMATCH"),
        ({"registry_version": "a" * 64}, "DESKTOP_REGISTRY_STALE"),
        ({"tool_name": "adapter.reference.gpr.acquire"}, "DESKTOP_TOOL_DENIED"),
    ],
)
def test_client_cannot_change_session_scope_registry_or_tool(
    updates: dict[str, object], code: str
) -> None:
    harness = Harness()
    try:
        with pytest.raises(DesktopBridgeError) as captured:
            asyncio.run(harness.service.invoke(harness.request(**updates)))
        assert captured.value.code == code
        assert harness.provider.calls == 0
        assert any(
            event.action == "desktop.bridge.deny"
            and event.decision == code
            and event.outcome.value == "DENIED"
            for event in harness.audit_repository.list(SCOPE)
        )
    finally:
        harness.close()


def test_registry_permission_denial_remains_typed_and_audited() -> None:
    harness = Harness(granted=False)
    try:
        with pytest.raises(DesktopBridgeError) as captured:
            asyncio.run(harness.service.invoke(harness.request()))
        assert captured.value.code == "TOOL_PERMISSION_DENIED"
        assert harness.provider.calls == 0
        assert any(event.action == "tool.deny" for event in harness.audit_repository.list(SCOPE))
    finally:
        harness.close()


def test_same_idempotency_key_replays_and_changed_input_is_denied() -> None:
    harness = Harness()
    try:
        first = asyncio.run(harness.service.invoke(harness.request()))
        replay = asyncio.run(harness.service.invoke(harness.request()))
        assert replay.tool_result == first.tool_result
        assert harness.provider.calls == 1

        with pytest.raises(DesktopBridgeError) as captured:
            asyncio.run(
                harness.service.invoke(
                    harness.request(arguments={"fixture_id": "reference-ut-other"})
                )
            )
        assert captured.value.code == "TOOL_SCHEMA_INVALID"
        assert harness.provider.calls == 1
    finally:
        harness.close()


def test_expired_session_is_revoked_before_execution() -> None:
    harness = Harness()
    try:
        harness.authority.install(
            SESSION_HANDLE,
            DesktopSessionGrant(
                context=harness.context,
                budget=BudgetGuard(default_budget_policy("P1")),
                observation_sha256="9" * 64,
                expires_at=NOW - timedelta(seconds=1),
            ),
        )
        with pytest.raises(DesktopBridgeError) as captured:
            asyncio.run(harness.service.invoke(harness.request()))
        assert captured.value.code == "DESKTOP_SESSION_EXPIRED"
        assert harness.provider.calls == 0
    finally:
        harness.close()


def test_cancel_requires_authoritative_scope_then_fails_without_adapter() -> None:
    harness = Harness()
    try:
        with pytest.raises(DesktopBridgeError) as captured:
            asyncio.run(harness.service.cancel(harness.cancel_request()))
        assert captured.value.code == "DESKTOP_CANCEL_UNAVAILABLE"
        assert harness.provider.calls == 0
        assert any(
            event.action == "desktop.bridge.cancel.deny"
            and event.target_id == "b" * 64
            and event.decision == "DESKTOP_CANCEL_UNAVAILABLE"
            for event in harness.audit_repository.list(SCOPE)
        )

        with pytest.raises(DesktopBridgeError) as mismatched:
            asyncio.run(
                harness.service.cancel(
                    harness.cancel_request(task_id=UUID("00000000-0000-4000-8000-000000000699"))
                )
            )
        assert mismatched.value.code == "DESKTOP_SCOPE_MISMATCH"
    finally:
        harness.close()
