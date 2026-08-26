# S6 Budget Calibration Contract V1

## Purpose

This contract converts successful-task P95 and P99 observations into immutable candidate runtime
budgets. It does not authorize a budget increase or replace S6-06 evidence.

## Required evidence

Each G0, P1, P2, P3, and K1 task class requires one observation for graph steps, LLM calls, tool
calls, total tokens, wall time, professional concurrency, review rounds, and correction rounds.
Every observation binds the exact build, S6-06 profile, workload, environment, sample count,
provider-measurement state, quality result, and correctness/isolation counts.

K1 observations calibrate the base one-file policy. The existing deterministic file-count scaling
and global tool-call ceiling remain authoritative for larger batches.

## Formula and invariants

```text
default = ceil(successful_task_P95 * 1.15)
hard = min(ceil(successful_task_P99 * 1.25), V1_product_global_limit)
active = default
```

The candidate is invalid if default exceeds hard. Calibration never expands an existing product
global ceiling and never mutates the source V1 policy. A new hash-bound profile preserves all 40
observation hashes and five calibrated task-class policies.

## Qualification

Duplicate, missing, stale, insufficient, failed-quality, correctness-failed, or isolation-failed
evidence fails or blocks calibration. Local or unapproved-reference evidence remains provisional.
LLM-call and token observations also require provider measurement. Only a complete exact-build
approved-reference set may become an approvable production profile.
