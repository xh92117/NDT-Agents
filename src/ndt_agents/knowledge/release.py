"""S3-09 reviewed, human-approved, atomic knowledge release workflow."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ndt_agents.approval import (
    ApprovalGrant,
    ApprovalKind,
    ApprovalService,
)
from ndt_agents.contracts.v1 import ReviewDecision, StrictModel, TenantScope
from ndt_agents.knowledge.retrieval import (
    IndexSnapshot,
    IndexStatus,
    InMemoryKnowledgeIndex,
)
from ndt_agents.knowledge.standards import (
    RightsBasis,
    StandardCatalog,
    StandardLifecycle,
)
from ndt_agents.orchestration.review import (
    ReviewWorkflowResult,
    ReviewWorkflowStatus,
    agent_result_sha256,
)

RELEASE_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
_USABLE_RIGHTS = {
    RightsBasis.PUBLIC_DOMAIN,
    RightsBasis.LICENSED,
    RightsBasis.OWNER_AUTHORIZED,
}


class KnowledgeState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    FAILED = "FAILED"


class ReleaseActionKind(StrEnum):
    WITHDRAW = "WITHDRAW"
    ROLLBACK = "ROLLBACK"


class ReleaseActionState(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class KnowledgeReleaseError(RuntimeError):
    def __init__(self, code: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(code)


class KnowledgeTransition(StrictModel):
    sequence: int = Field(ge=1)
    source: KnowledgeState | None
    target: KnowledgeState
    event: str = Field(min_length=1, max_length=128)
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() != UTC.utcoffset(
            self.occurred_at
        ):
            raise ValueError("knowledge transition time must use UTC")
        return self


class KnowledgeDiff(StrictModel):
    added_document_ids: tuple[str, ...]
    updated_document_ids: tuple[str, ...]
    removed_document_ids: tuple[str, ...]
    added_chunk_ids: tuple[str, ...]
    removed_chunk_ids: tuple[str, ...]
    diff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        expected = _canonical_hash(self.model_dump(mode="json", exclude={"diff_sha256"}))
        if self.diff_sha256 != expected:
            raise ValueError("knowledge diff hash is invalid")
        return self


class KnowledgeValidationReport(StrictModel):
    passed: bool
    codes: tuple[str, ...] = Field(max_length=100)
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_at: datetime

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.passed == bool(self.codes):
            raise ValueError("passing validation has no error codes")
        expected = _canonical_hash(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("validation report hash is invalid")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() != UTC.utcoffset(
            self.completed_at
        ):
            raise ValueError("validation completion time must use UTC")
        return self


class KnowledgeReviewEvidence(StrictModel):
    workflow_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_sha256s: tuple[str, ...] = Field(min_length=1, max_length=10)
    reviewer_versions: tuple[str, ...] = Field(min_length=1, max_length=10)
    completed_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        expected = _canonical_hash(self.model_dump(mode="json", exclude={"evidence_sha256"}))
        if self.evidence_sha256 != expected:
            raise ValueError("knowledge review evidence hash is invalid")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() != UTC.utcoffset(
            self.completed_at
        ):
            raise ValueError("review completion time must use UTC")
        return self


class KnowledgeCandidate(StrictModel):
    schema_version: Literal["1.0.0"] = RELEASE_CONTRACT_VERSION
    candidate_id: UUID
    scope: TenantScope
    task_id: UUID
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    corpus_id: str = Field(min_length=1, max_length=128)
    corpus_version: str = Field(min_length=1, max_length=64)
    index_version: str = Field(min_length=1, max_length=64)
    embedding_version: str = Field(min_length=1, max_length=128)
    base_publication_id: UUID | None = None
    snapshots: tuple[IndexSnapshot, ...] = Field(min_length=1, max_length=10_000)
    diff: KnowledgeDiff
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: KnowledgeState
    transitions: tuple[KnowledgeTransition, ...] = Field(min_length=1)
    validation: KnowledgeValidationReport | None = None
    review: KnowledgeReviewEvidence | None = None
    approval_id: UUID | None = None
    publication_id: UUID | None = None

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        expected = _canonical_hash(_candidate_identity(self))
        if self.candidate_sha256 != expected:
            raise ValueError("knowledge candidate hash is invalid")
        if [item.sequence for item in self.transitions] != list(
            range(1, len(self.transitions) + 1)
        ):
            raise ValueError("knowledge transitions must be contiguous")
        if self.transitions[-1].target is not self.state:
            raise ValueError("candidate state must match its final transition")
        if (
            self.transitions[0].source is not None
            or self.transitions[0].target is not KnowledgeState.DRAFT
        ):
            raise ValueError("candidate transition history must begin at draft creation")
        if any(
            current.source is not previous.target
            for previous, current in zip(self.transitions, self.transitions[1:], strict=False)
        ):
            raise ValueError("candidate transition history is discontinuous")
        if self.state is KnowledgeState.REVIEW_REQUIRED:
            if self.validation is None or not self.validation.passed:
                raise ValueError("review-required candidate needs passing validation")
        if self.state is KnowledgeState.FAILED:
            if self.validation is None or self.validation.passed:
                raise ValueError("failed candidate needs failed validation")
        if self.state is KnowledgeState.PUBLISHED and self.publication_id is None:
            raise ValueError("published candidate requires publication identity")
        return self


class KnowledgePublication(StrictModel):
    schema_version: Literal["1.0.0"] = RELEASE_CONTRACT_VERSION
    publication_id: UUID
    scope: TenantScope
    candidate_id: UUID
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_id: str = Field(min_length=1, max_length=128)
    corpus_version: str = Field(min_length=1, max_length=64)
    index_version: str = Field(min_length=1, max_length=64)
    state: Literal[
        KnowledgeState.PUBLISHED,
        KnowledgeState.SUPERSEDED,
        KnowledgeState.WITHDRAWN,
    ]
    snapshots: tuple[IndexSnapshot, ...] = Field(min_length=1, max_length=10_000)
    previous_publication_id: UUID | None = None
    restored_from_publication_id: UUID | None = None
    approval_grant: ApprovalGrant
    transitions: tuple[KnowledgeTransition, ...] = Field(min_length=1)
    published_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        expected = {
            KnowledgeState.PUBLISHED: IndexStatus.PUBLISHED,
            KnowledgeState.SUPERSEDED: IndexStatus.SUPERSEDED,
            KnowledgeState.WITHDRAWN: IndexStatus.WITHDRAWN,
        }[self.state]
        if any(snapshot.status is not expected for snapshot in self.snapshots):
            raise ValueError("publication and snapshot states must match")
        if self.transitions[-1].target is not self.state:
            raise ValueError("publication transition does not match state")
        if self.published_at.tzinfo is None or self.published_at.utcoffset() != UTC.utcoffset(
            self.published_at
        ):
            raise ValueError("publication time must use UTC")
        if any(
            current.source is not previous.target
            for previous, current in zip(self.transitions, self.transitions[1:], strict=False)
        ):
            raise ValueError("publication transition history is discontinuous")
        return self


class KnowledgeReleaseAction(StrictModel):
    schema_version: Literal["1.0.0"] = RELEASE_CONTRACT_VERSION
    operation_id: UUID
    scope: TenantScope
    kind: ReleaseActionKind
    corpus_id: str = Field(min_length=1, max_length=128)
    target_publication_id: UUID
    expected_current_publication_id: UUID
    action_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_id: UUID
    state: ReleaseActionState = ReleaseActionState.PENDING
    approval_grant: ApprovalGrant | None = None

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        expected = _canonical_hash(_action_identity(self))
        if self.action_sha256 != expected:
            raise ValueError("knowledge release action hash is invalid")
        if self.state is ReleaseActionState.COMPLETED and self.approval_grant is None:
            raise ValueError("completed knowledge action requires approval grant")
        return self


class InMemoryKnowledgeReleaseRepository:
    """Exact-scope release journal with local atomic index/reference swaps."""

    def __init__(self, index: InMemoryKnowledgeIndex) -> None:
        self.index = index
        self._candidates: dict[tuple[str, ...], KnowledgeCandidate] = {}
        self._publications: dict[tuple[str, ...], KnowledgePublication] = {}
        self._actions: dict[tuple[str, ...], KnowledgeReleaseAction] = {}
        self._current: dict[tuple[str, ...], UUID] = {}
        self._lock = RLock()
        self.fail_next_commit = False

    @staticmethod
    def _scope_key(scope: TenantScope) -> tuple[str, ...]:
        return (
            str(scope.tenant_id),
            str(scope.project_id),
            str(scope.user_id),
            scope.permission_version,
            *scope.role_codes,
        )

    def save_candidate(self, candidate: KnowledgeCandidate) -> KnowledgeCandidate:
        key = (*self._scope_key(candidate.scope), str(candidate.candidate_id))
        with self._lock:
            existing = self._candidates.get(key)
            if existing is not None and existing != candidate:
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_CANDIDATE_CONFLICT", "Use the original candidate or a new ID."
                )
            self._candidates[key] = candidate
        return candidate

    def update_candidate(self, candidate: KnowledgeCandidate) -> None:
        key = (*self._scope_key(candidate.scope), str(candidate.candidate_id))
        with self._lock:
            if key not in self._candidates:
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_CANDIDATE_NOT_FOUND", "Create the exact candidate first."
                )
            self._candidates[key] = candidate

    def get_candidate(self, scope: TenantScope, candidate_id: UUID) -> KnowledgeCandidate:
        item = self._candidates.get((*self._scope_key(scope), str(candidate_id)))
        if item is None:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_CANDIDATE_NOT_FOUND", "Use the exact candidate scope and ID."
            )
        return item

    def find_candidate(self, scope: TenantScope, candidate_id: UUID) -> KnowledgeCandidate | None:
        return self._candidates.get((*self._scope_key(scope), str(candidate_id)))

    def current(self, scope: TenantScope, corpus_id: str) -> KnowledgePublication | None:
        current_id = self._current.get((*self._scope_key(scope), corpus_id))
        return self.get_publication(scope, current_id) if current_id is not None else None

    def get_publication(self, scope: TenantScope, publication_id: UUID) -> KnowledgePublication:
        item = self._publications.get((*self._scope_key(scope), str(publication_id)))
        if item is None:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_PUBLICATION_NOT_FOUND", "Use a preserved publication in the exact scope."
            )
        return item

    def list_publications(self, scope: TenantScope) -> tuple[KnowledgePublication, ...]:
        prefix = self._scope_key(scope)
        return tuple(
            sorted(
                (item for key, item in self._publications.items() if key[: len(prefix)] == prefix),
                key=lambda item: (item.published_at, str(item.publication_id)),
            )
        )

    def save_action(self, action: KnowledgeReleaseAction) -> KnowledgeReleaseAction:
        key = (*self._scope_key(action.scope), str(action.operation_id))
        with self._lock:
            existing = self._actions.get(key)
            if existing is not None and existing != action:
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_ACTION_CONFLICT", "Use the original action or a new operation ID."
                )
            self._actions[key] = action
        return action

    def get_action(self, scope: TenantScope, operation_id: UUID) -> KnowledgeReleaseAction:
        item = self._actions.get((*self._scope_key(scope), str(operation_id)))
        if item is None:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_ACTION_NOT_FOUND", "Use the exact action scope and operation ID."
            )
        return item

    def commit_publication(
        self,
        candidate: KnowledgeCandidate,
        publication: KnowledgePublication,
        published_candidate: KnowledgeCandidate,
    ) -> KnowledgePublication:
        scope = candidate.scope
        current_key = (*self._scope_key(scope), candidate.corpus_id)
        publication_key = (*self._scope_key(scope), str(publication.publication_id))
        with self._lock:
            existing = self._publications.get(publication_key)
            if existing is not None:
                if existing.candidate_sha256 == candidate.candidate_sha256:
                    return existing
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_PUBLICATION_CONFLICT", "Use a new publication ID."
                )
            current_id = self._current.get(current_key)
            if current_id != candidate.base_publication_id:
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_BASE_STALE", "Rebuild and reapprove against the current publication."
                )
            previous = self.get_publication(scope, current_id) if current_id is not None else None
            if self.fail_next_commit:
                self.fail_next_commit = False
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_ATOMIC_COMMIT_FAILED", "Retry the exact approved commit."
                )
            index_batch: list[IndexSnapshot] = []
            previous_update: KnowledgePublication | None = None
            if previous is not None:
                previous_update = _publication_state(
                    previous,
                    KnowledgeState.SUPERSEDED,
                    "candidate_published",
                    publication.published_at,
                )
                new_keys = {_snapshot_key(item) for item in publication.snapshots}
                index_batch.extend(
                    item
                    for item in previous_update.snapshots
                    if _snapshot_key(item) not in new_keys
                )
            index_batch.extend(publication.snapshots)
            self.index.replace_many(tuple(index_batch))
            if previous_update is not None:
                self._publications[
                    (*self._scope_key(scope), str(previous_update.publication_id))
                ] = previous_update
            self._publications[publication_key] = publication
            self._current[current_key] = publication.publication_id
            self._candidates[(*self._scope_key(scope), str(candidate.candidate_id))] = (
                published_candidate
            )
            return publication

    def commit_withdrawal(
        self,
        action: KnowledgeReleaseAction,
        grant: ApprovalGrant,
    ) -> KnowledgePublication:
        current_key = (*self._scope_key(action.scope), action.corpus_id)
        with self._lock:
            stored = self.get_action(action.scope, action.operation_id)
            if stored.state is ReleaseActionState.COMPLETED:
                return self.get_publication(action.scope, action.target_publication_id)
            if self._current.get(current_key) != action.expected_current_publication_id:
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_CURRENT_STALE",
                    "Create a new withdrawal for the current publication.",
                )
            if self.fail_next_commit:
                self.fail_next_commit = False
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_ATOMIC_COMMIT_FAILED", "Retry the exact approved withdrawal."
                )
            current = self.get_publication(action.scope, action.target_publication_id)
            withdrawn = _publication_state(
                current, KnowledgeState.WITHDRAWN, "withdrawn", grant.resumed_at
            )
            self.index.replace_many(withdrawn.snapshots)
            self._publications[(*self._scope_key(action.scope), str(withdrawn.publication_id))] = (
                withdrawn
            )
            del self._current[current_key]
            self._actions[(*self._scope_key(action.scope), str(action.operation_id))] = (
                action.model_copy(
                    update={"state": ReleaseActionState.COMPLETED, "approval_grant": grant}
                )
            )
            return withdrawn

    def commit_rollback(
        self,
        action: KnowledgeReleaseAction,
        grant: ApprovalGrant,
        rolled_back: KnowledgePublication,
    ) -> KnowledgePublication:
        current_key = (*self._scope_key(action.scope), action.corpus_id)
        new_key = (*self._scope_key(action.scope), str(rolled_back.publication_id))
        with self._lock:
            stored = self.get_action(action.scope, action.operation_id)
            if stored.state is ReleaseActionState.COMPLETED:
                return self.get_publication(action.scope, rolled_back.publication_id)
            if self._current.get(current_key) != action.expected_current_publication_id:
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_CURRENT_STALE", "Create a new rollback from the current publication."
                )
            if self.fail_next_commit:
                self.fail_next_commit = False
                raise KnowledgeReleaseError(
                    "KNOWLEDGE_ATOMIC_COMMIT_FAILED", "Retry the exact approved rollback."
                )
            current = self.get_publication(action.scope, action.expected_current_publication_id)
            superseded = _publication_state(
                current,
                KnowledgeState.SUPERSEDED,
                "rolled_back",
                rolled_back.published_at,
            )
            restored_keys = {_snapshot_key(item) for item in rolled_back.snapshots}
            index_batch = [
                item for item in superseded.snapshots if _snapshot_key(item) not in restored_keys
            ]
            index_batch.extend(rolled_back.snapshots)
            self.index.replace_many(tuple(index_batch))
            self._publications[(*self._scope_key(action.scope), str(superseded.publication_id))] = (
                superseded
            )
            self._publications[new_key] = rolled_back
            self._current[current_key] = rolled_back.publication_id
            self._actions[(*self._scope_key(action.scope), str(action.operation_id))] = (
                action.model_copy(
                    update={"state": ReleaseActionState.COMPLETED, "approval_grant": grant}
                )
            )
            return rolled_back


class KnowledgeReleaseService:
    def __init__(
        self,
        repository: InMemoryKnowledgeReleaseRepository,
        standards: StandardCatalog,
        approvals: ApprovalService,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._standards = standards
        self._approvals = approvals
        self._clock = clock

    def create_candidate(
        self,
        *,
        candidate_id: UUID,
        scope: TenantScope,
        task_id: UUID,
        request_id: str,
        corpus_id: str,
        corpus_version: str,
        index_version: str,
        embedding_version: str,
        snapshots: tuple[IndexSnapshot, ...],
        base_publication_id: UUID | None,
    ) -> KnowledgeCandidate:
        if any(snapshot.scope != scope for snapshot in snapshots):
            raise KnowledgeReleaseError(
                "KNOWLEDGE_SCOPE_DENIED", "Use only exact-scope candidate snapshots."
            )
        existing = self._repository.find_candidate(scope, candidate_id)
        if existing is not None:
            requested_identity = {
                **_candidate_identity(existing),
                "task_id": str(task_id),
                "request_id": request_id,
                "corpus_id": corpus_id,
                "corpus_version": corpus_version,
                "index_version": index_version,
                "embedding_version": embedding_version,
                "base_publication_id": str(base_publication_id) if base_publication_id else None,
                "snapshots": [item.model_dump(mode="json") for item in snapshots],
            }
            if _canonical_hash(requested_identity) == existing.candidate_sha256:
                return existing
            raise KnowledgeReleaseError(
                "KNOWLEDGE_CANDIDATE_CONFLICT", "Use the original candidate or a new ID."
            )
        current = self._repository.current(scope, corpus_id)
        current_id = current.publication_id if current is not None else None
        if current_id != base_publication_id:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_BASE_STALE", "Rebuild the candidate from the current publication."
            )
        diff = _knowledge_diff(current.snapshots if current else (), snapshots)
        now = self._clock()
        values: dict[str, Any] = {
            "candidate_id": candidate_id,
            "scope": scope,
            "task_id": task_id,
            "request_id": request_id,
            "corpus_id": corpus_id,
            "corpus_version": corpus_version,
            "index_version": index_version,
            "embedding_version": embedding_version,
            "base_publication_id": base_publication_id,
            "snapshots": snapshots,
            "diff": diff,
        }
        identity = {
            "schema_version": RELEASE_CONTRACT_VERSION,
            "candidate_id": str(candidate_id),
            "scope": scope.model_dump(mode="json"),
            "task_id": str(task_id),
            "request_id": request_id,
            "corpus_id": corpus_id,
            "corpus_version": corpus_version,
            "index_version": index_version,
            "embedding_version": embedding_version,
            "base_publication_id": str(base_publication_id) if base_publication_id else None,
            "snapshots": [item.model_dump(mode="json") for item in snapshots],
            "diff": diff.model_dump(mode="json"),
        }
        values["candidate_sha256"] = _canonical_hash(identity)
        candidate = KnowledgeCandidate(
            **values,
            state=KnowledgeState.DRAFT,
            transitions=(
                KnowledgeTransition(
                    sequence=1,
                    source=None,
                    target=KnowledgeState.DRAFT,
                    event="candidate_created",
                    occurred_at=now,
                ),
            ),
        )
        return self._repository.save_candidate(candidate)

    def validate(self, scope: TenantScope, candidate_id: UUID) -> KnowledgeCandidate:
        candidate = self._repository.get_candidate(scope, candidate_id)
        if candidate.state is not KnowledgeState.DRAFT:
            return candidate
        validating = _candidate_transition(
            candidate, KnowledgeState.VALIDATING, "validation_started", self._clock()
        )
        self._repository.update_candidate(validating)
        codes = self._validation_codes(validating)
        report_draft = KnowledgeValidationReport.model_construct(
            passed=not codes,
            codes=tuple(codes),
            candidate_sha256=candidate.candidate_sha256,
            report_sha256="0" * 64,
            completed_at=self._clock(),
        )
        report_payload = report_draft.model_dump(mode="json", exclude={"report_sha256"})
        report = KnowledgeValidationReport.model_validate(
            {**report_payload, "report_sha256": _canonical_hash(report_payload)}
        )
        target = KnowledgeState.REVIEW_REQUIRED if report.passed else KnowledgeState.FAILED
        completed = _candidate_transition(
            validating,
            target,
            "validation_passed" if report.passed else "validation_failed",
            self._clock(),
            validation=report,
        )
        self._repository.update_candidate(completed)
        return completed

    def record_review(
        self,
        scope: TenantScope,
        candidate_id: UUID,
        workflow: ReviewWorkflowResult,
    ) -> KnowledgeCandidate:
        candidate = self._repository.get_candidate(scope, candidate_id)
        if candidate.state is not KnowledgeState.REVIEW_REQUIRED or candidate.validation is None:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_REVIEW_STATE_INVALID", "Pass automated validation before review."
            )
        if (
            workflow.scope != scope
            or workflow.task_id != candidate.task_id
            or workflow.status is not ReviewWorkflowStatus.APPROVED
            or not workflow.aggregation_ready
            or workflow.skipped_assignment_ids
            or len(workflow.assignments) != 1
        ):
            raise KnowledgeReleaseError(
                "KNOWLEDGE_REVIEW_INVALID", "Provide one exact-scope approved S1-09 workflow."
            )
        assignment = workflow.assignments[0]
        data = assignment.current_result.structured_data
        if (
            assignment.decision is not ReviewDecision.PASS
            or not assignment.review_history
            or assignment.review_history[-1].decision is not ReviewDecision.PASS
            or data.get("knowledge_candidate_id") != str(candidate.candidate_id)
            or data.get("knowledge_candidate_sha256") != candidate.candidate_sha256
            or data.get("knowledge_validation_sha256") != candidate.validation.report_sha256
        ):
            raise KnowledgeReleaseError(
                "KNOWLEDGE_REVIEW_BINDING_INVALID",
                "Review the exact candidate and validation report through S1-09.",
            )
        review_sha256s = tuple(
            _canonical_hash(item.model_dump(mode="json")) for item in assignment.review_history
        )
        reviewer_versions = tuple(
            dict.fromkeys(item.reviewer_version for item in assignment.review_history)
        )
        evidence_draft = KnowledgeReviewEvidence.model_construct(
            workflow_manifest_sha256=workflow.review_manifest_sha256,
            reviewed_result_sha256=agent_result_sha256(assignment.current_result),
            review_sha256s=review_sha256s,
            reviewer_versions=reviewer_versions,
            completed_at=workflow.completed_at,
            evidence_sha256="0" * 64,
        )
        evidence_payload = evidence_draft.model_dump(mode="json", exclude={"evidence_sha256"})
        evidence = KnowledgeReviewEvidence.model_validate(
            {**evidence_payload, "evidence_sha256": _canonical_hash(evidence_payload)}
        )
        updated = candidate.model_copy(update={"review": evidence})
        self._repository.update_candidate(updated)
        return updated

    def request_publish_approval(
        self,
        *,
        scope: TenantScope,
        candidate_id: UUID,
        approval_id: UUID,
    ) -> KnowledgeCandidate:
        candidate = self._repository.get_candidate(scope, candidate_id)
        if candidate.state is not KnowledgeState.REVIEW_REQUIRED or candidate.review is None:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_REVIEW_REQUIRED", "Complete exact independent review before approval."
            )
        if candidate.approval_id not in {None, approval_id}:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_APPROVAL_CONFLICT", "Use the original approval checkpoint."
            )
        self._approvals.create(
            approval_id=approval_id,
            scope=scope,
            task_id=candidate.task_id,
            request_id=candidate.request_id,
            kind=ApprovalKind.KNOWLEDGE,
            action="knowledge.publish",
            target_type="knowledge_candidate",
            target_id=candidate.candidate_id,
            target_version=candidate.corpus_version,
            candidate_sha256=candidate.candidate_sha256,
            preview={
                "candidate_id": str(candidate.candidate_id),
                "candidate_sha256": candidate.candidate_sha256,
                "validation_sha256": candidate.validation.report_sha256
                if candidate.validation
                else None,
                "review_sha256": candidate.review.evidence_sha256,
                "diff_sha256": candidate.diff.diff_sha256,
            },
        )
        updated = candidate.model_copy(update={"approval_id": approval_id})
        self._repository.update_candidate(updated)
        return updated

    def publish(
        self,
        *,
        scope: TenantScope,
        candidate_id: UUID,
        publication_id: UUID,
        resume_id: UUID,
    ) -> KnowledgePublication:
        candidate = self._repository.get_candidate(scope, candidate_id)
        if (
            candidate.state is KnowledgeState.PUBLISHED
            and candidate.publication_id == publication_id
        ):
            return self._repository.get_publication(scope, publication_id)
        if (
            candidate.state is not KnowledgeState.REVIEW_REQUIRED
            or candidate.review is None
            or candidate.approval_id is None
        ):
            raise KnowledgeReleaseError(
                "KNOWLEDGE_PUBLICATION_NOT_READY",
                "Complete validation, review, and approval before publication.",
            )
        self._require_checkpoint(
            scope,
            candidate.approval_id,
            action="knowledge.publish",
            target_id=candidate.candidate_id,
            candidate_sha256=candidate.candidate_sha256,
        )
        current = self._repository.current(scope, candidate.corpus_id)
        current_id = current.publication_id if current is not None else None
        if current_id != candidate.base_publication_id:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_BASE_STALE", "Rebuild and reapprove against the current publication."
            )
        grant = self._approvals.resume(
            resume_id=resume_id,
            scope=scope,
            approval_id=candidate.approval_id,
            expected_candidate_sha256=candidate.candidate_sha256,
        )
        now = self._clock()
        snapshots = tuple(
            IndexSnapshot.model_validate({**snapshot.model_dump(), "status": IndexStatus.PUBLISHED})
            for snapshot in candidate.snapshots
        )
        publication = KnowledgePublication(
            publication_id=publication_id,
            scope=scope,
            candidate_id=candidate.candidate_id,
            candidate_sha256=candidate.candidate_sha256,
            corpus_id=candidate.corpus_id,
            corpus_version=candidate.corpus_version,
            index_version=candidate.index_version,
            state=KnowledgeState.PUBLISHED,
            snapshots=snapshots,
            previous_publication_id=candidate.base_publication_id,
            approval_grant=grant,
            transitions=(
                KnowledgeTransition(
                    sequence=1,
                    source=KnowledgeState.REVIEW_REQUIRED,
                    target=KnowledgeState.PUBLISHED,
                    event="human_approved_publication",
                    occurred_at=now,
                ),
            ),
            published_at=now,
        )
        published_candidate = _candidate_transition(
            candidate,
            KnowledgeState.PUBLISHED,
            "publication_committed",
            now,
            publication_id=publication_id,
        )
        return self._repository.commit_publication(candidate, publication, published_candidate)

    def request_action(
        self,
        *,
        scope: TenantScope,
        operation_id: UUID,
        approval_id: UUID,
        kind: ReleaseActionKind,
        target_publication_id: UUID,
        request_id: str,
    ) -> KnowledgeReleaseAction:
        target = self._repository.get_publication(scope, target_publication_id)
        current = self._repository.current(scope, target.corpus_id)
        if current is None:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_CURRENT_MISSING", "Publish a current version before this action."
            )
        if kind is ReleaseActionKind.WITHDRAW and current.publication_id != target_publication_id:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_CURRENT_STALE", "Withdraw only the current publication."
            )
        if kind is ReleaseActionKind.ROLLBACK and current.publication_id == target_publication_id:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_ROLLBACK_TARGET_CURRENT", "Choose a preserved prior publication."
            )
        values = {
            "operation_id": operation_id,
            "scope": scope,
            "kind": kind,
            "corpus_id": target.corpus_id,
            "target_publication_id": target_publication_id,
            "expected_current_publication_id": current.publication_id,
        }
        action_identity = {
            "operation_id": str(operation_id),
            "scope": scope.model_dump(mode="json"),
            "kind": kind.value,
            "corpus_id": target.corpus_id,
            "target_publication_id": str(target_publication_id),
            "expected_current_publication_id": str(current.publication_id),
        }
        action_hash = _canonical_hash(action_identity)
        action = KnowledgeReleaseAction.model_validate(
            {
                **values,
                "action_sha256": action_hash,
                "approval_id": approval_id,
            }
        )
        stored = self._repository.save_action(action)
        verb = "withdraw" if kind is ReleaseActionKind.WITHDRAW else "rollback"
        self._approvals.create(
            approval_id=approval_id,
            scope=scope,
            task_id=target.approval_grant.task_id,
            request_id=request_id,
            kind=ApprovalKind.KNOWLEDGE,
            action=f"knowledge.{verb}",
            target_type="knowledge_operation",
            target_id=operation_id,
            target_version=target.corpus_version,
            candidate_sha256=action_hash,
            preview={
                "operation_id": str(operation_id),
                "kind": kind.value,
                "target_publication_id": str(target_publication_id),
                "expected_current_publication_id": str(current.publication_id),
                "action_sha256": action_hash,
            },
        )
        return stored

    def withdraw(
        self,
        *,
        scope: TenantScope,
        operation_id: UUID,
        resume_id: UUID,
    ) -> KnowledgePublication:
        action = self._repository.get_action(scope, operation_id)
        if action.kind is not ReleaseActionKind.WITHDRAW:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_ACTION_KIND_MISMATCH", "Use a withdrawal operation."
            )
        if action.state is ReleaseActionState.COMPLETED:
            return self._repository.get_publication(scope, action.target_publication_id)
        self._require_current(action)
        self._require_checkpoint(
            scope,
            action.approval_id,
            action="knowledge.withdraw",
            target_id=action.operation_id,
            candidate_sha256=action.action_sha256,
        )
        grant = self._approvals.resume(
            resume_id=resume_id,
            scope=scope,
            approval_id=action.approval_id,
            expected_candidate_sha256=action.action_sha256,
        )
        return self._repository.commit_withdrawal(action, grant)

    def rollback(
        self,
        *,
        scope: TenantScope,
        operation_id: UUID,
        resume_id: UUID,
    ) -> KnowledgePublication:
        action = self._repository.get_action(scope, operation_id)
        if action.kind is not ReleaseActionKind.ROLLBACK:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_ACTION_KIND_MISMATCH", "Use a rollback operation."
            )
        if action.state is ReleaseActionState.COMPLETED:
            return self._repository.get_publication(scope, operation_id)
        self._require_current(action)
        target = self._repository.get_publication(scope, action.target_publication_id)
        self._require_checkpoint(
            scope,
            action.approval_id,
            action="knowledge.rollback",
            target_id=action.operation_id,
            candidate_sha256=action.action_sha256,
        )
        grant = self._approvals.resume(
            resume_id=resume_id,
            scope=scope,
            approval_id=action.approval_id,
            expected_candidate_sha256=action.action_sha256,
        )
        now = self._clock()
        restored = KnowledgePublication(
            publication_id=operation_id,
            scope=scope,
            candidate_id=target.candidate_id,
            candidate_sha256=target.candidate_sha256,
            corpus_id=target.corpus_id,
            corpus_version=target.corpus_version,
            index_version=target.index_version,
            state=KnowledgeState.PUBLISHED,
            snapshots=tuple(
                IndexSnapshot.model_validate(
                    {**snapshot.model_dump(), "status": IndexStatus.PUBLISHED}
                )
                for snapshot in target.snapshots
            ),
            previous_publication_id=action.expected_current_publication_id,
            restored_from_publication_id=target.publication_id,
            approval_grant=grant,
            transitions=(
                KnowledgeTransition(
                    sequence=1,
                    source=target.state,
                    target=KnowledgeState.PUBLISHED,
                    event="human_approved_rollback",
                    occurred_at=now,
                ),
            ),
            published_at=now,
        )
        return self._repository.commit_rollback(action, grant, restored)

    def _validation_codes(self, candidate: KnowledgeCandidate) -> tuple[str, ...]:
        codes: list[str] = []
        current = self._repository.current(candidate.scope, candidate.corpus_id)
        current_id = current.publication_id if current is not None else None
        if current_id != candidate.base_publication_id:
            codes.append("KNOWLEDGE_BASE_STALE")
        document_ids = [snapshot.document_id for snapshot in candidate.snapshots]
        if len(set(document_ids)) != len(document_ids):
            codes.append("KNOWLEDGE_DOCUMENT_DUPLICATE")
        chunk_ids = [
            record.chunk_id for snapshot in candidate.snapshots for record in snapshot.records
        ]
        if len(set(chunk_ids)) != len(chunk_ids):
            codes.append("KNOWLEDGE_CHUNK_DUPLICATE")
        for snapshot in candidate.snapshots:
            if snapshot.scope != candidate.scope:
                codes.append("KNOWLEDGE_SCOPE_DENIED")
            if snapshot.status is not IndexStatus.DRAFT:
                codes.append("KNOWLEDGE_SNAPSHOT_NOT_DRAFT")
            if (
                snapshot.corpus_id != candidate.corpus_id
                or snapshot.corpus_version != candidate.corpus_version
                or snapshot.index_version != candidate.index_version
                or snapshot.embedding_version != candidate.embedding_version
            ):
                codes.append("KNOWLEDGE_VERSION_MISMATCH")
            standard_id = snapshot.metadata.get("standard_version_id")
            standard = (
                self._standards.get(candidate.scope, standard_id)
                if standard_id is not None
                else None
            )
            if standard is None:
                codes.append("KNOWLEDGE_STANDARD_UNREGISTERED")
            elif (
                standard.lifecycle not in {StandardLifecycle.CURRENT, StandardLifecycle.RESTRICTED}
                or standard.rights_basis not in _USABLE_RIGHTS
                or not standard.rights_reference
                or not set(standard.required_roles).issubset(candidate.scope.role_codes)
                or self._standards.is_superseded(candidate.scope, standard.version_id)
            ):
                codes.append("KNOWLEDGE_STANDARD_UNUSABLE")
        return tuple(dict.fromkeys(codes))

    def _require_checkpoint(
        self,
        scope: TenantScope,
        approval_id: UUID,
        *,
        action: str,
        target_id: UUID,
        candidate_sha256: str,
    ) -> None:
        status = self._approvals.status(scope, approval_id)
        candidate = status.candidate
        if (
            candidate.kind is not ApprovalKind.KNOWLEDGE
            or candidate.action != action
            or candidate.target_id != target_id
            or candidate.candidate_sha256 != candidate_sha256
        ):
            raise KnowledgeReleaseError(
                "KNOWLEDGE_APPROVAL_BINDING_INVALID",
                "Use the exact action-specific knowledge approval checkpoint.",
            )

    def _require_current(self, action: KnowledgeReleaseAction) -> None:
        current = self._repository.current(action.scope, action.corpus_id)
        if current is None or current.publication_id != action.expected_current_publication_id:
            raise KnowledgeReleaseError(
                "KNOWLEDGE_CURRENT_STALE",
                "Create and approve a new action for the current version.",
            )


def _candidate_identity(candidate: KnowledgeCandidate) -> dict[str, Any]:
    return {
        "schema_version": candidate.schema_version,
        "candidate_id": str(candidate.candidate_id),
        "scope": candidate.scope.model_dump(mode="json"),
        "task_id": str(candidate.task_id),
        "request_id": candidate.request_id,
        "corpus_id": candidate.corpus_id,
        "corpus_version": candidate.corpus_version,
        "index_version": candidate.index_version,
        "embedding_version": candidate.embedding_version,
        "base_publication_id": str(candidate.base_publication_id)
        if candidate.base_publication_id
        else None,
        "snapshots": [item.model_dump(mode="json") for item in candidate.snapshots],
        "diff": candidate.diff.model_dump(mode="json"),
    }


def _action_identity(action: KnowledgeReleaseAction) -> dict[str, Any]:
    return {
        "operation_id": str(action.operation_id),
        "scope": action.scope.model_dump(mode="json"),
        "kind": action.kind.value,
        "corpus_id": action.corpus_id,
        "target_publication_id": str(action.target_publication_id),
        "expected_current_publication_id": str(action.expected_current_publication_id),
    }


def _knowledge_diff(
    previous: tuple[IndexSnapshot, ...], candidate: tuple[IndexSnapshot, ...]
) -> KnowledgeDiff:
    old_documents = {item.document_id: item for item in previous}
    new_documents = {item.document_id: item for item in candidate}
    added_documents = tuple(sorted(set(new_documents) - set(old_documents)))
    removed_documents = tuple(sorted(set(old_documents) - set(new_documents)))
    updated_documents = tuple(
        sorted(
            document_id
            for document_id in set(old_documents) & set(new_documents)
            if old_documents[document_id].document_sha256
            != new_documents[document_id].document_sha256
        )
    )
    old_chunks = {record.chunk_id for item in previous for record in item.records}
    new_chunks = {record.chunk_id for item in candidate for record in item.records}
    values = {
        "added_document_ids": added_documents,
        "updated_document_ids": updated_documents,
        "removed_document_ids": removed_documents,
        "added_chunk_ids": tuple(sorted(new_chunks - old_chunks)),
        "removed_chunk_ids": tuple(sorted(old_chunks - new_chunks)),
    }
    return KnowledgeDiff(**values, diff_sha256=_canonical_hash(values))


def _candidate_transition(
    candidate: KnowledgeCandidate,
    target: KnowledgeState,
    event: str,
    occurred_at: datetime,
    **updates: Any,
) -> KnowledgeCandidate:
    transition = KnowledgeTransition(
        sequence=len(candidate.transitions) + 1,
        source=candidate.state,
        target=target,
        event=event,
        occurred_at=occurred_at,
    )
    return candidate.model_copy(
        update={
            "state": target,
            "transitions": (*candidate.transitions, transition),
            **updates,
        }
    )


def _publication_state(
    publication: KnowledgePublication,
    target: Literal[KnowledgeState.SUPERSEDED, KnowledgeState.WITHDRAWN],
    event: str,
    occurred_at: datetime,
) -> KnowledgePublication:
    status = (
        IndexStatus.SUPERSEDED if target is KnowledgeState.SUPERSEDED else IndexStatus.WITHDRAWN
    )
    snapshots = tuple(
        IndexSnapshot.model_validate({**snapshot.model_dump(), "status": status})
        for snapshot in publication.snapshots
    )
    transition = KnowledgeTransition(
        sequence=len(publication.transitions) + 1,
        source=publication.state,
        target=target,
        event=event,
        occurred_at=occurred_at,
    )
    return publication.model_copy(
        update={
            "state": target,
            "snapshots": snapshots,
            "transitions": (*publication.transitions, transition),
        }
    )


def _snapshot_key(snapshot: IndexSnapshot) -> tuple[str, str, str, str]:
    return (
        snapshot.corpus_id,
        snapshot.corpus_version,
        snapshot.index_version,
        snapshot.document_id,
    )


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
