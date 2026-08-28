"""Strict offline Web agent acceptance catalog and loopback browser harness."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self
from uuid import uuid4

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ndt_agents.models.inference import (  # noqa: E402
    ModelMetric,
    ModelProviderError,
    ModelProviderReply,
    ModelProviderRequest,
    ModelProviderStatus,
)
from ndt_agents.orchestration.general_model_delegate import (  # noqa: E402
    DEEPSEEK_POLICY_ACKNOWLEDGEMENT,
)
from ndt_agents.runtime.config import AppSettings, RuntimeEnvironment  # noqa: E402
from ndt_agents.runtime.local_workbench import create_local_workbench_app  # noqa: E402

CATALOG_PATH = ROOT / "config/acceptance/web-agent.v1.json"
HOST = "127.0.0.1"
PORT = 8766
MAX_CATALOG_BYTES = 65_536
FIXED_REQUESTS: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "G0": (
        "Validate the fixed synthetic G0 Web acceptance path.",
        ("Render ordered General events.", "Preserve non-formal limitations."),
    ),
    "P1": (
        "Validate the fixed synthetic P1 Web acceptance path.",
        ("Run independent review.", "Preserve non-formal limitations."),
    ),
}

_MANDATORY_SCENARIOS = frozenset(
    {
        "g0_success",
        "p1_success",
        "p1_review_conflict",
        "p1_malformed_review",
        "g0_malformed_output",
        "g0_provider_failure",
        "p1_budget_denial",
        "p1_restart_replay",
        "authorization_denial",
        "cross_scope_denial",
        "browser_g0_success",
        "browser_p1_success",
    }
)


class AcceptanceSurface(StrEnum):
    WEB_TASK = "WEB_TASK"
    DELEGATE_PREFLIGHT = "DELEGATE_PREFLIGHT"
    RESTART_REPLAY = "RESTART_REPLAY"
    ACCESS_PREFLIGHT = "ACCESS_PREFLIGHT"
    BROWSER = "BROWSER"


class OfflineProviderMode(StrEnum):
    SUCCESS = "SUCCESS"
    REVIEW_CONFLICT = "REVIEW_CONFLICT"
    MALFORMED_REVIEW = "MALFORMED_REVIEW"
    MALFORMED_GENERAL = "MALFORMED_GENERAL"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"


class AcceptanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WebAgentAcceptanceScenario(AcceptanceModel):
    scenario_id: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_]+$")
    surface: AcceptanceSurface
    task_class: Literal["G0", "P1"]
    provider_mode: OfflineProviderMode
    expected_terminal_state: Literal["SUCCEEDED", "FAILED"] | None
    expected_error_code: str | None = Field(default=None, max_length=128)
    expected_event_states: tuple[
        Literal["ACCEPTED", "RUNNING", "REVIEW_REQUIRED", "SUCCEEDED", "FAILED"], ...
    ] = Field(max_length=8)
    expected_general_provider_calls: int = Field(ge=0, le=1)
    expected_professional_provider_calls: int = Field(ge=0, le=1)
    expected_review_provider_calls: int = Field(ge=0, le=1)
    expected_replay_provider_calls: Literal[0]
    expected_physical_tool_calls: Literal[0]
    review_required: bool
    main_aggregation_required: bool
    persistence_mode: Literal["MEMORY", "SQLITE"]
    browser_required: bool
    formal_use_allowed: Literal[False]
    external_network_allowed: Literal[False]

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.browser_required != (self.surface is AcceptanceSurface.BROWSER):
            raise ValueError("browser_required must match the browser surface")
        if self.expected_terminal_state == "SUCCEEDED":
            if self.expected_error_code is not None or not self.main_aggregation_required:
                raise ValueError("successful scenarios require aggregation and no error")
            if not self.expected_event_states or self.expected_event_states[-1] != "SUCCEEDED":
                raise ValueError("successful scenarios require a successful final event")
        elif self.expected_terminal_state == "FAILED":
            if self.expected_error_code is None or self.main_aggregation_required:
                raise ValueError("failed scenarios require an error and no aggregation")
            if not self.expected_event_states or self.expected_event_states[-1] != "FAILED":
                raise ValueError("failed scenarios require a failed final event")
        elif self.expected_event_states:
            raise ValueError("preflight scenarios cannot expect task events")
        if self.task_class == "G0" and (
            self.review_required or self.expected_review_provider_calls != 0
        ):
            raise ValueError("G0 scenarios cannot require a Review Agent")
        if (
            self.task_class == "P1"
            and self.expected_terminal_state == "SUCCEEDED"
            and (
                not self.review_required
                or self.expected_professional_provider_calls != 1
                or self.expected_review_provider_calls != 1
                or "REVIEW_REQUIRED" not in self.expected_event_states
            )
        ):
            raise ValueError("successful P1 scenarios require professional and review calls")
        if (
            self.expected_general_provider_calls
            + self.expected_professional_provider_calls
            + self.expected_review_provider_calls
            > 2
        ):
            raise ValueError("a scenario cannot authorize more than two provider calls")
        return self


class WebAgentAcceptanceCatalog(AcceptanceModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    catalog_version: Literal["1.0.0"] = "1.0.0"
    scenarios: tuple[WebAgentAcceptanceScenario, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        scenario_ids = tuple(item.scenario_id for item in self.scenarios)
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("acceptance scenario IDs must be unique")
        missing = sorted(_MANDATORY_SCENARIOS.difference(scenario_ids))
        unexpected = sorted(set(scenario_ids).difference(_MANDATORY_SCENARIOS))
        if missing or unexpected:
            raise ValueError(
                f"acceptance scenario coverage mismatch: missing={missing}, unexpected={unexpected}"
            )
        return self

    def scenario(self, scenario_id: str) -> WebAgentAcceptanceScenario:
        for item in self.scenarios:
            if item.scenario_id == scenario_id:
                return item
        raise KeyError(scenario_id)


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_acceptance_catalog(path: Path = CATALOG_PATH) -> WebAgentAcceptanceCatalog:
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_CATALOG_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("acceptance catalog bytes are invalid")
    payload = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object)
    return WebAgentAcceptanceCatalog.model_validate(payload)


class OfflineAcceptanceProvider:
    """Schema-aware deterministic provider that performs no network or tool action."""

    def __init__(self, mode: OfflineProviderMode = OfflineProviderMode.SUCCESS) -> None:
        self.mode = mode
        self.requests: list[ModelProviderRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def calls_for(self, output_schema_id: str) -> int:
        return sum(item.output_schema_id == output_schema_id for item in self.requests)

    async def infer(self, request: ModelProviderRequest) -> object:
        self.requests.append(request)
        if self.mode is OfflineProviderMode.PROVIDER_FAILURE:
            raise ModelProviderError(
                "MODEL_PROVIDER_UNAVAILABLE",
                "offline acceptance provider failure",
                retryable=True,
                next_action="Inspect deterministic acceptance evidence.",
                physical_network_calls=0,
            )
        if request.output_schema_id == "general-agent-result@1.0.0":
            output = self._general_output(request)
            if self.mode is OfflineProviderMode.MALFORMED_GENERAL:
                output.pop("summary")
        elif request.output_schema_id == "technical-qa-agent-result@1.0.0":
            output = self._professional_output(request)
        elif request.output_schema_id == "review-agent-result@1.0.0":
            output = self._review_output(request)
            if self.mode is OfflineProviderMode.MALFORMED_REVIEW:
                output.pop("decision")
        else:
            raise AssertionError(f"unexpected acceptance schema: {request.output_schema_id}")
        return ModelProviderReply(
            call_id=request.call_id,
            provider_request_sha256=request.provider_request_sha256,
            provider_id=request.provider_id,
            provider_version=request.provider_version,
            endpoint_id=request.endpoint_id,
            model_id=request.model_id,
            model_snapshot=request.model_snapshot,
            provider_request_id=f"offline-acceptance-{self.calls}",
            status=ModelProviderStatus.SUCCESS,
            output=output,
            artifacts=(),
            input_tokens=300,
            output_tokens=100,
            confidence=Decimal("0.90"),
            metrics=(ModelMetric(metric="quality_score", value=Decimal("1")),),
            finish_reason="stop",
            physical_network_calls=0,
        )

    @staticmethod
    def _general_output(request: ModelProviderRequest) -> dict[str, Any]:
        context = request.parameters["child_context"]
        assert isinstance(context, dict)
        return {
            "schema_version": "1.0.0",
            "task_id": context["parent_task_id"],
            "run_id": context["run_id"],
            "status": "SUCCESS",
            "summary": "The fixed synthetic General acceptance path completed.",
            "structured_data": {
                "completed_work": ["Validated the configured General child path."],
                "limitations": ["Offline SYNTHETIC evidence only."],
                "next_action": "Review the bounded acceptance evidence.",
            },
            "artifacts": [],
            "evidence": [],
            "confidence": Decimal("0.90"),
            "issues": [],
            "retryable": False,
            "failure_code": None,
            "completed_at": "2026-08-28T00:00:00Z",
        }

    @staticmethod
    def _professional_output(request: ModelProviderRequest) -> dict[str, Any]:
        context = request.parameters["child_context"]
        assert isinstance(context, dict)
        return {
            "schema_version": "1.0.0",
            "task_id": context["parent_task_id"],
            "run_id": context["run_id"],
            "status": "SUCCESS",
            "summary": "The fixed synthetic Technical QA limitations were identified.",
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
            "completed_at": "2026-08-28T00:00:00Z",
        }

    def _review_output(self, request: ModelProviderRequest) -> dict[str, Any]:
        context = request.parameters["review_context"]
        assert isinstance(context, dict)
        conflict = self.mode is OfflineProviderMode.REVIEW_CONFLICT
        return {
            "schema_version": "1.0.0",
            "review_id": str(uuid4()),
            "task_id": context["task_id"],
            "target_run_id": context["review_target_run_id"],
            "target_sha256": context["review_target_sha256"],
            "reviewer_version": context["reviewer_version"],
            "decision": "CONFLICT" if conflict else "PASS",
            "findings": (
                [
                    {
                        "code": "MODEL_REVIEW_BLOCKED",
                        "severity": "ERROR",
                        "message": "The synthetic result is not aggregation ready.",
                        "affected_path": "summary",
                        "next_action": "Preserve the result for human inspection.",
                    }
                ]
                if conflict
                else []
            ),
            "correction_count": context["correction_count"],
            "completed_at": "2026-08-28T00:00:01Z",
        }


class FixedAcceptanceRequestMiddleware:
    """Deny every task payload except the two fixed SYNTHETIC browser cases."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/v1/workbench/tasks"
        ):
            await self._app(scope, receive, send)
            return
        body, receive = await self._bounded_body(receive)
        if body is None or not self._is_fixed_request(body):
            response = JSONResponse(
                status_code=403,
                content={
                    "error_code": "ACCEPTANCE_SYNTHETIC_REQUEST_REQUIRED",
                    "message": "The offline acceptance server accepts only fixed synthetic tasks.",
                    "retryable": False,
                    "next_action": "Use one fixed G0 or P1 acceptance case.",
                },
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)

    @staticmethod
    async def _bounded_body(receive: Receive) -> tuple[bytes | None, Receive]:
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return None, receive
            body.extend(message.get("body", b""))
            if len(body) > 16_384:
                return None, receive
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        return bytes(body), replay

    @staticmethod
    def _is_fixed_request(body: bytes) -> bool:
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        task_class = payload.get("task_class") if isinstance(payload, dict) else None
        expected = FIXED_REQUESTS.get(str(task_class))
        return bool(
            expected
            and payload.get("schema_version") == "1.0.0"
            and payload.get("goal") == expected[0]
            and payload.get("success_criteria") == list(expected[1])
        )


