# S1-06 Task Scheduler Local Evidence

**Run ID:** S1-06-TASK-20260821-01  
**Task:** S1-06  
**Environment:** local Windows with deterministic injected child executors and in-process queue  
**Result:** PASS for isolated scheduler execution

## Candidate identity

- Workspace state: Git repository without an immutable commit.
- Task Scheduler contract: 1.0.0.
- Controlled-document version: 1.11.
- Configuration SHA-256: `58a788d07ee3e436f6ec15c7fc4497081e5daf6a2626894004e2bc1bcd3e041e`.
- Python: CPython 3.12.13.
- uv: 0.11.20, build `9252ba6b5`.

The configuration hash covers sorted hashes for the task-scheduler contract, all orchestration
source files, and all orchestration tests.

## Reproducible task profile

Started at `2026-08-21T23:49:55.1443567+08:00` and ended at
`2026-08-21T23:50:01.2172496+08:00`.

```text
uv run pytest tests/orchestration tests/contracts tests/identity
uv run ruff check src tools tests migrations
uv run mypy
uv run python tools/check_controlled_docs.py
```

Results:

- task tests: 61 passed in 1.79 seconds;
- Ruff: passed;
- strict mypy: passed across 50 source files;
- DOC: passed for four version 1.11 controlled documents and seven gates.

The final complete QUICK run started at `2026-08-21T23:50:08.3937221+08:00`, ended at
`2026-08-21T23:50:18.2202837+08:00`, and passed 104 tests in 2.31 seconds. Ruff, strict mypy, DOC,
and the local dependency audit also passed. No dependency changed in S1-06.

## Acceptance evidence

- One General child completed synchronously before `run_sync` returned.
- Asynchronous enqueue made zero executor calls and returned a task- and complete-scope-bound
  handle; only explicit authorized `advance` started execution.
- Wrong user or permission binding was denied without removing the queued work.
- Repeated terminal `advance` returned the same result and made no duplicate executor call.
- Whole-schedule and per-assignment cancellation before start made zero cancelled executor calls.
- Known acyclic dependencies formed deterministic topological waves.
- Independent read-only assignments ran in batches bounded by the active professional limit.
- Dependent assignments and independent mutating assignments ran serially.
- Failed or cancelled prerequisites returned typed blocked dependents with zero executor calls.
- Duplicate assignments, executor mismatch, unknown dependencies, cycles, mixed scope, budget
  mismatch, invalid active concurrency, and configured hard-ceiling violations were rejected before
  any child started.
- Every launched assignment called `ChildSubgraph` exactly once; the scheduler contains no retry.
- Professional child results remained review-pending and unavailable for direct aggregation.

## Limitations and next action

This queue is intentionally in-process and requires explicit advancement. It is not restart durable
and has no distributed worker lease, checkpoint, idempotency store, or mid-execution interrupt.
S1-07 must add persistence, checkpoints, idempotency, interrupts, and recovery. S1-08 and S1-09
still own complete budget telemetry and review transitions. R-010 requires exact approved-candidate
revalidation, and this local evidence does not satisfy TG-01.
