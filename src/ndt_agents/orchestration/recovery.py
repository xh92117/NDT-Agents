"""Scoped immutable checkpoints, idempotency, interrupts, and restart recovery."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, Self
from uuid import UUID, uuid4

from pydantic import Field, ValidationError, model_validator

from ndt_agents.contracts.v1 import (
    Checkpoint,
    DataClassification,
    TenantScope,
)
from ndt_agents.orchestration.budget import (
    BudgetContractError,
    BudgetExceeded,
    BudgetGuard,
    BudgetTelemetry,
)
from ndt_agents.orchestration.child_context import child_context_manifest_sha256
from ndt_agents.orchestration.child_models import ChildModel, ChildTaskContext
from ndt_agents.orchestration.scheduler import (
    AssignmentStatus,
    ScheduledAssignment,
    ScheduleMode,
    ScheduleResult,
    ScheduleStatus,
    TaskScheduler,
)
from ndt_agents.orchestration.subgraph import (
    ChildExecutor,
    ChildExecutorError,
)
from ndt_agents.storage.artifacts import ArtifactStorageService
from ndt_agents.storage.errors import StorageError

RECOVERY_GRAPH_VERSION: Literal["scheduler-recovery-1"] = "scheduler-recovery-1"
RECOVERY_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
RECOVERY_STATE_SCHEMA_VERSION: Literal["1.1.0"] = "1.1.0"
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class RecoveryPhase(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    INTERRUPTED = "INTERRUPTED"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RecoveryFaultPoint(StrEnum):
    AFTER_RUNNING_CHECKPOINT = "AFTER_RUNNING_CHECKPOINT"
    AFTER_ASSIGNMENT_OUTPUTS = "AFTER_ASSIGNMENT_OUTPUTS"


class SideEffectClaimStatus(StrEnum):
    NEW = "NEW"
    STARTED = "STARTED"
    COMMITTED = "COMMITTED"


class SimulatedProcessTermination(BaseException):
    """Test-only process-loss signal that normal child failure handling must not swallow."""


class RecoveryError(RuntimeError):
    """Stable recovery-boundary error with an actionable next step."""

    def __init__(self, code: str, message: str, next_action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action


class RecoverySnapshot(ChildModel):
    schema_version: Literal["1.0.0"] = RECOVERY_CONTRACT_VERSION
    recovery_id: UUID
    parent_task_id: UUID
    scope: TenantScope
    idempotency_key: str = Field(min_length=1, max_length=256)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_version: Literal["scheduler-recovery-1"] = RECOVERY_GRAPH_VERSION
    state_schema_version: Literal["1.1.0"] = RECOVERY_STATE_SCHEMA_VERSION
    sequence: int = Field(ge=0)
    phase: RecoveryPhase
    contexts: tuple[ChildTaskContext, ...] = Field(min_length=1, max_length=4)
    budget_telemetry: BudgetTelemetry
    schedule_result: ScheduleResult | None = None
    interrupt_reason: str | None = Field(default=None, max_length=1000)
    committed_side_effect_ids: tuple[UUID, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if (
            self.phase
            in {
                RecoveryPhase.COMPLETED,
                RecoveryPhase.PARTIAL,
                RecoveryPhase.FAILED,
                RecoveryPhase.CANCELLED,
            }
            and self.schedule_result is None
        ):
            raise ValueError("terminal recovery snapshot requires a schedule result")
        if self.phase is not RecoveryPhase.INTERRUPTED and self.interrupt_reason is not None:
            raise ValueError("only interrupted snapshots may contain an interrupt reason")
        if self.schedule_result is not None:
            if self.schedule_result.schedule_id != self.recovery_id:
                raise ValueError("schedule result must use the stable recovery ID")
            if (
                self.schedule_result.parent_task_id != self.parent_task_id
                or self.schedule_result.scope != self.scope
            ):
                raise ValueError("schedule result scope or task does not match recovery")
        if any(context.budget != self.budget_telemetry.policy for context in self.contexts):
            raise ValueError("recovery budget telemetry must match every child context policy")
        return self


class RecoveryHandle(ChildModel):
    schema_version: Literal["1.0.0"] = RECOVERY_CONTRACT_VERSION
    recovery_id: UUID
    parent_task_id: UUID
    scope: TenantScope
    idempotency_key: str
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phase: RecoveryPhase
    latest_sequence: int = Field(ge=0)
    reused: bool


class RecoveryOutcome(ChildModel):
    schema_version: Literal["1.0.0"] = RECOVERY_CONTRACT_VERSION
    recovery_id: UUID
    parent_task_id: UUID
    scope: TenantScope
    phase: RecoveryPhase
    checkpoint: Checkpoint
    schedule_result: ScheduleResult | None
    budget_telemetry: BudgetTelemetry
    recovered: bool
    interrupt_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryClaim:
    recovery_id: UUID
    reused: bool


@dataclass(frozen=True, slots=True)
class SideEffectClaim:
    status: SideEffectClaimStatus
    output: bytes | None


class RecoveryBackend(Protocol):
    async def claim(
        self,
        scope: TenantScope,
        parent_task_id: UUID,
        idempotency_key: str,
        request_sha256: str,
        proposed_recovery_id: UUID,
    ) -> RecoveryClaim: ...

    async def append_checkpoint(
        self, recovery_id: UUID, scope: TenantScope, checkpoint: Checkpoint
    ) -> None: ...

    async def latest_checkpoint(self, recovery_id: UUID, scope: TenantScope) -> Checkpoint: ...

    async def request_interrupt(
        self, recovery_id: UUID, scope: TenantScope, reason: str
    ) -> None: ...

    async def interrupt_reason(self, recovery_id: UUID, scope: TenantScope) -> str | None: ...

    async def clear_interrupt(self, recovery_id: UUID, scope: TenantScope) -> None: ...

    async def get_assignment_output(
        self, recovery_id: UUID, scope: TenantScope, execution_key: str
    ) -> bytes | None: ...

    async def put_assignment_output(
        self,
        recovery_id: UUID,
        scope: TenantScope,
        execution_key: str,
        output: bytes,
    ) -> None: ...

    async def begin_side_effect(
        self,
        recovery_id: UUID,
        scope: TenantScope,
        side_effect_id: UUID,
        request_sha256: str,
    ) -> SideEffectClaim: ...

    async def commit_side_effect(
        self,
        recovery_id: UUID,
        scope: TenantScope,
        side_effect_id: UUID,
        request_sha256: str,
        output: bytes,
    ) -> None: ...

    async def committed_side_effect_ids(
        self, recovery_id: UUID, scope: TenantScope
    ) -> tuple[UUID, ...]: ...


@dataclass(frozen=True, slots=True)
class _IdempotencyRecord:
    recovery_id: UUID
    parent_task_id: UUID
    request_sha256: str


@dataclass(frozen=True, slots=True)
class _HashedOutput:
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class _SideEffectRecord:
    request_sha256: str
    status: SideEffectClaimStatus
    output: _HashedOutput | None


def _scope_key(scope: TenantScope) -> str:
    return scope.model_dump_json()


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RecoveryError(
            "RECOVERY_RESULT_NOT_JSON",
            "A recoverable result is not canonical JSON data.",
            "Return a JSON-compatible typed result before checkpointing.",
        ) from error


class InMemoryRecoveryBackend:
    """Deterministic restart-test backend; production persistence uses the same port."""

    def __init__(self) -> None:
        import asyncio

        self._lock = asyncio.Lock()
        self._claims: dict[tuple[str, str], _IdempotencyRecord] = {}
        self._checkpoints: dict[UUID, list[Checkpoint]] = {}
        self._interrupts: dict[tuple[str, UUID], str] = {}
        self._outputs: dict[tuple[str, UUID, str], _HashedOutput] = {}
        self._effects: dict[tuple[str, UUID, UUID], _SideEffectRecord] = {}

    async def claim(
        self,
        scope: TenantScope,
        parent_task_id: UUID,
        idempotency_key: str,
        request_sha256: str,
        proposed_recovery_id: UUID,
    ) -> RecoveryClaim:
        key = (_scope_key(scope), idempotency_key)
        async with self._lock:
            existing = self._claims.get(key)
            if existing is None:
                self._claims[key] = _IdempotencyRecord(
                    recovery_id=proposed_recovery_id,
                    parent_task_id=parent_task_id,
                    request_sha256=request_sha256,
                )
                return RecoveryClaim(proposed_recovery_id, reused=False)
            if (
                existing.parent_task_id != parent_task_id
                or existing.request_sha256 != request_sha256
            ):
                raise RecoveryError(
                    "IDEMPOTENCY_CONFLICT",
                    "The scoped idempotency key is already bound to different input.",
                    "Use the original exact request or a new idempotency key.",
                )
            return RecoveryClaim(existing.recovery_id, reused=True)

    async def append_checkpoint(
        self, recovery_id: UUID, scope: TenantScope, checkpoint: Checkpoint
    ) -> None:
        if checkpoint.scope != scope:
            raise RecoveryError(
                "CHECKPOINT_SCOPE_DENIED",
                "The checkpoint does not match the active identity scope.",
                "Write only checkpoints for the complete active scope.",
            )
        async with self._lock:
            values = self._checkpoints.setdefault(recovery_id, [])
            expected = len(values)
            if checkpoint.sequence != expected:
                raise RecoveryError(
                    "CHECKPOINT_SEQUENCE_CONFLICT",
                    "The checkpoint sequence is not the next monotonic value.",
                    "Reload the latest checkpoint and retry one transition.",
                )
            values.append(checkpoint)

    async def latest_checkpoint(self, recovery_id: UUID, scope: TenantScope) -> Checkpoint:
        async with self._lock:
            values = self._checkpoints.get(recovery_id)
            if not values:
                initializing = any(
                    record.recovery_id == recovery_id and stored_scope == _scope_key(scope)
                    for (stored_scope, _idempotency_key), record in self._claims.items()
                )
                if initializing:
                    raise RecoveryError(
                        "RECOVERY_INITIALIZING",
                        "The first immutable checkpoint is not committed yet.",
                        "Retry after initialization or reconcile the incomplete claim.",
                    )
                raise RecoveryError(
                    "RECOVERY_SCOPE_DENIED",
                    "No recovery state is authorized for this identity scope.",
                    "Use the original task and complete authenticated scope.",
                )
            if values[-1].scope != scope:
                raise RecoveryError(
                    "RECOVERY_SCOPE_DENIED",
                    "No recovery state is authorized for this identity scope.",
                    "Use the original task and complete authenticated scope.",
                )
            return values[-1]

    async def request_interrupt(self, recovery_id: UUID, scope: TenantScope, reason: str) -> None:
        await self.latest_checkpoint(recovery_id, scope)
        async with self._lock:
            self._interrupts[(_scope_key(scope), recovery_id)] = reason

    async def interrupt_reason(self, recovery_id: UUID, scope: TenantScope) -> str | None:
        await self.latest_checkpoint(recovery_id, scope)
        async with self._lock:
            return self._interrupts.get((_scope_key(scope), recovery_id))

    async def clear_interrupt(self, recovery_id: UUID, scope: TenantScope) -> None:
        await self.latest_checkpoint(recovery_id, scope)
        async with self._lock:
            self._interrupts.pop((_scope_key(scope), recovery_id), None)

    async def get_assignment_output(
        self, recovery_id: UUID, scope: TenantScope, execution_key: str
    ) -> bytes | None:
        await self.latest_checkpoint(recovery_id, scope)
        async with self._lock:
            value = self._outputs.get((_scope_key(scope), recovery_id, execution_key))
            if value is None:
                return None
            if _digest(value.content) != value.sha256:
                raise RecoveryError(
                    "ASSIGNMENT_OUTPUT_INTEGRITY_FAILED",
                    "A durable assignment output failed integrity validation.",
                    "Quarantine the output and restore from verified evidence.",
                )
            return value.content

    async def put_assignment_output(
        self,
        recovery_id: UUID,
        scope: TenantScope,
        execution_key: str,
        output: bytes,
    ) -> None:
        await self.latest_checkpoint(recovery_id, scope)
        key = (_scope_key(scope), recovery_id, execution_key)
        value = _HashedOutput(output, _digest(output))
        async with self._lock:
            existing = self._outputs.get(key)
            if existing is not None and existing != value:
                raise RecoveryError(
                    "ASSIGNMENT_OUTPUT_CONFLICT",
                    "An assignment execution key produced different output.",
                    "Stop recovery and reconcile the non-deterministic execution evidence.",
                )
            self._outputs[key] = value

    async def begin_side_effect(
        self,
        recovery_id: UUID,
        scope: TenantScope,
        side_effect_id: UUID,
        request_sha256: str,
    ) -> SideEffectClaim:
        await self.latest_checkpoint(recovery_id, scope)
        key = (_scope_key(scope), recovery_id, side_effect_id)
        async with self._lock:
            existing = self._effects.get(key)
            if existing is None:
                self._effects[key] = _SideEffectRecord(
                    request_sha256=request_sha256,
                    status=SideEffectClaimStatus.STARTED,
                    output=None,
                )
                return SideEffectClaim(SideEffectClaimStatus.NEW, None)
            if existing.request_sha256 != request_sha256:
                raise RecoveryError(
                    "SIDE_EFFECT_IDEMPOTENCY_CONFLICT",
                    "The side-effect ID is bound to different input.",
                    "Use the original exact input or a new stable side-effect ID.",
                )
            if (
                existing.output is not None
                and _digest(existing.output.content) != existing.output.sha256
            ):
                raise RecoveryError(
                    "SIDE_EFFECT_RESULT_INTEGRITY_FAILED",
                    "The committed side-effect result failed integrity validation.",
                    "Reconcile the external evidence before continuing.",
                )
            return SideEffectClaim(
                existing.status,
                existing.output.content if existing.output is not None else None,
            )

    async def commit_side_effect(
        self,
        recovery_id: UUID,
        scope: TenantScope,
        side_effect_id: UUID,
        request_sha256: str,
        output: bytes,
    ) -> None:
        await self.latest_checkpoint(recovery_id, scope)
        key = (_scope_key(scope), recovery_id, side_effect_id)
        value = _HashedOutput(output, _digest(output))
        async with self._lock:
            existing = self._effects.get(key)
            if (
                existing is None
                or existing.request_sha256 != request_sha256
                or existing.status is not SideEffectClaimStatus.STARTED
            ):
                raise RecoveryError(
                    "SIDE_EFFECT_COMMIT_CONFLICT",
                    "The side effect has no matching started claim.",
                    "Reconcile the side-effect journal before committing.",
                )
            self._effects[key] = _SideEffectRecord(
                request_sha256=request_sha256,
                status=SideEffectClaimStatus.COMMITTED,
                output=value,
            )

    async def committed_side_effect_ids(
        self, recovery_id: UUID, scope: TenantScope
    ) -> tuple[UUID, ...]:
        await self.latest_checkpoint(recovery_id, scope)
        scope_key = _scope_key(scope)
        async with self._lock:
            return tuple(
                sorted(
                    (
                        side_effect_id
                        for (stored_scope, stored_recovery, side_effect_id), record in (
                            self._effects.items()
                        )
                        if stored_scope == scope_key
                        and stored_recovery == recovery_id
                        and record.status is SideEffectClaimStatus.COMMITTED
                    ),
                    key=str,
                )
            )

    def corrupt_assignment_output(
        self, scope: TenantScope, recovery_id: UUID, execution_key: str
    ) -> None:
        key = (_scope_key(scope), recovery_id, execution_key)
        value = self._outputs[key]
        self._outputs[key] = _HashedOutput(b"corrupt", value.sha256)

    async def checkpoint_sequences(self, recovery_id: UUID, scope: TenantScope) -> tuple[int, ...]:
        await self.latest_checkpoint(recovery_id, scope)
        async with self._lock:
            return tuple(item.sequence for item in self._checkpoints[recovery_id])


class RecoverableChildExecutor(Protocol):
    async def execute(
        self, context: ChildTaskContext, control: RecoveryControl
    ) -> Mapping[str, Any]: ...


class RecoverableExecutorBinder(Protocol):
    def bind(
        self, contexts: Sequence[ChildTaskContext]
    ) -> Mapping[str, RecoverableChildExecutor]: ...


class RecoveryControl:
    """Durable side-effect and interrupt boundary supplied to a recoverable child."""

    def __init__(
        self,
        backend: RecoveryBackend,
        recovery_id: UUID,
        scope: TenantScope,
    ) -> None:
        self.recovery_id = recovery_id
        self._backend = backend
        self._scope = scope

    async def interruption_requested(self) -> bool:
        return await self._backend.interrupt_reason(self.recovery_id, self._scope) is not None

    async def execute_side_effect(
        self,
        *,
        side_effect_id: UUID,
        request_sha256: str,
        operation: Callable[[], Awaitable[Mapping[str, Any]]],
    ) -> Mapping[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", request_sha256):
            raise RecoveryError(
                "SIDE_EFFECT_REQUEST_HASH_INVALID",
                "The side-effect request hash is invalid.",
                "Provide the SHA-256 of the exact side-effect input.",
            )
        claim = await self._backend.begin_side_effect(
            self.recovery_id,
            self._scope,
            side_effect_id,
            request_sha256,
        )
        if claim.status is SideEffectClaimStatus.COMMITTED:
            assert claim.output is not None
            payload = json.loads(claim.output)
            if not isinstance(payload, dict):
                raise RecoveryError(
                    "SIDE_EFFECT_RESULT_INVALID",
                    "The committed side-effect result is invalid.",
                    "Reconcile the side-effect evidence before continuing.",
                )
            return payload
        if claim.status is SideEffectClaimStatus.STARTED:
            raise RecoveryError(
                "SIDE_EFFECT_RECONCILIATION_REQUIRED",
                "A prior side-effect attempt has no committed outcome.",
                "Reconcile the external system using the stable side-effect ID; do not repeat it.",
            )
        output = await operation()
        encoded = _canonical_json(output)
        await self._backend.commit_side_effect(
            self.recovery_id,
            self._scope,
            side_effect_id,
            request_sha256,
            encoded,
        )
        return dict(output)


class _DurableExecutor(ChildExecutor):
    def __init__(
        self,
        backend: RecoveryBackend,
        recovery_id: UUID,
        physical: RecoverableChildExecutor,
    ) -> None:
        self._backend = backend
        self._recovery_id = recovery_id
        self._physical = physical

    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]:
        execution_key = (
            f"{context.assignment_id}:{context.run_id}:{context.context_manifest_sha256}"
        )
        try:
            cached = await self._backend.get_assignment_output(
                self._recovery_id, context.scope, execution_key
            )
            if cached is not None:
                payload = json.loads(cached)
                if not isinstance(payload, dict):
                    raise RecoveryError(
                        "ASSIGNMENT_OUTPUT_INVALID",
                        "The durable assignment output is not an object.",
                        "Quarantine the output and restore verified evidence.",
                    )
                return payload
            control = RecoveryControl(self._backend, self._recovery_id, context.scope)
            payload = await self._physical.execute(context, control)
            encoded = _canonical_json(payload)
            await self._backend.put_assignment_output(
                self._recovery_id,
                context.scope,
                execution_key,
                encoded,
            )
            return dict(payload)
        except RecoveryError as error:
            raise ChildExecutorError(error.code, error.next_action) from error


@dataclass(frozen=True, slots=True)
class _LoadedRecovery:
    snapshot: RecoverySnapshot
    checkpoint: Checkpoint


class TaskRecoveryRuntime:
    """Persist scheduler boundaries and safely resume from the last committed checkpoint."""

    def __init__(
        self,
        *,
        backend: RecoveryBackend,
        artifact_service: ArtifactStorageService,
        hard_professional_concurrency: int = 4,
        fault_injector: Callable[[RecoveryFaultPoint, RecoverySnapshot], None] | None = None,
        executor_binder: RecoverableExecutorBinder | None = None,
    ) -> None:
        self._backend = backend
        self._artifact_service = artifact_service
        self._hard_professional_concurrency = hard_professional_concurrency
        self._fault_injector = fault_injector
        self._executor_binder = executor_binder
        self._bindings: dict[UUID, Mapping[str, RecoverableChildExecutor]] = {}

    async def submit(
        self,
        contexts: Sequence[ChildTaskContext],
        executors: Mapping[str, RecoverableChildExecutor] | None = None,
        *,
        idempotency_key: str,
    ) -> RecoveryHandle:
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise RecoveryError(
                "IDEMPOTENCY_KEY_INVALID",
                "The idempotency key is invalid.",
                "Use 1 to 256 registered alphanumeric key characters.",
            )
        prepared = tuple(contexts)
        bound = self._resolve_executors(prepared, executors)
        self._validate_schedule(prepared, bound)
        request_sha256 = self._request_sha256(prepared)
        proposed = uuid4()
        first = prepared[0]
        claim = await self._backend.claim(
            first.scope,
            first.parent_task_id,
            idempotency_key,
            request_sha256,
            proposed,
        )
        self._bindings[claim.recovery_id] = dict(bound)
        if claim.reused:
            loaded = await self._load(claim.recovery_id, first.scope, first.parent_task_id)
        else:
            snapshot = RecoverySnapshot(
                recovery_id=claim.recovery_id,
                parent_task_id=first.parent_task_id,
                scope=first.scope,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                sequence=0,
                phase=RecoveryPhase.QUEUED,
                contexts=prepared,
                budget_telemetry=BudgetGuard(first.budget).telemetry(),
                created_at=datetime.now(UTC),
            )
            loaded = await self._write_checkpoint(snapshot)
        return RecoveryHandle(
            recovery_id=claim.recovery_id,
            parent_task_id=loaded.snapshot.parent_task_id,
            scope=loaded.snapshot.scope,
            idempotency_key=loaded.snapshot.idempotency_key,
            request_sha256=loaded.snapshot.request_sha256,
            phase=loaded.snapshot.phase,
            latest_sequence=loaded.snapshot.sequence,
            reused=claim.reused,
        )

    async def advance(
        self,
        recovery_id: UUID,
        *,
        scope: TenantScope,
        parent_task_id: UUID,
        executors: Mapping[str, RecoverableChildExecutor] | None = None,
    ) -> RecoveryOutcome:
        return await self._advance(
            recovery_id,
            scope=scope,
            parent_task_id=parent_task_id,
            executors=executors,
            resume_interrupted=False,
        )

    async def resume(
        self,
        recovery_id: UUID,
        *,
        scope: TenantScope,
        parent_task_id: UUID,
        executors: Mapping[str, RecoverableChildExecutor] | None = None,
    ) -> RecoveryOutcome:
        loaded = await self._load(recovery_id, scope, parent_task_id)
        if loaded.snapshot.phase is not RecoveryPhase.INTERRUPTED:
            raise RecoveryError(
                "RECOVERY_NOT_INTERRUPTED",
                "The recovery run is not waiting at an interrupt.",
                "Advance the active run or select an interrupted checkpoint.",
            )
        await self._backend.clear_interrupt(recovery_id, scope)
        return await self._advance(
            recovery_id,
            scope=scope,
            parent_task_id=parent_task_id,
            executors=executors,
            resume_interrupted=True,
        )

    async def request_interrupt(
        self,
        recovery_id: UUID,
        *,
        scope: TenantScope,
        parent_task_id: UUID,
        reason: str,
    ) -> None:
        if not 1 <= len(reason) <= 1000:
            raise RecoveryError(
                "INTERRUPT_REASON_INVALID",
                "The interrupt reason is missing or too long.",
                "Provide a bounded operator-visible reason.",
            )
        loaded = await self._load(recovery_id, scope, parent_task_id)
        if self._is_terminal(loaded.snapshot.phase):
            raise RecoveryError(
                "RECOVERY_ALREADY_TERMINAL",
                "A terminal recovery run cannot be interrupted.",
                "Inspect the terminal result or submit new work.",
            )
        await self._backend.request_interrupt(recovery_id, scope, reason)

    async def inspect(
        self, recovery_id: UUID, *, scope: TenantScope, parent_task_id: UUID
    ) -> RecoveryOutcome:
        loaded = await self._load(recovery_id, scope, parent_task_id)
        return self._outcome(loaded, recovered=True)

    async def _advance(
        self,
        recovery_id: UUID,
        *,
        scope: TenantScope,
        parent_task_id: UUID,
        executors: Mapping[str, RecoverableChildExecutor] | None,
        resume_interrupted: bool,
    ) -> RecoveryOutcome:
        loaded = await self._load(recovery_id, scope, parent_task_id)
        snapshot = loaded.snapshot
        if self._is_terminal(snapshot.phase):
            return self._outcome(loaded, recovered=True)
        if snapshot.phase is RecoveryPhase.INTERRUPTED and not resume_interrupted:
            return self._outcome(loaded, recovered=True)
        if snapshot.phase is RecoveryPhase.INTERRUPTED and snapshot.schedule_result is not None:
            terminal = self._terminal_snapshot(snapshot, snapshot.schedule_result)
            return self._outcome(await self._write_checkpoint(terminal), recovered=True)
        if snapshot.phase is RecoveryPhase.RUNNING and snapshot.schedule_result is not None:
            reason = await self._backend.interrupt_reason(recovery_id, scope)
            if reason is not None:
                interrupted = self._next_snapshot(
                    snapshot,
                    phase=RecoveryPhase.INTERRUPTED,
                    schedule_result=snapshot.schedule_result,
                    interrupt_reason=reason,
                )
                return self._outcome(await self._write_checkpoint(interrupted), recovered=True)
            terminal = self._terminal_snapshot(snapshot, snapshot.schedule_result)
            return self._outcome(await self._write_checkpoint(terminal), recovered=True)
        reason = await self._backend.interrupt_reason(recovery_id, scope)
        if reason is not None:
            interrupted = self._next_snapshot(
                snapshot,
                phase=RecoveryPhase.INTERRUPTED,
                interrupt_reason=reason,
            )
            return self._outcome(
                await self._write_checkpoint(interrupted),
                recovered=snapshot.phase is not RecoveryPhase.QUEUED,
            )
        bound = executors if executors is not None else self._bindings.get(recovery_id)
        if bound is None and self._executor_binder is not None:
            bound = self._executor_binder.bind(snapshot.contexts)
        if bound is None:
            raise RecoveryError(
                "RECOVERY_EXECUTOR_BINDING_REQUIRED",
                "Recovered work requires explicit authorized executor bindings.",
                "Rebind the exact registered assignment executors and resume.",
            )
        self._validate_schedule(snapshot.contexts, bound)
        self._bindings[recovery_id] = dict(bound)
        prior_phase = snapshot.phase
        try:
            guard = BudgetGuard.from_telemetry(snapshot.budget_telemetry)
        except BudgetContractError as error:
            raise RecoveryError(
                error.code,
                "The persisted budget state cannot be restored safely.",
                "Inspect or migrate the checkpoint before resuming execution.",
            ) from error
        if guard.telemetry().counters.reserved_graph_steps:
            guard.abandon_graph_reservation()
        try:
            guard.reserve_graph_steps(4 * len(snapshot.contexts))
        except BudgetExceeded as error:
            guard.record_terminal_transition(budget_stop=True)
            result = self._budget_stop_result(snapshot, error)
            terminal = self._terminal_snapshot(
                snapshot,
                result,
                budget_telemetry=guard.telemetry(),
            )
            return self._outcome(
                await self._write_checkpoint(terminal),
                recovered=prior_phase is not RecoveryPhase.QUEUED,
            )
        running = self._next_snapshot(
            snapshot,
            phase=RecoveryPhase.RUNNING,
            budget_telemetry=guard.telemetry(),
        )
        loaded_running = await self._write_checkpoint(running)
        self._inject(RecoveryFaultPoint.AFTER_RUNNING_CHECKPOINT, loaded_running.snapshot)
        durable = {
            assignment_id: _DurableExecutor(self._backend, recovery_id, executor)
            for assignment_id, executor in bound.items()
        }
        scheduler = TaskScheduler(
            hard_professional_concurrency=self._hard_professional_concurrency,
            budget_guard=guard,
        )
        result = await scheduler.run_sync(
            snapshot.contexts,
            durable,
            schedule_id=recovery_id,
        )
        guard.release_graph_reservation()
        post_execution = self._next_snapshot(
            loaded_running.snapshot,
            phase=RecoveryPhase.RUNNING,
            schedule_result=result,
            budget_telemetry=guard.telemetry(),
        )
        loaded_post_execution = await self._write_checkpoint(post_execution)
        self._inject(
            RecoveryFaultPoint.AFTER_ASSIGNMENT_OUTPUTS,
            loaded_post_execution.snapshot,
        )
        reason = await self._backend.interrupt_reason(recovery_id, scope)
        if reason is not None:
            interrupted = self._next_snapshot(
                loaded_post_execution.snapshot,
                phase=RecoveryPhase.INTERRUPTED,
                schedule_result=result,
                interrupt_reason=reason,
            )
            return self._outcome(
                await self._write_checkpoint(interrupted),
                recovered=prior_phase is not RecoveryPhase.QUEUED,
            )
        terminal = self._terminal_snapshot(loaded_post_execution.snapshot, result)
        return self._outcome(
            await self._write_checkpoint(terminal),
            recovered=prior_phase is not RecoveryPhase.QUEUED,
        )

    def _validate_schedule(
        self,
        contexts: tuple[ChildTaskContext, ...],
        executors: Mapping[str, RecoverableChildExecutor],
    ) -> None:
        keys = set(executors)
        placeholders = {key: _NeverExecute() for key in keys}
        TaskScheduler(hard_professional_concurrency=self._hard_professional_concurrency).validate(
            contexts, placeholders
        )

    def _resolve_executors(
        self,
        contexts: tuple[ChildTaskContext, ...],
        executors: Mapping[str, RecoverableChildExecutor] | None,
    ) -> Mapping[str, RecoverableChildExecutor]:
        if executors is not None:
            return executors
        if self._executor_binder is not None:
            return self._executor_binder.bind(contexts)
        raise RecoveryError(
            "RECOVERY_EXECUTOR_BINDING_REQUIRED",
            "Recovered work requires explicit authorized executor bindings.",
            "Provide exact executors or configure an authorized recoverable binder.",
        )

    @staticmethod
    def _request_sha256(contexts: tuple[ChildTaskContext, ...]) -> str:
        payload = {
            "graph_version": RECOVERY_GRAPH_VERSION,
            "state_schema_version": RECOVERY_STATE_SCHEMA_VERSION,
            "contexts": [item.model_dump(mode="json") for item in contexts],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return _digest(encoded)

    async def _write_checkpoint(self, snapshot: RecoverySnapshot) -> _LoadedRecovery:
        committed = (
            await self._backend.committed_side_effect_ids(snapshot.recovery_id, snapshot.scope)
            if snapshot.sequence > 0
            else ()
        )
        snapshot = RecoverySnapshot.model_validate(
            {
                **snapshot.model_dump(mode="json"),
                "committed_side_effect_ids": committed,
            }
        )
        content = snapshot.model_dump_json().encode("utf-8")
        state_sha256 = _digest(content)
        checkpoint_id = uuid4()
        classification = self._checkpoint_classification(snapshot.contexts)
        try:
            artifact = await self._artifact_service.put(
                scope=snapshot.scope,
                artifact_id=uuid4(),
                artifact_version=f"checkpoint-{snapshot.sequence}",
                content=content,
                media_type="application/vnd.ndt.recovery+json",
                classification=classification,
            )
        except StorageError as error:
            raise RecoveryError(
                error.code,
                "Checkpoint artifact storage failed.",
                error.next_action,
            ) from error
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            task_id=snapshot.parent_task_id,
            scope=snapshot.scope,
            sequence=snapshot.sequence,
            graph_version=RECOVERY_GRAPH_VERSION,
            state_schema_version=RECOVERY_STATE_SCHEMA_VERSION,
            state_artifact=artifact,
            state_sha256=state_sha256,
            committed_side_effect_ids=committed,
            created_at=snapshot.created_at,
        )
        await self._backend.append_checkpoint(snapshot.recovery_id, snapshot.scope, checkpoint)
        return _LoadedRecovery(snapshot=snapshot, checkpoint=checkpoint)

    async def _load(
        self, recovery_id: UUID, scope: TenantScope, parent_task_id: UUID
    ) -> _LoadedRecovery:
        checkpoint = await self._backend.latest_checkpoint(recovery_id, scope)
        if checkpoint.task_id != parent_task_id:
            raise RecoveryError(
                "RECOVERY_SCOPE_DENIED",
                "No recovery state is authorized for this task binding.",
                "Use the original task and complete authenticated scope.",
            )
        if (
            checkpoint.graph_version != RECOVERY_GRAPH_VERSION
            or checkpoint.state_schema_version != RECOVERY_STATE_SCHEMA_VERSION
        ):
            raise RecoveryError(
                "CHECKPOINT_VERSION_INCOMPATIBLE",
                "The checkpoint graph or state schema is incompatible.",
                "Run an approved migration or restore with the matching runtime version.",
            )
        if (
            not checkpoint.state_artifact.immutable
            or checkpoint.state_artifact.scope != scope
            or checkpoint.state_artifact.sha256 != checkpoint.state_sha256
        ):
            raise RecoveryError(
                "CHECKPOINT_BINDING_INVALID",
                "The checkpoint artifact reference does not match trusted metadata.",
                "Quarantine the checkpoint and restore verified evidence.",
            )
        try:
            content = await self._artifact_service.get(scope, checkpoint.state_artifact)
        except StorageError as error:
            raise RecoveryError(
                "CHECKPOINT_INTEGRITY_FAILED",
                "The checkpoint artifact failed integrity validation.",
                error.next_action,
            ) from error
        if _digest(content) != checkpoint.state_sha256:
            raise RecoveryError(
                "CHECKPOINT_INTEGRITY_FAILED",
                "The checkpoint payload hash does not match its metadata.",
                "Quarantine the checkpoint and restore verified evidence.",
            )
        try:
            snapshot = RecoverySnapshot.model_validate_json(content)
        except ValidationError as error:
            raise RecoveryError(
                "CHECKPOINT_SCHEMA_INVALID",
                "The checkpoint payload does not match the recovery schema.",
                "Migrate or restore a valid versioned checkpoint.",
            ) from error
        if (
            snapshot.recovery_id != recovery_id
            or snapshot.parent_task_id != parent_task_id
            or snapshot.scope != scope
            or snapshot.sequence != checkpoint.sequence
            or snapshot.committed_side_effect_ids != checkpoint.committed_side_effect_ids
        ):
            raise RecoveryError(
                "CHECKPOINT_BINDING_INVALID",
                "The checkpoint payload does not match its trusted metadata.",
                "Quarantine the checkpoint and restore verified evidence.",
            )
        if any(
            context.context_manifest_sha256 != child_context_manifest_sha256(context)
            for context in snapshot.contexts
        ):
            raise RecoveryError(
                "CHECKPOINT_CONTEXT_INTEGRITY_FAILED",
                "A restored child context failed manifest validation.",
                "Restore a checkpoint created from the verified dispatch.",
            )
        return _LoadedRecovery(snapshot=snapshot, checkpoint=checkpoint)

    @staticmethod
    def _next_snapshot(
        snapshot: RecoverySnapshot,
        *,
        phase: RecoveryPhase,
        schedule_result: ScheduleResult | None = None,
        budget_telemetry: BudgetTelemetry | None = None,
        interrupt_reason: str | None = None,
    ) -> RecoverySnapshot:
        return RecoverySnapshot.model_validate(
            {
                **snapshot.model_dump(mode="json"),
                "sequence": snapshot.sequence + 1,
                "phase": phase,
                "schedule_result": (
                    schedule_result.model_dump(mode="json") if schedule_result is not None else None
                ),
                "budget_telemetry": (
                    budget_telemetry.model_dump(mode="json")
                    if budget_telemetry is not None
                    else snapshot.budget_telemetry.model_dump(mode="json")
                ),
                "interrupt_reason": interrupt_reason,
                "created_at": datetime.now(UTC),
            }
        )

    def _terminal_snapshot(
        self,
        snapshot: RecoverySnapshot,
        result: ScheduleResult,
        *,
        budget_telemetry: BudgetTelemetry | None = None,
    ) -> RecoverySnapshot:
        phase = {
            ScheduleStatus.COMPLETED: RecoveryPhase.COMPLETED,
            ScheduleStatus.PARTIAL: RecoveryPhase.PARTIAL,
            ScheduleStatus.FAILED: RecoveryPhase.FAILED,
            ScheduleStatus.CANCELLED: RecoveryPhase.CANCELLED,
        }[result.status]
        return self._next_snapshot(
            snapshot,
            phase=phase,
            schedule_result=result,
            budget_telemetry=budget_telemetry,
        )

    @staticmethod
    def _budget_stop_result(snapshot: RecoverySnapshot, error: BudgetExceeded) -> ScheduleResult:
        return ScheduleResult(
            schedule_id=snapshot.recovery_id,
            parent_task_id=snapshot.parent_task_id,
            scope=snapshot.scope,
            mode=ScheduleMode.SYNC,
            status=ScheduleStatus.FAILED,
            assignments=tuple(
                ScheduledAssignment(
                    assignment_id=context.assignment_id,
                    run_id=context.run_id,
                    wave=1,
                    status=AssignmentStatus.BLOCKED,
                    execution_calls=0,
                    outcome=None,
                    error_code=error.code,
                    next_action=error.next_action,
                )
                for context in snapshot.contexts
            ),
            waves_completed=0,
            max_concurrency_observed=0,
        )

    @staticmethod
    def _checkpoint_classification(contexts: tuple[ChildTaskContext, ...]) -> DataClassification:
        priority = {
            DataClassification.PUBLIC: 0,
            DataClassification.INTERNAL: 1,
            DataClassification.CONFIDENTIAL: 2,
            DataClassification.RESTRICTED: 3,
        }
        classifications = [
            artifact.classification for context in contexts for artifact in context.artifacts
        ]
        return max(classifications, key=priority.__getitem__, default=DataClassification.INTERNAL)

    @staticmethod
    def _is_terminal(phase: RecoveryPhase) -> bool:
        return phase in {
            RecoveryPhase.COMPLETED,
            RecoveryPhase.PARTIAL,
            RecoveryPhase.FAILED,
            RecoveryPhase.CANCELLED,
        }

    @staticmethod
    def _outcome(loaded: _LoadedRecovery, *, recovered: bool) -> RecoveryOutcome:
        return RecoveryOutcome(
            recovery_id=loaded.snapshot.recovery_id,
            parent_task_id=loaded.snapshot.parent_task_id,
            scope=loaded.snapshot.scope,
            phase=loaded.snapshot.phase,
            checkpoint=loaded.checkpoint,
            schedule_result=loaded.snapshot.schedule_result,
            budget_telemetry=loaded.snapshot.budget_telemetry,
            recovered=recovered,
            interrupt_reason=loaded.snapshot.interrupt_reason,
        )

    def _inject(self, point: RecoveryFaultPoint, snapshot: RecoverySnapshot) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point, snapshot)


class _NeverExecute:
    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]:
        raise AssertionError(f"validation executor called for {context.assignment_id}")
