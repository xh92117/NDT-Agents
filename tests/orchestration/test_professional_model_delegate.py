"""S6-02-PRO-LIVE bounded Technical QA and Review Agent model tests."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ndt_agents.client import ClientTaskClass, WorkbenchRuntime
from ndt_agents.client.execution import ProfessionalWorkbenchExecutor
from ndt_agents.client.service import InMemoryTaskRepository
from ndt_agents.contracts.v1 import ReviewDecision
from ndt_agents.models.inference import (
    ModelInferenceError,
    ModelMetric,
    ModelProviderReply,
    ModelProviderRequest,
    ModelProviderStatus,
)
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import ChildInput
from ndt_agents.orchestration.models import DispatchPlan, ProfessionalAssignment, RouteKind
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings
from tests.client.test_general_model_workbench import local_settings
from tests.client.test_web_workbench import (
    SCOPE,
    create_request,
    headers,
    identity,
    signing_material,
    token,
)

ROOT = Path(__file__).resolve().parents[2]


class ProfessionalReviewProvider:
    def __init__(
        self,
        *,
        review_decision: ReviewDecision = ReviewDecision.PASS,
        malformed_review: bool = False,
    ) -> None:
        self.review_decision = review_decision
        self.malformed_review = malformed_review
        self.requests: list[ModelProviderRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    async def infer(self, request: ModelProviderRequest) -> object:
        self.requests.append(request)
        if request.output_schema_id == "technical-qa-agent-result@1.0.0":
            context = request.parameters["child_context"]
            assert isinstance(context, dict)
            output: dict[str, Any] = {
                "schema_version": "1.0.0",
                "task_id": context["parent_task_id"],
                "run_id": context["run_id"],
                "status": "SUCCESS",
                "summary": "Synthetic Technical QA limitations were identified.",
                "structured_data": {
                    "answer_scope": "SYNTHETIC_LIMITATIONS_ONLY",
                    "observations": ["No approved external evidence was supplied."],
                    "limitations": ["Not eligible for a technical or formal conclusion."],
                    "next_action": "Obtain approved evidence before technical use.",
                },
                "artifacts": [],
                "evidence": [],
                "confidence": Decimal("0.75"),
                "issues": [],
                "retryable": False,
                "failure_code": None,
                "completed_at": "2026-08-27T00:00:00Z",
            }
        else:
            assert request.output_schema_id == "review-agent-result@1.0.0"
            context = request.parameters["review_context"]
            assert isinstance(context, dict)
            decision = self.review_decision.value
            findings = (
                []
                if self.review_decision is ReviewDecision.PASS
                else [
                    {
                        "code": "MODEL_REVIEW_BLOCKED",
                        "severity": "ERROR",
                        "message": "The synthetic result is not aggregation ready.",
                        "affected_path": "summary",
                        "next_action": "Preserve the result for human inspection.",
                    }
                ]
            )
            output = {
                "schema_version": "1.0.0",
                "review_id": str(uuid4()),
                "task_id": context["task_id"],
                "target_run_id": context["review_target_run_id"],
                "target_sha256": context["review_target_sha256"],
                "reviewer_version": context["reviewer_version"],
                "decision": decision,
                "findings": findings,
                "correction_count": context["correction_count"],
                "completed_at": "2026-08-27T00:00:01Z",
            }
            if self.malformed_review:
                output.pop("decision")
        return ModelProviderReply(
            call_id=request.call_id,
            provider_request_sha256=request.provider_request_sha256,
            provider_id=request.provider_id,
            provider_version=request.provider_version,
            endpoint_id=request.endpoint_id,
            model_id=request.model_id,
            model_snapshot=request.model_snapshot,
            provider_request_id=f"offline-professional-{self.calls}",
            status=ModelProviderStatus.SUCCESS,
            output=output,
            artifacts=(),
            input_tokens=300,
            output_tokens=100,
            confidence=Decimal("0.9"),
            metrics=(ModelMetric(metric="quality_score", value=Decimal("1")),),
            finish_reason="stop",
            physical_network_calls=1,
        )


def professional_settings(
    tmp_path: Path,
    *,
    match_workbench_scope: bool = True,
) -> AppSettings:
    base = local_settings(tmp_path, match_workbench_scope=match_workbench_scope)
    assert base.agent_config_path is not None
    agent_path = Path(base.agent_config_path)
    agent_path.write_text(
        agent_path.read_text(encoding="utf-8")
        + """\
    - name: technical_qa
      kind: PROFESSIONAL
      description: Synthetic Technical QA limitations path.
      model: reference
      prompt: technical_qa
      skill_version: technical-qa-1.0.0
      graph_version: child-react-1.0.0
      allowed_tools: []
      max_turns: 3
      timeout_ms: 90000
