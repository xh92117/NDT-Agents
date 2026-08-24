"""S2-03 protected-field validation and automatic fallback tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import JsonValue

from ndt_agents.context import (
    CompressionLevel,
    CompressionValidationError,
    CompressionValidationState,
    ContextCompressionPolicy,
    ContextCompressionRequest,
    ContextCompressionValidator,
    ContextCompressor,
    ContextEventKind,
    ContextValidationPolicy,
    ContextValidationRequest,
    ContextValidationResult,
    RawContextEvent,
    SemanticCompressionRequest,
    SemanticCompressionResult,
    ValidationDecision,
    context_event_content_sha256,
)
from ndt_agents.contracts.v1 import Checkpoint, TaskContext

ROOT = Path(__file__).resolve().parents[2]
BASE_TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
BASE_CHECKPOINT = Checkpoint.model_validate_json(
    (ROOT / "examples/contracts/v1/checkpoint.valid.json").read_text("utf-8")
).model_copy(update={"task_id": BASE_TASK.task_id, "scope": BASE_TASK.scope})
NOW = datetime(2026, 8, 24, 11, 0, tzinfo=UTC)


class SequenceCompressor:
    def __init__(self, modes: tuple[str, ...]) -> None:
        self.modes = list(modes)
        self.requests: list[SemanticCompressionRequest] = []

    async def summarize(self, request: SemanticCompressionRequest) -> SemanticCompressionResult:
        self.requests.append(request)
        mode = self.modes.pop(0)
        records: list[JsonValue] = []
        for event in request.source_events:
            record = dict(event.content)
            if mode == "drop-critical":
                record.pop("value", None)
                record.pop("unit", None)
            if mode == "drop-noncritical":
                record.pop("description", None)
            records.append(record)
        return SemanticCompressionResult(
            content={"records": records},
            source_event_ids=tuple(event.event_id for event in request.source_events),
            output_tokens=50,
            provider_version="fake-1",
            model_version="fake-1",
            prompt_version="validation-1",
        )


def event(sequence: int, *, protected: bool = False) -> RawContextEvent:
    content: dict[str, JsonValue] = {
        "description": f"observation-{sequence}",
        "value": sequence + 0.5,
        "unit": "mm",
        "standard_id": "GB-T-0001",
    }
    return RawContextEvent(
        event_id=f"validation-{sequence}",
        task_id=BASE_TASK.task_id,
        scope=BASE_TASK.scope,
        sequence=sequence,
        kind=ContextEventKind.PROJECT_FACT,
        content=content,
        content_sha256=context_event_content_sha256(content),
        token_estimate=300,
        protected=protected,
        created_at=NOW + timedelta(seconds=sequence),
    )


def compression_request(
    *, level: CompressionLevel, semantic_used: int = 0
) -> ContextCompressionRequest:
    pressure = {
        CompressionLevel.C1: 0.5,
        CompressionLevel.C2: 0.7,
        CompressionLevel.C3: 0.9,
    }[level]
    return ContextCompressionRequest(
        task_id=BASE_TASK.task_id,
        scope=BASE_TASK.scope,
        raw_events=tuple(event(index, protected=index == 1) for index in range(1, 9)),
        active_context_tokens=int(pressure * 10_000),
        active_context_limit=10_000,
        semantic_compressions_used=semantic_used,
        checkpoint=BASE_CHECKPOINT if level is CompressionLevel.C3 else None,
        policy=ContextCompressionPolicy(policy_version="compression-1"),
    )


def run_validation(
    compression: ContextCompressionRequest,
    adapter: SequenceCompressor,
    *,
    scores: dict[CompressionLevel, float],
) -> ContextValidationResult:
    compressor = ContextCompressor(adapter)
    candidate = asyncio.run(compressor.compress(compression))
    request = ContextValidationRequest(
        compression_request=compression,
        candidate=candidate,
        policy=ContextValidationPolicy(policy_version="validation-1"),
        baseline_quality_score=95.0,
        candidate_quality_scores=scores,
    )
    return asyncio.run(
        ContextCompressionValidator().validate_or_fallback(request, compressor=compressor)
    )


def test_safe_c2_candidate_gets_hash_bound_execution_proof() -> None:
    result = run_validation(
        compression_request(level=CompressionLevel.C2),
        SequenceCompressor(("safe",)),
        scores={CompressionLevel.C2: 93.0},
    )

    assert result.result.level is CompressionLevel.C2
    assert result.result.validation_state is CompressionValidationState.READY
    assert result.result.execution_ready is True
    assert result.result.validation_report_sha256 == result.reports[0].report_sha256
    assert result.reports[0].critical_retention_ratio == 1.0
    assert result.reports[0].noncritical_retention_ratio == 1.0


def test_missing_critical_field_forces_c2_to_deterministic_c1() -> None:
    result = run_validation(
        compression_request(level=CompressionLevel.C2),
        SequenceCompressor(("drop-critical",)),
        scores={CompressionLevel.C2: 95.0},
    )

    assert result.fallback_levels == (CompressionLevel.C1,)
    assert [report.decision for report in result.reports] == [
        ValidationDecision.FALLBACK,
        ValidationDecision.ACCEPT,
    ]
    assert result.result.level is CompressionLevel.C1
    assert result.result.execution_ready is True


def test_c3_falls_back_through_c2_from_raw_events_and_respects_two_call_limit() -> None:
    adapter = SequenceCompressor(("drop-critical", "safe"))
    result = run_validation(
        compression_request(level=CompressionLevel.C3),
        adapter,
        scores={CompressionLevel.C3: 95.0, CompressionLevel.C2: 94.0},
    )

    assert result.fallback_levels == (CompressionLevel.C2,)
    assert result.result.level is CompressionLevel.C2
    assert result.result.semantic_compressions_used == 2
    assert len(adapter.requests) == 2
    assert all(
        request.source_events[0].is_semantic_summary is False for request in adapter.requests
    )


def test_unmeasured_or_degraded_semantic_quality_forces_fallback() -> None:
    unmeasured = run_validation(
        compression_request(level=CompressionLevel.C2),
        SequenceCompressor(("safe",)),
        scores={},
    )
    degraded = run_validation(
        compression_request(level=CompressionLevel.C2),
        SequenceCompressor(("safe",)),
        scores={CompressionLevel.C2: 91.9},
    )

    assert unmeasured.result.level is CompressionLevel.C1
    assert degraded.result.level is CompressionLevel.C1
    assert degraded.reports[0].quality_degradation_points > 3.0


def test_missing_noncritical_fact_fails_98_percent_threshold() -> None:
    result = run_validation(
        compression_request(level=CompressionLevel.C2),
        SequenceCompressor(("drop-noncritical",)),
        scores={CompressionLevel.C2: 95.0},
    )

    assert result.reports[0].noncritical_retention_ratio == 0.0
    assert result.result.level is CompressionLevel.C1


def test_candidate_binding_rejects_cross_task_or_mutated_manifest() -> None:
    compression = compression_request(level=CompressionLevel.C2)
    adapter = SequenceCompressor(("safe",))
    compressor = ContextCompressor(adapter)
    candidate = asyncio.run(compressor.compress(compression)).model_copy(
        update={"task_id": UUID("00000000-0000-4000-8000-000000000999")}
    )
    request = ContextValidationRequest(
        compression_request=compression,
        candidate=candidate,
        policy=ContextValidationPolicy(policy_version="validation-1"),
        baseline_quality_score=95.0,
        candidate_quality_scores={CompressionLevel.C2: 95.0},
    )

    with pytest.raises(CompressionValidationError, match="exact raw context") as error:
        asyncio.run(
            ContextCompressionValidator().validate_or_fallback(request, compressor=compressor)
        )
    assert error.value.code == "CONTEXT_VALIDATION_BINDING_MISMATCH"


def test_candidate_source_coverage_must_be_exact() -> None:
    compression = compression_request(level=CompressionLevel.C2)
    adapter = SequenceCompressor(("safe",))
    compressor = ContextCompressor(adapter)
    candidate = asyncio.run(compressor.compress(compression))
    first = candidate.items[0].model_copy(update={"source_event_ids": ("validation-1", "extra")})
    candidate = candidate.model_copy(update={"items": (first, *candidate.items[1:])})
    request = ContextValidationRequest(
        compression_request=compression,
        candidate=candidate,
        policy=ContextValidationPolicy(policy_version="validation-1"),
        baseline_quality_score=95.0,
        candidate_quality_scores={CompressionLevel.C2: 95.0},
    )

    with pytest.raises(CompressionValidationError, match="every raw event") as error:
        asyncio.run(
            ContextCompressionValidator().validate_or_fallback(request, compressor=compressor)
        )
    assert error.value.code == "CONTEXT_VALIDATION_SOURCE_COVERAGE"
