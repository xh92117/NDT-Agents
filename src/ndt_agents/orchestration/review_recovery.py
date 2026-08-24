"""Durable replay boundary for review, correction, and pre-aggregation recovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from threading import RLock
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.orchestration.budget import BudgetGuard, BudgetTelemetry
from ndt_agents.orchestration.child_models import ChildModel, ChildTaskContext
from ndt_agents.orchestration.review import (
    CorrectionContext,
    CorrectionExecutor,
    ReviewContext,
    ReviewerDefinition,
    ReviewExecutor,
    ReviewWorkflow,
    ReviewWorkflowResult,
)
from ndt_agents.orchestration.scheduler import ScheduleResult

REVIEW_RECOVERY_VERSION: Literal["1.0.0"] = "1.0.0"
ZERO_SHA256 = "0" * 64


class ReviewRecoveryEventType(StrEnum):
    PREPARED = "PREPARED"
    REVIEW_OUTPUT = "REVIEW_OUTPUT"
    CORRECTION_OUTPUT = "CORRECTION_OUTPUT"
    RESULT = "RESULT"


class ReviewRecoveryFaultPoint(StrEnum):
    BEFORE_REVIEW = "BEFORE_REVIEW"
    AFTER_FIRST_COMPLETED_CALL = "AFTER_FIRST_COMPLETED_CALL"
    BEFORE_MAIN_AGGREGATION = "BEFORE_MAIN_AGGREGATION"


class SimulatedReviewTermination(BaseException):
    """Test-only process-loss signal that is never converted to a review failure."""


class ReviewRecoveryError(RuntimeError):
    def __init__(self, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class ReviewRecoveryEvent(ChildModel):
    schema_version: Literal["1.0.0"] = REVIEW_RECOVERY_VERSION
    event_id: UUID
    recovery_id: UUID
    scope: TenantScope
    sequence: int = Field(ge=1)
    event_type: ReviewRecoveryEventType
    payload: dict[str, Any]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReviewRecoveryOutcome(ChildModel):
    schema_version: Literal["1.0.0"] = REVIEW_RECOVERY_VERSION
    recovery_id: UUID
    result: ReviewWorkflowResult
    recovered: bool
    latest_sequence: int = Field(ge=1)


def _canonical_sha256(value: object) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ReviewRecoveryError(
            "REVIEW_RECOVERY_PAYLOAD_INVALID",
            "The recovery payload is not canonical JSON.",
            "Provide strict JSON-compatible review state.",
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _project_key(scope: TenantScope) -> tuple[UUID, UUID]:
    return scope.tenant_id, scope.project_id


class ReviewRecoveryRepository(Protocol):
    def append(
        self,
        *,
        recovery_id: UUID,
        scope: TenantScope,
        event_type: ReviewRecoveryEventType,
        payload: Mapping[str, Any],
    ) -> ReviewRecoveryEvent: ...

    def list(self, scope: TenantScope, recovery_id: UUID) -> tuple[ReviewRecoveryEvent, ...]: ...


class InMemoryReviewRecoveryRepository:
    """Append-only reference journal shared by restarted runtime instances."""

    def __init__(self) -> None:
        self._events: dict[UUID, list[ReviewRecoveryEvent]] = {}
        self._scopes: dict[UUID, tuple[UUID, UUID]] = {}
        self._lock = RLock()

    def append(
        self,
        *,
        recovery_id: UUID,
        scope: TenantScope,
        event_type: ReviewRecoveryEventType,
        payload: Mapping[str, Any],
    ) -> ReviewRecoveryEvent:
        payload_dict = dict(payload)
        with self._lock:
            bound_scope = self._scopes.setdefault(recovery_id, _project_key(scope))
            if bound_scope != _project_key(scope):
                raise ReviewRecoveryError(
                    "REVIEW_RECOVERY_SCOPE_MISMATCH",
                    "The recovery ID is bound to another project.",
                    "Use the exact original tenant and project.",
                )
            chain = self._events.setdefault(recovery_id, [])
            sequence = len(chain) + 1
            previous = chain[-1].event_sha256 if chain else ZERO_SHA256
            payload_sha256 = _canonical_sha256(payload_dict)
            event_data = {
                "event_id": str(event_id := uuid4()),
                "recovery_id": str(recovery_id),
                "scope": scope.model_dump(mode="json"),
                "sequence": sequence,
                "event_type": event_type.value,
                "payload": payload_dict,
                "payload_sha256": payload_sha256,
                "previous_sha256": previous,
            }
            event = ReviewRecoveryEvent(
                event_id=event_id,
                recovery_id=recovery_id,
                scope=scope,
                sequence=sequence,
                event_type=event_type,
                payload=payload_dict,
                payload_sha256=payload_sha256,
                previous_sha256=previous,
                event_sha256=_canonical_sha256(event_data),
            )
            chain.append(event)
            return event

    def list(self, scope: TenantScope, recovery_id: UUID) -> tuple[ReviewRecoveryEvent, ...]:
        with self._lock:
            bound_scope = self._scopes.get(recovery_id)
            if bound_scope is not None and bound_scope != _project_key(scope):
                raise ReviewRecoveryError(
                    "REVIEW_RECOVERY_SCOPE_MISMATCH",
                    "The recovery ID is outside the authorized project.",
                    "Use the exact original tenant and project.",
                )
            events = tuple(self._events.get(recovery_id, ()))
        self.verify(events)
        return events

    @staticmethod
    def verify(events: tuple[ReviewRecoveryEvent, ...]) -> None:
        previous = ZERO_SHA256
        for sequence, event in enumerate(events, start=1):
            event_data = {
                "event_id": str(event.event_id),
                "recovery_id": str(event.recovery_id),
                "scope": event.scope.model_dump(mode="json"),
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "payload": event.payload,
                "payload_sha256": event.payload_sha256,
                "previous_sha256": event.previous_sha256,
            }
            if (
                event.sequence != sequence
                or event.previous_sha256 != previous
                or event.payload_sha256 != _canonical_sha256(event.payload)
                or event.event_sha256 != _canonical_sha256(event_data)
            ):
                raise ReviewRecoveryError(
                    "REVIEW_RECOVERY_CHAIN_INVALID",
                    "The review recovery chain failed integrity validation.",
                    "Stop aggregation and reconcile immutable recovery evidence.",
                )
            previous = event.event_sha256


class _CallJournal:
    def __init__(
        self,
        repository: ReviewRecoveryRepository,
        recovery_id: UUID,
        scope: TenantScope,
        events: Sequence[ReviewRecoveryEvent],
        fault: ReviewRecoveryFaultPoint | None,
    ) -> None:
        self.repository = repository
        self.recovery_id = recovery_id
        self.scope = scope
        self.fault = fault
        self.completed_calls = 0
        self.outputs: dict[tuple[ReviewRecoveryEventType, str], dict[str, Any]] = {}
        for event in events:
            if event.event_type in {
                ReviewRecoveryEventType.REVIEW_OUTPUT,
                ReviewRecoveryEventType.CORRECTION_OUTPUT,
            }:
                signature = str(event.payload["signature"])
                output = event.payload["output"]
                if not isinstance(output, dict):
                    raise ReviewRecoveryError(
                        "REVIEW_RECOVERY_OUTPUT_INVALID",
                        "A cached executor output is not an object.",
                        "Reconcile the recovery journal before retrying.",
                    )
                self.outputs[(event.event_type, signature)] = output

    async def call(
        self,
        event_type: ReviewRecoveryEventType,
        context: ReviewContext | CorrectionContext,
        operation: Any,
    ) -> Mapping[str, Any]:
        signature = _canonical_sha256(context.model_dump(mode="json"))
        cached = self.outputs.get((event_type, signature))
        if cached is not None:
            return cached
        output = await operation(context)
        output_dict = dict(output)
        self.repository.append(
            recovery_id=self.recovery_id,
            scope=self.scope,
            event_type=event_type,
            payload={"signature": signature, "output": output_dict},
        )
        self.outputs[(event_type, signature)] = output_dict
        self.completed_calls += 1
        if (
            self.fault is ReviewRecoveryFaultPoint.AFTER_FIRST_COMPLETED_CALL
            and self.completed_calls == 1
        ):
            raise SimulatedReviewTermination
        return output_dict


class _JournalReviewer:
    def __init__(self, journal: _CallJournal, executor: ReviewExecutor) -> None:
        self.journal = journal
        self.executor = executor

    async def review(self, context: ReviewContext) -> Mapping[str, Any]:
        return await self.journal.call(
            ReviewRecoveryEventType.REVIEW_OUTPUT, context, self.executor.review
        )


class _JournalCorrector:
    def __init__(self, journal: _CallJournal, executor: CorrectionExecutor) -> None:
        self.journal = journal
        self.executor = executor

    async def correct(self, context: CorrectionContext) -> Mapping[str, Any]:
        return await self.journal.call(
            ReviewRecoveryEventType.CORRECTION_OUTPUT, context, self.executor.correct
        )


class RecoverableReviewWorkflow:
    """Replay the deterministic review graph without repeating committed executor calls."""

    def __init__(self, repository: ReviewRecoveryRepository) -> None:
        self._repository = repository

    async def run(
        self,
        recovery_id: UUID,
        schedule: ScheduleResult,
        contexts: Sequence[ChildTaskContext],
        *,
        reviewer: ReviewExecutor,
        reviewer_definition: ReviewerDefinition,
        correctors: Mapping[str, CorrectionExecutor],
        budget_guard: BudgetGuard,
        cross_result_required: bool | None = None,
        fault: ReviewRecoveryFaultPoint | None = None,
    ) -> ReviewRecoveryOutcome:
        scope = schedule.scope
        request = {
            "schedule": schedule.model_dump(mode="json"),
            "contexts": [context.model_dump(mode="json") for context in contexts],
            "reviewer_definition": reviewer_definition.model_dump(mode="json"),
            "corrector_ids": sorted(correctors),
            "cross_result_required": cross_result_required,
        }
        request_sha256 = _canonical_sha256(request)
        events = self._repository.list(scope, recovery_id)
        if events:
            prepared = events[0]
            if (
                prepared.event_type is not ReviewRecoveryEventType.PREPARED
                or prepared.payload.get("request_sha256") != request_sha256
            ):
                raise ReviewRecoveryError(
                    "REVIEW_RECOVERY_IDEMPOTENCY_CONFLICT",
                    "The recovery ID is bound to different review input.",
                    "Use the original exact input or a new recovery ID.",
                )
            terminal = next(
                (
                    event
                    for event in reversed(events)
                    if event.event_type is ReviewRecoveryEventType.RESULT
                ),
                None,
            )
            if terminal is not None:
                result = ReviewWorkflowResult.model_validate(terminal.payload["result"])
                if terminal.payload.get("review_manifest_sha256") != result.review_manifest_sha256:
                    raise ReviewRecoveryError(
                        "REVIEW_RECOVERY_MANIFEST_INVALID",
                        "The committed review manifest binding is invalid.",
                        "Stop aggregation and reconcile the review evidence.",
                    )
                return ReviewRecoveryOutcome(
                    recovery_id=recovery_id,
                    result=result,
                    recovered=True,
                    latest_sequence=events[-1].sequence,
                )
            initial_budget = BudgetTelemetry.model_validate(prepared.payload["initial_budget"])
            active_guard = BudgetGuard.from_telemetry(initial_budget)
            recovered = True
        else:
            initial_budget = budget_guard.telemetry()
            self._repository.append(
                recovery_id=recovery_id,
                scope=scope,
                event_type=ReviewRecoveryEventType.PREPARED,
                payload={
                    "request_sha256": request_sha256,
                    "initial_budget": initial_budget.model_dump(mode="json"),
                },
            )
            events = self._repository.list(scope, recovery_id)
            active_guard = budget_guard
            recovered = False
        if fault is ReviewRecoveryFaultPoint.BEFORE_REVIEW:
            raise SimulatedReviewTermination
        journal = _CallJournal(self._repository, recovery_id, scope, events, fault)
        result = await ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=_JournalReviewer(journal, reviewer),
            reviewer_definition=reviewer_definition,
            correctors={
                key: _JournalCorrector(journal, value) for key, value in correctors.items()
            },
            budget_guard=active_guard,
            cross_result_required=cross_result_required,
        )
        result_event = self._repository.append(
            recovery_id=recovery_id,
            scope=scope,
            event_type=ReviewRecoveryEventType.RESULT,
            payload={
                "result": result.model_dump(mode="json"),
                "review_manifest_sha256": result.review_manifest_sha256,
            },
        )
        if fault is ReviewRecoveryFaultPoint.BEFORE_MAIN_AGGREGATION:
            raise SimulatedReviewTermination
        return ReviewRecoveryOutcome(
            recovery_id=recovery_id,
            result=result,
            recovered=recovered,
            latest_sequence=result_event.sequence,
        )