def _offline_settings(work_directory: Path, *, port: int) -> AppSettings:
    config_root = work_directory / "config"
    runtime_root = config_root / "runtime"
    model_root = config_root / "model-providers"
    runtime_root.mkdir(parents=True)
    shutil.copytree(ROOT / "config/model-providers", model_root)
    model_text = (ROOT / "config/runtime/model-bindings.example.yaml").read_text(encoding="utf-8")
    model_path = runtime_root / "model-bindings.local.yaml"
    model_path.write_text(
        model_text.replace("state: DISABLED", "state: ENABLED", 1), encoding="utf-8"
    )
    agent_path = runtime_root / "agent-runtime.local.yaml"
    shutil.copyfile(ROOT / "config/runtime/agent-runtime.example.yaml", agent_path)
    return AppSettings(
        environment=RuntimeEnvironment.LOCAL,
        host=HOST,
        port=port,
        model_config_path=str(model_path),
        prompt_config_path=str(ROOT / "prompts/professional/catalog.v1.yaml"),
        agent_config_path=str(agent_path),
        general_model_delegate_enabled=True,
        professional_model_delegate_enabled=True,
        local_workbench_enabled=True,
        local_workbench_state_path=str(work_directory / "workbench.sqlite3"),
        deepseek_policy_acknowledgement=DEEPSEEK_POLICY_ACKNOWLEDGEMENT,
    )


