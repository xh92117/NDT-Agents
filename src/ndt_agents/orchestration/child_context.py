"""Build minimal immutable child contexts from verified dispatch plans."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from pydantic import ValidationError

from ndt_agents.context.assembly import task_context_manifest_sha256
from ndt_agents.context.models import ContextBundle, SelectedContextEntry
from ndt_agents.contracts.v1 import ArtifactRef, TaskContext
from ndt_agents.orchestration.child_models import (
    AgentDefinition,
    ChildAgentKind,
    ChildInput,
    ChildSideEffectClass,
    ChildTaskContext,
)
from ndt_agents.orchestration.models import DispatchPlan
from ndt_agents.orchestration.registry import AgentRegistry, AgentRegistryError


def child_context_manifest_sha256(context: ChildTaskContext) -> str:
    """Hash the complete child context except its self-referential manifest field."""

    payload = context.model_dump(mode="json", exclude={"context_manifest_sha256"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ChildContextFactory:
    """Filter parent state into one private context per registered child."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def prepare(
        self,
        task: TaskContext,
        dispatch: DispatchPlan,
        *,
        professional_inputs: tuple[ChildInput, ...] = (),
    ) -> tuple[ChildTaskContext, ...]:
        if dispatch.task_id != task.task_id:
            raise AgentRegistryError(
                code="CHILD_TASK_MISMATCH",
                message="The dispatch does not belong to the active parent task.",
                next_action="Prepare child contexts from the active verified dispatch.",
            )
        if dispatch.general_agent:
            if dispatch.professional_assignments or professional_inputs:
                raise AgentRegistryError(
                    code="CHILD_INPUT_MISMATCH",
                    message="General dispatch cannot contain professional inputs.",
                    next_action="Use only the General child for a general dispatch.",
                )
            definition = self._registry.require("general", ChildAgentKind.GENERAL)
            child_input = ChildInput(
                assignment_id="general",
                goal=task.goal,
                success_criteria=task.success_criteria,
                context_entry_sha256s=tuple(
                    entry.content_sha256 for entry in self._context_bundle(task).entries
                ),
                artifact_ids=tuple(artifact.artifact_id for artifact in task.artifacts),
                requested_tools=task.allowed_tools,
                side_effect_class=ChildSideEffectClass.READ_ONLY,
            )
            return (
                self._build(
                    task=task,
                    definition=definition,
                    child_input=child_input,
                    dependencies=(),
                ),
            )

        if not dispatch.professional_assignments or not dispatch.review_required:
            raise AgentRegistryError(
                code="CHILD_DISPATCH_INVALID",
                message="Professional dispatch requires assignments and review.",
                next_action="Use a verified Main Graph professional dispatch.",
            )

        assignments = {item.assignment_id: item for item in dispatch.professional_assignments}
        inputs = {item.assignment_id: item for item in professional_inputs}
        if set(assignments) != set(inputs) or len(inputs) != len(professional_inputs):
            raise AgentRegistryError(
                code="CHILD_INPUT_MISMATCH",
                message="Professional inputs must match the verified assignments exactly.",
                next_action="Provide one minimal input for every professional assignment.",
            )
        contexts = []
        for assignment in dispatch.professional_assignments:
            definition = self._registry.require(assignment.agent_type, ChildAgentKind.PROFESSIONAL)
            contexts.append(
                self._build(
                    task=task,
                    definition=definition,
                    child_input=inputs[assignment.assignment_id],
                    dependencies=assignment.depends_on,
                )
            )
        return tuple(contexts)

    @staticmethod
    def _context_bundle(task: TaskContext) -> ContextBundle:
        raw_bundle = task.dependency_data.get("context_bundle")
        if raw_bundle is None:
            return ContextBundle(
                policy_version="legacy-empty",
                authorization_sha256="0" * 64,
                selected_content_bytes=0,
                entries=(),
            )
        if task_context_manifest_sha256(task) != task.context_manifest_sha256:
            raise AgentRegistryError(
                code="CHILD_CONTEXT_MANIFEST_INVALID",
                message="The parent context manifest failed integrity validation.",
                next_action="Reassemble the parent TaskContext from verified source candidates.",
            )
        try:
            return ContextBundle.model_validate(raw_bundle)
        except ValidationError as exc:
            raise AgentRegistryError(
                code="CHILD_CONTEXT_BUNDLE_INVALID",
                message="The parent context bundle failed strict validation.",
                next_action="Reassemble the parent TaskContext with the supported context schema.",
            ) from exc

    @classmethod
    def _select_context_entries(
        cls, task: TaskContext, content_sha256s: tuple[str, ...]
    ) -> tuple[SelectedContextEntry, ...]:
        bundle = cls._context_bundle(task)
        available = {entry.content_sha256: entry for entry in bundle.entries}
        requested = set(content_sha256s)
        if len(requested) != len(content_sha256s) or not requested <= set(available):
            raise AgentRegistryError(
                code="CHILD_CONTEXT_ENTRY_DENIED",
                message="A requested context entry is not in the authorized parent bundle.",
                next_action="Use only content hashes from the verified parent context bundle.",
            )
        return tuple(available[content_sha256] for content_sha256 in content_sha256s)

    @staticmethod
    def _select_artifacts(
        task: TaskContext, artifact_ids: tuple[UUID, ...]
    ) -> tuple[ArtifactRef, ...]:
        requested = set(artifact_ids)
        available = {artifact.artifact_id: artifact for artifact in task.artifacts}
        if not requested <= set(available):
            raise AgentRegistryError(
                code="CHILD_ARTIFACT_DENIED",
                message="A requested child artifact is not in the authorized parent context.",
                next_action="Use only authorized parent artifact references.",
            )
        if any(
            available[artifact_id].scope.tenant_id != task.scope.tenant_id
            or available[artifact_id].scope.project_id != task.scope.project_id
            for artifact_id in artifact_ids
        ):
            raise AgentRegistryError(
                code="CHILD_ARTIFACT_SCOPE_DENIED",
                message="A requested child artifact is outside the parent scope.",
                next_action="Use only artifacts in the active tenant and project.",
            )
        return tuple(available[artifact_id] for artifact_id in artifact_ids)

    def _build(
        self,
        *,
        task: TaskContext,
        definition: AgentDefinition,
        child_input: ChildInput,
        dependencies: tuple[str, ...],
    ) -> ChildTaskContext:
        run_id = uuid4()
        allowed = tuple(
            sorted(
                set(child_input.requested_tools)
                & set(task.allowed_tools)
                & set(definition.allowed_tools)
            )
        )
        placeholder = ChildTaskContext(
            parent_task_id=task.task_id,
            run_id=run_id,
            assignment_id=child_input.assignment_id,
            kind=definition.kind,
            agent_type=definition.agent_type,
            agent_configuration_sha256=definition.agent_configuration_sha256,
            scope=task.scope,
            task_class=task.task_class,
            goal=child_input.goal,
            success_criteria=child_input.success_criteria,
            risk_level=task.risk_level,
            context_entries=self._select_context_entries(task, child_input.context_entry_sha256s),
            artifacts=self._select_artifacts(task, child_input.artifact_ids),
            dependency_assignment_ids=dependencies,
            side_effect_class=child_input.side_effect_class,
            allowed_tools=allowed,
            skill_version=definition.skill_version,
            prompt_version=definition.prompt_version,
            model_version=definition.model_version,
            knowledge_versions=task.knowledge_versions,
            budget=task.budget,
            output_schema_id=task.output_schema_id,
            review_checklist=task.review_checklist,
            scratch_namespace=(
                f"scratch://{task.scope.tenant_id}/{task.scope.project_id}/{task.task_id}/{run_id}"
            ),
            context_manifest_sha256="0" * 64,
        )
        return placeholder.model_copy(
            update={"context_manifest_sha256": child_context_manifest_sha256(placeholder)}
        )
