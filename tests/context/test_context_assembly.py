"""S2-01 UNIT-CONTEXT permission filtering and deterministic assembly tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import JsonValue

from ndt_agents.context import (
    ArtifactCandidate,
    ContextAssemblyError,
    ContextAssemblyPolicy,
    ContextItemCandidate,
    ContextSelectionReason,
    ContextSourceType,
    ContextTrustLevel,
    ContextVisibility,
    TaskContextAssembler,
    TaskContextAssemblyRequest,
    TaskContextAssemblyResult,
    ToolAuthorization,
    context_content_sha256,
    task_context_manifest_sha256,
)
from ndt_agents.context.assembly import canonical_json_bytes
from ndt_agents.contracts.v1 import DataClassification, TaskContext, TenantScope
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import AgentDefinition, ChildAgentKind, ChildInput
from ndt_agents.orchestration.models import DispatchPlan, ProfessionalAssignment, RouteKind
from ndt_agents.orchestration.registry import AgentRegistry, AgentRegistryError

ROOT = Path(__file__).resolve().parents[2]
BASE_TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
NOW = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
OTHER_TENANT = UUID("00000000-0000-4000-8000-000000000101")
OTHER_PROJECT = UUID("00000000-0000-4000-8000-000000000102")
OTHER_USER = UUID("00000000-0000-4000-8000-000000000103")


def scope(
    *,
    tenant_id: UUID | None = None,
    project_id: UUID | None = None,
    user_id: UUID | None = None,
    permission_version: str | None = None,
) -> TenantScope:
    return BASE_TASK.scope.model_copy(
        update={
            "tenant_id": tenant_id or BASE_TASK.scope.tenant_id,
            "project_id": project_id or BASE_TASK.scope.project_id,
            "user_id": user_id or BASE_TASK.scope.user_id,
            "permission_version": permission_version or BASE_TASK.scope.permission_version,
        }
    )


def item(
    item_id: str,
    content: dict[str, JsonValue],
    *,
    item_scope: TenantScope | None = None,
    visibility: ContextVisibility = ContextVisibility.PROJECT,
    required_roles: tuple[str, ...] = (),
    required_permissions: tuple[str, ...] = ("context:read",),
    relevance: float = 0.9,
    protected: bool = False,
    classification: DataClassification = DataClassification.INTERNAL,
    source_type: ContextSourceType = ContextSourceType.PROJECT_FACT,
    trust: ContextTrustLevel = ContextTrustLevel.VERIFIED_INTERNAL,
) -> ContextItemCandidate:
    normalized = dict(content)
    return ContextItemCandidate(
        item_id=item_id,
        scope=item_scope or scope(),
        visibility=visibility,
        source_type=source_type,
        source_ref=f"source://{item_id}",
        source_version="1",
        source_sha256=(item_id.encode().hex() + "0" * 64)[:64],
        trust_level=trust,
        classification=classification,
        content=normalized,
        content_sha256=context_content_sha256(normalized),
        required_roles=required_roles,
        required_permissions=required_permissions,
        relevance_score=relevance,
        protected=protected,
        observed_at=NOW,
    )


def request(
    *,
    candidates: tuple[ContextItemCandidate, ...] = (),
    artifact_candidates: tuple[ArtifactCandidate, ...] = (),
    requested_tools: tuple[str, ...] = ("artifact.read@1",),
    tool_authorizations: tuple[ToolAuthorization, ...] | None = None,
    granted_permissions: tuple[str, ...] = ("artifact:read", "context:read"),
    clearance: DataClassification = DataClassification.INTERNAL,
    policy: ContextAssemblyPolicy | None = None,
) -> TaskContextAssemblyRequest:
    authorizations = tool_authorizations
    if authorizations is None:
        authorizations = (
            ToolAuthorization(
                tool_name="artifact.read@1",
                scope=scope(),
                required_permissions=("artifact:read",),
            ),
        )
    return TaskContextAssemblyRequest(
        task_id=BASE_TASK.task_id,
        scope=BASE_TASK.scope.model_copy(update={"role_codes": ("NDT_ENGINEER",)}),
        task_class=BASE_TASK.task_class,
        goal=BASE_TASK.goal,
        success_criteria=BASE_TASK.success_criteria,
        risk_level=BASE_TASK.risk_level,
        candidates=candidates,
        artifact_candidates=artifact_candidates,
        requested_tools=requested_tools,
        tool_authorizations=authorizations,
        granted_permissions=granted_permissions,
        clearance=clearance,
        policy=policy
        or ContextAssemblyPolicy(policy_version="context-policy-1", minimum_relevance=0.5),
        skill_versions=BASE_TASK.skill_versions,
        prompt_versions=BASE_TASK.prompt_versions,
        model_versions=BASE_TASK.model_versions,
        knowledge_versions=BASE_TASK.knowledge_versions,
        budget=BASE_TASK.budget,
        output_schema_id=BASE_TASK.output_schema_id,
        review_checklist=BASE_TASK.review_checklist,
        created_at=NOW,
    )


def decision_map(
    result: TaskContextAssemblyResult,
) -> dict[tuple[str, str], ContextSelectionReason]:
    return {(item.candidate_kind, item.candidate_id): item.reason for item in result.decisions}


def test_deterministic_assembly_deduplicates_and_preserves_authorized_provenance() -> None:
    instruction = item(
        "instruction",
        {"instruction": "Preserve the current user constraint."},
        relevance=0.0,
        protected=True,
        source_type=ContextSourceType.USER_INSTRUCTION,
        trust=ContextTrustLevel.USER_PROVIDED,
    )
    fact_one = item("fact-a", {"span_mm": 1250, "unit": "mm"})
    fact_two = item("fact-b", {"unit": "mm", "span_mm": 1250})

    first = TaskContextAssembler().assemble(request(candidates=(fact_two, instruction, fact_one)))
    second = TaskContextAssembler().assemble(request(candidates=(fact_one, fact_two, instruction)))

    assert first.context == second.context
    assert first.context.context_manifest_sha256 == second.context.context_manifest_sha256
    assert task_context_manifest_sha256(first.context) == first.context.context_manifest_sha256
    bundle = first.context.dependency_data["context_bundle"]
    assert bundle["selected_content_bytes"] == first.selected_content_bytes
    assert len(bundle["entries"]) == 2
    merged = next(entry for entry in bundle["entries"] if entry["content"].get("span_mm") == 1250)
    assert [source["item_id"] for source in merged["sources"]] == ["fact-a", "fact-b"]
    assert {source["trust_level"] for source in merged["sources"]} == {"VERIFIED_INTERNAL"}
    decisions = decision_map(first)
    assert decisions[("ITEM", "fact-a")] is ContextSelectionReason.SELECTED
    assert decisions[("ITEM", "fact-b")] is ContextSelectionReason.DEDUPLICATED


def test_permission_filter_excludes_every_unauthorized_or_irrelevant_item() -> None:
    candidates = (
        item("safe", {"value": "SAFE"}),
        item("tenant", {"value": "TENANT_SECRET"}, item_scope=scope(tenant_id=OTHER_TENANT)),
        item("project", {"value": "PROJECT_SECRET"}, item_scope=scope(project_id=OTHER_PROJECT)),
        item(
            "user",
            {"value": "USER_SECRET"},
            item_scope=scope(user_id=OTHER_USER),
            visibility=ContextVisibility.USER,
        ),
        item(
            "stale",
            {"value": "STALE_SECRET"},
            item_scope=scope(permission_version="perm-old"),
        ),
        item("role", {"value": "ROLE_SECRET"}, required_roles=("ADMIN",)),
        item("permission", {"value": "PERMISSION_SECRET"}, required_permissions=("secret:read",)),
        item(
            "classification",
            {"value": "CLASSIFIED_SECRET"},
            classification=DataClassification.RESTRICTED,
        ),
        item("irrelevant", {"value": "IRRELEVANT_SECRET"}, relevance=0.1),
    )

    result = TaskContextAssembler().assemble(request(candidates=candidates))
    serialized = result.context.model_dump_json()

    assert "SAFE" in serialized
    for secret in (
        "TENANT_SECRET",
        "PROJECT_SECRET",
        "USER_SECRET",
        "STALE_SECRET",
        "ROLE_SECRET",
        "PERMISSION_SECRET",
        "CLASSIFIED_SECRET",
        "IRRELEVANT_SECRET",
    ):
        assert secret not in serialized
    reasons = set(decision_map(result).values())
    assert {
        ContextSelectionReason.TENANT_DENIED,
        ContextSelectionReason.PROJECT_DENIED,
        ContextSelectionReason.USER_DENIED,
        ContextSelectionReason.PERMISSION_VERSION_STALE,
        ContextSelectionReason.ROLE_DENIED,
        ContextSelectionReason.PERMISSION_DENIED,
        ContextSelectionReason.CLASSIFICATION_DENIED,
        ContextSelectionReason.IRRELEVANT,
    } <= reasons


def test_project_visibility_allows_an_authorized_fact_from_another_project_member() -> None:
    shared = item(
        "shared",
        {"project_fact": "approved"},
        item_scope=scope(user_id=OTHER_USER),
        visibility=ContextVisibility.PROJECT,
    )

    result = TaskContextAssembler().assemble(request(candidates=(shared,)))

    assert result.context.dependency_data["context_bundle"]["entries"][0]["content"] == {
        "project_fact": "approved"
    }


def test_artifacts_and_tools_are_scope_filtered_and_default_denied() -> None:
    authorized_ref = BASE_TASK.artifacts[0]
    denied_ref = authorized_ref.model_copy(
        update={
            "artifact_id": UUID("00000000-0000-4000-8000-000000000111"),
            "scope": scope(project_id=OTHER_PROJECT),
            "uri": "artifact://other/project/secret",
        }
    )
    artifacts = (
        ArtifactCandidate(
            artifact=authorized_ref,
            visibility=ContextVisibility.PROJECT,
            required_permissions=("artifact:read",),
            relevance_score=1.0,
        ),
        ArtifactCandidate(
            artifact=denied_ref,
            visibility=ContextVisibility.PROJECT,
            required_permissions=("artifact:read",),
            relevance_score=1.0,
        ),
    )
    authorizations = (
        ToolAuthorization(
            tool_name="artifact.read@1",
            scope=scope(),
            required_permissions=("artifact:read",),
        ),
        ToolAuthorization(
            tool_name="web.search@1",
            scope=scope(),
            required_permissions=("web:search",),
        ),
    )

    result = TaskContextAssembler().assemble(
        request(
            artifact_candidates=artifacts,
            requested_tools=("artifact.read@1", "missing@1", "web.search@1"),
            tool_authorizations=authorizations,
        )
    )

    assert result.context.artifacts == (authorized_ref,)
    assert result.context.allowed_tools == ("artifact.read@1",)
    assert "artifact://other/project/secret" not in result.context.model_dump_json()
    decisions = decision_map(result)
    assert (
        decisions[("ARTIFACT", str(denied_ref.artifact_id))]
        is ContextSelectionReason.PROJECT_DENIED
    )
    assert decisions[("TOOL", "missing@1")] is ContextSelectionReason.UNREGISTERED
    assert decisions[("TOOL", "web.search@1")] is ContextSelectionReason.PERMISSION_DENIED


def test_c0_baseline_is_lossless_for_authorized_content_and_protected_fields() -> None:
    content: dict[str, JsonValue] = {
        "clause": "7.3",
        "limit": 12.5,
        "unit": "mm",
        "uncertain": True,
    }
    current = item("current", content, protected=True, relevance=0.0)

    result = TaskContextAssembler().assemble(request(candidates=(current,)))
    entry = result.context.dependency_data["context_bundle"]["entries"][0]

    assert entry["content"] == content
    assert entry["protected"] is True
    assert result.context.goal == BASE_TASK.goal
    assert result.context.success_criteria == BASE_TASK.success_criteria
    assert result.context.scope == BASE_TASK.scope


def test_protected_content_never_drops_silently_when_policy_is_too_small() -> None:
    protected = item("protected", {"required": "x" * 100}, protected=True)
    policy = ContextAssemblyPolicy(
        policy_version="context-policy-small",
        max_selected_items=1,
        max_selected_content_bytes=10,
    )

    with pytest.raises(ContextAssemblyError) as captured:
        TaskContextAssembler().assemble(request(candidates=(protected,), policy=policy))

    assert captured.value.code == "CONTEXT_PROTECTED_OVERFLOW"
    assert "artifact" in captured.value.next_action.lower()


def test_size_budget_deterministically_keeps_the_more_relevant_item() -> None:
    high = item("high", {"value": "high"}, relevance=0.9)
    low = item("low", {"value": "low"}, relevance=0.6)
    policy = ContextAssemblyPolicy(
        policy_version="context-policy-bounded",
        max_selected_items=2,
        max_selected_content_bytes=len(canonical_json_bytes(high.content)),
    )

    result = TaskContextAssembler().assemble(request(candidates=(low, high), policy=policy))

    entries = result.context.dependency_data["context_bundle"]["entries"]
    assert [entry["content"] for entry in entries] == [{"value": "high"}]
    assert decision_map(result)[("ITEM", "low")] is ContextSelectionReason.BUDGET_EXCLUDED


def test_candidate_input_is_bounded_before_relevance_selection() -> None:
    large = item("large", {"value": "x" * 100}, relevance=0.0)
    policy = ContextAssemblyPolicy(
        policy_version="context-policy-input-bounded",
        max_candidate_content_bytes=10,
    )

    with pytest.raises(ContextAssemblyError) as captured:
        TaskContextAssembler().assemble(request(candidates=(large,), policy=policy))

    assert captured.value.code == "CONTEXT_CANDIDATE_INPUT_OVERFLOW"
    assert "artifacts" in captured.value.next_action.lower()


def test_authorization_state_is_bound_into_the_stable_manifest() -> None:
    candidate = item("safe", {"value": "same"}, required_permissions=())

    first = TaskContextAssembler().assemble(
        request(candidates=(candidate,), granted_permissions=("context:read",))
    )
    second = TaskContextAssembler().assemble(
        request(candidates=(candidate,), granted_permissions=("context:read", "extra:read"))
    )

    assert (
        first.context.dependency_data["context_bundle"]["entries"]
        == second.context.dependency_data["context_bundle"]["entries"]
    )
    assert first.context.context_manifest_sha256 != second.context.context_manifest_sha256


def test_budget_task_class_mismatch_returns_typed_actionable_failure() -> None:
    mismatched = request().model_copy(update={"task_class": "G0"})

    with pytest.raises(ContextAssemblyError) as captured:
        TaskContextAssembler().assemble(mismatched)

    assert captured.value.code == "CONTEXT_BUDGET_CLASS_MISMATCH"
    assert "budget policy" in captured.value.next_action.lower()


def test_verified_bundle_reaches_general_child_without_parent_private_state() -> None:
    selected = item("selected", {"fact": "authorized"})
    parent = TaskContextAssembler().assemble(request(candidates=(selected,))).context
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset({"artifact.read@1"}),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="reference",
            ),
        )
    )
    dispatch = DispatchPlan(
        task_id=parent.task_id,
        route=RouteKind.GENERAL_SYNC,
        general_agent=True,
        professional_assignments=(),
        asynchronous=False,
        review_required=False,
        human_required=False,
    )

    child = ChildContextFactory(registry).prepare(parent, dispatch)[0]

    assert child.context_entries[0].content == {"fact": "authorized"}
    assert "context_bundle" not in child.model_dump_json()
    assert "granted_permissions" not in child.model_dump_json()


def test_tampered_parent_bundle_is_rejected_before_child_context_creation() -> None:
    selected = item("selected", {"fact": "authorized"})
    parent = TaskContextAssembler().assemble(request(candidates=(selected,))).context
    tampered = parent.model_copy(
        update={"dependency_data": {"context_bundle": {"unexpected": True}}}
    )
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset(),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="reference",
            ),
        )
    )
    dispatch = DispatchPlan(
        task_id=parent.task_id,
        route=RouteKind.GENERAL_SYNC,
        general_agent=True,
        professional_assignments=(),
        asynchronous=False,
        review_required=False,
        human_required=False,
    )

    with pytest.raises(AgentRegistryError) as captured:
        ChildContextFactory(registry).prepare(tampered, dispatch)

    assert captured.value.code == "CHILD_CONTEXT_MANIFEST_INVALID"


def test_recomputed_manifest_cannot_bypass_selected_content_integrity() -> None:
    selected = item("selected", {"fact": "authorized"})
    parent = TaskContextAssembler().assemble(request(candidates=(selected,))).context
    bundle = dict(parent.dependency_data["context_bundle"])
    entries = [dict(entry) for entry in bundle["entries"]]
    entries[0]["content"] = {"fact": "forged"}
    bundle["entries"] = entries
    tampered = parent.model_copy(update={"dependency_data": {"context_bundle": bundle}})
    tampered = tampered.model_copy(
        update={"context_manifest_sha256": task_context_manifest_sha256(tampered)}
    )
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset(),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="reference",
            ),
        )
    )
    dispatch = DispatchPlan(
        task_id=parent.task_id,
        route=RouteKind.GENERAL_SYNC,
        general_agent=True,
        professional_assignments=(),
        asynchronous=False,
        review_required=False,
        human_required=False,
    )

    with pytest.raises(AgentRegistryError) as captured:
        ChildContextFactory(registry).prepare(tampered, dispatch)

    assert captured.value.code == "CHILD_CONTEXT_BUNDLE_INVALID"


def test_professional_child_receives_only_explicitly_selected_verified_entries() -> None:
    first = item("first", {"fact": "first"})
    second = item("second", {"fact": "second"})
    parent = (
        TaskContextAssembler()
        .assemble(request(candidates=(first, second), requested_tools=(), tool_authorizations=()))
        .context
    )
    entries = parent.dependency_data["context_bundle"]["entries"]
    selected_sha256 = entries[0]["content_sha256"]
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset(),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="reference",
            ),
            AgentDefinition(
                agent_type="technical_qa",
                kind=ChildAgentKind.PROFESSIONAL,
                allowed_tools=frozenset(),
                skill_version="technical-qa-1",
                prompt_version="technical-qa-1",
                model_version="reference",
            ),
        )
    )
    dispatch = DispatchPlan(
        task_id=parent.task_id,
        route=RouteKind.ONE_PROFESSIONAL_SYNC_REVIEW,
        general_agent=False,
        professional_assignments=(
            ProfessionalAssignment(assignment_id="qa", agent_type="technical_qa"),
        ),
        asynchronous=False,
        review_required=True,
        human_required=False,
    )
    child_input = ChildInput(
        assignment_id="qa",
        goal="Assess one selected fact.",
        success_criteria=("Return one typed finding.",),
        context_entry_sha256s=(selected_sha256,),
    )

    child = ChildContextFactory(registry).prepare(
        parent, dispatch, professional_inputs=(child_input,)
    )[0]

    assert len(child.context_entries) == 1
    assert child.context_entries[0].content_sha256 == selected_sha256

    denied_input = child_input.model_copy(update={"context_entry_sha256s": ("f" * 64,)})
    with pytest.raises(AgentRegistryError) as captured:
        ChildContextFactory(registry).prepare(parent, dispatch, professional_inputs=(denied_input,))
    assert captured.value.code == "CHILD_CONTEXT_ENTRY_DENIED"
