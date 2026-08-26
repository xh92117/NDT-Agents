# S6-08 Shadow Deployment and Expert Pilot Evidence

## Status

`BLOCKED`

The immutable ledger and pilot acceptance state machine are implemented and tested. No live shadow
day is claimed. S6-05, S6-06, and S6-07 are blocked, no approved production-like deployment exists,
seven real service dates have not elapsed, and no qualified expert review has occurred.

## Implemented boundary

- Exactly seven consecutive UTC service dates.
- At least 144 elapsed hours from first start to final evaluation.
- One unchanged immutable build, assurance catalog, performance profile, calibrated budget profile,
  configuration, workload, and approved environment.
- Hash-chained daily records and one content-hashed ledger.
- Nonzero task, critical workflow, noncritical workflow, and expert-visible case counts.
- Daily PASS states for security, resilience, performance, and token economics.
- Zero P0/P1, tenant leak, duplicate committed side effect, correctness failure, and isolation
  failure.
- Critical workflow pass rate of 100 percent and noncritical pass rate of at least 98 percent.
- Two distinct qualified expert acceptances bound to the exact ledger and rubric.
- Typed blocked/failed states for incomplete time, missing experts, synthetic/unapproved evidence,
  future or nonconsecutive dates, changed bindings, unsafe counts, failed gates, broken chains, and
  stale expert review.

## Verification

- Implementation SHA-256: `d76a3cc56df44bc777400bfc852117392d3f1ec9984f1c9482bea45afaef3bbb`.
- Dedicated pilot-contract tests: 11 passed.
- Affected S6 operations and evidence-contract set: 54 passed in 0.89 seconds.
- Ruff: pass.
- Strict mypy for implementation and tests: pass.
- DOC 1.62: pass.

The positive unit fixture uses clearly synthetic historical dates to validate only the PASS contract.
It is not stored as a candidate ledger and counts as zero live pilot days.

## Required next action

First clear S6-05 through S6-07 for one exact immutable build and approved environment. Deploy that
candidate in shadow mode, collect seven real hash-chained daily records over at least 144 elapsed
hours, stop on any safety or quality failure, and obtain two distinct qualified expert reviews of
the completed ledger. Only that evidence can complete S6-08.
