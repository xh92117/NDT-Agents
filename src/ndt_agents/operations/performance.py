"""Versioned S6-06 performance and token-economics evidence contracts."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel


class BenchmarkEnvironment(StrEnum):
    LOCAL = "LOCAL"
    CI = "CI"
    REFERENCE = "REFERENCE"


class MetricRequirement(StrEnum):
    LOCAL_CONTRACT = "LOCAL_CONTRACT"
    REFERENCE_LIVE = "REFERENCE_LIVE"


class PerformanceMetric(StrEnum):
    LOCAL_CACHE_KEY = "LOCAL_CACHE_KEY"
    LOCAL_TASK_CREATE = "LOCAL_TASK_CREATE"
    LOCAL_EVENT_SERIALIZE = "LOCAL_EVENT_SERIALIZE"
    LOCAL_CONCURRENT_TASK = "LOCAL_CONCURRENT_TASK"
    CACHED_SIMPLE_ANSWER = "CACHED_SIMPLE_ANSWER"
    UNCACHED_FIRST_TOKEN = "UNCACHED_FIRST_TOKEN"
    ORDINARY_TOOL_TASK = "ORDINARY_TOOL_TASK"
    ASYNC_TASK_ENQUEUE = "ASYNC_TASK_ENQUEUE"
    REFERENCE_CONCURRENT_TASK = "REFERENCE_CONCURRENT_TASK"
    DATABASE_LOAD = "DATABASE_LOAD"
    VECTOR_SEARCH = "VECTOR_SEARCH"
    PARSER_THROUGHPUT = "PARSER_THROUGHPUT"
    ARTIFACT_TRANSFER = "ARTIFACT_TRANSFER"
    CLIENT_STREAMING = "CLIENT_STREAMING"


class MetricDefinition(StrictModel):
    metric: PerformanceMetric
    requirement: MetricRequirement
    minimum_samples: int = Field(ge=20)
    maximum_p95_ms: float | None = Field(default=None, gt=0)
    minimum_concurrency: int | None = Field(default=None, ge=1)


class BenchmarkProfile(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    profile_version: str = Field(min_length=1, max_length=128)
    definitions: tuple[MetricDefinition, ...] = Field(min_length=1)
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if len({item.metric for item in self.definitions}) != len(self.definitions):
            raise ValueError("performance metric definitions must be unique")
        if self.profile_sha256 != benchmark_profile_sha256(self):
            raise ValueError("benchmark profile hash is invalid")
        return self


class HardwareDescriptor(StrictModel):
    platform: str = Field(min_length=1, max_length=256)
    processor: str = Field(min_length=1, max_length=256)
    logical_cpus: int = Field(ge=1)
    python_version: str = Field(min_length=1, max_length=64)


class MetricSeries(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    metric: PerformanceMetric
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment: BenchmarkEnvironment
    hardware: HardwareDescriptor
    latency_ms: tuple[float, ...] = Field(min_length=20)
    elapsed_seconds: float = Field(gt=0)
    operations: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    failures: int = Field(ge=0)
    correctness_failures: int = Field(ge=0)
    isolation_failures: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_samples(self) -> Self:
        if any(not math.isfinite(value) or value <= 0 for value in self.latency_ms):
            raise ValueError("latency samples must be finite and positive")
        if self.operations < len(self.latency_ms):
            raise ValueError("operations cannot be smaller than the sample count")
        return self

    @property
    def p50_ms(self) -> float:
        return nearest_rank(self.latency_ms, 0.50)

    @property
    def p95_ms(self) -> float:
        return nearest_rank(self.latency_ms, 0.95)

    @property
    def p99_ms(self) -> float:
        return nearest_rank(self.latency_ms, 0.99)

    @property
    def throughput_per_second(self) -> float:
        return self.operations / self.elapsed_seconds


class TokenBreakdown(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    hidden_orchestration_tokens: int = Field(ge=0)
    review_tokens: int = Field(ge=0)
    retry_tokens: int = Field(ge=0)
    cache_hit_tokens: int = Field(ge=0)
    cache_miss_tokens: int = Field(ge=0)

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.hidden_orchestration_tokens
            + self.review_tokens
            + self.retry_tokens
            + self.cache_hit_tokens
            + self.cache_miss_tokens
        )


class TokenWorkloadPair(StrictModel):
    workload_id: str = Field(min_length=1, max_length=128)
    task_class: Literal["G0", "P1", "P2", "P3", "K1"]
    route: Literal[
        "RULES_ONLY",
        "GENERAL",
        "SINGLE_PROFESSIONAL",
        "MULTI_PROFESSIONAL",
        "COMPRESSED",
        "RESTORED",
    ]
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cold: TokenBreakdown
    warm: TokenBreakdown
    cache_eligible: bool
    cache_hits: int = Field(ge=0)
    cache_lookups: int = Field(ge=1)
    provider_measured: bool

    @model_validator(mode="after")
    def validate_cache_counts(self) -> Self:
        if self.cache_hits > self.cache_lookups:
            raise ValueError("cache hits cannot exceed cache lookups")
        if self.warm.total_tokens > self.cold.total_tokens:
            raise ValueError("warm total tokens cannot exceed cold total tokens")
        return self

    @property
    def reduction_fraction(self) -> float:
        if self.cold.total_tokens == 0:
            return 0.0
        return 1.0 - (self.warm.total_tokens / self.cold.total_tokens)

    @property
    def input_reduction_fraction(self) -> float:
        if self.cold.input_tokens == 0:
            return 0.0
        return 1.0 - (self.warm.input_tokens / self.cold.input_tokens)


class BenchmarkStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class BenchmarkAssessment(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: BenchmarkStatus
    build_sha256: str
    profile_sha256: str
    local_metrics_passed: int = Field(ge=0)
    required_metrics: int = Field(ge=1)
    missing_reference_metrics: tuple[PerformanceMetric, ...]
    median_token_reduction: float = Field(ge=0, le=1)
    cache_hit_rate: float = Field(ge=0, le=1)
    reason_code: str
    next_action: str


def nearest_rank(values: tuple[float, ...], quantile: float) -> float:
    if not values or not 0 < quantile <= 1:
        raise ValueError("nearest-rank requires samples and a quantile in (0, 1]")
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


def benchmark_profile_sha256(profile: BenchmarkProfile) -> str:
    payload = profile.model_dump(mode="json", exclude={"profile_sha256"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def build_benchmark_profile() -> BenchmarkProfile:
    definitions = (
        MetricDefinition(
            metric=PerformanceMetric.LOCAL_CACHE_KEY,
            requirement=MetricRequirement.LOCAL_CONTRACT,
            minimum_samples=20,
            maximum_p95_ms=100,
        ),
        MetricDefinition(
            metric=PerformanceMetric.LOCAL_TASK_CREATE,
            requirement=MetricRequirement.LOCAL_CONTRACT,
            minimum_samples=20,
            maximum_p95_ms=100,
        ),
        MetricDefinition(
            metric=PerformanceMetric.LOCAL_EVENT_SERIALIZE,
            requirement=MetricRequirement.LOCAL_CONTRACT,
            minimum_samples=20,
            maximum_p95_ms=100,
        ),
        MetricDefinition(
            metric=PerformanceMetric.LOCAL_CONCURRENT_TASK,
            requirement=MetricRequirement.LOCAL_CONTRACT,
            minimum_samples=100,
            maximum_p95_ms=1000,
            minimum_concurrency=100,
        ),
        MetricDefinition(
            metric=PerformanceMetric.CACHED_SIMPLE_ANSWER,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
            maximum_p95_ms=3000,
        ),
        MetricDefinition(
            metric=PerformanceMetric.UNCACHED_FIRST_TOKEN,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
            maximum_p95_ms=5000,
        ),
        MetricDefinition(
            metric=PerformanceMetric.ORDINARY_TOOL_TASK,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
            maximum_p95_ms=30000,
        ),
        MetricDefinition(
            metric=PerformanceMetric.ASYNC_TASK_ENQUEUE,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
            maximum_p95_ms=1000,
        ),
        MetricDefinition(
            metric=PerformanceMetric.REFERENCE_CONCURRENT_TASK,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
            minimum_concurrency=100,
        ),
        MetricDefinition(
            metric=PerformanceMetric.DATABASE_LOAD,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
        ),
        MetricDefinition(
            metric=PerformanceMetric.VECTOR_SEARCH,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
        ),
        MetricDefinition(
            metric=PerformanceMetric.PARSER_THROUGHPUT,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
        ),
        MetricDefinition(
            metric=PerformanceMetric.ARTIFACT_TRANSFER,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
        ),
        MetricDefinition(
            metric=PerformanceMetric.CLIENT_STREAMING,
            requirement=MetricRequirement.REFERENCE_LIVE,
            minimum_samples=100,
        ),
    )
    provisional = BenchmarkProfile.model_construct(
        profile_version="s6-performance-1", definitions=definitions, profile_sha256="0" * 64
    )
    return BenchmarkProfile(
        profile_version="s6-performance-1",
        definitions=definitions,
        profile_sha256=benchmark_profile_sha256(provisional),
    )


def assess_benchmark(
    profile: BenchmarkProfile,
    build_sha256: str,
    series: tuple[MetricSeries, ...],
    token_pairs: tuple[TokenWorkloadPair, ...],
) -> BenchmarkAssessment:
    definitions = {item.metric: item for item in profile.definitions}
    if len({item.metric for item in series}) != len(series) or any(
        item.metric not in definitions for item in series
    ):
        return _assessment(
            profile,
            build_sha256,
            BenchmarkStatus.FAILED,
            0,
            (),
            token_pairs,
            "PERF_RESULT_SET_INVALID",
            "Provide one series for each known metric identity.",
        )
    local_passed = 0
    present_reference: set[PerformanceMetric] = set()
    for item in series:
        definition = definitions[item.metric]
        if item.build_sha256 != build_sha256 or item.profile_sha256 != profile.profile_sha256:
            return _assessment(
                profile,
                build_sha256,
                BenchmarkStatus.FAILED,
                local_passed,
                (),
                token_pairs,
                "PERF_EVIDENCE_BINDING_INVALID",
                "Rerun the exact build and benchmark profile.",
            )
        if len(item.latency_ms) < definition.minimum_samples:
            return _assessment(
                profile,
                build_sha256,
                BenchmarkStatus.FAILED,
                local_passed,
                (),
                token_pairs,
                "PERF_SAMPLE_COUNT_LOW",
                f"Collect at least {definition.minimum_samples} samples for {item.metric.value}.",
            )
        if item.failures or item.correctness_failures or item.isolation_failures:
            return _assessment(
                profile,
                build_sha256,
                BenchmarkStatus.FAILED,
                local_passed,
                (),
                token_pairs,
                "PERF_CORRECTNESS_FAILED",
                f"Correct failures in {item.metric.value} and rerun.",
            )
        if definition.maximum_p95_ms is not None and item.p95_ms > definition.maximum_p95_ms:
            return _assessment(
                profile,
                build_sha256,
                BenchmarkStatus.FAILED,
                local_passed,
                (),
                token_pairs,
                "PERF_TARGET_BREACHED",
                f"Reduce P95 latency for {item.metric.value}.",
            )
        if (
            definition.minimum_concurrency is not None
            and item.concurrency < definition.minimum_concurrency
        ):
            return _assessment(
                profile,
                build_sha256,
                BenchmarkStatus.FAILED,
                local_passed,
                (),
                token_pairs,
                "PERF_CONCURRENCY_LOW",
                f"Run {item.metric.value} at the required concurrency.",
            )
        if definition.requirement is MetricRequirement.LOCAL_CONTRACT:
            local_passed += 1
        elif item.environment is BenchmarkEnvironment.REFERENCE:
            present_reference.add(item.metric)
    missing_local = tuple(
        item.metric
        for item in profile.definitions
        if item.requirement is MetricRequirement.LOCAL_CONTRACT
        and item.metric not in {sample.metric for sample in series}
    )
    if missing_local:
        return _assessment(
            profile,
            build_sha256,
            BenchmarkStatus.FAILED,
            local_passed,
            (),
            token_pairs,
            "PERF_LOCAL_METRIC_MISSING",
            "Run every local contract metric.",
        )
    token_error = _token_error(build_sha256, token_pairs)
    if token_error is not None:
        return _assessment(
            profile,
            build_sha256,
            BenchmarkStatus.FAILED,
            local_passed,
            (),
            token_pairs,
            token_error[0],
            token_error[1],
        )
    missing_reference = tuple(
        item.metric
        for item in profile.definitions
        if item.requirement is MetricRequirement.REFERENCE_LIVE
        and item.metric not in present_reference
    )
    provider_missing = any(not item.provider_measured for item in token_pairs)
    if missing_reference or provider_missing:
        return _assessment(
            profile,
            build_sha256,
            BenchmarkStatus.BLOCKED,
            local_passed,
            missing_reference,
            token_pairs,
            "PERF_REFERENCE_EVIDENCE_MISSING",
            "Run all live metrics and token workloads on the approved reference environment.",
        )
    return _assessment(
        profile,
        build_sha256,
        BenchmarkStatus.PASS,
        local_passed,
        (),
        token_pairs,
        "PERF_ACCEPTED",
        "Preserve the exact evidence for budget calibration.",
    )


def _token_error(build_sha256: str, pairs: tuple[TokenWorkloadPair, ...]) -> tuple[str, str] | None:
    if not pairs or len({item.workload_id for item in pairs}) != len(pairs):
        return "TOKEN_WORKLOAD_SET_INVALID", "Provide unique cold/warm workload pairs."
    if any(item.build_sha256 != build_sha256 for item in pairs):
        return "TOKEN_EVIDENCE_BINDING_INVALID", "Use token evidence for the exact build."
    if statistics.median(item.reduction_fraction for item in pairs) < 0.25:
        return (
            "TOKEN_REDUCTION_LOW",
            "Achieve at least 25 percent median repeated-workload reduction.",
        )
    lookups = sum(item.cache_lookups for item in pairs)
    if sum(item.cache_hits for item in pairs) / lookups < 0.35:
        return "CACHE_HIT_RATE_LOW", "Achieve at least 35 percent stable-query cache hit rate."
    if any(item.cache_eligible and item.input_reduction_fraction < 0.80 for item in pairs):
        return (
            "CACHE_INPUT_REDUCTION_LOW",
            "Reduce exact eligible cache-hit input tokens by 80 percent.",
        )
    return None


def _assessment(
    profile: BenchmarkProfile,
    build_sha256: str,
    status: BenchmarkStatus,
    local_passed: int,
    missing: tuple[PerformanceMetric, ...],
    pairs: tuple[TokenWorkloadPair, ...],
    reason: str,
    action: str,
) -> BenchmarkAssessment:
    reductions = [item.reduction_fraction for item in pairs]
    lookups = sum(item.cache_lookups for item in pairs)
    return BenchmarkAssessment(
        status=status,
        build_sha256=build_sha256,
        profile_sha256=profile.profile_sha256,
        local_metrics_passed=local_passed,
        required_metrics=len(profile.definitions),
        missing_reference_metrics=missing,
        median_token_reduction=statistics.median(reductions) if reductions else 0,
        cache_hit_rate=(sum(item.cache_hits for item in pairs) / lookups) if lookups else 0,
        reason_code=reason,
        next_action=action,
    )
