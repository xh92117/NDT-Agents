"""S2-06 INT-MEMORY snapshot and branch restore tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import JsonValue, ValidationError

from ndt_agents.contracts.v1 import (
    ArtifactRef,
    Checkpoint,
    DataClassification,
    TaskContext,
    TenantScope,
)
from ndt_agents.memory import (
    InMemorySnapshotRepository,
    IntentRestoreAction,
    MemoryAccess,
    MemoryRestoreService,
    MemorySnapshot,
    RestoreError,
    RestoreOutcome,
    SnapshotMatch,
    snapshot_state_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
BASE_TASK = TaskContext.model_validate_json(
    (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
)
BASE_CHECKPOINT = Checkpoint.model_validate_json(
    (ROOT / "examples/contracts/v1/checkpoint.valid.json").read_text("utf-8")
)
NOW = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)
ACCESS = MemoryAccess(
    scope=BASE_TASK.scope,
    permissions=("memory:snapshot", "memory:restore"),
    clearance=DataClassification.RESTRICTED,
)


class Availability:
    def __init__(self, available: bool = True) -> None:
        self.available = available

    async def exists(self, scope: TenantScope, artifact: ArtifactRef) -> bool:
        return self.available and artifact.scope == scope


class Matcher:
    def __init__(self, matches: tuple[SnapshotMatch, ...]) -> None:
        self.matches = matches
        self.limit: int | None = None

    async def search(
        self, intent: str, snapshots: tuple[MemorySnapshot, ...], limit: int
    ) -> tuple[SnapshotMatch, ...]:
        assert intent
        self.limit = limit
        visible_ids = {snapshot.snapshot_id for snapshot in snapshots}
        return tuple(match for match in self.matches if match.snapshot_id in visible_ids)


def snapshot(index: int = 1, *, version: str = "1.0.0") -> MemorySnapshot:
    state: dict[str, JsonValue] = {"step": index, "status": "paused"}
    digest = snapshot_state_sha256(state)
    checkpoint = BASE_CHECKPOINT.model_copy(
        update={
            "task_id": BASE_TASK.task_id,
            "scope": BASE_TASK.scope,
            "state_sha256": digest,
            "state_schema_version": version,
        }
    )
    return MemorySnapshot(
        snapshot_id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
        task_id=BASE_TASK.task_id,
        scope=BASE_TASK.scope,
        branch_id=UUID(f"10000000-0000-4000-8000-{index:012d}"),
        checkpoint=checkpoint,
        graph_version="graph-1",
        state_schema_version=version,
        state=state,
        state_sha256=digest,
        memory_ids=(UUID(f"20000000-0000-4000-8000-{index:012d}"),),
        project_facts=({"fact": f"bridge-{index}"},),
        artifacts=(BASE_CHECKPOINT.state_artifact,),
        required_turns=({"role": "user", "text": "continue"},),
        injection_tokens=500,
        created_at=NOW,
    )


def service(
    *, availability: Availability | None = None
) -> tuple[MemoryRestoreService, InMemorySnapshotRepository]:
    repository = InMemorySnapshotRepository()
    return (
        MemoryRestoreService(
            repository=repository,
            artifact_availability=availability or Availability(),
            supported_state_versions=frozenset({"1.0.0"}),
        ),
        repository,
    )


def test_direct_restore_requires_preview_and_creates_new_branch() -> None:
    async def scenario() -> None:
        restore, _ = service()
        original = snapshot()
        restore.create_snapshot(ACCESS, original)
        preview = await restore.preview_direct(ACCESS, original.snapshot_id, now=NOW)
        branch = await restore.confirm(ACCESS, preview, now=NOW + timedelta(seconds=1))

        assert branch.branch_id == preview.target_branch_id
        assert branch.branch_id != original.branch_id
        assert branch.parent_branch_id == original.branch_id
        assert branch.state == original.state
        assert branch.source_snapshot_id == original.snapshot_id

    asyncio.run(scenario())


def test_cancel_is_terminal_idempotent_and_conflicts_with_confirm() -> None:
    async def scenario() -> None:
        restore, _ = service()
        original = snapshot()
        restore.create_snapshot(ACCESS, original)
        preview = await restore.preview_direct(ACCESS, original.snapshot_id, now=NOW)
        first = restore.cancel(ACCESS, preview, now=NOW + timedelta(seconds=1))
        second = restore.cancel(ACCESS, preview, now=NOW + timedelta(seconds=2))
        assert first == second
        assert first.outcome is RestoreOutcome.CANCELLED
        with pytest.raises(RestoreError, match="terminal decision") as conflict:
            await restore.confirm(ACCESS, preview, now=NOW + timedelta(seconds=3))
        assert conflict.value.code == "RESTORE_DECISION_CONFLICT"

    asyncio.run(scenario())


def test_intent_auto_preview_requires_confidence_and_margin() -> None:
    async def scenario() -> None:
        restore, _ = service()
        first, second = snapshot(1), snapshot(2)
        restore.create_snapshot(ACCESS, first)
        restore.create_snapshot(ACCESS, second)
        matcher = Matcher(
            (
                SnapshotMatch(snapshot_id=first.snapshot_id, score=0.94),
                SnapshotMatch(snapshot_id=second.snapshot_id, score=0.80),
            )
        )
        result = await restore.preview_intent(
            ACCESS, "continue bridge task", matcher=matcher, now=NOW
        )
        assert matcher.limit == 5
        assert result.action is IntentRestoreAction.AUTO_PREVIEW
        assert result.preview is not None
        assert result.preview.snapshot_id == first.snapshot_id

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "matches",
    [
        (0.89, 0.50),
        (0.94, 0.83),
    ],
)
def test_ambiguous_or_low_confidence_intent_shows_candidates(
    matches: tuple[float, float],
) -> None:
    async def scenario() -> None:
        restore, _ = service()
        first, second = snapshot(1), snapshot(2)
        restore.create_snapshot(ACCESS, first)
        restore.create_snapshot(ACCESS, second)
        result = await restore.preview_intent(
            ACCESS,
            "continue",
            matcher=Matcher(
                (
                    SnapshotMatch(snapshot_id=first.snapshot_id, score=matches[0]),
                    SnapshotMatch(snapshot_id=second.snapshot_id, score=matches[1]),
                )
            ),
            now=NOW,
        )
        assert result.action is IntentRestoreAction.SHOW_CANDIDATES
        assert result.preview is None

    asyncio.run(scenario())


def test_restore_denies_cross_scope_snapshot() -> None:
    async def scenario() -> None:
        restore, repository = service()
        original = snapshot()
        repository.insert_snapshot(original)
        other_scope = BASE_TASK.scope.model_copy(
            update={"project_id": UUID("00000000-0000-4000-8000-000000000999")}
        )
        other_access = ACCESS.model_copy(update={"scope": other_scope})
        with pytest.raises(RestoreError, match="outside") as denied:
            await restore.preview_direct(other_access, original.snapshot_id, now=NOW)
        assert denied.value.code == "RESTORE_SCOPE_DENIED"

    asyncio.run(scenario())


def test_restore_rechecks_version_and_artifact_availability() -> None:
    async def scenario() -> None:
        incompatible, _ = service()
        old = snapshot(version="0.9.0")
        incompatible.create_snapshot(ACCESS, old)
        with pytest.raises(RestoreError, match="not compatible") as version:
            await incompatible.preview_direct(ACCESS, old.snapshot_id, now=NOW)
        assert version.value.code == "RESTORE_VERSION_INCOMPATIBLE"

        unavailable, _ = service(availability=Availability(False))
        current = snapshot()
        unavailable.create_snapshot(ACCESS, current)
        with pytest.raises(RestoreError, match="artifact") as missing:
            await unavailable.preview_direct(ACCESS, current.snapshot_id, now=NOW)
        assert missing.value.code == "RESTORE_ARTIFACT_MISSING"

    asyncio.run(scenario())


def test_preview_tampering_is_rejected() -> None:
    async def scenario() -> None:
        restore, _ = service()
        original = snapshot()
        restore.create_snapshot(ACCESS, original)
        preview = await restore.preview_direct(ACCESS, original.snapshot_id, now=NOW)
        tampered = preview.model_copy(update={"injection_tokens": 501})
        with pytest.raises(RestoreError, match="does not match") as rejected:
            await restore.confirm(ACCESS, tampered, now=NOW)
        assert rejected.value.code == "RESTORE_PREVIEW_TAMPERED"

    asyncio.run(scenario())


def test_snapshot_contract_enforces_injection_limits_and_state_hash() -> None:
    payload = snapshot().model_dump()
    payload["injection_tokens"] = 6001
    with pytest.raises(ValidationError):
        MemorySnapshot.model_validate(payload)
    payload = snapshot().model_dump()
    payload["state"] = {"tampered": True}
    with pytest.raises(ValidationError, match="hash does not match"):
        MemorySnapshot.model_validate(payload)
