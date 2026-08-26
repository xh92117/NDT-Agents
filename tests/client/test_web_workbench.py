"""S6-01 client contract, E2E boundary, and accessibility checks."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ndt_agents.client import (
    ClientTaskClass,
    InMemoryTaskRepository,
    TaskCreateRequest,
    TaskEvent,
    TaskEventKind,
    TaskState,
    WorkbenchError,
    WorkbenchRuntime,
    WorkbenchTask,
)
from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.identity.middleware import IdentityRuntime
from ndt_agents.identity.models import OidcSettings
from ndt_agents.identity.oidc import OidcJwtVerifier
from ndt_agents.identity.rbac import Permission, RbacPolicy, RoutePermissionPolicy
from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings

TENANT_ID = UUID("00000000-0000-4000-8000-000000000601")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000602")
USER_ID = UUID("00000000-0000-4000-8000-000000000603")
OTHER_USER_ID = UUID("00000000-0000-4000-8000-000000000604")
SCOPE = TenantScope(
    tenant_id=TENANT_ID,
    project_id=PROJECT_ID,
    user_id=USER_ID,
    role_codes=("PROJECT_OPERATOR",),
    permission_version="permissions-s6-1",
)


def create_request(**updates: Any) -> TaskCreateRequest:
    values: dict[str, Any] = {
        "task_class": ClientTaskClass.PROFESSIONAL_ASYNC,
        "goal": "Assess the supplied inspection evidence.",
        "success_criteria": ("Preserve evidence traceability", "Disclose uncertainty"),
        "idempotency_key": "workbench-request-0001",
    }
    values.update(updates)
    return TaskCreateRequest(**values)


def signing_material() -> tuple[RSAPrivateKey, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "s6-key", "alg": "RS256", "use": "sig"})
    return private_key, {"keys": [public_jwk]}


def token(private_key: RSAPrivateKey, *, roles: tuple[str, ...] = ("PROJECT_OPERATOR",)) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "https://identity.example.test/",
            "aud": "ndt-agents-api",
            "sub": "s6-user",
            "user_id": str(USER_ID),
            "tenant_id": str(TENANT_ID),
            "project_ids": [str(PROJECT_ID)],
            "roles": list(roles),
            "permission_version": "permissions-s6-1",
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
            "jti": "s6-token",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "s6-key", "typ": "JWT"},
    )


def identity(jwks: dict[str, Any], *, grant: bool = True) -> IdentityRuntime:
    permissions = (
        frozenset(
            {
                Permission.WORKBENCH_TASK_CREATE,
                Permission.WORKBENCH_TASK_READ,
                Permission.WORKBENCH_EVENT_READ,
            }
        )
        if grant
        else frozenset()
    )
    return IdentityRuntime(
        verifier=OidcJwtVerifier(
            settings=OidcSettings(
                issuer="https://identity.example.test/", audience="ndt-agents-api"
            ),
            jwks=jwks,
        ),
        rbac=RbacPolicy(policy_version="rbac-s6-1", grants={"PROJECT_OPERATOR": permissions}),
        routes=RoutePermissionPolicy(
            policy_version="routes-s6-1",
            permissions={
                ("POST", "/v1/workbench/tasks"): Permission.WORKBENCH_TASK_CREATE,
                ("GET", "/v1/workbench/task"): Permission.WORKBENCH_TASK_READ,
                ("GET", "/v1/workbench/events"): Permission.WORKBENCH_EVENT_READ,
            },
        ),
    )


def headers(encoded_token: str) -> dict[str, str]:
    return {
        "authorization": f"Bearer {encoded_token}",
        "x-tenant-id": str(TENANT_ID),
        "x-project-id": str(PROJECT_ID),
        "x-request-id": "s6-client-test",
    }


def test_contract_rejects_unbounded_ambiguous_or_client_owned_state() -> None:
    with pytest.raises(ValidationError):
        create_request(goal=" surrounding whitespace ")
    with pytest.raises(ValidationError):
        create_request(success_criteria=("same", "same"))
    with pytest.raises(ValidationError):
        TaskCreateRequest.model_validate({**create_request().model_dump(), "state": "SUCCEEDED"})


def test_repository_binds_scope_idempotency_sequence_and_terminal_state() -> None:
    repository = InMemoryTaskRepository()
    task = repository.create(SCOPE, create_request())
    replay = repository.create(SCOPE, create_request())
    assert replay.task_id == task.task_id
    assert task.state is TaskState.ACCEPTED
    assert task.formal_use_allowed is False
    assert repository.events(SCOPE, task.task_id, 0).events[0].sequence == 1

    with pytest.raises(WorkbenchError) as conflict:
        repository.create(SCOPE, create_request(goal="Changed input."))
    assert conflict.value.code == "CLIENT_IDEMPOTENCY_CONFLICT"

    other_scope = SCOPE.model_copy(update={"user_id": OTHER_USER_ID})
    with pytest.raises(WorkbenchError) as hidden:
        repository.get(other_scope, task.task_id)
    assert hidden.value.code == "CLIENT_TASK_NOT_FOUND"

    with pytest.raises(WorkbenchError) as transition:
        repository.append(
            SCOPE,
            TaskEvent(
                event_id=UUID("00000000-0000-4000-8000-000000000609"),
                task_id=task.task_id,
                scope=SCOPE,
                sequence=2,
                kind=TaskEventKind.RESULT,
                state=TaskState.SUCCEEDED,
                message="Result attempted before execution and review.",
                progress_percent=100,
            ),
        )
    assert transition.value.code == "CLIENT_STATE_TRANSITION_INVALID"

    running = TaskEvent(
        event_id=UUID("00000000-0000-4000-8000-000000000608"),
        task_id=task.task_id,
        scope=SCOPE,
        sequence=2,
        kind=TaskEventKind.STATUS,
        state=TaskState.RUNNING,
        message="Main Agent routing completed and execution started.",
        progress_percent=10,
    )
    repository.append(SCOPE, running)
    with pytest.raises(WorkbenchError) as unreviewed:
        repository.append(
            SCOPE,
            TaskEvent(
                event_id=UUID("00000000-0000-4000-8000-000000000611"),
                task_id=task.task_id,
                scope=SCOPE,
                sequence=3,
                kind=TaskEventKind.RESULT,
                state=TaskState.SUCCEEDED,
                message="Unreviewed result attempted completion.",
                progress_percent=100,
            ),
        )
    assert unreviewed.value.code == "CLIENT_REVIEW_REQUIRED"
    repository.append(
        SCOPE,
        TaskEvent(
            event_id=UUID("00000000-0000-4000-8000-000000000612"),
            task_id=task.task_id,
            scope=SCOPE,
            sequence=3,
            kind=TaskEventKind.REVIEW,
            state=TaskState.REVIEW_REQUIRED,
            message="Complex result entered mandatory review.",
            progress_percent=80,
        ),
    )
    repository.append(
        SCOPE,
        TaskEvent(
            event_id=UUID("00000000-0000-4000-8000-000000000613"),
            task_id=task.task_id,
            scope=SCOPE,
            sequence=4,
            kind=TaskEventKind.REVIEW,
            state=TaskState.RUNNING,
            message="Mandatory review passed and aggregation resumed.",
            progress_percent=90,
        ),
    )
    completed = TaskEvent(
        event_id=UUID("00000000-0000-4000-8000-000000000610"),
        task_id=task.task_id,
        scope=SCOPE,
        sequence=5,
        kind=TaskEventKind.RESULT,
        state=TaskState.SUCCEEDED,
        message="Reviewed result is ready for Main Agent aggregation.",
        progress_percent=100,
    )
    repository.append(SCOPE, completed)
    batch = repository.events(SCOPE, task.task_id, 1)
    assert [event.sequence for event in batch.events] == [2, 3, 4, 5]
    assert batch.terminal is True
    with pytest.raises(WorkbenchError) as terminal:
        repository.append(SCOPE, completed.model_copy(update={"sequence": 6}))
    assert terminal.value.code == "CLIENT_TASK_TERMINAL"


def test_concurrent_append_commits_one_event_per_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = InMemoryTaskRepository()
    task = repository.create(SCOPE, create_request())
    original_get = repository.get
    barrier = Barrier(2)

    def synchronized_get(scope: TenantScope, task_id: UUID) -> WorkbenchTask:
        snapshot = original_get(scope, task_id)
        barrier.wait(timeout=2)
        return snapshot

    monkeypatch.setattr(repository, "get", synchronized_get)

    def append(index: int) -> str:
        try:
            repository.append(
                SCOPE,
                TaskEvent(
                    event_id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
                    task_id=task.task_id,
                    scope=SCOPE,
                    sequence=2,
                    kind=TaskEventKind.STATUS,
                    state=TaskState.RUNNING,
                    message="Concurrent transition.",
                    progress_percent=10,
                ),
            )
        except WorkbenchError as error:
            return error.code
        return "COMMITTED"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(append, (1, 2)))

    assert sorted(outcomes) == ["CLIENT_EVENT_SEQUENCE_INVALID", "COMMITTED"]
    batch = repository.events(SCOPE, task.task_id, 0)
    assert [event.sequence for event in batch.events] == [1, 2]
    assert batch.last_sequence == 2


def test_authenticated_api_creates_reads_and_replays_sse_without_duplicates() -> None:
    private_key, jwks = signing_material()
    runtime = WorkbenchRuntime()
    app = create_app(
        AppSettings(), configure_logs=False, identity=identity(jwks), workbench=runtime
    )
    with TestClient(app) as client:
        denied = client.post("/v1/workbench/tasks", json=create_request().model_dump(mode="json"))
        created = client.post(
            "/v1/workbench/tasks",
            headers=headers(token(private_key)),
            json=create_request().model_dump(mode="json"),
        )
        task_id = created.json()["task_id"]
        read = client.get(
            "/v1/workbench/task", params={"task_id": task_id}, headers=headers(token(private_key))
        )
        stream = client.get(
            "/v1/workbench/events",
            params={"task_id": task_id, "after_sequence": 0},
            headers=headers(token(private_key)),
        )
        replay = client.get(
            "/v1/workbench/events",
            params={"task_id": task_id, "after_sequence": 1},
            headers=headers(token(private_key)),
        )

    assert denied.status_code == 401
    assert created.status_code == 202
    assert created.headers["cache-control"] == "no-store"
    assert read.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.text.count("event: task-event") == 1
    assert '"sequence":1' in stream.text
    assert replay.text.count("event: task-event") == 0
    assert '"last_sequence":1' in replay.text
    assert "authorization" not in stream.text.lower()


def test_route_permission_is_default_deny_and_error_is_non_disclosing() -> None:
    private_key, jwks = signing_material()
    app = create_app(
        AppSettings(),
        configure_logs=False,
        identity=identity(jwks, grant=False),
        workbench=WorkbenchRuntime(),
    )
    encoded = token(private_key)
    with TestClient(app) as client:
        response = client.post(
            "/v1/workbench/tasks",
            headers=headers(encoded),
            json=create_request().model_dump(mode="json"),
        )
    assert response.status_code == 403
    assert response.json()["error_code"] == "AUTH_PERMISSION_DENIED"
    assert encoded not in response.text


def test_web_shell_has_security_accessibility_and_responsive_controls() -> None:
    _, jwks = signing_material()
    app = create_app(
        AppSettings(), configure_logs=False, identity=identity(jwks), workbench=WorkbenchRuntime()
    )
    with TestClient(app) as client:
        shell = client.get("/workbench")
        script = client.get("/workbench/assets/workbench.js")
        styles = client.get("/workbench/assets/workbench.css")

    assert shell.status_code == 200
    assert "frame-ancestors 'none'" in shell.headers["content-security-policy"]
    for marker in ("<main", "<form", 'aria-live="polite"', "<label", "skip-link"):
        assert marker in shell.text
    assert "innerHTML" not in script.text
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text
    assert "textContent" in script.text
    assert "@media (max-width: 760px)" in styles.text
    assert "prefers-reduced-motion" in styles.text
    assert ":focus-visible" in styles.text


def test_contract_document_and_assets_are_ascii_safe() -> None:
    root = Path(__file__).resolve().parents[2]
    contract = (root / "docs/contracts/client-api-v1.md").read_text(encoding="ascii")
    assert "CLIENT_EVENT_CURSOR_INVALID" in contract


def test_pwa_manifest_and_service_worker_cache_only_public_shell_gets() -> None:
    _, jwks = signing_material()
    app = create_app(
        AppSettings(), configure_logs=False, identity=identity(jwks), workbench=WorkbenchRuntime()
    )
    with TestClient(app) as client:
        manifest_response = client.get("/workbench/assets/manifest.webmanifest")
        worker_response = client.get("/workbench/sw.js")
        icon_response = client.get("/workbench/assets/icon.svg")

    manifest = manifest_response.json()
    assert manifest["id"] == "/workbench"
    assert manifest["start_url"] == "/workbench"
    assert manifest["scope"] == "/workbench"
    assert manifest["display"] == "standalone"
    assert manifest["icons"] == [
        {
            "src": "/workbench/assets/icon.svg",
            "sizes": "any",
            "type": "image/svg+xml",
            "purpose": "any maskable",
        }
    ]
    assert worker_response.status_code == 200
    assert worker_response.headers["service-worker-allowed"] == "/workbench"
    assert worker_response.headers["cache-control"] == "no-store"
    worker = worker_response.text
    assert 'request.method !== "GET"' in worker
    assert "url.origin !== self.location.origin" in worker
    assert 'request.headers.has("authorization")' in worker
    assert 'url.pathname.startsWith("/v1/")' in worker
    assert 'url.pathname.startsWith("/workbench/assets/")' in worker
    assert "caches.open(CACHE_NAME)" in worker
    assert "queue" not in worker.lower()
    assert icon_response.headers["content-type"].startswith("image/svg+xml")


def test_pwa_reports_offline_limits_and_never_queues_mutations() -> None:
    root = Path(__file__).resolve().parents[2]
    web = root / "src/ndt_agents/client/web"
    script = (web / "assets/workbench.js").read_text(encoding="utf-8")
    shell = (web / "index.html").read_text(encoding="utf-8")
    styles = (web / "assets/workbench.css").read_text(encoding="utf-8")
    assert 'navigator.serviceWorker.register("/workbench/sw.js"' in script
    assert "if (!navigator.onLine)" in script
    assert "Offline / no task queued" in script
    assert "Offline mode cannot create or update tasks" in shell
    assert "safe-area-inset-top" in styles
    assert "safe-area-inset-bottom" in styles
