"""S3-09 reviewed and human-approved knowledge release tests."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest

from ndt_agents.approval import (
    ApprovalActor,
    ApprovalError,
    ApprovalService,
    InMemoryApprovalRepository,
    default_approval_policy,
)
from ndt_agents.contracts.v1 import (
    AgentResult,
    AgentStatus,
    ApprovalOutcome,
    Issue,
    ReviewDecision,
    ReviewResult,
    TaskContext,
    TenantScope,
)
from ndt_agents.knowledge.normalization import LocatorType
from ndt_agents.knowledge.release import (
    InMemoryKnowledgeReleaseRepository,
    KnowledgeCandidate,
    KnowledgeReleaseError,
    KnowledgeReleaseService,
    KnowledgeState,
    ReleaseActionKind,
)
from ndt_agents.knowledge.retrieval import (
    DeterministicHashEmbedding,
    IndexRecord,
    IndexSnapshot,
    IndexStatus,
    InMemoryKnowledgeIndex,
    tokenize,
)
from ndt_agents.knowledge.standards import (
    RightsBasis,
    StandardCatalog,
    StandardLifecycle,
    StandardVersionDraft,
    finalize_standard_version,
)
from ndt_agents.observability import (
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import (
    AgentDefinition,
    ChildAgentKind,
    ChildInput,
    ChildTaskContext,
)
from ndt_agents.orchestration.models import DispatchPlan, ProfessionalAssignment, RouteKind
from ndt_agents.orchestration.registry import AgentRegistry
from ndt_agents.orchestration.review import (
    ReviewContext,
    ReviewerDefinition,
    ReviewWorkflow,
    ReviewWorkflowResult,
)
from ndt_agents.orchestration.scheduler import TaskScheduler

ROOT = Path(__file__).resolve().parents[2]
TASK_TEMPLATE = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
TENANT = UUID("00000000-0000-4000-8000-000000000101")
PROJECT = UUID("00000000-0000-4000-8000-000000000201")
REQUESTER = UUID("00000000-0000-4000-8000-000000000301")
APPROVER = UUID("00000000-0000-4000-8000-000000000302")
TASK_ID = UUID("00000000-0000-4000-8000-000000000401")
REVIEW_NAMESPACE = UUID("00000000-0000-4000-8000-000000000402")
EMBEDDING = DeterministicHashEmbedding(dimension=64)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def scope(
    *,
    user: UUID = REQUESTER,
    roles: tuple[str, ...] = ("knowledge-owner",),
    permission: str = "permissions-1",
) -> TenantScope:
    return TenantScope(
        tenant_id=TENANT,
        project_id=PROJECT,
        user_id=user,
        role_codes=roles,
        permission_version=permission,
    )


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 25, 2, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self.now
        self.now += timedelta(seconds=1)
        return current


class Runtime:
    def __init__(self) -> None:
        self.clock = Clock()
        self.index = InMemoryKnowledgeIndex()
        self.repository = InMemoryKnowledgeReleaseRepository(self.index)
        self.catalog = StandardCatalog()
        self.standard = finalize_standard_version(
            StandardVersionDraft(
                scope=scope(),
                standard_type="NATIONAL",
                standard_identifier="GB-T-RELEASE",
                edition="2026",
                title="Knowledge release test standard",
                publication_date=date(2026, 1, 1),
                effective_date=date(2026, 6, 1),
                regions=("CN",),
                lifecycle=StandardLifecycle.CURRENT,
                rights_basis=RightsBasis.LICENSED,
                rights_reference="rights://test/release",
            )
        )
        self.catalog.register(scope(), self.standard)
        self.audit = InMemoryAuditRepository()
        self.traces = TraceService(
            service_name="knowledge-release-test",
            service_version="1.0.0",
            exporter=InMemorySpanExporter(),
        )
        self.approvals = ApprovalService(
            InMemoryApprovalRepository(),
            default_approval_policy(),
            AuditService(self.audit, self.traces),
            clock=self.clock,
        )
        self.service = KnowledgeReleaseService(
            self.repository, self.catalog, self.approvals, clock=self.clock
        )

    def close(self) -> None:
        self.traces.shutdown()

    def approve(self, approval_id: UUID, candidate_sha256: str) -> None:
        with self.traces.start_span("knowledge.approval.decide"):
            self.approvals.decide(
                decision_id=uuid4(),
                scope=scope(),
                approval_id=approval_id,
                expected_candidate_sha256=candidate_sha256,
                actor=ApprovalActor(scope=scope(user=APPROVER, roles=("QUALIFIED_APPROVER",))),
                outcome=ApprovalOutcome.APPROVED,
                reason="Candidate, review, rights, and hashes verified.",
            )

    def request_publish(self, candidate: KnowledgeCandidate, approval_id: UUID) -> None:
        with self.traces.start_span("knowledge.approval.create"):
            self.service.request_publish_approval(
                scope=scope(), candidate_id=candidate.candidate_id, approval_id=approval_id
            )

    def request_action(
        self,
        kind: ReleaseActionKind,
        target_publication_id: UUID,
        *,
        operation_id: UUID,
        approval_id: UUID,
    ) -> str:
        with self.traces.start_span("knowledge.action.create"):
            action = self.service.request_action(
                scope=scope(),
                operation_id=operation_id,
                approval_id=approval_id,
                kind=kind,
                target_publication_id=target_publication_id,
                request_id=f"release-{operation_id}",
            )
        return action.action_sha256


def snapshot(
    runtime: Runtime,
    key: str,
    text: str,
    *,
    corpus_version: str,
    owner: TenantScope | None = None,
    status: IndexStatus = IndexStatus.DRAFT,
    standard_id: str | None = None,
) -> IndexSnapshot:
    actual_scope = owner or scope()
    chunk_id = digest(f"chunk:{key}:{text}")
    vector = EMBEDDING.embed((text,))[0]
    record = IndexRecord(
        chunk_id=chunk_id,
        document_id=digest(f"document:{key}"),
        document_sha256=digest(f"document:{key}:{text}"),
        artifact_id="00000000-0000-4000-8000-000000000001",
        artifact_version="source-v1",
        source_sha256=digest(f"source:{key}"),
        source_title=f"Source {key}",
        source_media_type="application/pdf",
        parser_name="mineru",
        parser_version="3.0.0",
        normalizer_version="1.0.0",
        page_index=0,
        section_path=("Scope",),
        locator_type=LocatorType.PAGE,
        locator="page:1",
        text=text,
        content_sha256=digest(text),
        tokens=tokenize(text),
        vector=vector,
    )
    return IndexSnapshot(
        snapshot_id=digest(f"snapshot:{key}:{text}:{corpus_version}"),
        scope=actual_scope,
        corpus_id="ndt-standards",
        corpus_version=corpus_version,
        index_version="index-v1",
        status=status,
        document_id=record.document_id,
        document_sha256=record.document_sha256,
        embedding_version=EMBEDDING.version,
        embedding_dimension=EMBEDDING.dimension,
        metadata={"standard_version_id": standard_id or runtime.standard.version_id},
        records=(record,),
    )


def create(
    runtime: Runtime,
    snapshots: tuple[IndexSnapshot, ...],
    *,
    candidate_id: UUID | None = None,
    base: UUID | None = None,
    corpus_version: str = "corpus-v1",
) -> KnowledgeCandidate:
    return runtime.service.create_candidate(
        candidate_id=candidate_id or uuid4(),
        scope=scope(),
        task_id=TASK_ID,
        request_id=f"candidate-{corpus_version}",
        corpus_id="ndt-standards",
        corpus_version=corpus_version,
        index_version="index-v1",
        embedding_version=EMBEDDING.version,
        snapshots=snapshots,
        base_publication_id=base,
    )


class CandidateExecutor:
    def __init__(self, candidate: KnowledgeCandidate, *, stale_hash: bool = False) -> None:
        self.candidate = candidate
        self.stale_hash = stale_hash

    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]:
        validation = self.candidate.validation
        assert validation is not None
        candidate_hash = "f" * 64 if self.stale_hash else self.candidate.candidate_sha256
        return AgentResult(
            task_id=context.parent_task_id,
            run_id=context.run_id,
            status=AgentStatus.SUCCESS,
            summary="Independent Knowledge Agent candidate validation recommendation.",
            structured_data={
                "knowledge_candidate_id": str(self.candidate.candidate_id),
                "knowledge_candidate_sha256": candidate_hash,
                "knowledge_validation_sha256": validation.report_sha256,
                "recommendation": "PUBLISH",
            },
            artifacts=(),
            evidence=(),
            confidence=1,
            issues=(),
            retryable=False,
            completed_at=datetime(2026, 8, 25, tzinfo=UTC),
        ).model_dump(mode="json")


class Reviewer:
    def __init__(self, decision: ReviewDecision = ReviewDecision.PASS) -> None:
        self.decision = decision

    async def review(self, context: ReviewContext) -> Mapping[str, Any]:
        findings: tuple[Issue, ...] = ()
        if self.decision is not ReviewDecision.PASS:
            findings = (
                Issue.model_validate(
                    {
                        "code": "KNOWLEDGE_REVIEW_FAILED",
                        "severity": "ERROR",
                        "message": "Candidate evidence is not publishable.",
                        "next_action": "Repair the candidate and run independent review again.",
                    }
                ),
            )
        return ReviewResult(
            review_id=uuid5(REVIEW_NAMESPACE, context.review_target_sha256),
            task_id=context.task_id,
            target_run_id=context.review_target_run_id,
            target_sha256=context.review_target_sha256,
            reviewer_version=context.reviewer_version,
            decision=self.decision,
            findings=findings,
            correction_count=context.correction_count,
            completed_at=datetime(2026, 8, 25, tzinfo=UTC),
        ).model_dump(mode="json")


def review_workflow(
    candidate: KnowledgeCandidate,
    *,
    stale_hash: bool = False,
    decision: ReviewDecision = ReviewDecision.PASS,
) -> ReviewWorkflowResult:
    task = TASK_TEMPLATE.model_copy(
        update={
            "task_id": TASK_ID,
            "scope": scope(),
            "task_class": "P3",
            "budget": default_budget_policy("P3"),
            "review_checklist": ("Validate schema, evidence, rights, and candidate hashes.",),
            "context_manifest_sha256": "0" * 64,
        }
    )
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset(),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="general-model-1",
            ),
            AgentDefinition(
                agent_type="knowledge_validator",
                kind=ChildAgentKind.PROFESSIONAL,
                allowed_tools=frozenset(),
                skill_version="knowledge-validator-1",
                prompt_version="knowledge-review-1",
                model_version="review-model-1",
            ),
        )
    )
    dispatch = DispatchPlan(
        task_id=TASK_ID,
        route=RouteKind.ONE_PROFESSIONAL_SYNC_REVIEW,
        general_agent=False,
        professional_assignments=(
            ProfessionalAssignment(
                assignment_id="knowledge-review",
                agent_type="knowledge_validator",
                depends_on=(),
            ),
        ),
        asynchronous=False,
        review_required=True,
        human_required=False,
    )
    contexts = ChildContextFactory(registry).prepare(
        task,
        dispatch,
        professional_inputs=(
            ChildInput(
                assignment_id="knowledge-review",
                goal="Independently review the exact knowledge candidate.",
                success_criteria=("Return an exact hash-bound recommendation.",),
            ),
        ),
    )
    guard = BudgetGuard(contexts[0].budget)
    schedule = asyncio.run(
        TaskScheduler(budget_guard=guard).run_sync(
            contexts,
            {"knowledge-review": CandidateExecutor(candidate, stale_hash=stale_hash)},
        )
    )
    return asyncio.run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=Reviewer(decision),
            reviewer_definition=ReviewerDefinition(
                reviewer_version="knowledge-reviewer-1",
                prompt_version="knowledge-review-prompt-1",
                model_version="review-model-1",
            ),
            correctors={},
            budget_guard=guard,
        )
    )


def validate_and_review(runtime: Runtime, candidate: KnowledgeCandidate) -> KnowledgeCandidate:
    validated = runtime.service.validate(scope(), candidate.candidate_id)
    assert validated.state is KnowledgeState.REVIEW_REQUIRED
    return runtime.service.record_review(
        scope(), validated.candidate_id, review_workflow(validated)
    )


def publish(
    runtime: Runtime,
    snapshots: tuple[IndexSnapshot, ...],
    *,
    corpus_version: str,
    base: UUID | None = None,
) -> tuple[KnowledgeCandidate, UUID]:
    reviewed = validate_and_review(
        runtime,
        create(
            runtime,
            snapshots,
            base=base,
            corpus_version=corpus_version,
        ),
    )
    approval_id = uuid4()
    runtime.request_publish(reviewed, approval_id)
    runtime.approve(approval_id, reviewed.candidate_sha256)
    publication_id = uuid4()
    with runtime.traces.start_span("knowledge.publish"):
        runtime.service.publish(
            scope=scope(),
            candidate_id=reviewed.candidate_id,
            publication_id=publication_id,
            resume_id=uuid4(),
        )
    return reviewed, publication_id


def test_candidate_diff_identity_idempotency_conflict_and_scope_denial() -> None:
    runtime = Runtime()
    candidate_id = uuid4()
    first_snapshot = snapshot(runtime, "A", "first crack rule", corpus_version="corpus-v1")
    try:
        first = create(runtime, (first_snapshot,), candidate_id=candidate_id)
        replay = create(runtime, (first_snapshot,), candidate_id=candidate_id)

        assert replay == first
        assert first.diff.added_document_ids == (first_snapshot.document_id,)
        assert first.diff.added_chunk_ids == (first_snapshot.records[0].chunk_id,)
        assert len(first.candidate_sha256) == 64
        with pytest.raises(KnowledgeReleaseError, match="CANDIDATE_CONFLICT"):
            create(
                runtime,
                (snapshot(runtime, "A", "changed", corpus_version="corpus-v1"),),
                candidate_id=candidate_id,
            )
        with pytest.raises(KnowledgeReleaseError, match="SCOPE_DENIED"):
            runtime.service.create_candidate(
                candidate_id=uuid4(),
                scope=scope(),
                task_id=TASK_ID,
                request_id="cross-scope",
                corpus_id="ndt-standards",
                corpus_version="corpus-v1",
                index_version="index-v1",
                embedding_version=EMBEDDING.version,
                snapshots=(
                    snapshot(
                        runtime,
                        "X",
                        "cross scope",
                        corpus_version="corpus-v1",
                        owner=scope(permission="permissions-2"),
                    ),
                ),
                base_publication_id=None,
            )
        with pytest.raises(KnowledgeReleaseError, match="BASE_STALE"):
            create(runtime, (first_snapshot,), base=uuid4())
    finally:
        runtime.close()


def test_validation_passes_all_required_states_and_is_idempotent() -> None:
    runtime = Runtime()
    try:
        candidate = create(
            runtime,
            (snapshot(runtime, "A", "valid crack rule", corpus_version="corpus-v1"),),
        )

        validated = runtime.service.validate(scope(), candidate.candidate_id)
        replay = runtime.service.validate(scope(), candidate.candidate_id)

        assert replay == validated
        assert validated.state is KnowledgeState.REVIEW_REQUIRED
        assert [transition.target for transition in validated.transitions] == [
            KnowledgeState.DRAFT,
            KnowledgeState.VALIDATING,
            KnowledgeState.REVIEW_REQUIRED,
        ]
        assert validated.validation is not None and validated.validation.passed
    finally:
        runtime.close()


def test_validation_fails_closed_with_stable_aggregate_codes() -> None:
    runtime = Runtime()
    try:
        first = snapshot(
            runtime,
            "A",
            "invalid first",
            corpus_version="wrong-version",
            status=IndexStatus.PUBLISHED,
            standard_id="f" * 64,
        )
        duplicate = snapshot(
            runtime,
            "A",
            "invalid second",
            corpus_version="wrong-version",
            standard_id="f" * 64,
        )
        candidate = create(
            runtime,
            (first, duplicate),
            corpus_version="corpus-v1",
        )

        failed = runtime.service.validate(scope(), candidate.candidate_id)

        assert failed.state is KnowledgeState.FAILED
        assert failed.validation is not None
        assert set(failed.validation.codes) == {
            "KNOWLEDGE_DOCUMENT_DUPLICATE",
            "KNOWLEDGE_SNAPSHOT_NOT_DRAFT",
            "KNOWLEDGE_VERSION_MISMATCH",
            "KNOWLEDGE_STANDARD_UNREGISTERED",
        }
        with pytest.raises(KnowledgeReleaseError, match="REVIEW_STATE_INVALID"):
            runtime.service.record_review(scope(), failed.candidate_id, review_workflow(failed))
    finally:
        runtime.close()


def test_actual_s1_review_must_bind_exact_candidate_and_pass() -> None:
    runtime = Runtime()
    try:
        validated = runtime.service.validate(
            scope(),
            create(
                runtime,
                (snapshot(runtime, "A", "reviewed rule", corpus_version="corpus-v1"),),
            ).candidate_id,
        )
        stale = review_workflow(validated, stale_hash=True)
        with pytest.raises(KnowledgeReleaseError, match="REVIEW_BINDING_INVALID"):
            runtime.service.record_review(scope(), validated.candidate_id, stale)

        failed_review = review_workflow(validated, decision=ReviewDecision.HUMAN_REQUIRED)
        with pytest.raises(KnowledgeReleaseError, match="REVIEW_INVALID"):
            runtime.service.record_review(scope(), validated.candidate_id, failed_review)

        reviewed = runtime.service.record_review(
            scope(), validated.candidate_id, review_workflow(validated)
        )
        assert reviewed.review is not None
        assert reviewed.review.workflow_manifest_sha256
        assert reviewed.review.reviewer_versions == ("knowledge-reviewer-1",)
    finally:
        runtime.close()


def test_publish_requires_review_and_human_approval_then_is_idempotent() -> None:
    runtime = Runtime()
    try:
        candidate = create(
            runtime,
            (snapshot(runtime, "A", "publish rule", corpus_version="corpus-v1"),),
        )
        with pytest.raises(KnowledgeReleaseError, match="REVIEW_REQUIRED"):
            with runtime.traces.start_span("knowledge.approval.create"):
                runtime.service.request_publish_approval(
                    scope=scope(), candidate_id=candidate.candidate_id, approval_id=uuid4()
                )
        reviewed = validate_and_review(runtime, candidate)
        approval_id = uuid4()
        runtime.request_publish(reviewed, approval_id)
        with pytest.raises(ApprovalError) as captured:
            with runtime.traces.start_span("knowledge.publish"):
                runtime.service.publish(
                    scope=scope(),
                    candidate_id=reviewed.candidate_id,
                    publication_id=uuid4(),
                    resume_id=uuid4(),
                )
        assert captured.value.code == "APPROVAL_NOT_APPROVED"

        runtime.approve(approval_id, reviewed.candidate_sha256)
        publication_id = uuid4()
        resume_id = uuid4()
        with runtime.traces.start_span("knowledge.publish"):
            first = runtime.service.publish(
                scope=scope(),
                candidate_id=reviewed.candidate_id,
                publication_id=publication_id,
                resume_id=resume_id,
            )
            replay = runtime.service.publish(
                scope=scope(),
                candidate_id=reviewed.candidate_id,
                publication_id=publication_id,
                resume_id=resume_id,
            )

        assert replay == first
        assert first.state is KnowledgeState.PUBLISHED
        assert runtime.repository.current(scope(), "ndt-standards") == first
        assert runtime.index.list_for_scope(scope())[0].status is IndexStatus.PUBLISHED
    finally:
        runtime.close()


def test_incremental_publication_supersedes_changed_and_removed_snapshots() -> None:
    runtime = Runtime()
    try:
        _, first_id = publish(
            runtime,
            (
                snapshot(runtime, "A", "old crack rule", corpus_version="corpus-v1"),
                snapshot(runtime, "B", "removed rule", corpus_version="corpus-v1"),
            ),
            corpus_version="corpus-v1",
        )
        changed = snapshot(runtime, "A", "new crack rule", corpus_version="corpus-v2")
        candidate = create(
            runtime,
            (changed,),
            base=first_id,
            corpus_version="corpus-v2",
        )

        assert candidate.diff.updated_document_ids == (changed.document_id,)
        assert len(candidate.diff.removed_document_ids) == 1
        _, second_id = publish(
            runtime,
            (changed,),
            corpus_version="corpus-v2",
            base=first_id,
        )

        first = runtime.repository.get_publication(scope(), first_id)
        second = runtime.repository.get_publication(scope(), second_id)
        assert first.state is KnowledgeState.SUPERSEDED
        assert second.state is KnowledgeState.PUBLISHED
        assert all(item.status is IndexStatus.SUPERSEDED for item in first.snapshots)
        assert runtime.repository.current(scope(), "ndt-standards") == second
    finally:
        runtime.close()


def test_injected_commit_failure_has_zero_partial_mutation_and_exact_retry() -> None:
    runtime = Runtime()
    try:
        reviewed = validate_and_review(
            runtime,
            create(
                runtime,
                (snapshot(runtime, "A", "atomic rule", corpus_version="corpus-v1"),),
            ),
        )
        approval_id = uuid4()
        runtime.request_publish(reviewed, approval_id)
        runtime.approve(approval_id, reviewed.candidate_sha256)
        publication_id = uuid4()
        resume_id = uuid4()
        runtime.repository.fail_next_commit = True
        with pytest.raises(KnowledgeReleaseError, match="ATOMIC_COMMIT_FAILED"):
            with runtime.traces.start_span("knowledge.publish"):
                runtime.service.publish(
                    scope=scope(),
                    candidate_id=reviewed.candidate_id,
                    publication_id=publication_id,
                    resume_id=resume_id,
                )

        assert runtime.repository.current(scope(), "ndt-standards") is None
        assert runtime.index.list_for_scope(scope()) == ()
        assert (
            runtime.repository.get_candidate(scope(), reviewed.candidate_id).state
            is KnowledgeState.REVIEW_REQUIRED
        )
        with runtime.traces.start_span("knowledge.publish"):
            published = runtime.service.publish(
                scope=scope(),
                candidate_id=reviewed.candidate_id,
                publication_id=publication_id,
                resume_id=resume_id,
            )
        assert published.state is KnowledgeState.PUBLISHED
    finally:
        runtime.close()


def test_withdrawal_needs_distinct_approval_and_removes_current_visibility() -> None:
    runtime = Runtime()
    try:
        _, publication_id = publish(
            runtime,
            (snapshot(runtime, "A", "withdraw rule", corpus_version="corpus-v1"),),
            corpus_version="corpus-v1",
        )
        operation_id = uuid4()
        approval_id = uuid4()
        action_hash = runtime.request_action(
            ReleaseActionKind.WITHDRAW,
            publication_id,
            operation_id=operation_id,
            approval_id=approval_id,
        )
        with pytest.raises(ApprovalError) as captured:
            with runtime.traces.start_span("knowledge.withdraw"):
                runtime.service.withdraw(
                    scope=scope(), operation_id=operation_id, resume_id=uuid4()
                )
        assert captured.value.code == "APPROVAL_NOT_APPROVED"
        runtime.approve(approval_id, action_hash)
        resume_id = uuid4()
        with runtime.traces.start_span("knowledge.withdraw"):
            withdrawn = runtime.service.withdraw(
                scope=scope(), operation_id=operation_id, resume_id=resume_id
            )
            replay = runtime.service.withdraw(
                scope=scope(), operation_id=operation_id, resume_id=resume_id
            )

        assert replay == withdrawn
        assert withdrawn.state is KnowledgeState.WITHDRAWN
        assert runtime.repository.current(scope(), "ndt-standards") is None
        assert all(
            item.status is IndexStatus.WITHDRAWN for item in runtime.index.list_for_scope(scope())
        )
    finally:
        runtime.close()


def test_rollback_creates_new_approved_publication_from_preserved_history() -> None:
    runtime = Runtime()
    try:
        _, first_id = publish(
            runtime,
            (snapshot(runtime, "A", "original rule", corpus_version="corpus-v1"),),
            corpus_version="corpus-v1",
        )
        _, second_id = publish(
            runtime,
            (snapshot(runtime, "A", "replacement rule", corpus_version="corpus-v2"),),
            corpus_version="corpus-v2",
            base=first_id,
        )
        operation_id = uuid4()
        approval_id = uuid4()
        action_hash = runtime.request_action(
            ReleaseActionKind.ROLLBACK,
            first_id,
            operation_id=operation_id,
            approval_id=approval_id,
        )
        runtime.approve(approval_id, action_hash)
        with runtime.traces.start_span("knowledge.rollback"):
            restored = runtime.service.rollback(
                scope=scope(), operation_id=operation_id, resume_id=uuid4()
            )

        assert restored.publication_id == operation_id
        assert restored.restored_from_publication_id == first_id
        assert restored.previous_publication_id == second_id
        assert restored.state is KnowledgeState.PUBLISHED
        assert (
            runtime.repository.get_publication(scope(), second_id).state
            is KnowledgeState.SUPERSEDED
        )
        assert len(runtime.repository.list_publications(scope())) == 3
        assert runtime.repository.current(scope(), "ndt-standards") == restored
        assert restored.snapshots[0].records[0].text == "original rule"
    finally:
        runtime.close()


def test_wrong_action_and_cross_scope_operation_are_denied_without_mutation() -> None:
    runtime = Runtime()
    try:
        _, publication_id = publish(
            runtime,
            (snapshot(runtime, "A", "safe rule", corpus_version="corpus-v1"),),
            corpus_version="corpus-v1",
        )
        operation_id = uuid4()
        approval_id = uuid4()
        runtime.request_action(
            ReleaseActionKind.WITHDRAW,
            publication_id,
            operation_id=operation_id,
            approval_id=approval_id,
        )
        with pytest.raises(KnowledgeReleaseError, match="ACTION_KIND_MISMATCH"):
            runtime.service.rollback(scope=scope(), operation_id=operation_id, resume_id=uuid4())
        with pytest.raises(KnowledgeReleaseError, match="ACTION_NOT_FOUND"):
            runtime.service.withdraw(
                scope=scope(permission="permissions-2"),
                operation_id=operation_id,
                resume_id=uuid4(),
            )
        current = runtime.repository.current(scope(), "ndt-standards")
        assert current is not None and current.publication_id == publication_id
    finally:
        runtime.close()
