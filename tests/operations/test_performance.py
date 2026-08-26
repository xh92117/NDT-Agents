"""S6-06 performance and token-economics contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ndt_agents.operations.performance import (
    BenchmarkEnvironment,
    BenchmarkStatus,
    HardwareDescriptor,
    MetricSeries,
    PerformanceMetric,
    TokenBreakdown,
    TokenWorkloadPair,
    assess_benchmark,
    build_benchmark_profile,
    nearest_rank,
)

BUILD = "a" * 64
CONFIG = "b" * 64
WORKLOAD = "c" * 64
HARDWARE = HardwareDescriptor(
    platform="test", processor="test", logical_cpus=8, python_version="3.12"
)


def breakdown(input_tokens: int, total_extra: int) -> TokenBreakdown:
    return TokenBreakdown(
        input_tokens=input_tokens,
        output_tokens=total_extra,
        hidden_orchestration_tokens=0,
        review_tokens=0,
        retry_tokens=0,
        cache_hit_tokens=0,
        cache_miss_tokens=0,
    )


def pair(**updates: object) -> TokenWorkloadPair:
    values: dict[str, object] = {
        "workload_id": "repeat-g0",
        "task_class": "G0",
        "route": "GENERAL",
        "build_sha256": BUILD,
        "workload_sha256": WORKLOAD,
        "cold": breakdown(1000, 100),
        "warm": breakdown(100, 100),
        "cache_eligible": True,
        "cache_hits": 4,
        "cache_lookups": 5,
        "provider_measured": False,
    }
    values.update(updates)
    return TokenWorkloadPair.model_validate(values)


def local_series(metric: PerformanceMetric, **updates: object) -> MetricSeries:
    profile = build_benchmark_profile()
    count = 100 if metric is PerformanceMetric.LOCAL_CONCURRENT_TASK else 20
    values: dict[str, object] = {
        "metric": metric,
        "build_sha256": BUILD,
        "profile_sha256": profile.profile_sha256,
        "configuration_sha256": CONFIG,
        "workload_sha256": WORKLOAD,
        "environment": BenchmarkEnvironment.LOCAL,
        "hardware": HARDWARE,
        "latency_ms": tuple(1.0 for _ in range(count)),
        "elapsed_seconds": 1.0,
        "operations": count,
        "concurrency": 100 if metric is PerformanceMetric.LOCAL_CONCURRENT_TASK else 1,
        "failures": 0,
        "correctness_failures": 0,
        "isolation_failures": 0,
    }
    values.update(updates)
    return MetricSeries.model_validate(values)


def local_set() -> tuple[MetricSeries, ...]:
    return tuple(
        local_series(metric)
        for metric in (
            PerformanceMetric.LOCAL_CACHE_KEY,
            PerformanceMetric.LOCAL_TASK_CREATE,
            PerformanceMetric.LOCAL_EVENT_SERIALIZE,
            PerformanceMetric.LOCAL_CONCURRENT_TASK,
        )
    )


def test_nearest_rank_is_deterministic() -> None:
    values = tuple(float(value) for value in range(1, 101))
    assert nearest_rank(values, 0.50) == 50
    assert nearest_rank(values, 0.95) == 95
    assert nearest_rank(values, 0.99) == 99


def test_local_green_is_blocked_not_promoted() -> None:
    assessment = assess_benchmark(build_benchmark_profile(), BUILD, local_set(), (pair(),))
    assert assessment.status is BenchmarkStatus.BLOCKED
    assert assessment.local_metrics_passed == 4
    assert assessment.median_token_reduction > 0.25
    assert PerformanceMetric.DATABASE_LOAD in assessment.missing_reference_metrics


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"failures": 1}, "PERF_CORRECTNESS_FAILED"),
        ({"correctness_failures": 1}, "PERF_CORRECTNESS_FAILED"),
        ({"isolation_failures": 1}, "PERF_CORRECTNESS_FAILED"),
        ({"profile_sha256": "d" * 64}, "PERF_EVIDENCE_BINDING_INVALID"),
    ],
)
def test_metric_failures_are_typed(updates: dict[str, object], reason: str) -> None:
    changed = (local_series(PerformanceMetric.LOCAL_CACHE_KEY, **updates), *local_set()[1:])
    assessment = assess_benchmark(build_benchmark_profile(), BUILD, changed, (pair(),))
    assert assessment.status is BenchmarkStatus.FAILED
    assert assessment.reason_code == reason


def test_missing_and_duplicate_local_metrics_fail() -> None:
    profile = build_benchmark_profile()
    missing = assess_benchmark(profile, BUILD, local_set()[:-1], (pair(),))
    duplicate = assess_benchmark(profile, BUILD, (*local_set(), local_set()[0]), (pair(),))
    assert missing.reason_code == "PERF_LOCAL_METRIC_MISSING"
    assert duplicate.reason_code == "PERF_RESULT_SET_INVALID"


def test_low_token_reduction_hit_rate_and_input_saving_fail() -> None:
    profile = build_benchmark_profile()
    low_total = pair(warm=breakdown(800, 100))
    low_hits = pair(cache_hits=1, cache_lookups=5)
    low_input = pair(warm=breakdown(300, 0))
    assert (
        assess_benchmark(profile, BUILD, local_set(), (low_total,)).reason_code
        == "TOKEN_REDUCTION_LOW"
    )
    assert (
        assess_benchmark(profile, BUILD, local_set(), (low_hits,)).reason_code
        == "CACHE_HIT_RATE_LOW"
    )
    assert (
        assess_benchmark(profile, BUILD, local_set(), (low_input,)).reason_code
        == "CACHE_INPUT_REDUCTION_LOW"
    )


def test_series_rejects_nonpositive_and_short_samples() -> None:
    with pytest.raises(ValidationError):
        local_series(PerformanceMetric.LOCAL_CACHE_KEY, latency_ms=(1.0,) * 19)
    with pytest.raises(ValidationError):
        local_series(PerformanceMetric.LOCAL_CACHE_KEY, latency_ms=(0.0,) * 20)
