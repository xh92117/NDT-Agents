"""Bounded memory distillation with candidates, deduplication, and conflicts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, Self
from uuid import UUID, uuid5

from pydantic import Field, JsonValue, model_validator

from ndt_agents.context.compression_models import ContextEventKind, RawContextEvent
from ndt_agents.contracts.v1 import DataClassification, MemoryScope, TenantScope
from ndt_agents.memory.models import (
    MemoryAccess,
    MemoryApprovalState,
    MemoryModel,
    MemoryQuery,
    ScopedMemoryRecord,
    memory_content_sha256,
)
from ndt_agents.memory.store import MemoryStore

_DISTILLATION_NAMESPACE = UUID("e2b8d6ab-204d-49a5-977e-d44f80d99f61")
_TURN_KINDS = {ContextEventKind.USER_TURN, ContextEventKind.ASSISTANT_TURN}


class DistillationError(RuntimeError):
    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class MemoryCandidateKind(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    PREFERENCE = "PREFERENCE"


class DistillationTrigger(StrEnum):
    CONTEXT_PRESSURE = "CONTEXT_PRESSURE"
    TURN_COUNT = "TURN_COUNT"
    TASK_COMPLETED = "TASK_COMPLETED"
    USER_MEMORY_INTENT = "USER_MEMORY_INTENT"
    ARCHIVED = "ARCHIVED"


class DistillationSignals(MemoryModel):
    active_context_ratio: float = Field(ge=0.0)
    conversation_turn_count: int = Field(ge=0)
    task_completed: bool = False
    user_memory_intent: bool = False
    archived: bool = False


class MemoryCandidateProposal(MemoryModel):
    proposal_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    kind: MemoryCandidateKind
    memory_scope: Literal[MemoryScope.USER, MemoryScope.PROJECT]
    fact_key: str = Field(min_length=1, max_length=256)
    content: dict[str, JsonValue] = Field(min_length=1)
    provenance_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)
    classification: DataClassification
    sensitive: bool = False
    durable: bool = False
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_proposal(self) -> Self:
        if len(self.provenance_ids) != len(set(self.provenance_ids)):
            raise ValueError("candidate provenance IDs must be unique")
        if self.expires_at is not None and self.expires_at.utcoffset() is None:
            raise ValueError("candidate expiry must include an explicit UTC offset")
        return self


class DistillationAdapterRequest(MemoryModel):
    task_id: UUID
    scope: TenantScope
    source_events: tuple[RawContextEvent, ...] = Field(min_length=1)
    max_digest_tokens: int = Field(default=800, ge=1, le=800)
    max_project_facts: int = Field(default=30, ge=1, le=30)
    policy_version: str = Field(min_length=1, max_length=128)


class DistillationAdapterResult(MemoryModel):
    digest: dict[str, JsonValue] = Field(min_length=1)
    digest_tokens: int = Field(ge=1, le=800)
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    proposals: tuple[MemoryCandidateProposal, ...] = Field(max_length=100)
    provider_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)


class MemoryDistiller(Protocol):
    async def distill(self, request: DistillationAdapterRequest) -> DistillationAdapterResult: ...


class MemoryConflict(MemoryModel):
    fact_key: str
    existing_memory_ids: tuple[UUID, ...] = Field(min_length=1)
    candidate_memory_id: UUID
    existing_hashes: tuple[str, ...] = Field(min_length=1)
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DistillationRequest(MemoryModel):
    task_id: UUID
    scope: TenantScope
    namespace_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    access: MemoryAccess
    raw_events: tuple[RawContextEvent, ...] = Field(min_length=1, max_length=1000)
    signals: DistillationSignals
    policy_version: str = Field(min_length=1, max_length=128)
    now: datetime

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.now.utcoffset() is None:
            raise ValueError("distillation time must include an explicit UTC offset")
        if self.access.scope.model_dump(mode="json") != self.scope.model_dump(mode="json"):
            raise ValueError("distillation access must use the exact request scope")
        for event in self.raw_events:
            if event.task_id != self.task_id or event.scope.model_dump(
                mode="json"
            ) != self.scope.model_dump(mode="json"):
                raise ValueError("distillation event is outside the exact task scope")
        return self


class DistillationResult(MemoryModel):
    triggers: tuple[DistillationTrigger, ...] = Field(min_length=1)
    retained_raw_event_ids: tuple[str, ...]
    digest: dict[str, JsonValue]
    digest_tokens: int = Field(ge=1, le=800)
    candidates: tuple[ScopedMemoryRecord, ...]
    deduplicated_proposal_ids: tuple[str, ...]
    conflicts: tuple[MemoryConflict, ...]


class MemoryDistillationPipeline:
    def __init__(self, *, store: MemoryStore, adapter: MemoryDistiller) -> None:
        self._store = store
        self._adapter = adapter

    async def distill(self, request: DistillationRequest) -> DistillationResult:
        triggers = _triggers(request.signals)
        if not triggers:
            raise DistillationError(
                code="MEMORY_DISTILLATION_NOT_TRIGGERED",
                message="No configured memory-distillation trigger is active.",
                next_action="Continue the task and retry when a versioned trigger becomes active.",
            )
        retained_ids = _retained_event_ids(request.raw_events)
        eligible = tuple(
            event
            for event in request.raw_events
            if event.event_id not in retained_ids and not event.protected
        )
        if not eligible:
            raise DistillationError(
                code="MEMORY_DISTILLATION_NO_ELIGIBLE_EVENTS",
                message="No older non-protected raw events are eligible for distillation.",
                next_action="Keep the current raw context without creating memory candidates.",
            )
        adapter_request = DistillationAdapterRequest(
            task_id=request.task_id,
            scope=request.scope,
            source_events=eligible,
            policy_version=request.policy_version,
        )
        output = await self._adapter.distill(adapter_request)
        expected_ids = tuple(event.event_id for event in eligible)
        if output.source_event_ids != expected_ids:
            raise DistillationError(
                code="MEMORY_DISTILLATION_SOURCE_MISMATCH",
                message="The distiller did not attest to the exact eligible raw events.",
                next_action="Reject the output and rerun from the verified raw-event stream.",
            )
        project_fact_count = sum(
            proposal.kind is MemoryCandidateKind.FACT
            and proposal.memory_scope is MemoryScope.PROJECT
            for proposal in output.proposals
        )
        if project_fact_count > adapter_request.max_project_facts:
            raise DistillationError(
                code="MEMORY_DISTILLATION_FACT_LIMIT",
                message="The distiller exceeded the project-fact candidate limit.",
                next_action="Reject the output and request at most 30 project facts.",
            )
        return await self._persist_candidates(request, triggers, retained_ids, output)

    async def _persist_candidates(
        self,
        request: DistillationRequest,
        triggers: tuple[DistillationTrigger, ...],
        retained_ids: frozenset[str],
        output: DistillationAdapterResult,
    ) -> DistillationResult:
        existing: list[ScopedMemoryRecord] = []
        for memory_scope in (MemoryScope.USER, MemoryScope.PROJECT):
            existing.extend(
                await self._store.query(
                    MemoryQuery(
                        access=request.access,
                        memory_scope=memory_scope,
                        namespace_id=request.namespace_id,
                        include_candidates=True,
                        now=request.now,
                        limit=500,
                    )
                )
            )
        existing_hashes = {record.content_sha256 for record in existing}
        existing_by_key: dict[str, list[ScopedMemoryRecord]] = {}
        for record in existing:
            fact_key = record.content.get("fact_key")
            if isinstance(fact_key, str):
                existing_by_key.setdefault(fact_key, []).append(record)

        candidates: list[ScopedMemoryRecord] = []
        deduplicated: list[str] = []
        conflicts: list[MemoryConflict] = []
        seen_hashes = set(existing_hashes)
        for proposal in output.proposals:
            content: dict[str, JsonValue] = {
                "fact_key": proposal.fact_key,
                "candidate_kind": proposal.kind.value,
                "value": proposal.content,
                "sensitive": proposal.sensitive,
                "durable": proposal.durable,
            }
            content_hash = memory_content_sha256(content)
            if content_hash in seen_hashes:
                deduplicated.append(proposal.proposal_id)
                continue
            memory_id = uuid5(
                _DISTILLATION_NAMESPACE,
                f"{request.scope.tenant_id}:{request.scope.project_id}:{request.namespace_id}:"
                f"{content_hash}",
            )
            record = ScopedMemoryRecord(
                memory_id=memory_id,
                scope=request.scope,
                memory_scope=proposal.memory_scope,
                namespace_id=request.namespace_id,
                content=content,
                content_sha256=content_hash,
                provenance_ids=proposal.provenance_ids,
                confidence=proposal.confidence,
                classification=proposal.classification,
                approval_state=MemoryApprovalState.CANDIDATE,
                protected=proposal.sensitive or proposal.durable,
                source_version=(
                    f"{request.policy_version}:{output.provider_version}:{output.model_version}:"
                    f"{output.prompt_version}"
                ),
                expires_at=proposal.expires_at,
                created_at=request.now,
            )
            clashes = [
                item
                for item in existing_by_key.get(proposal.fact_key, [])
                if item.content_sha256 != content_hash
            ]
            if clashes:
                conflicts.append(
                    MemoryConflict(
                        fact_key=proposal.fact_key,
                        existing_memory_ids=tuple(item.memory_id for item in clashes),
                        candidate_memory_id=memory_id,
                        existing_hashes=tuple(item.content_sha256 for item in clashes),
                        candidate_hash=content_hash,
                    )
                )
            await self._store.put(request.access, record)
            candidates.append(record)
            seen_hashes.add(content_hash)
            existing_by_key.setdefault(proposal.fact_key, []).append(record)

        return DistillationResult(
            triggers=triggers,
            retained_raw_event_ids=tuple(
                event.event_id for event in request.raw_events if event.event_id in retained_ids
            ),
            digest=output.digest,
            digest_tokens=output.digest_tokens,
            candidates=tuple(candidates),
            deduplicated_proposal_ids=tuple(deduplicated),
            conflicts=tuple(conflicts),
        )


def _triggers(signals: DistillationSignals) -> tuple[DistillationTrigger, ...]:
    active: list[DistillationTrigger] = []
    if signals.active_context_ratio >= 0.6:
        active.append(DistillationTrigger.CONTEXT_PRESSURE)
    if signals.conversation_turn_count >= 20:
        active.append(DistillationTrigger.TURN_COUNT)
    if signals.task_completed:
        active.append(DistillationTrigger.TASK_COMPLETED)
    if signals.user_memory_intent:
        active.append(DistillationTrigger.USER_MEMORY_INTENT)
    if signals.archived:
        active.append(DistillationTrigger.ARCHIVED)
    return tuple(active)


def _retained_event_ids(events: tuple[RawContextEvent, ...]) -> frozenset[str]:
    turns = [event.event_id for event in events if event.kind in _TURN_KINDS]
    protected = {event.event_id for event in events if event.protected}
    return frozenset((*turns[-6:], *protected))
