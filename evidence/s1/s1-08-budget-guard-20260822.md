# S1-08 Budget Guard Local Evidence

**Run ID:** S1-08-TASK-20260822-01  
**Task:** S1-08  
**Environment:** local Windows with deterministic clocks, executors, recovery, and object backends  
**Result:** PASS for isolated quantitative guard and restart-safe budget enforcement

## Candidate identity

- Workspace state: Git repository without an immutable commit.
- Budget Guard contract: 1.0.0.
- Recovery public contract: 1.0.0; persisted recovery state schema: 1.1.0.
- Controlled-document version: 1.13.
- Configuration SHA-256: `4e30acca0cb577b1c6ef8b01d4e8d7575afb9f95c159aeef8e8d926029d92ed4`.
- Python: CPython 3.12.13.
- uv: 0.11.20, build `9252ba6b5`.

The configuration hash covers sorted path-and-file hashes for four affected orchestration contracts,
all ten orchestration source files, and all six orchestration test files, for 20 files total.

## Reproducible task profile

Started at `2026-08-22T00:32:46.2146827+08:00` and ended at
`2026-08-22T00:32:55.6174573+08:00`.

```text
uv run pytest tests/orchestration tests/contracts tests/identity -o addopts='' -ra
uv run pytest -o addopts='' -ra
uv run ruff check src tools tests migrations
uv run ruff format --check <S1-08 changed Python files>
uv run mypy
uv run python tools/check_controlled_docs.py
PYTHONUTF8=1 uv run pip-audit --local --progress-spinner off
```

Results:

- task tests: 101 passed in 2.05 seconds;
- complete tests: 144 passed in 3.19 seconds;
- S1-08 budget tests: 29 passed;
- recovery tests, including restart budget cases: 10 passed;
- Ruff lint: passed;
- Ruff format check: seven changed Python files passed;
- strict mypy: passed across 54 source files;
- DOC: passed for four version 1.13 controlled documents and seven gates;
- dependency audit: no known vulnerabilities found.

## Acceptance evidence

- The central factory produced the exact G0, P1, P2, P3, and K1 defaults and hard ceilings from the
  controlled specification. K1 file-derived tool limits remained bounded at 400.
- Active elevation required a distinct policy ID and a deterministic-risk or human-approval
  reference and could not exceed a non-overridable hard limit.
- Graph, LLM, tool, token, wall-time, professional-concurrency, review, and correction checks denied
  work before the guarded action exceeded its active or hard ceiling.
- LLM calls reserved maximum tokens before execution and recorded actual provider tokens afterward.
  Failed calls, retries, actual tokens, and outstanding reservations remained separate.
- Tool calls used stable identity, canonical arguments, and observation SHA-256. An identical call
  with unchanged evidence was denied before a second physical call; new evidence allowed it.
- Cache lookup, cache hit, physical-call, logical-action, retry, failure, current-concurrency, and
  peak-concurrency metrics remained distinct.
- The 70, 85, 95, and 100 percent stages deterministically reduced low-value work, stopped query
  expansion, restricted work to validation/finalization, and stopped standard actions.
- Professional concurrency leases never exceeded active or hard limits and released after normal
  completion and exceptions.
- The scheduler used the exact child policy, shared one guard across children, and returned a typed
  zero-call failure when graph capacity denied a child before its executor.
- Four ReAct actions per successful child consumed graph budget. Terminal transitions and terminal
  budget stops were traced separately and did not spend an exhausted graph step.
- Recovery persisted graph reservations and complete telemetry before child execution, then
  persisted scheduler output and current telemetry before terminalization. The normal checkpoint
  sequence was `0, 1, 2, 3`.
- Recovery restored counters, elapsed time, trace events, and tool repetition history. Process loss
  charged the outstanding attempt reservation before retry instead of resetting usage.
- A process loss after the post-execution checkpoint terminalized with zero replacement executor
  calls. Two consecutive pre-execution process losses exhausted the G0 active graph budget; the
  third advance returned a typed failed schedule with zero executor calls.
- Recovery rejected an in-flight LLM-token reservation and active professional lease rather than
  treating them as safe restart state.

## Limitations and next action

The task proves a provider-neutral guard and deterministic scheduler/recovery integration. Physical
LLM and registered tool adapters do not yet exist; their later tasks must invoke the reservation
APIs at the actual provider boundaries. The local recovery backend and monotonic clock do not prove
distributed worker timing, queue leases, live PostgreSQL/object-store behavior, or approved SLOs.
S1-09 and S1-10 must add review state transitions and immutable audit correlation. Live
infrastructure evidence and exact approved-candidate revalidation remain required before TG-01;
R-010 remains open, and this evidence is not phase-gate evidence.