""",
        encoding="utf-8",
    )
    values = base.model_dump()
    values["professional_model_delegate_enabled"] = True
    return AppSettings.model_validate(values)


def test_professional_model_setting_is_default_off_and_requires_general(
    tmp_path: Path,
) -> None:
    assert AppSettings().professional_model_delegate_enabled is False
    values = local_settings(tmp_path).model_dump()
    values.update(
        {
            "professional_model_delegate_enabled": True,
            "general_model_delegate_enabled": False,
            "deepseek_policy_acknowledgement": None,
        }
    )
    with pytest.raises(ValidationError):
        AppSettings.model_validate(values)


def test_p1_runs_exact_professional_and_review_calls_before_main_aggregation(
    tmp_path: Path,
) -> None:
    private_key, jwks = signing_material()
    provider = ProfessionalReviewProvider()
    app = create_app(
        professional_settings(tmp_path),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    request = create_request(
        task_class=ClientTaskClass.PROFESSIONAL_SYNC,
        goal="State only the limits of one synthetic Technical QA result.",
        success_criteria=("Avoid a formal conclusion", "Require approved evidence"),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=request.model_dump(mode="json"),
        )
        events = client.get(
            "/v1/workbench/events",
            params={"task_id": response.json()["task_id"], "after_sequence": 0},
            headers=headers(token(private_key)),
        )
        completed = client.get(
            "/v1/workbench/task",
            params={"task_id": response.json()["task_id"]},
            headers=headers(token(private_key)),
        )
        capabilities = client.get("/v1/workbench/capabilities", headers=headers(token(private_key)))

    assert response.json()["state"] == "ACCEPTED"
    assert completed.json()["state"] == "SUCCEEDED", (
        events.text,
        app.state.professional_model_delegate.last_error_code,
        app.state.review_model_delegate.last_error_code,
    )
    assert capabilities.json()["task_classes"] == ["G0", "P1"]
    assert provider.calls == 2
    professional, review = provider.requests
    assert professional.output_schema_id == "technical-qa-agent-result@1.0.0"
    assert professional.canonical_prompt_mode == "FULL"
    assert professional.reasoning_mode == "PROVIDER_DEFAULT"
    assert professional.maximum_input_tokens == 3_600
    assert professional.maximum_output_tokens == 2_400
    assert "exact response_contract" in professional.instruction_text
    assert "within 1200 completion tokens" in professional.instruction_text
    assert "Produce `TechnicalQACandidate@1.0.0`" not in professional.instruction_text
    professional_properties = professional.output_schema["properties"]
    assert professional_properties["summary"]["maxLength"] == 600
    structured_properties = professional_properties["structured_data"]["properties"]
    assert structured_properties["observations"]["maxItems"] == 3
    assert structured_properties["observations"]["items"]["maxLength"] == 300
    assert structured_properties["limitations"]["maxItems"] == 3
    assert structured_properties["limitations"]["items"]["maxLength"] == 300
    assert structured_properties["next_action"]["maxLength"] == 300
    assert review.output_schema_id == "review-agent-result@1.0.0"
    assert review.canonical_prompt_mode == "IDENTITY_ONLY"
    assert review.reasoning_mode == "DISABLED"
    assert review.maximum_input_tokens == 3_000
    assert review.maximum_output_tokens == 1_000
    assert "exact response_contract" in review.instruction_text
    assert "within 300 completion tokens" in review.instruction_text
    review_properties = review.output_schema["properties"]
    assert review_properties["findings"]["maxItems"] == 3
    finding_properties = review_properties["findings"]["items"]["properties"]
    assert finding_properties["message"]["maxLength"] == 500
    assert finding_properties["affected_path"]["maxLength"] == 256
    assert finding_properties["next_action"]["maxLength"] == 300
    assert (
        sum(
            request.maximum_input_tokens + request.maximum_output_tokens
            for request in provider.requests
        )
        == 10_000
    )
    assert professional.parameters["child_context"]["formal_use"] is False
    assert professional.parameters["child_context"]["tools_allowed"] == []
    assert review.parameters["review_context"]["read_only"] is True
    assert review.parameters["review_context"]["user_delivery_allowed"] is False
    assert set(review.parameters["review_context"]) == {
        "context_manifest_sha256",
        "correction_count",
        "read_only",
        "review_checklist",
        "review_target_run_id",
        "review_target_sha256",
        "reviewer_version",
        "scope",
        "targets",
        "task_id",
        "user_delivery_allowed",
    }
    assert app.state.professional_model_delegate.calls == 1
    assert app.state.review_model_delegate.calls == 1
    assert app.state.professional_workbench_executor.last_review_manifest_sha256 is not None
    assert events.text.count("event: task-event") == 5


@pytest.mark.parametrize(
    ("decision", "malformed"),
    ((ReviewDecision.CONFLICT, False), (ReviewDecision.PASS, True)),
)
def test_non_pass_or_malformed_review_never_reaches_main_aggregation(
    tmp_path: Path,
    decision: ReviewDecision,
    malformed: bool,
) -> None:
    private_key, jwks = signing_material()
    provider = ProfessionalReviewProvider(
        review_decision=decision,
        malformed_review=malformed,
    )
    app = create_app(
        professional_settings(tmp_path),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
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
        completed = client.get(
            "/v1/workbench/task",
            params={"task_id": response.json()["task_id"]},
            headers=headers(token(private_key)),
        )

    assert response.json()["state"] == "ACCEPTED"
    assert completed.json()["state"] == "FAILED"
    assert provider.calls == 2
    assert app.state.professional_workbench_executor.last_review_manifest_sha256 is None
    assert '"state":"SUCCEEDED"' not in events.text
    assert "offline-placeholder" not in response.text + events.text + completed.text


def test_professional_delegate_has_no_test_or_live_tool_dependency() -> None:
    source = (ROOT / "src/ndt_agents/orchestration/professional_model_delegate.py").read_text(
        encoding="utf-8"
    )
    assert "from tests" not in source
    assert "tools.deepseek" not in source


def test_professional_token_reservation_denies_before_provider_call(tmp_path: Path) -> None:
    _, jwks = signing_material()
    provider = ProfessionalReviewProvider()
    app = create_app(
        professional_settings(tmp_path),
        configure_logs=False,
        identity=identity(jwks),
        workbench=WorkbenchRuntime(),
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    repository = InMemoryTaskRepository()
    task = repository.create(
        SCOPE,
        create_request(task_class=ClientTaskClass.PROFESSIONAL_SYNC),
    )
    task_context = ProfessionalWorkbenchExecutor(
        app.state.reviewed_orchestration_runtime
    )._task_context(task)
    total_tokens = task_context.budget.total_tokens.model_copy(update={"active": 5_999})
    task_context = task_context.model_copy(
        update={"budget": task_context.budget.model_copy(update={"total_tokens": total_tokens})}
    )
    context = ChildContextFactory(app.state.agent_runtime.build_agent_registry()).prepare(
        task_context,
        DispatchPlan(
            task_id=task.task_id,
            route=RouteKind.ONE_PROFESSIONAL_SYNC_REVIEW,
            general_agent=False,
            professional_assignments=(
                ProfessionalAssignment(
                    assignment_id="technical_qa",
                    agent_type="technical_qa",
                ),
            ),
            asynchronous=False,
            review_required=True,
            human_required=False,
        ),
        professional_inputs=(
            ChildInput(
                assignment_id="technical_qa",
                goal=task.goal,
                success_criteria=task.success_criteria,
            ),
        ),
    )[0]

    with pytest.raises(ModelInferenceError) as captured:
        asyncio.run(
            app.state.professional_model_delegate.execute(
                context,
                app.state.agent_runtime.prompt_instruction("technical_qa"),
            )
        )

    assert captured.value.code == "BUDGET_ACTIVE_LIMIT_EXCEEDED"
    assert provider.calls == 0
