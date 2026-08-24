"""S2-02 UNIT-CONTEXT and EVAL-COMPRESSION policy tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue, ValidationError

from ndt_agents.context import (
    CompressionItemKind,
    CompressionLevel,
    CompressionValidationState,
    ContextCompressionError,
    ContextCompressionPolicy,
    ContextCompressionRequest,
    ContextCompressor,
    ContextEventKind,
    RawContextEvent,
    SemanticCompressionRequest,
    SemanticCompressionResult,
    context_event_content_sha256,
    select_compression_level,
)
from ndt_agents.contracts.v1 import Checkpoint, TaskContext, TenantScope

ROOT = Path(__file__).resolve().parents[2]
BASE_TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
BASE_CHECKPOINT = Checkpoint.model_validate_json(
    (ROOT / "examples/contracts/v1/checkpoint.valid.json").read_text("utf-8")
)
NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


class FakeSemanticCompressor:
    def __init__(
        self,
        *,
        output_tokens: int = 100,
        source_override: tuple[str, ...] | None = None,
    ) -> None:
        self.output_tokens = output_tokens
        self.source_override = source_override
        self.requests: list[SemanticCompressionRequest] = []

    async def summarize(self, request: SemanticCompressionRequest) -> SemanticCompressionResult:
        self.requests.append(request)
        source_ids = self.source_override or tuple(
            event.event_id for event in request.source_events
        )
        return SemanticCompressionResult(
            content={"digest": "bounded semantic candidate", "source_count": len(source_ids)},
            source_event_ids=source_ids,
            output_tokens=self.output_tokens,
            provider_version="fake-provider-1",
            model_version="fake-model-1",
            prompt_version="context-compression-1",
        )


class FailingSemanticCompressor:
    async def summarize(self, request: SemanticCompressionRequest) -> SemanticCompressionResult:
        raise RuntimeError(f"simulated failure for {request.level}")


def event(
    sequence: int,
    *,
    kind: ContextEventKind = ContextEventKind.PROJECT_FACT,
    content: dict[str, JsonValue] | None = None,
    protected: bool = False,
    token_estimate: int = 250,
    event_scope: TenantScope | None = None,
    artifact: bool = False,
) -> RawContextEvent:
    normalized = content or {"sequence": sequence, "value": f"raw-{sequence}"}
    return RawContextEvent(
        event_id=f"event-{sequence}",
        task_id=BASE_TASK.task_id,
        scope=event_scope or BASE_TASK.scope,
        sequence=sequence,
        kind=kind,
        content=normalized,
        content_sha256=context_event_content_sha256(normalized),
        token_estimate=token_estimate,
        protected=protected,
        recoverable_artifact=(BASE_CHECKPOINT.state_artifact if artifact else None),
        created_at=NOW + timedelta(seconds=sequence),
    )


def request(
    events: tuple[RawContextEvent, ...],
    *,
    pressure: float,
    semantic_compressions_used: int = 0,
    checkpoint: Checkpoint | None = None,
) -> ContextCompressionRequest:
    return ContextCompressionRequest(
        task_id=BASE_TASK.task_id,
        scope=BASE_TASK.scope,
        raw_events=events,
        active_context_tokens=int(pressure * 10_000),
        active_context_limit=10_000,
        semantic_compressions_used=semantic_compressions_used,
        checkpoint=checkpoint,
        policy=ContextCompressionPolicy(policy_version="context-compression-1"),
    )


@pytest.mark.parametrize(
    ("pressure", "expected"),
    [
        (0.3999, CompressionLevel.C0),
        (0.4, CompressionLevel.C1),
        (0.5999, CompressionLevel.C1),
        (0.6, CompressionLevel.C2),
        (0.8, CompressionLevel.C2),
        (0.8001, CompressionLevel.C3),
    ],
)
def test_policy_selects_boundary_level(pressure: float, expected: CompressionLevel) -> None:
    assert select_compression_level(request((event(1),), pressure=pressure)) is expected


def test_c0_deduplicates_exact_unprotected_content_without_semantic_call() -> None:
    duplicate: dict[str, JsonValue] = {"fact": "same", "unit": "mm", "value": 12.5}
    events = (
        event(1, content=duplicate),
        event(2, content=duplicate),
        event(3, content=duplicate, protected=True),
    )
    adapter = FakeSemanticCompressor()

    result = asyncio.run(ContextCompressor(adapter).compress(request(events, pressure=0.2)))

    assert result.level is CompressionLevel.C0
    assert result.execution_ready is True
    assert result.validation_state is CompressionValidationState.READY
    assert [item.source_event_ids for item in result.items] == [
        ("event-1", "event-2"),
        ("event-3",),
    ]
    assert adapter.requests == []


def test_c1_replaces_recoverable_tool_log_with_hash_bound_artifact_reference() -> None:
    events = (
        event(1, kind=ContextEventKind.TOOL_LOG, artifact=True, token_estimate=900),
        event(2, kind=ContextEventKind.DECISION, token_estimate=40),
    )

    result = asyncio.run(ContextCompressor().compress(request(events, pressure=0.5)))

    assert result.execution_ready is True
    reference = next(
        item for item in result.items if item.kind is CompressionItemKind.ARTIFACT_REFERENCE
    )
    assert reference.content["source_event_sha256"] == events[0].content_sha256
    assert reference.content["artifact_sha256"] == BASE_CHECKPOINT.state_artifact.sha256
    assert result.output_tokens < result.input_tokens


def test_c2_keeps_six_recent_turns_and_all_protected_events() -> None:
    events = tuple(
        event(index, kind=ContextEventKind.USER_TURN, protected=index == 1)
        for index in range(1, 10)
    )
    adapter = FakeSemanticCompressor(output_tokens=120)

    result = asyncio.run(ContextCompressor(adapter).compress(request(events, pressure=0.7)))

    assert result.level is CompressionLevel.C2
    assert result.validation_state is CompressionValidationState.REQUIRED
    assert result.execution_ready is False
    assert len(adapter.requests) == 1
    assert adapter.requests[0].max_output_tokens == 800
    assert tuple(event.event_id for event in adapter.requests[0].source_events) == (
        "event-2",
        "event-3",
    )
    raw_ids = {
        source_id
        for item in result.items
        if item.kind is CompressionItemKind.RAW_EVENT
        for source_id in item.source_event_ids
    }
    assert raw_ids == {"event-1", "event-4", "event-5", "event-6", "event-7", "event-8", "event-9"}


def test_c2_fixture_meets_median_token_reduction_target_without_dropping_recent_turns() -> None:
    older = tuple(event(index, token_estimate=300) for index in range(1, 15))
    recent = tuple(
        event(index, kind=ContextEventKind.USER_TURN, token_estimate=80) for index in range(15, 21)
    )
    result = asyncio.run(
        ContextCompressor(FakeSemanticCompressor(output_tokens=300)).compress(
            request((*older, *recent), pressure=0.7)
        )
    )

    assert result.token_reduction_ratio >= 0.5
    retained = {
        source_id
        for item in result.items
        if item.kind is CompressionItemKind.RAW_EVENT
        for source_id in item.source_event_ids
    }
    assert retained == {f"event-{index}" for index in range(15, 21)}


def test_c3_requires_matching_checkpoint_and_builds_digest_from_raw_events() -> None:
    events = (
        event(1, kind=ContextEventKind.SYSTEM_INSTRUCTION, protected=True),
        event(2),
        event(3),
    )
    adapter = FakeSemanticCompressor(output_tokens=100)
    checkpoint = BASE_CHECKPOINT.model_copy(
        update={"task_id": BASE_TASK.task_id, "scope": BASE_TASK.scope}
    )

    result = asyncio.run(
        ContextCompressor(adapter).compress(request(events, pressure=0.9, checkpoint=checkpoint))
    )

    assert result.level is CompressionLevel.C3
    assert result.checkpoint_id == checkpoint.checkpoint_id
    assert result.execution_ready is False
    assert adapter.requests[0].max_output_tokens == 1200
    assert tuple(item.kind for item in result.items) == (
        CompressionItemKind.RAW_EVENT,
        CompressionItemKind.SEMANTIC_SUMMARY,
    )
    assert adapter.requests[0].source_events == events[1:]


def test_c3_rejects_missing_or_cross_scope_checkpoint() -> None:
    events = (event(1),)
    compressor = ContextCompressor(FakeSemanticCompressor())

    with pytest.raises(ContextCompressionError, match="checkpoint") as missing:
        asyncio.run(compressor.compress(request(events, pressure=0.9)))
    assert missing.value.code == "CONTEXT_C3_CHECKPOINT_REQUIRED"

    wrong_scope = BASE_TASK.scope.model_copy(
        update={"permission_version": "different-permission-version"}
    )
    checkpoint = BASE_CHECKPOINT.model_copy(
        update={"task_id": BASE_TASK.task_id, "scope": wrong_scope}
    )
    with pytest.raises(ContextCompressionError, match="checkpoint") as mismatch:
        asyncio.run(compressor.compress(request(events, pressure=0.9, checkpoint=checkpoint)))
    assert mismatch.value.code == "CONTEXT_C3_CHECKPOINT_SCOPE_MISMATCH"


def test_semantic_compression_limit_stops_before_provider_call() -> None:
    adapter = FakeSemanticCompressor()
    with pytest.raises(ContextCompressionError, match="limit") as stopped:
        asyncio.run(
            ContextCompressor(adapter).compress(
                request((event(1),), pressure=0.7, semantic_compressions_used=2)
            )
        )
    assert stopped.value.code == "CONTEXT_SEMANTIC_COMPRESSION_LIMIT"
    assert adapter.requests == []


def test_semantic_result_must_attest_exact_raw_source_order() -> None:
    adapter = FakeSemanticCompressor(source_override=("unknown-event",))
    with pytest.raises(ContextCompressionError, match="source event") as mismatch:
        asyncio.run(
            ContextCompressor(adapter).compress(request((event(1), event(2)), pressure=0.7))
        )
    assert mismatch.value.code == "CONTEXT_SEMANTIC_SOURCE_MISMATCH"


def test_c2_rejects_provider_output_over_level_limit() -> None:
    adapter = FakeSemanticCompressor(output_tokens=801)
    with pytest.raises(ContextCompressionError, match="output-token") as overflow:
        asyncio.run(ContextCompressor(adapter).compress(request((event(1),), pressure=0.7)))
    assert overflow.value.code == "CONTEXT_SEMANTIC_OUTPUT_OVERFLOW"


def test_semantic_candidate_must_reduce_eligible_raw_tokens() -> None:
    adapter = FakeSemanticCompressor(output_tokens=250)
    with pytest.raises(ContextCompressionError, match="does not reduce") as rejected:
        asyncio.run(ContextCompressor(adapter).compress(request((event(1),), pressure=0.7)))
    assert rejected.value.code == "CONTEXT_SEMANTIC_NO_REDUCTION"


def test_event_scope_is_checked_before_any_compression() -> None:
    wrong_scope = BASE_TASK.scope.model_copy(update={"permission_version": "stale"})
    adapter = FakeSemanticCompressor()
    with pytest.raises(ContextCompressionError, match="scope") as mismatch:
        asyncio.run(
            ContextCompressor(adapter).compress(
                request((event(1, event_scope=wrong_scope),), pressure=0.7)
            )
        )
    assert mismatch.value.code == "CONTEXT_EVENT_SCOPE_MISMATCH"
    assert adapter.requests == []


def test_semantic_adapter_failure_is_typed_and_preserves_raw_boundary() -> None:
    with pytest.raises(ContextCompressionError, match="adapter failed") as failed:
        asyncio.run(
            ContextCompressor(FailingSemanticCompressor()).compress(
                request((event(1),), pressure=0.7)
            )
        )
    assert failed.value.code == "CONTEXT_SEMANTIC_ADAPTER_FAILED"


def test_request_rejects_reordered_or_duplicate_raw_event_stream() -> None:
    with pytest.raises(ValidationError, match="ordered by sequence"):
        request((event(2), event(1)), pressure=0.2)
    with pytest.raises(ValidationError, match="IDs must be unique"):
        duplicate = event(1)
        request((duplicate, duplicate.model_copy(update={"sequence": 2})), pressure=0.2)


def test_raw_event_integrity_rejects_mutated_content() -> None:
    payload: dict[str, Any] = event(1).model_dump()
    payload["content"] = {"mutated": True}
    with pytest.raises(ValidationError, match="hash does not match"):
        RawContextEvent.model_validate(payload)


def test_raw_event_contract_rejects_summary_on_summary_input() -> None:
    payload: dict[str, Any] = event(1).model_dump()
    payload["is_semantic_summary"] = True
    with pytest.raises(ValidationError, match="False"):
        RawContextEvent.model_validate(payload)


def test_raw_event_rejects_cross_scope_recoverable_artifact() -> None:
    wrong_scope = BASE_TASK.scope.model_copy(update={"permission_version": "stale"})
    payload: dict[str, Any] = event(1, artifact=True).model_dump()
    payload["recoverable_artifact"]["scope"] = wrong_scope.model_dump(mode="json")
    with pytest.raises(ValidationError, match="exact raw event scope"):
        RawContextEvent.model_validate(payload)
