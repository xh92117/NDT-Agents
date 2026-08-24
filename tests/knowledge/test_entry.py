"""S3-01 explicit Knowledge intent, UI entry, scope, and approval tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ndt_agents.approval.service import (
    ApprovalCandidate,
    ApprovalGrant,
    ApprovalKind,
    ApprovalState,
    ApprovalStatus,
    canonical_sha256,
)
from ndt_agents.context.assembly import task_context_manifest_sha256
from ndt_agents.context.models import ContextBundle
from ndt_agents.contracts.v1 import TaskContext
from ndt_agents.identity.middleware import IdentityRuntime
from ndt_agents.identity.models import Principal
from ndt_agents.identity.oidc import OidcJwtVerifier
from ndt_agents.identity.rbac import Permission, RbacPolicy, RoutePermissionPolicy
from ndt_agents.knowledge.entry import (
    KNOWLEDGE_IMPORT_ACTION,
    KNOWLEDGE_IMPORT_TARGET,
    InMemoryKnowledgeTaskRepository,
    KnowledgeEntryGraph,
    knowledge_entry_candidate_sha256,
)
from ndt_agents.knowledge.models import (
    KnowledgeEntryTrigger,
    KnowledgeIntent,
    KnowledgeStartRequest,
)
from ndt_agents.orchestration.budget import default_budget_policy
from ndt_agents.orchestration.child_models import (
    AgentDefinition,
    ChildAgentKind,
    ChildSideEffectClass,
)
from ndt_agents.orchestration.models import RouteKind
from ndt_agents.orchestration.registry import AgentRegistry
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings, RuntimeEnvironment

ROOT = Path(__file__).resolve().parents[2]
BASE_TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
NOW = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)


def knowledge_task(*, immutable: bool = True) -> TaskContext:
    artifact = BASE_TASK.artifacts[0].model_copy(update={"immutable": immutable})
    task = BASE_TASK.model_copy(
        update={
            "task_class": "K1",
            "artifacts": (artifact,),
            "allowed_tools": ("file.read", "file.list", "file.execute", "web.search"),
            "budget": default_budget_policy("K1", file_count=1),
            "goal": "Prepare one source for the governed Knowledge pipeline.",
            "success_criteria": ("Return one typed candidate result for review.",),
            "dependency_data": {
                "context_bundle": ContextBundle(
                    policy_version="context-policy-1",
                    authorization_sha256="a" * 64,
                    selected_content_bytes=0,
                    entries=(),
                ).model_dump(mode="json")
            },
            "context_manifest_sha256": "0" * 64,
        }
    )
    return task.model_copy(update={"context_manifest_sha256": task_context_manifest_sha256(task)})


def registry() -> AgentRegistry:
    return AgentRegistry(
        (
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset(),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="reference",
            ),
            AgentDefinition(
                agent_type="knowledge",
                kind=ChildAgentKind.PROFESSIONAL,
                allowed_tools=frozenset({"file.read", "file.list", "file.execute"}),
                skill_version="knowledge-entry-1",
                prompt_version="knowledge-entry-1",
                model_version="reference",
            ),
        )
    )


def graph(
    task: TaskContext | None = None,
) -> tuple[KnowledgeEntryGraph, InMemoryKnowledgeTaskRepository]:
    repository = InMemoryKnowledgeTaskRepository((task or knowledge_task(),))
    return KnowledgeEntryGraph(repository, registry(), clock=lambda: NOW), repository


def import_request(
    task: TaskContext,
    *,
    trigger: KnowledgeEntryTrigger = KnowledgeEntryTrigger.USER_INTENT,
    approval_status: ApprovalStatus | None = None,
) -> KnowledgeStartRequest:
    return KnowledgeStartRequest(
        request_id="knowledge-request-1",
        task_id=task.task_id,
        trigger=trigger,
        intent=KnowledgeIntent.IMPORT,
        source_artifact_ids=(task.artifacts[0].artifact_id,),
        approval_status=approval_status,
    )


def test_explicit_user_intent_prepares_one_async_isolated_knowledge_child() -> None:
    task = knowledge_task()
    entry, repository = graph(task)

    result = entry.start(scope=task.scope, request=import_request(task))

    assert result.status == "DISPATCH_READY"
    assert repository.read_count == 1
    assert result.main_result is not None
    assert result.main_result.dispatch is not None
    assert result.main_result.dispatch.route is RouteKind.ONE_PROFESSIONAL_ASYNC_REVIEW
    assert result.main_result.dispatch.asynchronous is True
    assert result.main_result.dispatch.review_required is True
    assert result.main_result.dispatch.main_llm_calls == 0
    assert result.main_result.dispatch.main_allowed_tools == ()
    assert result.child_context is not None
    assert result.child_context.agent_type == "knowledge"
    assert result.child_context.kind is ChildAgentKind.PROFESSIONAL
    assert result.child_context.task_class == "K1"
    assert result.child_context.context_entries == ()
    assert result.child_context.artifacts == task.artifacts
    assert result.child_context.allowed_tools == ("file.execute", "file.list", "file.read")
    assert result.child_context.side_effect_class is ChildSideEffectClass.MUTATING
    assert result.child_context.user_delivery_allowed is False
    assert result.child_context.scratch_namespace.startswith(
        f"scratch://{task.scope.tenant_id}/{task.scope.project_id}/{task.task_id}/"
    )
    assert result.physical_child_calls == 0
    assert [transition.target.value for transition in result.transitions] == [
        "OBSERVE",
        "VALIDATE",
        "PLAN",
        "VERIFY",
        "DISPATCH_READY",
    ]


def test_normal_question_never_loads_a_task_or_starts_knowledge() -> None:
    task = knowledge_task()
    entry, repository = graph(task)
    request = KnowledgeStartRequest(
        request_id="question-1",
        task_id=task.task_id,
        trigger=KnowledgeEntryTrigger.USER_INTENT,
        intent=KnowledgeIntent.READ_ONLY_QUERY,
    )

    result = entry.start(scope=task.scope, request=request)

    assert result.status == "NOT_APPLICABLE"
    assert result.code == "KNOWLEDGE_ENTRY_NOT_EXPLICIT"
    assert result.main_result is None
    assert result.child_context is None
    assert result.physical_child_calls == 0
    assert repository.read_count == 0


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda task: task.scope.model_copy(update={"permission_version": "stale"}),
            "KNOWLEDGE_TASK_SCOPE_DENIED",
        ),
        (
            lambda task: task.scope,
            "KNOWLEDGE_SOURCE_INVALID",
        ),
    ],
)
def test_scope_and_immutable_source_fail_closed(mutator: Any, expected_code: str) -> None:
    task = knowledge_task(immutable=expected_code != "KNOWLEDGE_SOURCE_INVALID")
    entry, _repository = graph(task)

    result = entry.start(scope=mutator(task), request=import_request(task))

    assert result.status == "BLOCKED"
    assert result.code == expected_code
    assert result.child_context is None


def test_k1_budget_must_match_the_exact_file_count() -> None:
    task = knowledge_task().model_copy(update={"budget": default_budget_policy("K1", file_count=2)})
    entry, _repository = graph(task)

    result = entry.start(scope=task.scope, request=import_request(task))

    assert result.status == "BLOCKED"
    assert result.code == "KNOWLEDGE_BUDGET_INVALID"


def test_legacy_task_without_s2_context_bundle_is_rejected() -> None:
    task = knowledge_task().model_copy(
        update={"dependency_data": {}, "context_manifest_sha256": "0" * 64}
    )
    entry, _repository = graph(task)

    result = entry.start(scope=task.scope, request=import_request(task))

    assert result.status == "BLOCKED"
    assert result.code == "KNOWLEDGE_CONTEXT_REQUIRED"


def test_entry_contract_rejects_more_than_fifty_or_duplicate_sources() -> None:
    task = knowledge_task()
    with pytest.raises(ValidationError):
        KnowledgeStartRequest(
            request_id="too-many",
            task_id=task.task_id,
            trigger=KnowledgeEntryTrigger.USER_INTENT,
            intent=KnowledgeIntent.IMPORT,
            source_artifact_ids=tuple(uuid4() for _ in range(51)),
        )
    with pytest.raises(ValidationError):
        KnowledgeStartRequest(
            request_id="duplicate",
            task_id=task.task_id,
            trigger=KnowledgeEntryTrigger.USER_INTENT,
            intent=KnowledgeIntent.IMPORT,
            source_artifact_ids=(task.artifacts[0].artifact_id,) * 2,
        )


def approved_admin_status(task: TaskContext, *, expires_at: datetime) -> ApprovalStatus:
    candidate_sha256 = knowledge_entry_candidate_sha256(
        scope=task.scope,
        request_id="knowledge-request-1",
        task_id=task.task_id,
        trigger=KnowledgeEntryTrigger.ADMIN_JOB,
        intent=KnowledgeIntent.IMPORT,
        source_artifact_ids=(task.artifacts[0].artifact_id,),
    )
    approval_id = uuid4()
    preview = {"candidate_sha256": candidate_sha256}
    candidate = ApprovalCandidate(
        approval_id=approval_id,
        scope=task.scope,
        task_id=task.task_id,
        request_id="approval-request-1",
        kind=ApprovalKind.KNOWLEDGE,
        action=KNOWLEDGE_IMPORT_ACTION,
        target_type=KNOWLEDGE_IMPORT_TARGET,
        target_id=task.task_id,
        target_version="1.0.0",
        candidate_sha256=candidate_sha256,
        preview=preview,
        preview_sha256=canonical_sha256(preview),
        policy_version="approval-policy-1",
        created_at=NOW - timedelta(minutes=1),
        expires_at=expires_at,
    )
    grant = ApprovalGrant(
        resume_id=uuid4(),
        approval_id=approval_id,
        scope=task.scope,
        task_id=task.task_id,
        candidate_sha256=candidate_sha256,
        policy_version=candidate.policy_version,
        decision_sha256s=("a" * 64,),
        resumed_at=NOW - timedelta(seconds=30),
    )
    return ApprovalStatus(
        candidate=candidate,
        state=ApprovalState.APPROVED,
        decisions=(),
        delegations=(),
        grant=grant,
    )


def test_admin_job_requires_current_exact_candidate_approval() -> None:
    task = knowledge_task()
    entry, _repository = graph(task)
    approved = approved_admin_status(task, expires_at=NOW + timedelta(hours=1))

    accepted = entry.start(
        scope=task.scope,
        request=import_request(
            task,
            trigger=KnowledgeEntryTrigger.ADMIN_JOB,
            approval_status=approved,
        ),
    )
    expired = entry.start(
        scope=task.scope,
        request=import_request(
            task,
            trigger=KnowledgeEntryTrigger.ADMIN_JOB,
            approval_status=approved.model_copy(
                update={
                    "candidate": approved.candidate.model_copy(
                        update={"expires_at": NOW - timedelta(seconds=1)}
                    )
                }
            ),
        ),
    )

    assert accepted.status == "DISPATCH_READY"
    assert expired.status == "BLOCKED"
    assert expired.code == "KNOWLEDGE_ADMIN_APPROVAL_INVALID"


class StaticVerifier:
    def __init__(self, principal: Principal) -> None:
        self._principal = principal

    def verify(self, token: str) -> Principal:
        assert token == "test-token"
        return self._principal


def identity(task: TaskContext, *, register_route: bool = True) -> IdentityRuntime:
    principal = Principal(
        subject="knowledge-user",
        user_id=task.scope.user_id,
        tenant_id=task.scope.tenant_id,
        project_ids=(task.scope.project_id,),
        roles=task.scope.role_codes,
        permission_version=task.scope.permission_version,
        token_id="token-1",
    )
    routes = (
        {("POST", "/v1/knowledge/imports"): Permission.KNOWLEDGE_IMPORT_START}
        if register_route
        else {}
    )
    return IdentityRuntime(
        verifier=cast(OidcJwtVerifier, StaticVerifier(principal)),
        rbac=RbacPolicy(
            policy_version="rbac-knowledge-1",
            grants={
                role: frozenset({Permission.KNOWLEDGE_IMPORT_START})
                for role in task.scope.role_codes
            },
        ),
        routes=RoutePermissionPolicy(policy_version="routes-knowledge-1", permissions=routes),
    )


def headers(task: TaskContext) -> dict[str, str]:
    return {
        "authorization": "Bearer test-token",
        "x-tenant-id": str(task.scope.tenant_id),
        "x-project-id": str(task.scope.project_id),
        "x-request-id": "knowledge-ui-http-1",
    }


def test_authenticated_ui_entry_returns_only_safe_accepted_metadata() -> None:
    task = knowledge_task()
    entry, _repository = graph(task)
    app = create_app(
        AppSettings(environment=RuntimeEnvironment.CI),
        configure_logs=False,
        identity=identity(task),
        knowledge_entry=entry,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/knowledge/imports",
            headers=headers(task),
            json={
                "schema_version": "1.0.0",
                "request_id": "ui-import-1",
                "task_id": str(task.task_id),
                "source_artifact_ids": [str(task.artifacts[0].artifact_id)],
            },
        )

    assert response.status_code == 202
    assert response.json()["status"] == "DISPATCH_READY"
    assert response.json()["asynchronous"] is True
    assert response.json()["review_required"] is True
    serialized = response.text
    assert "child_context" not in serialized
    assert "scratch" not in serialized
    assert task.goal not in serialized


def test_ui_route_is_default_deny_and_cannot_be_enabled_without_identity() -> None:
    task = knowledge_task()
    entry, _repository = graph(task)
    app = create_app(
        AppSettings(environment=RuntimeEnvironment.CI),
        configure_logs=False,
        identity=identity(task, register_route=False),
        knowledge_entry=entry,
    )

    with TestClient(app) as client:
        denied = client.post(
            "/v1/knowledge/imports",
            headers=headers(task),
            json={
                "request_id": "ui-import-2",
                "task_id": str(task.task_id),
                "source_artifact_ids": [str(task.artifacts[0].artifact_id)],
            },
        )

    assert denied.status_code == 403
    assert denied.json()["error_code"] == "AUTH_ROUTE_UNREGISTERED"
    with pytest.raises(ValueError, match="authenticated identity"):
        create_app(
            AppSettings(environment=RuntimeEnvironment.CI),
            configure_logs=False,
            knowledge_entry=entry,
        )
