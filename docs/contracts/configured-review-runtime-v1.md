# Configured Review Runtime V1

## Purpose

S1-16 connects the S1-15 configured scheduler to the existing S1-09 Review Workflow and Main
Aggregation Gate. It does not replace either contract.

## Binding contract

The application injects one immutable reviewer definition, one reviewer executor, and exactly one
correction executor for every configured professional agent profile. Correction assignment IDs are
derived from verified child contexts. A user, route payload, or child result cannot select an
executor object.

## Execution contract

- A successful General schedule enters the existing direct Main aggregation gate.
- A synchronous professional schedule enters review before the configured call returns.
- An asynchronous professional schedule remains queued until explicit advancement and then enters
  review automatically.
- Every completed professional result receives per-result review.
- Two or more professional results receive cross-result review even when their execution
  dependencies are independent.
- A passing review manifest enters the professional Main aggregation gate.
- Review correction is bounded, targeted, and followed by review of changed results only.

## Failure contract

Schedule failure, invalid schedule/context binding, review conflict, human requirement, review or
correction failure, timeout, malformed output, missing correction, budget exhaustion, stale
configuration, and changed recovery input return a typed non-aggregatable result. No child,
reviewer, or corrector can deliver directly to the user.

When an S1-09 review recovery repository is injected, the runtime derives one stable recovery ID
from the schedule and reuses committed reviewer, corrector, and terminal review outputs. The
repository remains responsible for append-only integrity and replay validation.

## Non-goals

This layer does not select a production model, resolve credentials, publish an artifact, perform a
physical action, synthesize final user prose, or turn local evidence into TG-01 evidence.

## Verification

`tests/orchestration/test_configured_review_runtime.py` covers General aggregation, synchronous and
queued professional review, mandatory cross review, targeted correction binding, non-pass stops,
schedule failure, exact catalogs, startup assembly, and recoverable review replay.
