"""Run bounded local S6-06 microbenchmarks and print canonical JSON evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ndt_agents.cache.keys import CacheKeyInput, CacheKeyVersions, build_cache_key  # noqa: E402
from ndt_agents.cache.models import CacheClass  # noqa: E402
from ndt_agents.client.models import ClientTaskClass, TaskCreateRequest  # noqa: E402
from ndt_agents.client.service import InMemoryTaskRepository  # noqa: E402
from ndt_agents.contracts.v1 import TenantScope  # noqa: E402
from ndt_agents.operations.performance import (  # noqa: E402
    BenchmarkEnvironment,
    HardwareDescriptor,
    MetricSeries,
    PerformanceMetric,
    TokenBreakdown,
    TokenWorkloadPair,
    assess_benchmark,
    build_benchmark_profile,
)

SAMPLES = 200
CONCURRENT_SAMPLES = 100


def sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def measure(action: Callable[[int], object], count: int) -> tuple[tuple[float, ...], float]:
    samples: list[float] = []
    started = time.perf_counter()
    for index in range(count):
        item_started = time.perf_counter_ns()
        action(index)
        samples.append(max((time.perf_counter_ns() - item_started) / 1_000_000, 0.000001))
    return tuple(samples), time.perf_counter() - started


def scope(user: int = 3) -> TenantScope:
    return TenantScope(
        tenant_id=UUID("00000000-0000-4000-8000-000000000601"),
        project_id=UUID("00000000-0000-4000-8000-000000000602"),
        user_id=UUID(f"00000000-0000-4000-8000-{user:012d}"),
        role_codes=("PROJECT_OPERATOR",),
        permission_version="permissions-s6-1",
    )


def request(index: int) -> TaskCreateRequest:
    return TaskCreateRequest(
        task_class=ClientTaskClass.GENERAL,
        goal="Measure exact-scope local task acceptance.",
        success_criteria=("Return the accepted task",),
        idempotency_key=f"s6-benchmark-{index:08d}",
    )


def cache_input() -> CacheKeyInput:
    return CacheKeyInput(
        scope=scope(),
        cache_class=CacheClass.EXACT,
        request_text="Repeat stable benchmark query",
        task_type="G0",
        request_parameters={"mode": "benchmark"},
        versions=CacheKeyVersions(
            rbac_policy_version="rbac-s6-1",
            route_policy_version="route-s6-1",
            graph_version="graph-s6-1",
            model_version="model-s6-1",
            prompt_versions={"main": "1"},
            skill_versions={"general": "1"},
            tool_name="none",
            tool_version="1",
            adapter_version="1",
            knowledge_corpus_version="1",
            knowledge_document_versions={"fixture": "1"},
            public_schema_version="1",
            parser_version="1",
            context_policy_version="1",
        ),
    )


def token_pair(index: int, route: str) -> TokenWorkloadPair:
    cold = TokenBreakdown(
        input_tokens=1200 + index * 100,
        output_tokens=220,
        hidden_orchestration_tokens=80,
        review_tokens=0 if index < 2 else 100,
        retry_tokens=0,
        cache_hit_tokens=0,
        cache_miss_tokens=20,
    )
    warm = TokenBreakdown(
        input_tokens=100,
        output_tokens=220,
        hidden_orchestration_tokens=40,
        review_tokens=0 if index < 2 else 100,
        retry_tokens=0,
        cache_hit_tokens=10,
        cache_miss_tokens=0,
    )
    task_classes = ("G0", "G0", "P1", "P3", "P2", "P2")
    workload_hash = sha256_json({"index": index, "route": route, "revision": 1})
    return TokenWorkloadPair.model_validate(
        {
            "workload_id": f"local-estimate-{index + 1}",
            "task_class": task_classes[index],
            "route": route,
            "build_sha256": BUILD_SHA256,
            "workload_sha256": workload_hash,
            "cold": cold,
            "warm": warm,
            "cache_eligible": True,
            "cache_hits": 4,
            "cache_lookups": 5,
            "provider_measured": False,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-sha256", required=True)
    arguments = parser.parse_args()
    global BUILD_SHA256
    BUILD_SHA256 = arguments.build_sha256
    if len(BUILD_SHA256) != 64 or any(
        character not in "0123456789abcdef" for character in BUILD_SHA256
    ):
        raise ValueError("build SHA-256 must be 64 lowercase hexadecimal characters")

    profile = build_benchmark_profile()
    hardware = HardwareDescriptor(
        platform=platform.platform(),
        processor=platform.processor() or "unknown",
        logical_cpus=os.cpu_count() or 1,
        python_version=platform.python_version(),
    )
    configuration_sha256 = sha256_json(
        {
            "samples": SAMPLES,
            "concurrent_samples": CONCURRENT_SAMPLES,
            "profile": profile.profile_sha256,
        }
    )
    workload_sha256 = sha256_json({"suite": "s6-local-contract", "revision": 1})

    cache_value = cache_input()
    cache_samples, cache_elapsed = measure(lambda _: build_cache_key(cache_value), SAMPLES)
    task_repository = InMemoryTaskRepository()
    task_ids: list[UUID] = []

    def create_task(index: int) -> None:
        task_ids.append(task_repository.create(scope(), request(index)).task_id)

    task_samples, task_elapsed = measure(create_task, SAMPLES)
    event_samples, event_elapsed = measure(
        lambda index: task_repository.events(scope(), task_ids[index], 0).model_dump_json(),
        SAMPLES,
    )

    concurrent_repository = InMemoryTaskRepository()
    concurrent_samples: list[float] = []
    concurrency_started = time.perf_counter()

    def create_concurrent(index: int) -> None:
        started = time.perf_counter_ns()
        task = concurrent_repository.create(scope(index + 100), request(index + 1000))
        if task.scope != scope(index + 100):
            raise RuntimeError("concurrent scope mismatch")
        concurrent_samples.append(max((time.perf_counter_ns() - started) / 1_000_000, 0.000001))

    with ThreadPoolExecutor(max_workers=CONCURRENT_SAMPLES) as executor:
        tuple(executor.map(create_concurrent, range(CONCURRENT_SAMPLES)))
    concurrency_elapsed = time.perf_counter() - concurrency_started

    def series(
        metric: PerformanceMetric, samples: tuple[float, ...], elapsed: float, concurrency: int = 1
    ) -> MetricSeries:
        return MetricSeries(
            metric=metric,
            build_sha256=BUILD_SHA256,
            profile_sha256=profile.profile_sha256,
            configuration_sha256=configuration_sha256,
            workload_sha256=workload_sha256,
            environment=BenchmarkEnvironment.LOCAL,
            hardware=hardware,
            latency_ms=samples,
            elapsed_seconds=elapsed,
            operations=len(samples),
            concurrency=concurrency,
            failures=0,
            correctness_failures=0,
            isolation_failures=0,
        )

    measurements = (
        series(PerformanceMetric.LOCAL_CACHE_KEY, cache_samples, cache_elapsed),
        series(PerformanceMetric.LOCAL_TASK_CREATE, task_samples, task_elapsed),
        series(PerformanceMetric.LOCAL_EVENT_SERIALIZE, event_samples, event_elapsed),
        series(
            PerformanceMetric.LOCAL_CONCURRENT_TASK,
            tuple(concurrent_samples),
            concurrency_elapsed,
            CONCURRENT_SAMPLES,
        ),
    )
    routes = (
        "RULES_ONLY",
        "GENERAL",
        "SINGLE_PROFESSIONAL",
        "MULTI_PROFESSIONAL",
        "COMPRESSED",
        "RESTORED",
    )
    tokens = tuple(token_pair(index, route) for index, route in enumerate(routes))
    assessment = assess_benchmark(profile, BUILD_SHA256, measurements, tokens)
    output = {
        "schema_version": "1.0.0",
        "profile": profile.model_dump(mode="json"),
        "build_sha256": BUILD_SHA256,
        "configuration_sha256": configuration_sha256,
        "workload_sha256": workload_sha256,
        "hardware": hardware.model_dump(mode="json"),
        "metrics": [
            {
                "metric": item.metric.value,
                "samples": len(item.latency_ms),
                "p50_ms": item.p50_ms,
                "p95_ms": item.p95_ms,
                "p99_ms": item.p99_ms,
                "throughput_per_second": item.throughput_per_second,
                "concurrency": item.concurrency,
                "failures": item.failures,
                "correctness_failures": item.correctness_failures,
                "isolation_failures": item.isolation_failures,
            }
            for item in measurements
        ],
        "tokens": [
            {
                "workload_id": item.workload_id,
                "route": item.route,
                "provider_measured": item.provider_measured,
                "cold_total": item.cold.total_tokens,
                "warm_total": item.warm.total_tokens,
                "reduction_fraction": item.reduction_fraction,
                "input_reduction_fraction": item.input_reduction_fraction,
                "cache_hits": item.cache_hits,
                "cache_lookups": item.cache_lookups,
            }
            for item in tokens
        ],
        "assessment": assessment.model_dump(mode="json"),
    }
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))


BUILD_SHA256 = ""


if __name__ == "__main__":
    main()
