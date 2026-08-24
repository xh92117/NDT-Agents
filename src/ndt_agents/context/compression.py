"""Deterministic policy and provider-neutral C0-C3 compression pipeline."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ndt_agents.context.assembly import canonical_json_bytes
from ndt_agents.context.compression_models import (
    CompressedContextItem,
    CompressionItemKind,
    CompressionLevel,
    CompressionValidationState,
    ContextCompressionRequest,
    ContextCompressionResult,
    ContextEventKind,
    RawContextEvent,
    SemanticCompressionRequest,
    SemanticCompressionResult,
    SemanticCompressor,
)
from ndt_agents.contracts.v1 import TenantScope

_CONVERSATION_KINDS = {ContextEventKind.USER_TURN, ContextEventKind.ASSISTANT_TURN}


class ContextCompressionError(RuntimeError):
    """Stable compression failure with an actionable recovery instruction."""

    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


def context_event_content_sha256(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(content)).hexdigest()


def select_compression_level(request: ContextCompressionRequest) -> CompressionLevel:
    pressure = request.active_context_tokens / request.active_context_limit
    if pressure < request.policy.c1_threshold:
        return CompressionLevel.C0
    if pressure < request.policy.c2_threshold:
        return CompressionLevel.C1
    if pressure <= request.policy.c3_threshold:
        return CompressionLevel.C2
    return CompressionLevel.C3


class ContextCompressor:
    """Compress raw events without accepting summary-on-summary input."""

    def __init__(self, semantic_compressor: SemanticCompressor | None = None) -> None:
        self._semantic_compressor = semantic_compressor

    async def compress(self, request: ContextCompressionRequest) -> ContextCompressionResult:
        self._validate_request(request)
        level = select_compression_level(request)
        raw_hash = _raw_events_sha256(request.raw_events)
        input_tokens = sum(event.token_estimate for event in request.raw_events)

        if level is CompressionLevel.C0:
            items = _deduplicate_raw_events(request.raw_events)
            return _result(request, level, raw_hash, input_tokens, items)
        if level is CompressionLevel.C1:
            items = _lossless_c1(request.raw_events)
            return _result(request, level, raw_hash, input_tokens, items)

        if request.semantic_compressions_used >= request.policy.max_semantic_compressions:
            raise ContextCompressionError(
                code="CONTEXT_SEMANTIC_COMPRESSION_LIMIT",
                message="The task has reached its semantic compression limit.",
                next_action="Stop or rebuild the task context from a durable raw-event checkpoint.",
            )
        if self._semantic_compressor is None:
            raise ContextCompressionError(
                code="CONTEXT_SEMANTIC_COMPRESSOR_UNAVAILABLE",
                message="Semantic compression is required but no authorized adapter is available.",
                next_action=(
                    "Configure an authorized semantic compressor or reduce context pressure."
                ),
            )

        if level is CompressionLevel.C2:
            retained_ids = _recent_turn_ids(request.raw_events, request.policy.recent_turn_count)
            retained = tuple(
                event
                for event in request.raw_events
                if event.protected or event.event_id in retained_ids
            )
            eligible = tuple(
                event
                for event in request.raw_events
                if not event.protected and event.event_id not in retained_ids
            )
            limit = request.policy.c2_summary_token_limit
            checkpoint_id = None
        else:
            self._validate_checkpoint(request)
            retained = tuple(event for event in request.raw_events if event.protected)
            eligible = tuple(event for event in request.raw_events if not event.protected)
            limit = request.policy.c3_digest_token_limit
            assert request.checkpoint is not None
            checkpoint_id = request.checkpoint.checkpoint_id

        if not eligible:
            items = _deduplicate_raw_events(retained)
            return _result(
                request,
                level,
                raw_hash,
                input_tokens,
                items,
                semantic_increment=0,
                checkpoint_id=checkpoint_id,
            )

        semantic_request = SemanticCompressionRequest(
            task_id=request.task_id,
            scope=request.scope,
            level=level,
            source_events=eligible,
            max_output_tokens=limit,
            policy_version=request.policy.policy_version,
        )
        try:
            semantic_result = await self._semantic_compressor.summarize(semantic_request)
        except Exception as exc:
            raise ContextCompressionError(
                code="CONTEXT_SEMANTIC_ADAPTER_FAILED",
                message="The semantic compression adapter failed before producing a valid result.",
                next_action="Preserve the raw events and inspect or retry the authorized adapter.",
            ) from exc
        self._validate_semantic_result(semantic_request, semantic_result)
        items = (*_deduplicate_raw_events(retained), _semantic_item(semantic_result))
        return _result(
            request,
            level,
            raw_hash,
            input_tokens,
            items,
            semantic_increment=1,
            checkpoint_id=checkpoint_id,
        )

    @staticmethod
    def _validate_request(request: ContextCompressionRequest) -> None:
        for event in request.raw_events:
            if event.task_id != request.task_id or not _same_scope(event.scope, request.scope):
                raise ContextCompressionError(
                    code="CONTEXT_EVENT_SCOPE_MISMATCH",
                    message="A raw context event is outside the active task scope.",
                    next_action=(
                        "Rebuild the request from raw events authorized for the exact task scope."
                    ),
                )

    @staticmethod
    def _validate_checkpoint(request: ContextCompressionRequest) -> None:
        checkpoint = request.checkpoint
        if checkpoint is None:
            raise ContextCompressionError(
                code="CONTEXT_C3_CHECKPOINT_REQUIRED",
                message="C3 compression cannot start before a durable checkpoint exists.",
                next_action="Create and verify a task checkpoint, then retry C3 compression.",
            )
        if (
            checkpoint.task_id != request.task_id
            or not _same_scope(checkpoint.scope, request.scope)
            or not _same_scope(checkpoint.state_artifact.scope, request.scope)
        ):
            raise ContextCompressionError(
                code="CONTEXT_C3_CHECKPOINT_SCOPE_MISMATCH",
                message="The supplied checkpoint does not belong to the active task scope.",
                next_action=(
                    "Select a verified checkpoint for the exact tenant, project, user, and task."
                ),
            )

    @staticmethod
    def _validate_semantic_result(
        request: SemanticCompressionRequest, result: SemanticCompressionResult
    ) -> None:
        expected = tuple(event.event_id for event in request.source_events)
        if result.source_event_ids != expected:
            raise ContextCompressionError(
                code="CONTEXT_SEMANTIC_SOURCE_MISMATCH",
                message="The semantic compressor did not attest to the exact source event set.",
                next_action="Reject the output and rerun from the verified raw events.",
            )
        if result.output_tokens > request.max_output_tokens:
            raise ContextCompressionError(
                code="CONTEXT_SEMANTIC_OUTPUT_OVERFLOW",
                message="The semantic compressor exceeded the configured output-token limit.",
                next_action="Reject the output and request a bounded summary from the raw events.",
            )
        input_tokens = sum(event.token_estimate for event in request.source_events)
        if result.output_tokens >= input_tokens:
            raise ContextCompressionError(
                code="CONTEXT_SEMANTIC_NO_REDUCTION",
                message=(
                    "The semantic output does not reduce the selected raw-event token estimate."
                ),
                next_action="Reject the output and keep the verified raw events unchanged.",
            )


def _same_scope(left: TenantScope, right: TenantScope) -> bool:
    return left.model_dump(mode="json") == right.model_dump(mode="json")


def _raw_events_sha256(events: tuple[RawContextEvent, ...]) -> str:
    payload = [event.model_dump(mode="json") for event in events]
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _recent_turn_ids(events: tuple[RawContextEvent, ...], count: int) -> frozenset[str]:
    conversation = [event.event_id for event in events if event.kind in _CONVERSATION_KINDS]
    return frozenset(conversation[-count:])


def _deduplicate_raw_events(events: Iterable[RawContextEvent]) -> tuple[CompressedContextItem, ...]:
    grouped: dict[str, list[RawContextEvent]] = defaultdict(list)
    order: list[str] = []
    for event in events:
        key = event.content_sha256 if not event.protected else f"protected:{event.event_id}"
        if key not in grouped:
            order.append(key)
        grouped[key].append(event)
    return tuple(_raw_item(grouped[key]) for key in order)


def _lossless_c1(events: tuple[RawContextEvent, ...]) -> tuple[CompressedContextItem, ...]:
    grouped: dict[str, list[RawContextEvent]] = defaultdict(list)
    for event in events:
        key = event.content_sha256 if not event.protected else f"protected:{event.event_id}"
        grouped[key].append(event)

    emitted: set[str] = set()
    items: list[CompressedContextItem] = []
    for event in events:
        key = event.content_sha256 if not event.protected else f"protected:{event.event_id}"
        if key in emitted:
            continue
        emitted.add(key)
        if (
            event.kind is ContextEventKind.TOOL_LOG
            and not event.protected
            and event.recoverable_artifact is not None
        ):
            artifact = event.recoverable_artifact
            content = {
                "artifact_id": str(artifact.artifact_id),
                "artifact_sha256": artifact.sha256,
                "media_type": artifact.media_type,
                "source_event_sha256": event.content_sha256,
            }
            items.append(
                _make_item(
                    kind=CompressionItemKind.ARTIFACT_REFERENCE,
                    source_event_ids=tuple(item.event_id for item in grouped[key]),
                    content=content,
                    token_estimate=min(event.token_estimate, 80),
                    protected=event.protected,
                )
            )
        else:
            items.append(_raw_item(grouped[key]))
    return tuple(items)


def _raw_item(events: list[RawContextEvent]) -> CompressedContextItem:
    first = events[0]
    return _make_item(
        kind=CompressionItemKind.RAW_EVENT,
        source_event_ids=tuple(event.event_id for event in events),
        content=first.content,
        token_estimate=first.token_estimate,
        protected=first.protected,
    )


def _semantic_item(result: SemanticCompressionResult) -> CompressedContextItem:
    return _make_item(
        kind=CompressionItemKind.SEMANTIC_SUMMARY,
        source_event_ids=result.source_event_ids,
        content={
            "summary": result.content,
            "provider_version": result.provider_version,
            "model_version": result.model_version,
            "prompt_version": result.prompt_version,
        },
        token_estimate=result.output_tokens,
        protected=False,
    )


def _make_item(
    *,
    kind: CompressionItemKind,
    source_event_ids: tuple[str, ...],
    content: dict[str, Any],
    token_estimate: int,
    protected: bool,
) -> CompressedContextItem:
    return CompressedContextItem(
        kind=kind,
        source_event_ids=source_event_ids,
        content=content,
        content_sha256=context_event_content_sha256(content),
        token_estimate=token_estimate,
        protected=protected,
    )


def _result(
    request: ContextCompressionRequest,
    level: CompressionLevel,
    raw_hash: str,
    input_tokens: int,
    items: tuple[CompressedContextItem, ...],
    *,
    semantic_increment: int = 0,
    checkpoint_id: Any = None,
) -> ContextCompressionResult:
    output_tokens = sum(item.token_estimate for item in items)
    semantic = level in {CompressionLevel.C2, CompressionLevel.C3}
    return ContextCompressionResult(
        task_id=request.task_id,
        scope=request.scope,
        level=level,
        policy_version=request.policy.policy_version,
        raw_events_sha256=raw_hash,
        items=items,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        token_reduction_ratio=(input_tokens - output_tokens) / input_tokens,
        semantic_compressions_used=request.semantic_compressions_used + semantic_increment,
        checkpoint_id=checkpoint_id,
        validation_state=(
            CompressionValidationState.REQUIRED if semantic else CompressionValidationState.READY
        ),
        execution_ready=not semantic,
    )
