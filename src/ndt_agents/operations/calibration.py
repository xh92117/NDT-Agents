"""S6-07 measurement-bound runtime budget calibration."""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import BudgetPolicy, Limit, StrictModel
from ndt_agents.operations.performance import BenchmarkEnvironment
from ndt_agents.orchestration.budget import BudgetDimension, default_budget_policy

type TaskClass = Literal["G0", "P1", "P2", "P3", "K1"]

CALIBRATED_DIMENSIONS = (
    BudgetDimension.GRAPH_STEPS,
    BudgetDimension.LLM_CALLS,
    BudgetDimension.TOOL_CALLS,
    BudgetDimension.TOTAL_TOKENS,
    BudgetDimension.WALL_TIME_MS,
    BudgetDimension.PROFESSIONAL_CONCURRENCY,
    BudgetDimension.REVIEW_ROUNDS,
    BudgetDimension.CORRECTION_ROUNDS,
)
TASK_CLASSES: tuple[TaskClass, ...] = ("G0", "P1", "P2", "P3", "K1")


class CalibrationObservation(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_class: TaskClass
    dimension: BudgetDimension
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment: BenchmarkEnvironment
    reference_environment_approved: bool
    provider_measured: bool
    quality_passed: bool
    sample_count: int = Field(ge=100)
    successful_task_p95: float = Field(ge=0, allow_inf_nan=False)
    successful_task_p99: float = Field(ge=0, allow_inf_nan=False)
    correctness_failures: int = Field(ge=0)
    isolation_failures: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_percentiles(self) -> Self:
        if self.successful_task_p99 < self.successful_task_p95:
            raise ValueError("P99 cannot be below P95")
        return self


class CalibrationStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class BudgetCalibrationProfile(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    profile_version: str = Field(min_length=1, max_length=128)
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policies: tuple[BudgetPolicy, ...] = Field(min_length=5, max_length=5)
    observation_sha256s: tuple[str, ...] = Field(min_length=40, max_length=40)
    production_qualified: bool
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if tuple(policy.task_class for policy in self.policies) != TASK_CLASSES:
            raise ValueError("calibrated policies must use stable task-class order")
        if len(set(self.observation_sha256s)) != len(self.observation_sha256s):
            raise ValueError("calibration observations must be unique")
        if self.profile_sha256 != calibration_profile_sha256(self):
            raise ValueError("calibration profile hash is invalid")
        return self


class CalibrationAssessment(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: CalibrationStatus
    reason_code: str
    next_action: str
    expected_observations: int = 40
    accepted_observations: int = Field(ge=0, le=40)
    missing_pairs: tuple[str, ...]
    profile: BudgetCalibrationProfile | None


def observation_sha256(observation: CalibrationObservation) -> str:
    encoded = json.dumps(observation.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def calibration_profile_sha256(profile: BudgetCalibrationProfile) -> str:
    payload = profile.model_dump(mode="json", exclude={"profile_sha256"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def calibrate_budgets(
    *,
    build_sha256: str,
    benchmark_profile_sha256: str,
    observations: tuple[CalibrationObservation, ...],
) -> CalibrationAssessment:
    expected = {
        (task_class, dimension)
        for task_class in TASK_CLASSES
        for dimension in CALIBRATED_DIMENSIONS
    }
    identities = [(item.task_class, item.dimension) for item in observations]
    if len(set(identities)) != len(identities) or any(
        identity not in expected for identity in identities
    ):
        return _assessment(
            CalibrationStatus.FAILED,
            "CALIBRATION_RESULT_SET_INVALID",
            "Provide one known observation for every task-class and dimension pair.",
            0,
            (),
            None,
        )
    by_identity = dict(zip(identities, observations, strict=True))
    missing = tuple(
        f"{task_class}:{dimension.value}"
        for task_class in TASK_CLASSES
        for dimension in CALIBRATED_DIMENSIONS
        if (task_class, dimension) not in by_identity
    )
    if missing:
        return _assessment(
            CalibrationStatus.BLOCKED,
            "CALIBRATION_OBSERVATIONS_MISSING",
            "Measure every missing task-class and dimension pair on the approved "
            "reference environment.",
            len(observations),
            missing,
            None,
        )

    external_missing = False
    policies: list[BudgetPolicy] = []
    hashes: list[str] = []
    for task_class in TASK_CLASSES:
        source = default_budget_policy(task_class)
        updates: dict[str, Limit] = {}
        for dimension in CALIBRATED_DIMENSIONS:
            observation = by_identity[(task_class, dimension)]
            if (
                observation.build_sha256 != build_sha256
                or observation.benchmark_profile_sha256 != benchmark_profile_sha256
            ):
                return _assessment(
                    CalibrationStatus.FAILED,
                    "CALIBRATION_EVIDENCE_BINDING_INVALID",
                    "Use measurements for the exact accepted build and benchmark profile.",
                    len(hashes),
                    (),
                    None,
                )
            if (
                not observation.quality_passed
                or observation.correctness_failures
                or observation.isolation_failures
            ):
                return _assessment(
                    CalibrationStatus.FAILED,
                    "CALIBRATION_QUALITY_FAILED",
                    f"Correct and remeasure {task_class}:{dimension.value}.",
                    len(hashes),
                    (),
                    None,
                )
            if (
                observation.environment is not BenchmarkEnvironment.REFERENCE
                or not observation.reference_environment_approved
            ):
                external_missing = True
            if (
                dimension in {BudgetDimension.LLM_CALLS, BudgetDimension.TOTAL_TOKENS}
                and not observation.provider_measured
            ):
                external_missing = True
            global_limit = getattr(source, dimension.value).hard
            default_limit = math.ceil(observation.successful_task_p95 * 1.15)
            hard_limit = min(math.ceil(observation.successful_task_p99 * 1.25), global_limit)
            if default_limit > hard_limit:
                return _assessment(
                    CalibrationStatus.FAILED,
                    "CALIBRATION_LIMIT_ORDER_INVALID",
                    "P95/P99 formula exceeds the global ceiling for "
                    f"{task_class}:{dimension.value}.",
                    len(hashes),
                    (),
                    None,
                )
            updates[dimension.value] = Limit(
                default=default_limit, active=default_limit, hard=hard_limit
            )
            hashes.append(observation_sha256(observation))
        policies.append(
            source.model_copy(
                update={
                    "policy_id": f"budget-{task_class.lower()}-s6-calibrated-v1",
                    **updates,
                }
            )
        )

    provisional = BudgetCalibrationProfile.model_construct(
        profile_version="s6-budget-calibration-1",
        build_sha256=build_sha256,
        benchmark_profile_sha256=benchmark_profile_sha256,
        policies=tuple(policies),
        observation_sha256s=tuple(hashes),
        production_qualified=not external_missing,
        profile_sha256="0" * 64,
    )
    profile = BudgetCalibrationProfile(
        profile_version="s6-budget-calibration-1",
        build_sha256=build_sha256,
        benchmark_profile_sha256=benchmark_profile_sha256,
        policies=tuple(policies),
        observation_sha256s=tuple(hashes),
        production_qualified=not external_missing,
        profile_sha256=calibration_profile_sha256(provisional),
    )
    if external_missing:
        return _assessment(
            CalibrationStatus.BLOCKED,
            "CALIBRATION_REFERENCE_EVIDENCE_MISSING",
            "Replace local, estimated, or unapproved observations with approved-reference "
            "measurements.",
            40,
            (),
            profile,
        )
    return _assessment(
        CalibrationStatus.PASS,
        "CALIBRATION_ACCEPTED",
        "Preserve and approve the exact production budget profile.",
        40,
        (),
        profile,
    )


def _assessment(
    status: CalibrationStatus,
    reason: str,
    action: str,
    accepted: int,
    missing: tuple[str, ...],
    profile: BudgetCalibrationProfile | None,
) -> CalibrationAssessment:
    return CalibrationAssessment(
        status=status,
        reason_code=reason,
        next_action=action,
        accepted_observations=accepted,
        missing_pairs=missing,
        profile=profile,
    )