def create_offline_acceptance_app(work_directory: Path, *, port: int = PORT) -> Any:
    """Create one production-composed local app with a zero-network provider."""

    if not 1_024 <= port <= 65_535:
        raise ValueError("acceptance port is outside the allowed loopback range")
    provider = OfflineAcceptanceProvider()
    app = create_local_workbench_app(
        _offline_settings(work_directory, port=port),
        model_environment={"DEEPSEEK_API_KEY": "offline-placeholder"},
        model_provider=provider,
    )
    app.state.offline_acceptance_provider = provider

    @app.get("/local-acceptance/evidence", include_in_schema=False)
    async def acceptance_evidence(_request: Request) -> JSONResponse:
        return JSONResponse(
            content={
                "schema_version": "1.0.0",
                "provider_calls": provider.calls,
                "general_calls": provider.calls_for("general-agent-result@1.0.0"),
                "professional_calls": provider.calls_for("technical-qa-agent-result@1.0.0"),
                "review_calls": provider.calls_for("review-agent-result@1.0.0"),
                "external_network_calls": 0,
                "physical_tool_calls": 0,
                "formal_use_allowed": False,
            },
            headers={"Cache-Control": "no-store"},
        )

    app.add_middleware(FixedAcceptanceRequestMiddleware)
    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    catalog = load_acceptance_catalog()
    if not args.serve:
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "catalog_version": catalog.catalog_version,
                    "scenario_count": len(catalog.scenarios),
                }
            )
        )
        return 0
    with tempfile.TemporaryDirectory(prefix="ndt-web-acceptance-") as temp_directory:
        app = create_offline_acceptance_app(Path(temp_directory), port=args.port)
        print(
            json.dumps(
                {
                    "result": "READY",
                    "url": f"http://{HOST}:{args.port}/local/workbench/session",
                    "external_network_calls": 0,
                }
            ),
            flush=True,
        )
        uvicorn.run(app, host=HOST, port=args.port, log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
