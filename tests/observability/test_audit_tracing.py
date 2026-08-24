"""S1-10 immutable audit and OpenTelemetry correlation tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult
from pydantic import ValidationError

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.observability import (
    AuditError,
    AuditKind,
    AuditOutcome,
    AuditRecord,
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceError,
    TraceService,
)

SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("RUNTIME_OPERATOR",),
    permission_version="permission-1",
)
OTHER_SCOPE = SCOPE.model_copy(update={"project_id": UUID("00000000-0000-4000-8000-000000000202")})
TASK_ID = UUID("00000000-0000-4000-8000-000000000301")
OCCURRED_AT = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)


def tracing() -> tuple[TraceService, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    return (
        TraceService(service_name="ndt-test", service_version="1.0.0", exporter=exporter),
        exporter,
    )


def audit_record(
    event_number: int,
    kind: AuditKind = AuditKind.TASK,
    *,
    scope: TenantScope = SCOPE,
    action: str = "task.transition",
) -> AuditRecord:
    return AuditRecord(
        event_id=UUID(int=event_number),
        scope=scope,
        kind=kind,
        action=action,
        target_type="runtime.task",
        target_id=str(TASK_ID),
        task_id=TASK_ID,
        policy_version="audit-policy-1",
        decision="ALLOW",
        outcome=AuditOutcome.SUCCESS,
        input_sha256="a" * 64,
        output_sha256="b" * 64,
        request_id="request-1",
        occurred_at=OCCURRED_AT,
    )


def test_parent_child_spans_propagate_w3c_context_and_export() -> None:
    traces, exporter = tracing()
    try:
        with traces.start_span(
            "runtime.request",
            attributes={"request.id": "request-1", "operation.type": "request"},
        ) as parent:
            carrier = traces.inject()
            assert carrier["traceparent"].startswith(f"00-{parent.trace_id}-{parent.span_id}-")
            with traces.start_span("runtime.child", carrier=carrier) as child:
                assert child.trace_id == parent.trace_id
                assert child.span_id != parent.span_id
        spans = exporter.finished_spans
        assert {span.name for span in spans} == {"runtime.request", "runtime.child"}
        assert all(span.context is not None for span in spans)
    finally:
        traces.shutdown()


def test_audit_append_is_idempotent_sequenced_and_trace_correlated() -> None:
    traces, _ = tracing()
    repository = InMemoryAuditRepository()
    service = AuditService(repository, traces)
    try:
        with traces.start_span("audit.write") as link:
            first = service.record(audit_record(1))
            duplicate = service.record(audit_record(1))
            second = service.record(audit_record(2, AuditKind.CHECKPOINT))
        assert duplicate == first
        assert (first.sequence, second.sequence) == (1, 2)
        assert first.previous_sha256 == "0" * 64
        assert second.previous_sha256 == first.event_sha256
        assert (first.trace_id, first.span_id) == (link.trace_id, link.span_id)
        repository.verify(SCOPE)
    finally:
        traces.shutdown()


def test_event_id_conflict_and_cross_scope_read_are_typed_denials() -> None:
    traces, _ = tracing()
    repository = InMemoryAuditRepository()
    service = AuditService(repository, traces)
    try:
        with traces.start_span("audit.write"):
            event = service.record(audit_record(1))
            with pytest.raises(AuditError, match="different content") as conflict:
                service.record(audit_record(1, action="task.failed"))
        assert conflict.value.code == "AUDIT_IDEMPOTENCY_CONFLICT"
        with pytest.raises(AuditError, match="outside the authorized scope") as denied:
            repository.get(OTHER_SCOPE, event.event_id)
        assert denied.value.code == "AUDIT_SCOPE_MISMATCH"
        assert repository.list(OTHER_SCOPE) == ()
    finally:
        traces.shutdown()


def test_hash_chain_tampering_is_detected() -> None:
    traces, _ = tracing()
    repository = InMemoryAuditRepository()
    service = AuditService(repository, traces)
    try:
        with traces.start_span("audit.write"):
            event = service.record(audit_record(1))
        tampered = event.model_copy(update={"action": "task.failed"})
        with pytest.raises(AuditError, match="hash chain") as invalid:
            repository.verify_events((tampered,))
        assert invalid.value.code == "AUDIT_CHAIN_INVALID"
    finally:
        traces.shutdown()


def test_missing_or_malformed_trace_context_and_attributes_are_rejected() -> None:
    traces, _ = tracing()
    repository = InMemoryAuditRepository()
    service = AuditService(repository, traces)
    try:
        with pytest.raises(TraceError, match="No active trace") as missing:
            service.record(audit_record(1))
        assert missing.value.code == "TRACE_CONTEXT_INVALID"
        with pytest.raises(TraceError, match="W3C trace context") as malformed:
            with traces.start_span("bad.parent", carrier={"traceparent": "not-valid"}):
                pass
        assert malformed.value.code == "TRACE_CONTEXT_INVALID"
        with pytest.raises(TraceError, match="not allowlisted") as sensitive:
            with traces.start_span("bad.attribute", attributes={"authorization": "secret"}):
                pass
        assert sensitive.value.code == "TRACE_ATTRIBUTE_DENIED"
        with pytest.raises(TraceError, match="bounded identifier"):
            with traces.start_span("raw.content", attributes={"request.id": "x" * 257}):
                pass
    finally:
        traces.shutdown()


def test_export_failure_is_typed_and_not_hidden() -> None:
    class FailingExporter(InMemorySpanExporter):
        def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
            del spans
            return SpanExportResult.FAILURE

    traces = TraceService(
        service_name="ndt-test",
        service_version="1.0.0",
        exporter=FailingExporter(),
    )
    try:
        with pytest.raises(TraceError, match="exporter failed") as failure:
            with traces.start_span("failed.export"):
                pass
        assert failure.value.code == "TRACE_EXPORT_FAILED"
    finally:
        traces.shutdown()


def test_strict_event_contract_rejects_raw_fields_and_non_utc_time() -> None:
    payload = audit_record(1).model_dump()
    with pytest.raises(ValidationError):
        AuditRecord.model_validate({**payload, "prompt": "raw prompt"})
    with pytest.raises(ValidationError, match="must use UTC"):
        AuditRecord.model_validate(
            {**payload, "occurred_at": OCCURRED_AT.astimezone(timezone(timedelta(hours=8)))}
        )


def test_required_event_completeness_reaches_one_only_when_all_kinds_exist() -> None:
    traces, _ = tracing()
    repository = InMemoryAuditRepository()
    service = AuditService(repository, traces)
    required = frozenset(
        {
            AuditKind.AUTHORIZATION,
            AuditKind.TASK,
            AuditKind.AGENT,
            AuditKind.CHECKPOINT,
            AuditKind.BUDGET,
            AuditKind.REVIEW,
            AuditKind.CORRECTION,
            AuditKind.MODEL,
            AuditKind.TOOL,
            AuditKind.CACHE,
        }
    )
    try:
        with traces.start_span("workflow"):
            for event_number, kind in enumerate(sorted(required), start=1):
                service.record(audit_record(event_number, kind, action=f"{kind.lower()}.record"))
        result = service.completeness(
            scope=SCOPE,
            request_id="request-1",
            task_id=TASK_ID,
            required=required,
        )
        assert result.ratio == 1.0
        assert result.numerator == result.denominator == len(required)
        assert result.missing == frozenset()
        with pytest.raises(AuditError, match="cannot be empty"):
            service.completeness(
                scope=SCOPE,
                request_id="request-1",
                task_id=TASK_ID,
                required=frozenset(),
            )
    finally:
        traces.shutdown()
