# S6-06 Local Performance and Token Evidence

## Status

`BLOCKED`

The S6-06 measurement and aggregation contracts pass locally. This report is not a production
performance baseline, an approved SLO, provider billing evidence, or TG-06 evidence. The approved
reference environment and required live services are unavailable.

## Evidence identity

- Date: 2026-08-25
- Branch: `codex/s6-clients`
- Repository state: mutable working tree
- Source candidate SHA-256: `d44ca022e96acaa36682b7ded703183ab4c2f19ccc11c9589a51bdc856255b5d`
- Candidate rule: SHA-256 over sorted `src`, `tests`, and `tools` path plus file-SHA-256 entries
- Profile: `s6-performance-1`
- Profile SHA-256: `08c9049a8e3dc9f6c631eccb13565608394625fdfabb2dfc16d67ddc67f952b3`
- Configuration SHA-256: `316b59fb92b31db159112d73e59c7adc72acdf4e6e912fbaf7086d1598ce9159`
- Workload SHA-256: `4e361e7b1e4ea2e9187635ad51e2b24f100cf29586a507d81b4b3ca083ccab69`
- Environment: Windows 11 10.0.26200 SP0, CPython 3.12.13
- Processor: Intel64 Family 6 Model 186 Stepping 3, GenuineIntel
- Logical CPUs: 12

The source candidate hash is reproducible local evidence but is not an immutable Git build or
release-candidate identity.

## Commands

```powershell
.venv\Scripts\python.exe tools\run_s6_benchmarks.py --build-sha256 <source-candidate-sha256>
.venv\Scripts\pytest.exe tests\operations\test_performance.py tests\cache tests\client tests\orchestration\test_budget.py
.venv\Scripts\ruff.exe check src\ndt_agents\operations\performance.py tests\operations\test_performance.py tools\run_s6_benchmarks.py
.venv\Scripts\mypy.exe src\ndt_agents\operations\performance.py tools\run_s6_benchmarks.py tests\operations\test_performance.py
```

## Local measurements

Nearest-rank percentiles are in milliseconds. These are in-process contract microbenchmarks, not
user-visible service latency.

| Metric | Samples | Concurrency | P50 | P95 | P99 | Operations/s | Failures | Correctness | Isolation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Local cache-key construction | 200 | 1 | 0.0305 | 0.0344 | 0.0577 | 31028.92 | 0 | 0 | 0 |
| Local task creation | 200 | 1 | 0.0219 | 0.1068 | 0.1924 | 25649.25 | 0 | 0 | 0 |
| Local event serialization | 200 | 1 | 0.0138 | 0.0291 | 0.1098 | 54866.67 | 0 | 0 | 0 |
| Local exact-scope task creation | 100 | 100 | 0.0395 | 0.1703 | 0.2117 | 7204.35 | 0 | 0 | 0 |

All four local contract metrics passed their deliberately loose microbenchmark ceilings. The
100-concurrent sample verified unique task identity and exact user scope for every result.

## Token and cache calculation contract

Six estimated cold/warm pairs covered rules-only, General, single-professional,
multi-professional, compressed, and restored routes. Estimated values are explicitly marked
`provider_measured=false`.

- Median repeated-workload total-token reduction: 76.20 percent.
- Aggregate stable-query cache hit rate: 80.00 percent.
- Exact eligible input-token reductions: 91.67 to 94.12 percent.
- Calculation-contract acceptance thresholds: 25 percent, 35 percent, and 80 percent.

These values validate the pairing and threshold calculations only. They are not measured model
usage and cannot calibrate a production token budget.

## Automated verification

- Dedicated performance contract: 9 passed.
- Affected cache, client, budget, and performance set: 86 passed in 1.95 seconds.
- Ruff: pass.
- Strict mypy for the changed implementation, tool, and tests: pass.
- Local assessment: `BLOCKED`, reason `PERF_REFERENCE_EVIDENCE_MISSING`.

## Missing release evidence

The following metrics have no approved-reference live result:

- cached simple-answer latency;
- uncached first-token latency;
- ordinary tool-task latency;
- asynchronous enqueue latency;
- 100 concurrent active user tasks through the deployed stack;
- database load and queue delay;
- vector search;
- parser throughput;
- artifact transfer;
- production client streaming;
- provider-measured cold/warm tokens and matching quality results.

Run every metric on the approved reference environment with the exact immutable build and preserve
the raw series before S6-06 can pass or S6-07 can create an approved production budget profile.
