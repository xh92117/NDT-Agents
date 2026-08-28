"""S6-02-WEB-AGENT-ACCEPTANCE offline multi-scenario gate."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ndt_agents.client import ClientTaskClass, InMemoryTaskRepository, WorkbenchError
from ndt_agents.client.execution import ProfessionalWorkbenchExecutor
from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.models.inference import ModelInferenceError
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import ChildInput
from ndt_agents.orchestration.models import DispatchPlan, ProfessionalAssignment, RouteKind
from ndt_agents.runtime.local_workbench import (
    LOCAL_WORKBENCH_SESSION_PATH,
    create_local_workbench_app,
)
from tests.client.test_web_stability import reviewed_local_settings
from tests.client.test_web_workbench import create_request
from tools.web_agent_acceptance import (
    FIXED_REQUESTS,
    OfflineAcceptanceProvider,
    WebAgentAcceptanceCatalog,
    create_offline_acceptance_app,
    load_acceptance_catalog,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config/acceptance/web-agent.v1.json"
LOCAL_SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
    project_id=UUID("00000000-0000-4000-8000-000000000102"),
    user_id=UUID("00000000-0000-4000-8000-000000000103"),
    role_codes=("PROJECT_OPERATOR",),
    permission_version="permissions-1",
)


def test_acceptance_catalog_is_strict_complete_and_offline() -> None:
    catalog = load_acceptance_catalog(CATALOG)
    assert catalog.schema_version == "1.0.0"
    assert catalog.catalog_version == "1.0.0"
    assert len(catalog.scenarios) == 12
    assert all(item.expected_physical_tool_calls == 0 for item in catalog.scenarios)
    assert all(item.formal_use_allowed is False for item in catalog.scenarios)
    assert all(item.external_network_allowed is False for item in catalog.scenarios)


def test_acceptance_catalog_rejects_duplicate_unsafe_or_incomplete_scenarios() -> None:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    payload["scenarios"].append(dict(payload["scenarios"][0]))
    with pytest.raises(ValidationError, match="scenario IDs must be unique"):
        WebAgentAcceptanceCatalog.model_validate(payload)

    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    payload["scenarios"][0]["expected_physical_tool_calls"] = 1
    with pytest.raises(ValidationError):
        WebAgentAcceptanceCatalog.model_validate(payload)

    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    payload["scenarios"] = payload["scenarios"][:-1]
    with pytest.raises(ValidationError, match="coverage mismatch"):
        WebAgentAcceptanceCatalog.model_validate(payload)


def _events(stream: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for block in stream.replace("\r\n", "\n").split("\n\n"):
        if "event: task-event" not in block:
            continue
        data = next(line[6:] for line in block.splitlines() if line.startswith("data: "))
        parsed = json.loads(data)
        assert isinstance(parsed, dict)
        payloads.append(parsed)
    return payloads


@pytest.mark.parametrize(
    "scenario_id",
    [
        "g0_success",
        "p1_success",
        "p1_review_conflict",
        "p1_malformed_review",
        "g0_malformed_output",
        "g0_provider_failure",
    ],
)
def test_core_web_agent_acceptance_scenarios(
    tmp_path: Path,
    scenario_id: str,
) -> None:
    catalog = load_acceptance_catalog(CATALOG)
    scenario = catalog.scenario(scenario_id)
    provider = OfflineAcceptanceProvider(scenario.provider_mode)
    app = create_local_workbench_app(
        reviewed_local_settings(tmp_path),
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    task_class = (
        ClientTaskClass.GENERAL
        if scenario.task_class == "G0"
        else ClientTaskClass.PROFESSIONAL_SYNC
    )
    request = create_request(
        task_class=task_class,
        goal=f"Run fixed SYNTHETIC acceptance scenario {scenario_id}.",
        success_criteria=("Preserve non-formal scope", "Record bounded evidence"),
        idempotency_key=f"web-agent-acceptance-{scenario_id}",
    ).model_dump(mode="json")

    with TestClient(app) as client:
        assert client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False).status_code == 303
        accepted = client.post("/v1/workbench/tasks", json=request)
        stream = client.get(
            "/v1/workbench/events",
            params={"task_id": accepted.json()["task_id"], "after_sequence": 0},
        )
        terminal = client.get(
            "/v1/workbench/task",
            params={"task_id": accepted.json()["task_id"]},
        )
        calls_before_replay = provider.calls
        replay = client.post("/v1/workbench/tasks", json=request)

    event_payloads = _events(stream.text)
    assert accepted.status_code == 202
    assert accepted.json()["state"] == "ACCEPTED"
    assert terminal.json()["state"] == scenario.expected_terminal_state
    assert replay.json() == terminal.json()
    assert provider.calls - calls_before_replay == scenario.expected_replay_provider_calls
    assert [item["state"] for item in event_payloads] == list(scenario.expected_event_states)
    assert provider.calls_for("general-agent-result@1.0.0") == (
        scenario.expected_general_provider_calls
    )
    assert provider.calls_for("technical-qa-agent-result@1.0.0") == (
        scenario.expected_professional_provider_calls
    )
    assert provider.calls_for("review-agent-result@1.0.0") == (
        scenario.expected_review_provider_calls
    )
    assert terminal.json()["formal_use_allowed"] is False
    assert "offline-placeholder" not in accepted.text + stream.text + terminal.text
    if scenario.expected_error_code is None:
        assert event_payloads[-1].get("error_code") is None
    else:
        assert event_payloads[-1]["error_code"] == scenario.expected_error_code
    if scenario.task_class == "P1":
        manifest = app.state.professional_workbench_executor.last_review_manifest_sha256
        assert (manifest is not None) == scenario.main_aggregation_required
    inferences = tuple(
        inference
        for delegate in (
            app.state.general_model_delegate,
            app.state.professional_model_delegate,
            app.state.review_model_delegate,
        )
        if delegate is not None
        for inference in (delegate.last_inference,)
        if inference is not None and inference.evidence is not None
    )
    assert sum(item.evidence.physical_tool_calls for item in inferences) == 0


def test_p1_terminal_replay_after_sqlite_restart_makes_zero_calls(tmp_path: Path) -> None:
    scenario = load_acceptance_catalog(CATALOG).scenario("p1_restart_replay")
    settings = reviewed_local_settings(tmp_path)
    first_provider = OfflineAcceptanceProvider()
    first_app = create_local_workbench_app(
        settings,
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=first_provider,
    )
    request = create_request(
        task_class=ClientTaskClass.PROFESSIONAL_SYNC,
        goal="Run the fixed SYNTHETIC restart acceptance scenario.",
        success_criteria=("Complete independent review", "Replay without execution"),
        idempotency_key="web-agent-acceptance-p1-restart",
    ).model_dump(mode="json")

    with TestClient(first_app) as client:
        client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False)
        accepted = client.post("/v1/workbench/tasks", json=request)
        stream = client.get(
            "/v1/workbench/events",
            params={"task_id": accepted.json()["task_id"], "after_sequence": 0},
        )
        terminal = client.get("/v1/workbench/task", params={"task_id": accepted.json()["task_id"]})

    replay_provider = OfflineAcceptanceProvider()
    replay_app = create_local_workbench_app(
        settings,
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=replay_provider,
    )
    with TestClient(replay_app) as client:
        client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False)
        replay = client.post("/v1/workbench/tasks", json=request)
        replay_stream = client.get(
            "/v1/workbench/events",
            params={"task_id": accepted.json()["task_id"], "after_sequence": 0},
        )

    assert terminal.json()["state"] == scenario.expected_terminal_state
    assert [item["state"] for item in _events(stream.text)] == list(scenario.expected_event_states)
    assert replay.json() == terminal.json()
    assert _events(replay_stream.text) == _events(stream.text)
    assert first_provider.calls == 2
    assert replay_provider.calls == scenario.expected_replay_provider_calls


def test_missing_local_session_denies_before_provider_call(tmp_path: Path) -> None:
    scenario = load_acceptance_catalog(CATALOG).scenario("authorization_denial")
    provider = OfflineAcceptanceProvider()
    app = create_local_workbench_app(
        reviewed_local_settings(tmp_path),
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    request = create_request(
        task_class=ClientTaskClass.GENERAL,
        idempotency_key="web-agent-acceptance-auth-denial",
    ).model_dump(mode="json")

    with TestClient(app) as client:
        denied = client.post("/v1/workbench/tasks", json=request)

    assert denied.status_code == 401
    assert denied.json()["error_code"] == scenario.expected_error_code
    assert provider.calls == 0


def test_cross_scope_task_is_hidden_without_provider_call() -> None:
    scenario = load_acceptance_catalog(CATALOG).scenario("cross_scope_denial")
    provider = OfflineAcceptanceProvider()
    repository = InMemoryTaskRepository()
    task = repository.create(
        LOCAL_SCOPE,
        create_request(
            task_class=ClientTaskClass.GENERAL,
            idempotency_key="web-agent-acceptance-cross-scope",
        ),
    )
    other_scope = LOCAL_SCOPE.model_copy(
        update={"user_id": UUID("00000000-0000-4000-8000-000000000104")}
    )

    with pytest.raises(WorkbenchError) as captured:
        repository.get(other_scope, task.task_id)

    assert captured.value.code == scenario.expected_error_code
    assert provider.calls == 0


def test_professional_budget_preflight_denies_before_provider_call(tmp_path: Path) -> None:
    scenario = load_acceptance_catalog(CATALOG).scenario("p1_budget_denial")
    provider = OfflineAcceptanceProvider()
    app = create_local_workbench_app(
        reviewed_local_settings(tmp_path),
        configure_logs=False,
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    repository = InMemoryTaskRepository()
    task = repository.create(
        LOCAL_SCOPE,
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

    assert captured.value.code == scenario.expected_error_code
    assert provider.calls == 0


def test_loopback_acceptance_composition_is_fixed_synthetic_and_zero_network(
    tmp_path: Path,
) -> None:
    catalog = load_acceptance_catalog(CATALOG)
    app = create_offline_acceptance_app(tmp_path)
    with TestClient(app) as client:
        session = client.get(LOCAL_WORKBENCH_SESSION_PATH, follow_redirects=False)
        assert session.status_code == 303
        rejected = client.post(
            "/v1/workbench/tasks",
            json=create_request(
                task_class=ClientTaskClass.GENERAL,
                goal="Changed input.",
                idempotency_key="web-agent-acceptance-rejected",
            ).model_dump(mode="json"),
        )
        results: dict[str, tuple[dict[str, object], list[dict[str, object]]]] = {}
        for task_class in ("G0", "P1"):
            goal, criteria = FIXED_REQUESTS[task_class]
            created = client.post(
                "/v1/workbench/tasks",
                json={
                    "schema_version": "1.0.0",
                    "task_class": task_class,
                    "goal": goal,
                    "success_criteria": list(criteria),
                    "idempotency_key": f"web-agent-browser-{task_class.lower()}-0001",
                },
            )
            stream = client.get(
                "/v1/workbench/events",
                params={"task_id": created.json()["task_id"], "after_sequence": 0},
            )
            terminal = client.get(
                "/v1/workbench/task",
                params={"task_id": created.json()["task_id"]},
            )
            results[task_class] = (terminal.json(), _events(stream.text))
        evidence = client.get("/local-acceptance/evidence")

    assert rejected.status_code == 403
    assert rejected.json()["error_code"] == "ACCEPTANCE_SYNTHETIC_REQUEST_REQUIRED"
    assert results["G0"][0]["state"] == "SUCCEEDED"
    assert [item["state"] for item in results["G0"][1]] == list(
        catalog.scenario("browser_g0_success").expected_event_states
    )
    assert results["P1"][0]["state"] == "SUCCEEDED"
    assert [item["state"] for item in results["P1"][1]] == list(
        catalog.scenario("browser_p1_success").expected_event_states
    )
    assert evidence.json() == {
        "schema_version": "1.0.0",
        "provider_calls": 3,
        "general_calls": 1,
        "professional_calls": 1,
        "review_calls": 1,
        "external_network_calls": 0,
        "physical_tool_calls": 0,
        "formal_use_allowed": False,
    }
