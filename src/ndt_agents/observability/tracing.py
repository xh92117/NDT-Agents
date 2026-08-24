"""Small OpenTelemetry adapter with strict W3C propagation and attribute policy."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from threading import Lock
from typing import Final

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.util.types import AttributeValue
from pydantic import BaseModel, ConfigDict, Field, model_validator

_TRACEPARENT: Final[re.Pattern[str]] = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
_ALLOWED_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "request.id",
        "tenant.id",
        "project.id",
        "task.id",
        "agent.type",
        "operation.type",
        "outcome",
        "error.code",
    }
)


class TraceLink(BaseModel):
    """Stable identifiers that correlate an audit event to one active span."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    span_id: str = Field(pattern=r"^[0-9a-f]{16}$")

    @model_validator(mode="after")
    def validate_nonzero_ids(self) -> TraceLink:
        if int(self.trace_id, 16) == 0 or int(self.span_id, 16) == 0:
            raise ValueError("trace and span IDs must be nonzero")
        return self


class TraceError(RuntimeError):
    """Typed tracing boundary failure."""

    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class InMemorySpanExporter(SpanExporter):
    """Deterministic local exporter; no network or background worker is started."""

    def __init__(self) -> None:
        self._spans: list[ReadableSpan] = []
        self._lock = Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        del timeout_millis
        return True

    @property
    def finished_spans(self) -> tuple[ReadableSpan, ...]:
        with self._lock:
            return tuple(self._spans)


class _CheckedSpanProcessor(SpanProcessor):
    """Export synchronously and let TraceService surface a typed failure after span end."""

    def __init__(self, exporter: SpanExporter) -> None:
        self._exporter = exporter
        self._failures: dict[int, str] = {}
        self._lock = Lock()

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        del span, parent_context

    def on_end(self, span: ReadableSpan) -> None:
        failure: str | None
        try:
            result = self._exporter.export((span,))
        except Exception as error:  # exporter is an external adapter boundary
            failure = type(error).__name__
        else:
            failure = None if result is SpanExportResult.SUCCESS else "export rejected"
        if failure is not None:
            with self._lock:
                self._failures[span.context.span_id] = failure

    def consume_failure(self, span_id: int) -> str | None:
        with self._lock:
            return self._failures.pop(span_id, None)

    def shutdown(self) -> None:
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._exporter.force_flush(timeout_millis)


class TraceService:
    """Create correlated spans without exposing the SDK to domain code."""

    def __init__(
        self,
        *,
        service_name: str,
        service_version: str,
        exporter: SpanExporter,
    ) -> None:
        resource = Resource.create(
            {"service.name": service_name, "service.version": service_version}
        )
        self._provider = TracerProvider(resource=resource)
        self._processor = _CheckedSpanProcessor(exporter)
        self._provider.add_span_processor(self._processor)
        self._tracer = self._provider.get_tracer("ndt_agents.observability", "1.0.0")
        self._propagator = TraceContextTextMapPropagator()

    @contextmanager
    def start_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, AttributeValue] | None = None,
        carrier: Mapping[str, str] | None = None,
    ) -> Iterator[TraceLink]:
        if not name or len(name) > 128:
            raise TraceError(
                code="TRACE_CONTEXT_INVALID",
                message="The span name is invalid.",
                next_action="Use a stable bounded operation name.",
            )
        safe_attributes = self._validate_attributes(attributes or {})
        parent = self._extract_parent(carrier)
        with self._tracer.start_as_current_span(
            name,
            context=parent,
            attributes=safe_attributes,
        ) as span:
            yield self._link(span.get_span_context())
        export_failure = self._processor.consume_failure(span.get_span_context().span_id)
        if export_failure is not None:
            raise TraceError(
                code="TRACE_EXPORT_FAILED",
                message=f"The trace exporter failed: {export_failure}.",
                next_action="Preserve audit evidence and restore the approved trace exporter.",
            )

    def current_link(self) -> TraceLink:
        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            raise TraceError(
                code="TRACE_CONTEXT_INVALID",
                message="No active trace span is available for audit correlation.",
                next_action="Create the audit event inside a TraceService span.",
            )
        return self._link(span_context)

    def inject(self) -> dict[str, str]:
        if not trace.get_current_span().get_span_context().is_valid:
            raise TraceError(
                code="TRACE_CONTEXT_INVALID",
                message="No active trace span is available for propagation.",
                next_action="Inject trace context inside a TraceService span.",
            )
        carrier: dict[str, str] = {}
        self._propagator.inject(carrier)
        return carrier

    def shutdown(self) -> None:
        self._provider.shutdown()

    def _extract_parent(self, carrier: Mapping[str, str] | None) -> Context | None:
        if carrier is None:
            return None
        traceparent = carrier.get("traceparent")
        if traceparent is None or _TRACEPARENT.fullmatch(traceparent) is None:
            raise TraceError(
                code="TRACE_CONTEXT_INVALID",
                message="The incoming W3C trace context is invalid.",
                next_action="Discard it and start an explicit local root span.",
            )
        parent = self._propagator.extract(carrier)
        if not trace.get_current_span(parent).get_span_context().is_valid:
            raise TraceError(
                code="TRACE_CONTEXT_INVALID",
                message="The incoming W3C trace context contains invalid identifiers.",
                next_action="Discard it and start an explicit local root span.",
            )
        return parent

    @staticmethod
    def _link(span_context: trace.SpanContext) -> TraceLink:
        return TraceLink(
            trace_id=f"{span_context.trace_id:032x}",
            span_id=f"{span_context.span_id:016x}",
        )

    @staticmethod
    def _validate_attributes(
        attributes: Mapping[str, AttributeValue],
    ) -> dict[str, AttributeValue]:
        denied = sorted(set(attributes) - _ALLOWED_ATTRIBUTES)
        if denied:
            raise TraceError(
                code="TRACE_ATTRIBUTE_DENIED",
                message=f"Trace attributes are not allowlisted: {', '.join(denied)}.",
                next_action="Use stable IDs, versions, decisions, outcomes, or hashes only.",
            )
        if any(isinstance(value, str) and len(value) > 256 for value in attributes.values()):
            raise TraceError(
                code="TRACE_ATTRIBUTE_DENIED",
                message="A trace attribute value exceeds the bounded identifier length.",
                next_action="Export a stable identifier or hash instead of raw content.",
            )
        return dict(attributes)
