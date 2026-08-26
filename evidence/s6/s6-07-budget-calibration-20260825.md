# S6-07 Budget Calibration Evidence

## Status

`BLOCKED`

The calibration contract and deterministic formula tests pass. No production budget profile was
created because S6-06 has no complete approved-reference P95/P99 observation set.

## Implemented boundary

- Five task classes: G0, P1, P2, P3, and K1.
- Eight dimensions per class: graph steps, LLM calls, tool calls, total tokens, wall time,
  professional concurrency, review rounds, and correction rounds.
- Exactly 40 unique observations are required.
- Each observation binds build, benchmark profile, workload, environment, approval state, provider
  measurement, quality, sample count, P95, P99, correctness failures, and isolation failures.
- Default uses `ceil(P95 * 1.15)`.
- Hard uses `min(ceil(P99 * 1.25), V1_product_global_limit)`.
- Active equals default.
- Default above hard is rejected and no hard limit can expand a V1 global ceiling.
- Source V1 policies remain immutable; a candidate receives a new identity and content hash.
- Local, estimated, or unapproved evidence can produce only a provisional blocked profile.
- LLM-call and total-token calibration additionally requires provider measurement.

K1 calibration covers the base one-file policy. Existing deterministic file-count scaling and the
400-call global ceiling remain unchanged for larger batches.

## Verification

- Implementation SHA-256: `4346849a77ca35676708bf34a9cb8b8eab38d57ee94f48c654a99075badcace8`.
- Dedicated calibration tests: 6 passed.
- Calibration, performance, and runtime-budget affected set: 44 passed in 0.79 seconds.
- Ruff: pass.
- Strict mypy for implementation and tests: pass.
- DOC 1.61: pass.

The tests cover a complete synthetic positive contract, local/estimated provisional status,
missing and duplicate observations, stale binding, quality/correctness failure, reversed
percentiles, insufficient samples, formula/global-ceiling conflict, profile hashing, and unchanged
source policies. Synthetic measurements do not qualify the positive contract for production.

## Blocking evidence

The required exact-build P95/P99 set does not exist for any complete production task-class profile.
In particular, provider-measured LLM calls and tokens, deployed wall time, tool calls, graph steps,
review/correction rounds, and concurrency on the approved reference environment are missing.

Run and accept the complete S6-06 reference benchmark, then supply all 40 exact observations with
matching quality evidence. Only that input can create the approvable S6-07 production profile.
