"""S6-02-PRO-APP authenticated P1 professional and review Web path tests."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ndt_agents.client import ClientTaskClass, WorkbenchRuntime
from ndt_agents.contracts.v1 import AgentResult, ReviewDecision
from ndt_agents.models.config import load_model_runtime_configuration
from ndt_agents.models.instructions import ApplicationInstruction
from ndt_agents.orchestration.agent_config import load_agent_runtime_configuration
from ndt_agents.orchestration.child_models import ChildAgentKind, ChildTaskContext
from ndt_agents.orchestration.configured_review_runtime import ConfiguredReviewBindings
from ndt_agents.orchestration.prompt_registry import load_prompt_registry
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings
from tests.client.test_web_workbench import (
    create_request,
    headers,
    identity,
    signing_material,
    token,
)
from tests.orchestration.test_configured_review_runtime import (
    RESULT,
    REVIEWER_DEFINITION,
    CorrectorProbe,
    ReviewerProbe,
)

ROOT = Path(__file__).resolve().parents[2]
MODEL_CONFIG = ROOT / "config/runtime/model-bindings.example.yaml"
AGENT_CONFIG = ROOT / "config/runtime/agent-runtime.example.yaml"
PROMPT_CONFIG = ROOT / "prompts/professional/catalog.v1.yaml"


class ChildProbe:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.contexts: list[ChildTaskContext] = []
        self.instructions: list[ApplicationInstruction] = []

    async def execute(
        self,
        context: ChildTaskContext,
        instruction: ApplicationInstruction,
    ) -> Mapping[str, Any]:
        self.contexts.append(context)
        self.instructions.append(instruction)
        if self.fail:
            raise RuntimeError("deterministic professional failure")
        return (
            AgentResult.model_validate(RESULT)
            .model_copy(
                update={
                    "task_id": context.parent_task_id,
                    "run_id": context.run_id,
                    "summary": "Reviewed synthetic Technical QA result.",
                    "artifacts": (),
                    "evidence": (),
                }
            )
            .model_dump(mode="json")
        )


def test_authenticated_p1_runs_one_technical_qa_and_review_before_success() -> None:
    private_key, jwks = signing_material()
    reviewer = ReviewerProbe()
    models = load_model_runtime_configuration(MODEL_CONFIG, environ={})
    prompts = load_prompt_registry(PROMPT_CONFIG)
    runtime = load_agent_runtime_configuration(
        AGENT_CONFIG,
        model_runtime=models,
        prompt_registry=prompts,
    )
    children = {profile.name: ChildProbe() for profile in runtime.profiles}
    professional_names = {
        profile.name for profile in runtime.profiles if profile.kind is ChildAgentKind.PROFESSIONAL
    }
    bindings = ConfiguredReviewBindings(
        runtime,
        reviewer=reviewer,
        reviewer_definition=REVIEWER_DEFINITION,
        correctors={name: CorrectorProbe() for name in professional_names},
    )
    app = create_app(
        AppSettings(
            model_config_path=str(MODEL_CONFIG),
            prompt_config_path=str(PROMPT_CONFIG),
            agent_config_path=str(AGENT_CONFIG),
        ),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={},
        agent_delegates=children,
        review_bindings=bindings,
    )
    request = create_request(
        task_class=ClientTaskClass.PROFESSIONAL_SYNC,
        goal="Answer one synthetic Technical QA question.",
        success_criteria=("Preserve synthetic scope", "Disclose non-formal use"),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=request.model_dump(mode="json"),
        )
        replay = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=request.model_dump(mode="json"),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": response.json()["task_id"], "after_sequence": 0},
            headers=headers(token(private_key)),
        )
        general = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=create_request(
                task_class=ClientTaskClass.GENERAL,
                idempotency_key="workbench-general-reviewed-0001",
            ).model_dump(mode="json"),
        )
        capabilities = client.get(
            "/v1/workbench/capabilities",
            headers=headers(token(private_key)),
        )

    assert response.status_code == 202
    assert response.json()["state"] == "SUCCEEDED"
    assert response.json()["review_required"] is True
    assert response.json()["review_completed"] is True
    assert response.json()["formal_use_allowed"] is False
    assert replay.json()["task_id"] == response.json()["task_id"]
    assert replay.json()["state"] == "SUCCEEDED"
    assert general.json()["state"] == "SUCCEEDED"
    assert capabilities.json()["task_classes"] == ["G0", "P1"]
    assert len(children["technical_qa"].contexts) == 1
    assert len(children["general"].contexts) == 1
    assert all(
        not child.contexts
        for name, child in children.items()
        if name not in {"general", "technical_qa"}
    )
    child_context = children["technical_qa"].contexts[0]
    assert child_context.agent_type == "technical_qa"
    assert child_context.task_class == "P1"
    assert child_context.scope.tenant_id.hex == response.json()["scope"]["tenant_id"].replace(
        "-", ""
    )
    assert child_context.allowed_tools == ()
    assert child_context.artifacts == ()
    assert len(reviewer.contexts) == 1
    assert reviewer.contexts[0].allowed_tools == ()
    assert events.text.count("event: task-event") == 5
    for sequence in range(1, 6):
        assert f'"sequence":{sequence}' in events.text
    assert events.text.index('"state":"REVIEW_REQUIRED"') < events.text.index('"state":"SUCCEEDED"')
    executor = app.state.professional_workbench_executor
    assert executor.calls == 1
    assert executor.last_review_manifest_sha256 is not None
    assert executor.last_error_code is None


def test_non_pass_review_fails_without_main_result() -> None:
    private_key, jwks = signing_material()
    reviewer = ReviewerProbe(lambda _context: ReviewDecision.CONFLICT)
    models = load_model_runtime_configuration(MODEL_CONFIG, environ={})
    prompts = load_prompt_registry(PROMPT_CONFIG)
    runtime = load_agent_runtime_configuration(
        AGENT_CONFIG,
        model_runtime=models,
        prompt_registry=prompts,
    )
    children = {profile.name: ChildProbe() for profile in runtime.profiles}
    professional_names = {
        profile.name for profile in runtime.profiles if profile.kind is ChildAgentKind.PROFESSIONAL
    }
    bindings = ConfiguredReviewBindings(
        runtime,
        reviewer=reviewer,
        reviewer_definition=REVIEWER_DEFINITION,
        correctors={name: CorrectorProbe() for name in professional_names},
    )
    app = create_app(
        AppSettings(
            model_config_path=str(MODEL_CONFIG),
            prompt_config_path=str(PROMPT_CONFIG),
            agent_config_path=str(AGENT_CONFIG),
        ),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={},
        agent_delegates=children,
        review_bindings=bindings,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=create_request(task_class=ClientTaskClass.PROFESSIONAL_SYNC).model_dump(
                mode="json"
            ),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": response.json()["task_id"], "after_sequence": 0},
            headers=headers(token(private_key)),
        )

    assert response.json()["state"] == "FAILED"
    assert len(children["technical_qa"].contexts) == 1
    assert len(reviewer.contexts) == 1
    assert "REVIEW_CONFLICT" in events.text
    assert '"state":"SUCCEEDED"' not in events.text
    assert app.state.professional_workbench_executor.last_review_manifest_sha256 is None


def test_non_p1_task_is_denied_before_child_or_review() -> None:
    private_key, jwks = signing_material()
    reviewer = ReviewerProbe()
    models = load_model_runtime_configuration(MODEL_CONFIG, environ={})
    prompts = load_prompt_registry(PROMPT_CONFIG)
    runtime = load_agent_runtime_configuration(
        AGENT_CONFIG,
        model_runtime=models,
        prompt_registry=prompts,
    )
    children = {profile.name: ChildProbe() for profile in runtime.profiles}
    professional_names = {
        profile.name for profile in runtime.profiles if profile.kind is ChildAgentKind.PROFESSIONAL
    }
    app = create_app(
        AppSettings(
            model_config_path=str(MODEL_CONFIG),
            prompt_config_path=str(PROMPT_CONFIG),
            agent_config_path=str(AGENT_CONFIG),
        ),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={},
        agent_delegates=children,
        review_bindings=ConfiguredReviewBindings(
            runtime,
            reviewer=reviewer,
            reviewer_definition=REVIEWER_DEFINITION,
            correctors={name: CorrectorProbe() for name in professional_names},
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=create_request(task_class=ClientTaskClass.PROFESSIONAL_ASYNC).model_dump(
                mode="json"
            ),
        )

    assert response.json()["state"] == "FAILED"
    assert all(not child.contexts for child in children.values())
    assert reviewer.contexts == []
    assert app.state.professional_workbench_executor.calls == 0
