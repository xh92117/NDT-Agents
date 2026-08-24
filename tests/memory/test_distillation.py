"""S2-05 INT-MEMORY distillation tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import pytest
from pydantic import JsonValue

from ndt_agents.context import ContextEventKind, RawContextEvent, context_event_content_sha256
from ndt_agents.contracts.v1 import DataClassification, MemoryScope, TenantScope
from ndt_agents.memory import (
    DistillationAdapterRequest,
    DistillationAdapterResult,
    DistillationError,
    DistillationRequest,
    DistillationSignals,
    DistillationTrigger,
    InMemoryMemoryRepository,
    MemoryAccess,
    MemoryApprovalState,
    MemoryCandidateKind,
    MemoryCandidateProposal,
    MemoryDistillationPipeline,
    MemoryStore,
    ScopedMemoryRecord,
    memory_content_sha256,
)

NOW = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)
TASK_ID = UUID("00000000-0000-4000-8000-000000000004")
SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000001"),
    project_id=UUID("00000000-0000-4000-8000-000000000002"),
    user_id=UUID("00000000-0000-4000-8000-000000000003"),
    role_codes=("ENGINEER",),
    permission_version="perm-1",
)
ACCESS = MemoryAccess(
    scope=SCOPE,
    permissions=(
        "memory:user:read",
        "memory:user:write",
        "memory:project:read",
        "memory:project:write",
        "memory:candidate:read",
    ),
    clearance=DataClassification.RESTRICTED,
)


class FakeDistiller:
    def __init__(
        self,
        proposals: tuple[MemoryCandidateProposal, ...],
        *,
        source_override: tuple[str, ...] | None = None,
    ) -> None:
        self.proposals = proposals
        self.source_override = source_override
        self.requests: list[DistillationAdapterRequest] = []

    async def distill(self, request: DistillationAdapterRequest) -> DistillationAdapterResult:
        self.requests.append(request)
        return DistillationAdapterResult(
            digest={"summary": "older turns"},
            digest_tokens=120,
            source_event_ids=self.source_override
            or tuple(event.event_id for event in request.source_events),
            proposals=self.proposals,
            provider_version="fake-1",
            model_version="fake-1",
            prompt_version="distill-1",
        )


def event(index: int, *, protected: bool = False) -> RawContextEvent:
    content: dict[str, JsonValue] = {"turn": index, "text": f"turn-{index}"}
    return RawContextEvent(
        event_id=f"turn-{index}",
        task_id=TASK_ID,
        scope=SCOPE,
        sequence=index,
        kind=ContextEventKind.USER_TURN,
        content=content,
        content_sha256=context_event_content_sha256(content),
        token_estimate=100,
        protected=protected,
        created_at=NOW + timedelta(seconds=index),
    )


def proposal(
    index: int,
    *,
    fact_key: str = "bridge.name",
    value: str | None = None,
    memory_scope: Literal[MemoryScope.USER, MemoryScope.PROJECT] = MemoryScope.PROJECT,
    kind: MemoryCandidateKind = MemoryCandidateKind.FACT,
    sensitive: bool = False,
) -> MemoryCandidateProposal:
    return MemoryCandidateProposal(
        proposal_id=f"proposal-{index}",
        kind=kind,
        memory_scope=memory_scope,
        fact_key=fact_key,
        content={"value": value or f"value-{index}"},
        provenance_ids=(UUID(f"10000000-0000-4000-8000-{index:012d}"),),
        confidence=0.9,
        classification=DataClassification.INTERNAL,
        sensitive=sensitive,
        durable=sensitive,
    )


def request(signals: DistillationSignals | None = None) -> DistillationRequest:
    return DistillationRequest(
        task_id=TASK_ID,
        scope=SCOPE,
        namespace_id="project-memory",
        access=ACCESS,
        raw_events=tuple(event(index, protected=index == 1) for index in range(1, 11)),
        signals=signals
        or DistillationSignals(active_context_ratio=0.6, conversation_turn_count=20),
        policy_version="distillation-1",
        now=NOW + timedelta(minutes=1),
    )


def test_triggered_distillation_keeps_six_recent_and_all_protected_turns() -> None:
    async def scenario() -> None:
        adapter = FakeDistiller((proposal(1),))
        pipeline = MemoryDistillationPipeline(
            store=MemoryStore(InMemoryMemoryRepository()), adapter=adapter
        )
        result = await pipeline.distill(request())

        assert result.triggers == (
            DistillationTrigger.CONTEXT_PRESSURE,
            DistillationTrigger.TURN_COUNT,
        )
        assert result.retained_raw_event_ids == (
            "turn-1",
            "turn-5",
            "turn-6",
            "turn-7",
            "turn-8",
            "turn-9",
            "turn-10",
        )
        assert tuple(event.event_id for event in adapter.requests[0].source_events) == (
            "turn-2",
            "turn-3",
            "turn-4",
        )
        assert result.digest_tokens <= 800

    asyncio.run(scenario())


def test_candidates_are_immutable_scoped_and_pending_approval() -> None:
    async def scenario() -> None:
        sensitive = proposal(1, sensitive=True, memory_scope=MemoryScope.USER)
        pipeline = MemoryDistillationPipeline(
            store=MemoryStore(InMemoryMemoryRepository()), adapter=FakeDistiller((sensitive,))
        )
        first = await pipeline.distill(request())
        second_store = MemoryStore(InMemoryMemoryRepository())
        second = await MemoryDistillationPipeline(
            store=second_store, adapter=FakeDistiller((sensitive,))
        ).distill(request())

        candidate = first.candidates[0]
        assert candidate.approval_state is MemoryApprovalState.CANDIDATE
        assert candidate.memory_scope is MemoryScope.USER
        assert candidate.protected is True
        assert candidate.provenance_ids == sensitive.provenance_ids
        assert candidate.memory_id == second.candidates[0].memory_id

    asyncio.run(scenario())


def test_exact_duplicate_is_deduplicated_before_persistence() -> None:
    async def scenario() -> None:
        store = MemoryStore(InMemoryMemoryRepository())
        adapter = FakeDistiller((proposal(1), proposal(2, value="value-1")))
        result = await MemoryDistillationPipeline(store=store, adapter=adapter).distill(request())

        assert len(result.candidates) == 1
        assert result.deduplicated_proposal_ids == ("proposal-2",)

    asyncio.run(scenario())


def test_same_fact_key_with_different_value_creates_conflict_without_overwrite() -> None:
    async def scenario() -> None:
        store = MemoryStore(InMemoryMemoryRepository())
        existing_content: dict[str, JsonValue] = {
            "fact_key": "bridge.name",
            "candidate_kind": "FACT",
            "value": {"value": "old"},
            "sensitive": False,
            "durable": False,
        }
        existing = ScopedMemoryRecord(
            memory_id=UUID("20000000-0000-4000-8000-000000000001"),
            scope=SCOPE,
            memory_scope=MemoryScope.PROJECT,
            namespace_id="project-memory",
            content=existing_content,
            content_sha256=memory_content_sha256(existing_content),
            provenance_ids=(UUID("30000000-0000-4000-8000-000000000001"),),
            confidence=1.0,
            classification=DataClassification.INTERNAL,
            approval_state=MemoryApprovalState.APPROVED,
            source_version="manual-1",
            created_at=NOW,
        )
        await store.put(ACCESS, existing)
        result = await MemoryDistillationPipeline(
            store=store, adapter=FakeDistiller((proposal(1, value="new"),))
        ).distill(request())

        assert result.conflicts[0].existing_memory_ids == (existing.memory_id,)
        assert result.conflicts[0].candidate_memory_id == result.candidates[0].memory_id
        assert await store.get(ACCESS, existing.memory_id, now=NOW) == existing

    asyncio.run(scenario())


def test_no_trigger_or_source_mismatch_fails_without_candidates() -> None:
    async def scenario() -> None:
        no_trigger = DistillationSignals(active_context_ratio=0.1, conversation_turn_count=2)
        pipeline = MemoryDistillationPipeline(
            store=MemoryStore(InMemoryMemoryRepository()), adapter=FakeDistiller((proposal(1),))
        )
        with pytest.raises(DistillationError, match="trigger") as missing:
            await pipeline.distill(request(no_trigger))
        assert missing.value.code == "MEMORY_DISTILLATION_NOT_TRIGGERED"

        bad = MemoryDistillationPipeline(
            store=MemoryStore(InMemoryMemoryRepository()),
            adapter=FakeDistiller((proposal(1),), source_override=("wrong",)),
        )
        with pytest.raises(DistillationError, match="exact eligible") as mismatch:
            await bad.distill(request())
        assert mismatch.value.code == "MEMORY_DISTILLATION_SOURCE_MISMATCH"

    asyncio.run(scenario())


def test_project_fact_limit_is_enforced() -> None:
    async def scenario() -> None:
        proposals = tuple(proposal(index, fact_key=f"fact-{index}") for index in range(1, 32))
        pipeline = MemoryDistillationPipeline(
            store=MemoryStore(InMemoryMemoryRepository()), adapter=FakeDistiller(proposals)
        )
        with pytest.raises(DistillationError, match="fact candidate limit") as limit:
            await pipeline.distill(request())
        assert limit.value.code == "MEMORY_DISTILLATION_FACT_LIMIT"

    asyncio.run(scenario())
