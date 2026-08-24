"""Default-deny, deterministic assembly of minimal V1 task contexts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ndt_agents.context.models import (
    ArtifactCandidate,
    ContextBundle,
    ContextDecision,
    ContextItemCandidate,
    ContextSelectionReason,
    ContextSourceLabel,
    ContextVisibility,
    SelectedContextEntry,
    TaskContextAssemblyRequest,
    TaskContextAssemblyResult,
    ToolAuthorization,
)
from ndt_agents.contracts.v1 import ArtifactRef, DataClassification, TaskContext, TenantScope

_CLASSIFICATION_ORDER = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class ContextAssemblyError(RuntimeError):
    """Stable context-assembly failure with an actionable recovery instruction."""

    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def context_content_sha256(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(content)).hexdigest()


def task_context_manifest_sha256(context: TaskContext) -> str:
    payload = context.model_dump(mode="json", exclude={"context_manifest_sha256"})
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class _AccessInput:
    scope: TenantScope
    visibility: ContextVisibility
    required_roles: tuple[str, ...]
    required_permissions: tuple[str, ...]
    classification: DataClassification


class TaskContextAssembler:
    """Create one minimal immutable context and a non-content decision report."""

    def assemble(self, request: TaskContextAssemblyRequest) -> TaskContextAssemblyResult:
        scope = _canonical_scope(request.scope)
        self._validate_request(request)
        decisions: list[ContextDecision] = []
        entries = self._select_entries(request, scope, decisions)
        artifacts = self._select_artifacts(request, scope, decisions)
        tools = self._select_tools(request, scope, decisions)
        selected_content_bytes = sum(entry.content_size_bytes for entry in entries)
        authorization_sha256 = self._authorization_sha256(request, scope)
        bundle = ContextBundle(
            policy_version=request.policy.policy_version,
            authorization_sha256=authorization_sha256,
            selected_content_bytes=selected_content_bytes,
            entries=entries,
        )
        placeholder = TaskContext(
            task_id=request.task_id,
            scope=scope,
            task_class=request.task_class,
            goal=request.goal,
            success_criteria=request.success_criteria,
            risk_level=request.risk_level,
            dependency_data={"context_bundle": bundle.model_dump(mode="json")},
            context_manifest_sha256="0" * 64,
            artifacts=artifacts,
            skill_versions=dict(sorted(request.skill_versions.items())),
            prompt_versions=dict(sorted(request.prompt_versions.items())),
            model_versions=dict(sorted(request.model_versions.items())),
            knowledge_versions=tuple(sorted(set(request.knowledge_versions))),
            allowed_tools=tools,
            budget=request.budget,
            output_schema_id=request.output_schema_id,
            review_checklist=request.review_checklist,
            created_at=request.created_at,
        )
        context = placeholder.model_copy(
            update={"context_manifest_sha256": task_context_manifest_sha256(placeholder)}
        )
        return TaskContextAssemblyResult(
            context=context,
            policy_version=request.policy.policy_version,
            selected_content_bytes=selected_content_bytes,
            decisions=tuple(
                sorted(decisions, key=lambda item: (item.candidate_kind, item.candidate_id))
            ),
        )

    @staticmethod
    def _validate_request(request: TaskContextAssemblyRequest) -> None:
        if request.budget.task_class != request.task_class:
            raise ContextAssemblyError(
                code="CONTEXT_BUDGET_CLASS_MISMATCH",
                message="The context request and budget use different task classes.",
                next_action="Select the versioned budget policy for the active task class.",
            )
        candidate_bytes = 0
        for candidate in request.candidates:
            if candidate.content_sha256 != context_content_sha256(candidate.content):
                raise ContextAssemblyError(
                    code="CONTEXT_CONTENT_HASH_MISMATCH",
                    message="A context candidate failed content-integrity validation.",
                    next_action="Rebuild the candidate from its verified source content.",
                )
            candidate_bytes += len(canonical_json_bytes(candidate.content))
        if candidate_bytes > request.policy.max_candidate_content_bytes:
            raise ContextAssemblyError(
                code="CONTEXT_CANDIDATE_INPUT_OVERFLOW",
                message="Context candidates exceed the active bounded-input policy.",
                next_action="Move large content to authorized artifacts before assembly.",
            )

    def _select_entries(
        self,
        request: TaskContextAssemblyRequest,
        scope: TenantScope,
        decisions: list[ContextDecision],
    ) -> tuple[SelectedContextEntry, ...]:
        eligible: list[ContextItemCandidate] = []
        for candidate in request.candidates:
            access_reason = self._access_reason(
                _AccessInput(
                    scope=candidate.scope,
                    visibility=candidate.visibility,
                    required_roles=candidate.required_roles,
                    required_permissions=candidate.required_permissions,
                    classification=candidate.classification,
                ),
                request,
                scope,
            )
            if access_reason is None and not candidate.protected:
                if candidate.relevance_score < request.policy.minimum_relevance:
                    access_reason = ContextSelectionReason.IRRELEVANT
            if access_reason is not None:
                decisions.append(
                    ContextDecision(
                        candidate_kind="ITEM",
                        candidate_id=candidate.item_id,
                        reason=access_reason,
                    )
                )
                continue
            eligible.append(candidate)

        groups: dict[str, list[ContextItemCandidate]] = {}
        for candidate in eligible:
            groups.setdefault(candidate.content_sha256, []).append(candidate)
        entries = tuple(self._merge_group(group) for group in groups.values())
        ordered = tuple(
            sorted(
                entries,
                key=lambda item: (
                    not item.protected,
                    -item.relevance_score,
                    -max(source.observed_at.timestamp() for source in item.sources),
                    item.content_sha256,
                ),
            )
        )
        protected = tuple(entry for entry in ordered if entry.protected)
        protected_bytes = sum(entry.content_size_bytes for entry in protected)
        if (
            len(protected) > request.policy.max_selected_items
            or protected_bytes > request.policy.max_selected_content_bytes
        ):
            raise ContextAssemblyError(
                code="CONTEXT_PROTECTED_OVERFLOW",
                message="Protected context exceeds the active lossless context policy.",
                next_action=(
                    "Increase the approved context budget or move large content to an "
                    "authorized artifact."
                ),
            )

        selected: list[SelectedContextEntry] = []
        selected_bytes = 0
        for entry in ordered:
            exclusion_reason: ContextSelectionReason | None = None
            if len(selected) >= request.policy.max_selected_items:
                exclusion_reason = ContextSelectionReason.LIMIT_EXCLUDED
            elif (
                selected_bytes + entry.content_size_bytes
                > request.policy.max_selected_content_bytes
            ):
                exclusion_reason = ContextSelectionReason.BUDGET_EXCLUDED
            if exclusion_reason is not None:
                decisions.extend(
                    ContextDecision(
                        candidate_kind="ITEM",
                        candidate_id=source.item_id,
                        reason=exclusion_reason,
                    )
                    for source in entry.sources
                )
                continue
            selected.append(entry)
            selected_bytes += entry.content_size_bytes
            for index, source in enumerate(entry.sources):
                decisions.append(
                    ContextDecision(
                        candidate_kind="ITEM",
                        candidate_id=source.item_id,
                        reason=(
                            ContextSelectionReason.SELECTED
                            if index == 0
                            else ContextSelectionReason.DEDUPLICATED
                        ),
                    )
                )
        return tuple(selected)

    @staticmethod
    def _merge_group(group: Sequence[ContextItemCandidate]) -> SelectedContextEntry:
        ordered = tuple(sorted(group, key=lambda item: item.item_id))
        first = ordered[0]
        return SelectedContextEntry(
            content=first.content,
            content_sha256=first.content_sha256,
            classification=max(
                (item.classification for item in ordered), key=_CLASSIFICATION_ORDER.__getitem__
            ),
            relevance_score=max(item.relevance_score for item in ordered),
            protected=any(item.protected for item in ordered),
            content_size_bytes=len(canonical_json_bytes(first.content)),
            sources=tuple(
                ContextSourceLabel(
                    item_id=item.item_id,
                    source_type=item.source_type,
                    source_ref=item.source_ref,
                    source_version=item.source_version,
                    source_sha256=item.source_sha256,
                    trust_level=item.trust_level,
                    observed_at=item.observed_at,
                )
                for item in ordered
            ),
        )

    def _select_artifacts(
        self,
        request: TaskContextAssemblyRequest,
        scope: TenantScope,
        decisions: list[ContextDecision],
    ) -> tuple[ArtifactRef, ...]:
        eligible: list[ArtifactCandidate] = []
        for candidate in request.artifact_candidates:
            candidate_id = str(candidate.artifact.artifact_id)
            access_reason = self._access_reason(
                _AccessInput(
                    scope=candidate.artifact.scope,
                    visibility=candidate.visibility,
                    required_roles=candidate.required_roles,
                    required_permissions=candidate.required_permissions,
                    classification=candidate.artifact.classification,
                ),
                request,
                scope,
            )
            if access_reason is None and not candidate.protected:
                if candidate.relevance_score < request.policy.minimum_relevance:
                    access_reason = ContextSelectionReason.IRRELEVANT
            if access_reason is not None:
                decisions.append(
                    ContextDecision(
                        candidate_kind="ARTIFACT",
                        candidate_id=candidate_id,
                        reason=access_reason,
                    )
                )
                continue
            eligible.append(candidate)
        ordered = sorted(
            eligible,
            key=lambda item: (
                not item.protected,
                -item.relevance_score,
                str(item.artifact.artifact_id),
            ),
        )
        if sum(candidate.protected for candidate in ordered) > request.policy.max_artifacts:
            raise ContextAssemblyError(
                code="CONTEXT_PROTECTED_ARTIFACT_OVERFLOW",
                message="Protected artifact references exceed the active context policy.",
                next_action=(
                    "Increase the approved artifact-reference limit or reduce the protected set."
                ),
            )
        selected = ordered[: request.policy.max_artifacts]
        selected_ids = {item.artifact.artifact_id for item in selected}
        for candidate in ordered:
            decisions.append(
                ContextDecision(
                    candidate_kind="ARTIFACT",
                    candidate_id=str(candidate.artifact.artifact_id),
                    reason=(
                        ContextSelectionReason.SELECTED
                        if candidate.artifact.artifact_id in selected_ids
                        else ContextSelectionReason.LIMIT_EXCLUDED
                    ),
                )
            )
        return tuple(item.artifact for item in selected)

    def _select_tools(
        self,
        request: TaskContextAssemblyRequest,
        scope: TenantScope,
        decisions: list[ContextDecision],
    ) -> tuple[str, ...]:
        authorizations = {item.tool_name: item for item in request.tool_authorizations}
        requested = set(request.requested_tools)
        selected: list[str] = []
        for tool_name in sorted(requested):
            authorization = authorizations.get(tool_name)
            if authorization is None:
                decisions.append(
                    ContextDecision(
                        candidate_kind="TOOL",
                        candidate_id=tool_name,
                        reason=ContextSelectionReason.UNREGISTERED,
                    )
                )
                continue
            reason = self._tool_access_reason(authorization, request, scope)
            if reason is None:
                selected.append(tool_name)
                reason = ContextSelectionReason.SELECTED
            decisions.append(
                ContextDecision(candidate_kind="TOOL", candidate_id=tool_name, reason=reason)
            )
        for tool_name in sorted(set(authorizations) - requested):
            decisions.append(
                ContextDecision(
                    candidate_kind="TOOL",
                    candidate_id=tool_name,
                    reason=ContextSelectionReason.NOT_REQUESTED,
                )
            )
        return tuple(selected)

    def _tool_access_reason(
        self,
        authorization: ToolAuthorization,
        request: TaskContextAssemblyRequest,
        scope: TenantScope,
    ) -> ContextSelectionReason | None:
        return self._access_reason(
            _AccessInput(
                scope=authorization.scope,
                visibility=authorization.visibility,
                required_roles=authorization.required_roles,
                required_permissions=authorization.required_permissions,
                classification=DataClassification.PUBLIC,
            ),
            request,
            scope,
        )

    @staticmethod
    def _access_reason(
        access: _AccessInput,
        request: TaskContextAssemblyRequest,
        scope: TenantScope,
    ) -> ContextSelectionReason | None:
        if access.scope.tenant_id != scope.tenant_id:
            return ContextSelectionReason.TENANT_DENIED
        if access.scope.project_id != scope.project_id:
            return ContextSelectionReason.PROJECT_DENIED
        if access.visibility is ContextVisibility.USER and access.scope.user_id != scope.user_id:
            return ContextSelectionReason.USER_DENIED
        if access.scope.permission_version != scope.permission_version:
            return ContextSelectionReason.PERMISSION_VERSION_STALE
        if not set(access.required_roles) <= set(scope.role_codes):
            return ContextSelectionReason.ROLE_DENIED
        if not set(access.required_permissions) <= set(request.granted_permissions):
            return ContextSelectionReason.PERMISSION_DENIED
        if _CLASSIFICATION_ORDER[access.classification] > _CLASSIFICATION_ORDER[request.clearance]:
            return ContextSelectionReason.CLASSIFICATION_DENIED
        return None

    @staticmethod
    def _authorization_sha256(request: TaskContextAssemblyRequest, scope: TenantScope) -> str:
        payload = {
            "scope": scope.model_dump(mode="json"),
            "granted_permissions": sorted(set(request.granted_permissions)),
            "clearance": request.clearance.value,
            "policy_version": request.policy.policy_version,
        }
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _canonical_scope(scope: TenantScope) -> TenantScope:
    return scope.model_copy(update={"role_codes": tuple(sorted(set(scope.role_codes)))})
