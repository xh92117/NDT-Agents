"""Application General model delegate budget and source-boundary tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ndt_agents.client.execution import GeneralWorkbenchExecutor
from ndt_agents.client.service import InMemoryTaskRepository
from ndt_agents.models.config import load_model_runtime_configuration
from ndt_agents.models.inference import ModelInferenceError
from ndt_agents.observability import (
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.agent_config import load_agent_runtime_configuration
from ndt_agents.orchestration.budget import default_budget_policy
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.configured_runtime import (
    ConfiguredExecutorFactory,
    ConfiguredOrchestrationRuntime,
)
from ndt_agents.orchestration.general_model_delegate import (
    GeneralModelDelegate,
    build_general_delegate_catalog,
)
from ndt_agents.orchestration.models import DispatchPlan, RouteKind
from ndt_agents.orchestration.prompt_registry import load_prompt_registry
from tests.client.test_general_model_workbench import local_settings
from tests.client.test_web_workbench import SCOPE, create_request
from tests.tools.test_deepseek_agent_live_smoke import DeterministicAgentProvider

ROOT = Path(__file__).resolve().parents[2]


def test_token_reservation_denies_before_provider_call(tmp_path: Path) -> None:
    settings = local_settings(tmp_path)
    assert settings.model_config_path is not None
    assert settings.agent_config_path is not None
    configured_models = load_model_runtime_configuration(
        settings.model_config_path,
        environ={"DEEPSEEK_API_KEY": "offline-placeholder"},
    )
    agent_runtime = load_agent_runtime_configuration(
        settings.agent_config_path,
        model_runtime=configured_models,
        prompt_registry=load_prompt_registry(ROOT / "prompts/professional/catalog.v1.yaml"),
    )
    provider = DeterministicAgentProvider()
    traces = TraceService(
        service_name="general-model-budget-test",
        service_version="1.0.0",
        exporter=InMemorySpanExporter(),
    )
    delegate = GeneralModelDelegate(
        configured_models,
        provider,
        AuditService(InMemoryAuditRepository(), traces),
        trace_service=traces,
    )
    runtime = ConfiguredOrchestrationRuntime(
        ConfiguredExecutorFactory(
            agent_runtime,
            build_general_delegate_catalog(agent_runtime, delegate),
        )
    )
    repository = InMemoryTaskRepository()
    task = repository.create(SCOPE, create_request(task_class="G0"))
    task_context = GeneralWorkbenchExecutor(runtime)._task_context(task)
    task_context = task_context.model_copy(update={"budget": default_budget_policy("G0")})
    context = ChildContextFactory(agent_runtime.build_agent_registry()).prepare(
        task_context,
        DispatchPlan(
            task_id=task.task_id,
            route=RouteKind.GENERAL_SYNC,
            general_agent=True,
            professional_assignments=(),
            asynchronous=False,
            review_required=False,
            human_required=False,
        ),
    )[0]
    try:
        with pytest.raises(ModelInferenceError) as captured:
            asyncio.run(delegate.execute(context, agent_runtime.prompt_instruction("general")))
    finally:
        traces.shutdown()

    assert captured.value.code == "BUDGET_ACTIVE_LIMIT_EXCEEDED"
    assert provider.calls == 0
