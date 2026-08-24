"""Central versioned runtime budgets, reservations, degradation, and telemetry."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import Field

from ndt_agents.contracts.v1 import BudgetPolicy, Limit, StrictModel


class BudgetDimension(StrEnum):
    GRAPH_STEPS = "graph_steps"
    LLM_CALLS = "llm_calls"
    TOOL_CALLS = "tool_calls"
    TOTAL_TOKENS = "total_tokens"
    WALL_TIME_MS = "wall_time_ms"
    PROFESSIONAL_CONCURRENCY = "professional_concurrency"
    REVIEW_ROUNDS = "review_rounds"
    CORRECTION_ROUNDS = "correction_rounds"


class BudgetActionClass(StrEnum):
    LOW_VALUE = "LOW_VALUE"
    QUERY_EXPANSION = "QUERY_EXPANSION"
    STANDARD = "STANDARD"
    VALIDATION = "VALIDATION"
    FINALIZATION = "FINALIZATION"


class DegradationStage(StrEnum):
    NORMAL = "NORMAL"
    REDUCE_LOW_VALUE = "REDUCE_LOW_VALUE"
    STOP_EXPANSION = "STOP_EXPANSION"
    FINALIZE_ONLY = "FINALIZE_ONLY"
    STOPPED = "STOPPED"


class BudgetDecision(StrEnum):
    ALLOWED = "ALLOWED"
    RECORDED = "RECORDED"
    DENIED = "DENIED"


class BudgetEvent(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=128)
    dimension: BudgetDimension | None
    amount: int = Field(ge=0)
    before: int = Field(ge=0)
    after: int = Field(ge=0)
    active_limit: int | None = Field(default=None, ge=0)
    hard_limit: int | None = Field(default=None, ge=0)
    decision: BudgetDecision
    error_code: str | None = Field(default=None, max_length=128)
    elapsed_ms: int = Field(ge=0)
    action_signature: str | None = Field(default=None, max_length=512)
    observation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class BudgetCounters(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    graph_steps: int = Field(ge=0)
    reserved_graph_steps: int = Field(ge=0)
    terminal_transitions: int = Field(ge=0)
    terminal_budget_stops: int = Field(ge=0)
    physical_llm_calls: int = Field(ge=0)
    physical_tool_calls: int = Field(ge=0)
    actual_total_tokens: int = Field(ge=0)
    reserved_total_tokens: int = Field(ge=0)
    logical_actions: int = Field(ge=0)
    retries: int = Field(ge=0)
    llm_failures: int = Field(ge=0)
    tool_failures: int = Field(ge=0)
    cache_lookups: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    review_rounds: int = Field(ge=0)
    correction_rounds: int = Field(ge=0)
    current_professional_concurrency: int = Field(ge=0)
    peak_professional_concurrency: int = Field(ge=0)


class BudgetTelemetry(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy: BudgetPolicy
    counters: BudgetCounters
    elapsed_ms: int = Field(ge=0)
    degradation_stage: DegradationStage
    events: tuple[BudgetEvent, ...]


class BudgetStop(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["PARTIAL", "FAILED"]
    error_code: str = Field(min_length=1, max_length=128)
    cause: str = Field(min_length=1, max_length=1000)
    completed_work: tuple[str, ...]
    impact: str = Field(min_length=1, max_length=2000)
    next_action: str = Field(min_length=1, max_length=2000)
    telemetry: BudgetTelemetry


class BudgetElevationAuthority(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: Literal["DETERMINISTIC_RISK_POLICY", "HUMAN_APPROVAL"]
    reference_id: str = Field(min_length=1, max_length=128)


class BudgetElevationRecord(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_policy_id: str
    elevated_policy: BudgetPolicy
    authority: BudgetElevationAuthority
    active_limits: dict[str, int]


class BudgetExceeded(RuntimeError):
    """Typed pre-call or post-provider budget stop."""

    def __init__(
        self,
        *,
        code: str,
        cause: str,
        impact: str,
        next_action: str,
        telemetry: BudgetTelemetry,
    ) -> None:
        super().__init__(cause)
        self.code = code
        self.cause = cause
        self.impact = impact
        self.next_action = next_action
        self.telemetry = telemetry

    def to_stop(self, *, completed_work: tuple[str, ...] = (), partial: bool = False) -> BudgetStop:
        return BudgetStop(
            status="PARTIAL" if partial else "FAILED",
            error_code=self.code,
            cause=self.cause,
            completed_work=completed_work,
            impact=self.impact,
            next_action=self.next_action,
            telemetry=self.telemetry,
        )


class BudgetContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_DEFAULTS: dict[str, dict[str, tuple[int, int]]] = {
    "G0": {
        "graph_steps": (8, 12),
        "llm_calls": (3, 4),
        "tool_calls": (2, 4),
        "total_tokens": (4_000, 8_000),
        "wall_time_ms": (30_000, 60_000),
        "professional_concurrency": (0, 0),
    },
    "P1": {
        "graph_steps": (16, 24),
        "llm_calls": (6, 10),
        "tool_calls": (6, 10),
        "total_tokens": (10_000, 20_000),
        "wall_time_ms": (120_000, 300_000),
        "professional_concurrency": (1, 1),
    },
    "P2": {
        "graph_steps": (32, 48),
        "llm_calls": (18, 32),
        "tool_calls": (16, 24),
        "total_tokens": (35_000, 60_000),
        "wall_time_ms": (900_000, 1_800_000),
        "professional_concurrency": (1, 2),
    },
    "P3": {
        "graph_steps": (48, 64),
        "llm_calls": (24, 40),
        "tool_calls": (30, 48),
        "total_tokens": (60_000, 120_000),
        "wall_time_ms": (3_600_000, 7_200_000),
        "professional_concurrency": (3, 4),
    },
    "K1": {
        "graph_steps": (48, 64),
        "llm_calls": (7, 12),
        "tool_calls": (5, 8),
        "total_tokens": (20_000, 40_000),
        "wall_time_ms": (7_200_000, 14_400_000),
        "professional_concurrency": (2, 4),
    },
}


def default_budget_policy(
    task_class: Literal["G0", "P1", "P2", "P3", "K1"],
    *,
    file_count: int = 1,
) -> BudgetPolicy:
    """Create the single initial policy table defined by the controlled specification."""

    if not 1 <= file_count <= 10_000:
        raise BudgetContractError("BUDGET_FILE_COUNT_INVALID", "file count is outside bounds")
    values = dict(_DEFAULTS[task_class])
    policy_id = f"budget-{task_class.lower()}-v1"
    if task_class == "K1":
        values["tool_calls"] = (5 * file_count, min(8 * file_count, 400))
        if values["tool_calls"][0] > values["tool_calls"][1]:
            values["tool_calls"] = (values["tool_calls"][1], values["tool_calls"][1])
        policy_id = f"{policy_id}-files-{file_count}"

    def limit(name: str) -> Limit:
        default, hard = values[name]
        return Limit(default=default, active=default, hard=hard)

    return BudgetPolicy(
        policy_id=policy_id,
        task_class=task_class,
        graph_steps=limit("graph_steps"),
        llm_calls=limit("llm_calls"),
        tool_calls=limit("tool_calls"),
        total_tokens=limit("total_tokens"),
        wall_time_ms=limit("wall_time_ms"),
        professional_concurrency=limit("professional_concurrency"),
        review_rounds=Limit(default=1, active=1, hard=2),
        correction_rounds=Limit(default=1, active=1, hard=2),
    )


def elevate_budget_policy(
    policy: BudgetPolicy,
    *,
    new_policy_id: str,
    active_limits: Mapping[BudgetDimension, int],
    authority: BudgetElevationAuthority,
) -> BudgetElevationRecord:
    """Create an explicit elevation record without mutating the source policy."""

    if not new_policy_id or len(new_policy_id) > 128 or new_policy_id == policy.policy_id:
        raise BudgetContractError(
            "BUDGET_POLICY_ID_INVALID", "an elevated policy requires a distinct bounded ID"
        )
    updates: dict[str, Limit] = {}
    recorded: dict[str, int] = {}
    for dimension, active in active_limits.items():
        current = getattr(policy, dimension.value)
        if active < current.default or active > current.hard:
            raise BudgetContractError(
                "BUDGET_ELEVATION_DENIED",
                "active limit must remain between default and non-overridable hard limit",
            )
        updates[dimension.value] = Limit(
            default=current.default,
            active=active,
            hard=current.hard,
        )
        recorded[dimension.value] = active
    elevated = policy.model_copy(
        update={"policy_id": new_policy_id, **updates},
    )
    return BudgetElevationRecord(
        source_policy_id=policy.policy_id,
        elevated_policy=elevated,
        authority=authority,
        active_limits=recorded,
    )


class BudgetGuard:
    """Reserve before calls, trace every decision, and never exceed an active or hard limit."""

    def __init__(
        self,
        policy: BudgetPolicy,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy
        self._clock = clock
        self._started = clock()
        self._counts = {dimension: 0 for dimension in BudgetDimension}
        self._reserved_graph_steps = 0
        self._reserved_tokens = 0
        self._logical_actions = 0
        self._terminal_transitions = 0
        self._terminal_budget_stops = 0
        self._retries = 0
        self._llm_failures = 0
        self._tool_failures = 0
        self._cache_lookups = 0
        self._cache_hits = 0
        self._peak_concurrency = 0
        self._events: list[BudgetEvent] = []
        self._llm_reservations: dict[UUID, int] = {}
        self._tool_reservations: set[UUID] = set()
        self._action_history: list[tuple[str, str]] = []

    @classmethod
    def from_telemetry(
        cls,
        telemetry: BudgetTelemetry,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> BudgetGuard:
        """Restore durable counters without reopening in-flight external calls."""

        counters = telemetry.counters
        if counters.current_professional_concurrency != 0:
            raise BudgetContractError(
                "BUDGET_RESTORE_CONCURRENCY_ACTIVE",
                "budget telemetry cannot restore an active professional lease",
            )
        if counters.reserved_total_tokens != 0:
            raise BudgetContractError(
                "BUDGET_RESTORE_LLM_RESERVATION_ACTIVE",
                "budget telemetry cannot restore an in-flight LLM reservation",
            )
        guard = cls(telemetry.policy, clock=clock)
        guard._started = clock() - (telemetry.elapsed_ms / 1000)
        guard._counts.update(
            {
                BudgetDimension.GRAPH_STEPS: counters.graph_steps,
                BudgetDimension.LLM_CALLS: counters.physical_llm_calls,
                BudgetDimension.TOOL_CALLS: counters.physical_tool_calls,
                BudgetDimension.TOTAL_TOKENS: counters.actual_total_tokens,
                BudgetDimension.REVIEW_ROUNDS: counters.review_rounds,
                BudgetDimension.CORRECTION_ROUNDS: counters.correction_rounds,
                BudgetDimension.PROFESSIONAL_CONCURRENCY: 0,
            }
        )
        guard._reserved_graph_steps = counters.reserved_graph_steps
        guard._logical_actions = counters.logical_actions
        guard._terminal_transitions = counters.terminal_transitions
        guard._terminal_budget_stops = counters.terminal_budget_stops
        guard._retries = counters.retries
        guard._llm_failures = counters.llm_failures
        guard._tool_failures = counters.tool_failures
        guard._cache_lookups = counters.cache_lookups
        guard._cache_hits = counters.cache_hits
        guard._peak_concurrency = counters.peak_professional_concurrency
        guard._events = list(telemetry.events)
        guard._action_history = [
            (event.action_signature, event.observation_sha256)
            for event in telemetry.events
            if event.event_type == "tool_call_started"
            and event.action_signature is not None
            and event.observation_sha256 is not None
        ][-10:]
        return guard

    def telemetry(self) -> BudgetTelemetry:
        elapsed = self._elapsed_ms()
        counters = BudgetCounters(
            graph_steps=self._counts[BudgetDimension.GRAPH_STEPS],
            reserved_graph_steps=self._reserved_graph_steps,
            terminal_transitions=self._terminal_transitions,
            terminal_budget_stops=self._terminal_budget_stops,
            physical_llm_calls=self._counts[BudgetDimension.LLM_CALLS],
            physical_tool_calls=self._counts[BudgetDimension.TOOL_CALLS],
            actual_total_tokens=self._counts[BudgetDimension.TOTAL_TOKENS],
            reserved_total_tokens=self._reserved_tokens,
            logical_actions=self._logical_actions,
            retries=self._retries,
            llm_failures=self._llm_failures,
            tool_failures=self._tool_failures,
            cache_lookups=self._cache_lookups,
            cache_hits=self._cache_hits,
            review_rounds=self._counts[BudgetDimension.REVIEW_ROUNDS],
            correction_rounds=self._counts[BudgetDimension.CORRECTION_ROUNDS],
            current_professional_concurrency=self._counts[BudgetDimension.PROFESSIONAL_CONCURRENCY],
            peak_professional_concurrency=self._peak_concurrency,
        )
        return BudgetTelemetry(
            policy=self.policy,
            counters=counters,
            elapsed_ms=elapsed,
            degradation_stage=self._degradation_stage(elapsed),
            events=tuple(self._events),
        )

    def record_graph_step(
        self, *, action_class: BudgetActionClass = BudgetActionClass.STANDARD
    ) -> None:
        if self._reserved_graph_steps:
            self._check_time()
            before = self._counts[BudgetDimension.GRAPH_STEPS]
            self._reserved_graph_steps -= 1
            self._increment(BudgetDimension.GRAPH_STEPS, 1)
            self._logical_actions += 1
            self._record(
                event_type="graph_step_reservation_consumed",
                dimension=BudgetDimension.GRAPH_STEPS,
                amount=1,
                before=before,
                after=before + 1,
                decision=BudgetDecision.ALLOWED,
            )
            return
        self._ensure_capacity(BudgetDimension.GRAPH_STEPS, 1, "graph_step_denied")
        self.authorize_action(action_class)
        self._consume(BudgetDimension.GRAPH_STEPS, 1, "graph_step", logical=True)

    def reserve_graph_steps(self, amount: int) -> None:
        """Durably reserve a bounded execution attempt before starting child work."""

        if amount < 1:
            raise BudgetContractError(
                "BUDGET_GRAPH_RESERVATION_INVALID",
                "graph-step reservation must be positive",
            )
        self._check_time()
        current = self._counts[BudgetDimension.GRAPH_STEPS] + self._reserved_graph_steps
        self._ensure_capacity(
            BudgetDimension.GRAPH_STEPS,
            amount,
            "graph_steps_reservation_denied",
            current_override=current,
        )
        self.authorize_action(BudgetActionClass.STANDARD)
        self._reserved_graph_steps += amount
        self._record(
            event_type="graph_steps_reserved",
            dimension=BudgetDimension.GRAPH_STEPS,
            amount=amount,
            before=current,
            after=current + amount,
            decision=BudgetDecision.ALLOWED,
        )

    def abandon_graph_reservation(self) -> None:
        """Conservatively charge an attempt whose process ended before telemetry committed."""

        amount = self._reserved_graph_steps
        if amount == 0:
            return
        before = self._counts[BudgetDimension.GRAPH_STEPS]
        self._reserved_graph_steps = 0
        self._increment(BudgetDimension.GRAPH_STEPS, amount)
        self._logical_actions += amount
        self._retries += 1
        self._record(
            event_type="graph_reservation_abandoned",
            dimension=BudgetDimension.GRAPH_STEPS,
            amount=amount,
            before=before,
            after=before + amount,
            decision=BudgetDecision.RECORDED,
        )

    def release_graph_reservation(self) -> None:
        """Release unused capacity after a scheduler attempt returned a durable result."""

        amount = self._reserved_graph_steps
        if amount == 0:
            return
        current = self._counts[BudgetDimension.GRAPH_STEPS] + amount
        self._reserved_graph_steps = 0
        self._record(
            event_type="graph_reservation_released",
            dimension=BudgetDimension.GRAPH_STEPS,
            amount=amount,
            before=current,
            after=current - amount,
            decision=BudgetDecision.RECORDED,
        )

    def record_cache_lookup(self, *, hit: bool) -> None:
        self._ensure_capacity(BudgetDimension.GRAPH_STEPS, 1, "cache_lookup_denied")
        self.authorize_action(BudgetActionClass.STANDARD)
        self._consume(BudgetDimension.GRAPH_STEPS, 1, "cache_lookup", logical=True)
        self._cache_lookups += 1
        if hit:
            self._cache_hits += 1
        self._record(
            event_type="cache_hit" if hit else "cache_miss",
            decision=BudgetDecision.RECORDED,
        )

    def record_terminal_transition(self, *, budget_stop: bool = False) -> None:
        """Count a terminal state transition separately from ReAct action steps."""

        self._terminal_transitions += 1
        if budget_stop:
            self._terminal_budget_stops += 1
        self._record(
            event_type=(
                "terminal_budget_stop_transition" if budget_stop else "terminal_transition"
            ),
            decision=BudgetDecision.RECORDED,
        )

    def begin_llm_call(
        self,
        *,
        maximum_total_tokens: int,
        retry: bool = False,
        action_class: BudgetActionClass = BudgetActionClass.STANDARD,
    ) -> UUID:
        if maximum_total_tokens < 1:
            raise BudgetContractError(
                "BUDGET_TOKEN_RESERVATION_INVALID", "token reservation must be positive"
            )
        self._check_time()
        self._ensure_capacity(BudgetDimension.LLM_CALLS, 1, "llm_call_denied")
        self._ensure_token_capacity(maximum_total_tokens, "llm_token_reservation_denied")
        self.authorize_action(action_class)
        self._increment(BudgetDimension.LLM_CALLS, 1)
        self._logical_actions += 1
        if retry:
            self._retries += 1
        reservation_id = uuid4()
        token_before = self._counts[BudgetDimension.TOTAL_TOKENS] + self._reserved_tokens
        self._llm_reservations[reservation_id] = maximum_total_tokens
        self._reserved_tokens += maximum_total_tokens
        self._record(
            event_type="llm_call_reserved",
            dimension=BudgetDimension.LLM_CALLS,
            amount=1,
            before=self._counts[BudgetDimension.LLM_CALLS] - 1,
            after=self._counts[BudgetDimension.LLM_CALLS],
            decision=BudgetDecision.ALLOWED,
        )
        self._record(
            event_type="llm_tokens_reserved",
            dimension=BudgetDimension.TOTAL_TOKENS,
            amount=maximum_total_tokens,
            before=token_before,
            after=token_before + maximum_total_tokens,
            decision=BudgetDecision.ALLOWED,
        )
        return reservation_id

    def complete_llm_call(
        self,
        reservation_id: UUID,
        *,
        input_tokens: int,
        output_tokens: int,
        success: bool,
    ) -> None:
        reserved = self._llm_reservations.get(reservation_id)
        if reserved is None:
            raise BudgetContractError(
                "BUDGET_RESERVATION_UNKNOWN", "LLM reservation is missing or already completed"
            )
        if input_tokens < 0 or output_tokens < 0:
            raise BudgetContractError(
                "BUDGET_ACTUAL_TOKENS_INVALID", "actual token counts cannot be negative"
            )
        self._llm_reservations.pop(reservation_id)
        actual = input_tokens + output_tokens
        self._reserved_tokens -= reserved
        before = self._counts[BudgetDimension.TOTAL_TOKENS]
        self._increment(BudgetDimension.TOTAL_TOKENS, actual)
        if not success:
            self._llm_failures += 1
        if actual > reserved:
            self._record(
                event_type="llm_token_reservation_exceeded",
                dimension=BudgetDimension.TOTAL_TOKENS,
                amount=actual,
                before=before,
                after=before + actual,
                decision=BudgetDecision.DENIED,
                error_code="BUDGET_TOKEN_RESERVATION_EXCEEDED",
            )
            self._raise(
                "BUDGET_TOKEN_RESERVATION_EXCEEDED",
                "The provider reported more tokens than the pre-call reservation.",
                "Token telemetry may exceed the planned limit; no further model call is safe.",
                "Inspect the provider token cap and return a typed partial result.",
            )
        self._record(
            event_type="llm_call_completed" if success else "llm_call_failed",
            dimension=BudgetDimension.TOTAL_TOKENS,
            amount=actual,
            before=before,
            after=before + actual,
            decision=BudgetDecision.RECORDED,
        )

    def begin_tool_call(
        self,
        *,
        tool_name: str,
        tool_version: str,
        arguments: Mapping[str, Any],
        observation_sha256: str,
        retry: bool = False,
        action_class: BudgetActionClass = BudgetActionClass.STANDARD,
    ) -> UUID:
        self._check_time()
        if not 1 <= len(tool_name) <= 128 or not 1 <= len(tool_version) <= 64:
            raise BudgetContractError(
                "BUDGET_TOOL_IDENTITY_INVALID", "tool name and version are required"
            )
        if not _is_sha256(observation_sha256):
            raise BudgetContractError(
                "BUDGET_OBSERVATION_HASH_INVALID", "observation hash must be SHA-256"
            )
        try:
            encoded = json.dumps(
                dict(arguments), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise BudgetContractError(
                "BUDGET_TOOL_ARGUMENTS_INVALID", "tool arguments must be canonical JSON"
            ) from error
        arguments_sha256 = hashlib.sha256(encoded).hexdigest()
        signature = f"{tool_name}@{tool_version}:{arguments_sha256}"
        if (signature, observation_sha256) in self._action_history:
            self._record(
                event_type="identical_tool_call_denied",
                dimension=BudgetDimension.TOOL_CALLS,
                decision=BudgetDecision.DENIED,
                error_code="BUDGET_IDENTICAL_TOOL_CALL",
                action_signature=signature,
            )
            self._raise(
                "BUDGET_IDENTICAL_TOOL_CALL",
                "An identical tool call has no new observation.",
                "The repeated physical call was not started.",
                "Change the input, provide new evidence, or stop with the current result.",
            )
        self._ensure_capacity(BudgetDimension.TOOL_CALLS, 1, "tool_call_denied")
        self.authorize_action(action_class)
        before = self._counts[BudgetDimension.TOOL_CALLS]
        self._increment(BudgetDimension.TOOL_CALLS, 1)
        self._logical_actions += 1
        if retry:
            self._retries += 1
        self._action_history.append((signature, observation_sha256))
        self._action_history = self._action_history[-10:]
        reservation_id = uuid4()
        self._tool_reservations.add(reservation_id)
        self._record(
            event_type="tool_call_started",
            dimension=BudgetDimension.TOOL_CALLS,
            amount=1,
            before=before,
            after=before + 1,
            decision=BudgetDecision.ALLOWED,
            action_signature=signature,
            observation_sha256=observation_sha256,
        )
        return reservation_id

    def complete_tool_call(self, reservation_id: UUID, *, success: bool) -> None:
        if reservation_id not in self._tool_reservations:
            raise BudgetContractError(
                "BUDGET_RESERVATION_UNKNOWN", "tool reservation is missing or already completed"
            )
        self._tool_reservations.remove(reservation_id)
        if not success:
            self._tool_failures += 1
        self._record(
            event_type="tool_call_completed" if success else "tool_call_failed",
            decision=BudgetDecision.RECORDED,
        )

    def record_review(self) -> None:
        self._ensure_capacity(BudgetDimension.REVIEW_ROUNDS, 1, "review_round_denied")
        self.authorize_action(BudgetActionClass.VALIDATION)
        self._consume(BudgetDimension.REVIEW_ROUNDS, 1, "review_round", logical=True)

    def record_correction(self) -> None:
        self._ensure_capacity(BudgetDimension.CORRECTION_ROUNDS, 1, "correction_round_denied")
        self.authorize_action(BudgetActionClass.VALIDATION)
        self._consume(BudgetDimension.CORRECTION_ROUNDS, 1, "correction_round", logical=True)

    def authorize_action(self, action_class: BudgetActionClass) -> None:
        self._check_time()
        stage = self._degradation_stage(self._elapsed_ms())
        denied = False
        if stage is DegradationStage.STOPPED:
            denied = action_class not in {
                BudgetActionClass.VALIDATION,
                BudgetActionClass.FINALIZATION,
            }
        elif stage is DegradationStage.FINALIZE_ONLY:
            denied = action_class not in {
                BudgetActionClass.VALIDATION,
                BudgetActionClass.FINALIZATION,
            }
        elif stage is DegradationStage.STOP_EXPANSION:
            denied = action_class in {
                BudgetActionClass.LOW_VALUE,
                BudgetActionClass.QUERY_EXPANSION,
            }
        elif stage is DegradationStage.REDUCE_LOW_VALUE:
            denied = action_class is BudgetActionClass.LOW_VALUE
        if denied:
            code = f"BUDGET_DEGRADATION_{stage.value}"
            self._record(
                event_type="degradation_action_denied",
                decision=BudgetDecision.DENIED,
                error_code=code,
                action_signature=action_class.value,
            )
            self._raise(
                code,
                f"The {stage.value} policy denies this action class.",
                "The requested branch was not started.",
                "Continue only with an action permitted at the current degradation stage.",
            )

    @asynccontextmanager
    async def professional_slot(self) -> AsyncIterator[None]:
        self._check_time()
        dimension = BudgetDimension.PROFESSIONAL_CONCURRENCY
        self._ensure_capacity(dimension, 1, "professional_concurrency_denied")
        before = self._counts[dimension]
        self._increment(dimension, 1)
        self._peak_concurrency = max(self._peak_concurrency, self._counts[dimension])
        self._record(
            event_type="professional_slot_acquired",
            dimension=dimension,
            amount=1,
            before=before,
            after=before + 1,
            decision=BudgetDecision.ALLOWED,
        )
        try:
            yield
        finally:
            before_release = self._counts[dimension]
            self._increment(dimension, -1)
            self._record(
                event_type="professional_slot_released",
                dimension=dimension,
                before=before_release,
                after=before_release - 1,
                decision=BudgetDecision.RECORDED,
            )

    def _consume(
        self,
        dimension: BudgetDimension,
        amount: int,
        event_type: str,
        *,
        logical: bool,
    ) -> None:
        self._check_time()
        self._ensure_capacity(dimension, amount, f"{event_type}_denied")
        before = self._counts[dimension]
        self._increment(dimension, amount)
        if logical:
            self._logical_actions += 1
        self._record(
            event_type=event_type,
            dimension=dimension,
            amount=amount,
            before=before,
            after=before + amount,
            decision=BudgetDecision.ALLOWED,
        )

    def _ensure_token_capacity(self, amount: int, event_type: str) -> None:
        current = self._counts[BudgetDimension.TOTAL_TOKENS] + self._reserved_tokens
        self._ensure_capacity(
            BudgetDimension.TOTAL_TOKENS,
            amount,
            event_type,
            current_override=current,
        )

    def _ensure_capacity(
        self,
        dimension: BudgetDimension,
        amount: int,
        event_type: str,
        *,
        current_override: int | None = None,
    ) -> None:
        limit = self._limit(dimension)
        current = self._counts[dimension] if current_override is None else current_override
        projected = current + amount
        code: str | None = None
        if projected > limit.hard:
            code = "BUDGET_HARD_LIMIT_EXCEEDED"
        elif projected > limit.active:
            code = "BUDGET_ACTIVE_LIMIT_EXCEEDED"
        if code is not None:
            self._record(
                event_type=event_type,
                dimension=dimension,
                amount=amount,
                before=current,
                after=current,
                decision=BudgetDecision.DENIED,
                error_code=code,
            )
            self._raise(
                code,
                f"The {dimension.value} limit would be exceeded.",
                "The guarded action was not started and existing completed work is preserved.",
                "Finalize a partial result or obtain a recorded active-limit elevation.",
            )

    def _check_time(self) -> None:
        elapsed = self._elapsed_ms()
        limit = self.policy.wall_time_ms
        code: str | None = None
        if elapsed >= limit.hard:
            code = "BUDGET_HARD_TIME_EXCEEDED"
        elif elapsed >= limit.active:
            code = "BUDGET_ACTIVE_TIME_EXCEEDED"
        if code is not None:
            self._record(
                event_type="wall_time_denied",
                dimension=BudgetDimension.WALL_TIME_MS,
                before=elapsed,
                after=elapsed,
                decision=BudgetDecision.DENIED,
                error_code=code,
            )
            self._raise(
                code,
                "The task wall-time limit has been reached.",
                "No new guarded call was started.",
                "Return the preserved partial result or resume under an approved policy.",
            )

    def _degradation_stage(self, elapsed_ms: int) -> DegradationStage:
        ratios: list[float] = []
        for dimension in (
            BudgetDimension.GRAPH_STEPS,
            BudgetDimension.LLM_CALLS,
            BudgetDimension.TOOL_CALLS,
            BudgetDimension.TOTAL_TOKENS,
            BudgetDimension.WALL_TIME_MS,
            BudgetDimension.REVIEW_ROUNDS,
            BudgetDimension.CORRECTION_ROUNDS,
        ):
            limit = self._limit(dimension).active
            if limit == 0:
                continue
            if dimension is BudgetDimension.WALL_TIME_MS:
                value = elapsed_ms
            elif dimension is BudgetDimension.TOTAL_TOKENS:
                value = self._counts[dimension] + self._reserved_tokens
            elif dimension is BudgetDimension.GRAPH_STEPS:
                value = self._counts[dimension] + self._reserved_graph_steps
            else:
                value = self._counts[dimension]
            ratios.append(value / limit)
        ratio = max(ratios, default=0.0)
        if ratio >= 1.0:
            return DegradationStage.STOPPED
        if ratio >= 0.95:
            return DegradationStage.FINALIZE_ONLY
        if ratio >= 0.85:
            return DegradationStage.STOP_EXPANSION
        if ratio >= 0.70:
            return DegradationStage.REDUCE_LOW_VALUE
        return DegradationStage.NORMAL

    def _limit(self, dimension: BudgetDimension) -> Limit:
        return cast(Limit, getattr(self.policy, dimension.value))

    def _increment(self, dimension: BudgetDimension, amount: int) -> None:
        self._counts[dimension] += amount

    def _elapsed_ms(self) -> int:
        return max(0, int((self._clock() - self._started) * 1000))

    def _record(
        self,
        *,
        event_type: str,
        decision: BudgetDecision,
        dimension: BudgetDimension | None = None,
        amount: int = 0,
        before: int = 0,
        after: int = 0,
        error_code: str | None = None,
        action_signature: str | None = None,
        observation_sha256: str | None = None,
    ) -> None:
        limit = self._limit(dimension) if dimension is not None else None
        self._events.append(
            BudgetEvent(
                sequence=len(self._events) + 1,
                event_type=event_type,
                dimension=dimension,
                amount=amount,
                before=before,
                after=after,
                active_limit=limit.active if limit is not None else None,
                hard_limit=limit.hard if limit is not None else None,
                decision=decision,
                error_code=error_code,
                elapsed_ms=self._elapsed_ms(),
                action_signature=action_signature,
                observation_sha256=observation_sha256,
            )
        )

    def _raise(self, code: str, cause: str, impact: str, next_action: str) -> None:
        raise BudgetExceeded(
            code=code,
            cause=cause,
            impact=impact,
            next_action=next_action,
            telemetry=self.telemetry(),
        )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
