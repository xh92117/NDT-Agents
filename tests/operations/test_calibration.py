"""S6-07 measurement-bound budget calibration tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ndt_agents.operations.calibration import (
    CALIBRATED_DIMENSIONS,
    TASK_CLASSES,
    CalibrationObservation,
    CalibrationStatus,
    calibrate_budgets,
)
from ndt_agents.operations.performance import BenchmarkEnvironment
from ndt_agents.orchestration.budget import BudgetDimension, default_budget_policy

BUILD = "a" * 64
BENCHMARK = "b" * 64
WORKLOAD = "c" * 64


def observations(
    *,
    environment: BenchmarkEnvironment = BenchmarkEnvironment.REFERENCE,
    approved: bool = True,
    provider_measured: bool = True,
) -> tuple[CalibrationObservation, ...]:
    values: list[CalibrationObservation] = []
    for task_class in TASK_CLASSES:
        source = default_budget_policy(task_class)
        for dimension in CALIBRATED_DIMENSIONS:
            limit = getattr(source, dimension.value)
            p95 = 0.0 if limit.default == 0 else (limit.default - 0.1) / 1.15
            p99 = limit.hard / 1.25
            values.append(
                CalibrationObservation(
                    task_class=task_class,
                    dimension=dimension,
                    build_sha256=BUILD,
                    benchmark_profile_sha256=BENCHMARK,
                    workload_sha256=WORKLOAD,
                    environment=environment,
                    reference_environment_approved=approved,
                    provider_measured=provider_measured,
                    quality_passed=True,
                    sample_count=100,
                    successful_task_p95=p95,
                    successful_task_p99=max(p95, p99),
                    correctness_failures=0,
                    isolation_failures=0,
                )
            )
    return tuple(values)


def replace(
    items: tuple[CalibrationObservation, ...],
    index: int,
    **updates: object,
) -> tuple[CalibrationObservation, ...]:
    changed = items[index].model_copy(update=updates)
    return (*items[:index], changed, *items[index + 1 :])


def test_complete_reference_set_builds_immutable_calibrated_profile() -> None:
    source_before = default_budget_policy("G0")
    result = calibrate_budgets(
        build_sha256=BUILD,
        benchmark_profile_sha256=BENCHMARK,
        observations=observations(),
    )
    assert result.status is CalibrationStatus.PASS
    assert result.profile is not None
    assert result.profile.production_qualified is True
    assert len(result.profile.observation_sha256s) == 40
    assert result.profile.policies[0].total_tokens.default == 4000
    assert result.profile.policies[0].total_tokens.hard == 8000
    assert default_budget_policy("G0") == source_before
    for calibrated, task_class in zip(result.profile.policies, TASK_CLASSES, strict=True):
        source = default_budget_policy(task_class)
        for dimension in CALIBRATED_DIMENSIONS:
            assert (
                getattr(calibrated, dimension.value).hard <= getattr(source, dimension.value).hard
            )


def test_local_or_estimated_set_is_provisional_and_blocked() -> None:
    result = calibrate_budgets(
        build_sha256=BUILD,
        benchmark_profile_sha256=BENCHMARK,
        observations=observations(
            environment=BenchmarkEnvironment.LOCAL,
            approved=False,
            provider_measured=False,
        ),
    )
    assert result.status is CalibrationStatus.BLOCKED
    assert result.reason_code == "CALIBRATION_REFERENCE_EVIDENCE_MISSING"
    assert result.profile is not None
    assert result.profile.production_qualified is False


def test_missing_and_duplicate_observations_do_not_create_profile() -> None:
    items = observations()
    missing = calibrate_budgets(
        build_sha256=BUILD,
        benchmark_profile_sha256=BENCHMARK,
        observations=items[:-1],
    )
    duplicate = calibrate_budgets(
        build_sha256=BUILD,
        benchmark_profile_sha256=BENCHMARK,
        observations=(*items, items[0]),
    )
    assert missing.reason_code == "CALIBRATION_OBSERVATIONS_MISSING"
    assert missing.profile is None
    assert duplicate.reason_code == "CALIBRATION_RESULT_SET_INVALID"


def test_stale_binding_and_quality_failure_fail_closed() -> None:
    items = observations()
    stale = calibrate_budgets(
        build_sha256=BUILD,
        benchmark_profile_sha256=BENCHMARK,
        observations=replace(items, 0, build_sha256="d" * 64),
    )
    failed = calibrate_budgets(
        build_sha256=BUILD,
        benchmark_profile_sha256=BENCHMARK,
        observations=replace(items, 0, correctness_failures=1),
    )
    assert stale.reason_code == "CALIBRATION_EVIDENCE_BINDING_INVALID"
    assert failed.reason_code == "CALIBRATION_QUALITY_FAILED"


def test_formula_rejects_default_above_global_hard_limit() -> None:
    items = observations()
    token_index = CALIBRATED_DIMENSIONS.index(BudgetDimension.TOTAL_TOKENS)
    invalid = replace(
        items,
        token_index,
        successful_task_p95=8000,
        successful_task_p99=8000,
    )
    result = calibrate_budgets(
        build_sha256=BUILD,
        benchmark_profile_sha256=BENCHMARK,
        observations=invalid,
    )
    assert result.reason_code == "CALIBRATION_LIMIT_ORDER_INVALID"
    assert result.profile is None


def test_observation_rejects_reversed_percentiles_and_small_samples() -> None:
    value = observations()[0]
    with pytest.raises(ValidationError):
        CalibrationObservation.model_validate(
            {
                **value.model_dump(),
                "successful_task_p95": 2,
                "successful_task_p99": 1,
            }
        )
    with pytest.raises(ValidationError):
        CalibrationObservation.model_validate({**value.model_dump(), "sample_count": 99})
