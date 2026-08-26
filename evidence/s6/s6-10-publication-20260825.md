# S6-10 Publication Guard Evidence

## Status

`BLOCKED`

The exact-candidate release authorization, idempotent publisher boundary, deployed-hash check, and
post-publication smoke state machine are implemented and tested. No external publisher was called,
no deployment was created, and commercial V1.0 is not published.

## Implemented boundary

- PASS S6-09 sealed-candidate assessment and exact TG-06 candidate/evidence binding.
- Immutable authorized decision with candidate, artifact set, target, approver, release role,
  permission version, residual-risk acceptance, decision time, expiry, and decision hash.
- Zero publisher calls for failed candidate, TG-06, approval, target, artifact, freshness, or exact
  binding preflight.
- Exact-request idempotency: identical replay returns the same record; changed replay conflicts
  before a second publisher call.
- One injected publisher call after successful preflight.
- Exact deployed-candidate hash and immutable deployment-reference validation.
- Initial PUBLISHED_PENDING_SMOKE state.
- Nine live post-publication checks for health, identity, tenant isolation, task stream, review,
  approval control, cache isolation, tool denial, and artifact/version identity.
- COMPLETE only for exact, live, timely, all-pass smoke with zero P0/P1, leak, duplicate committed
  side effect, correctness failure, and isolation failure.
- ROLLBACK_REQUIRED for late, mismatched, failed, synthetic, or unsafe smoke.

## Verification

- Implementation SHA-256: `811bef7985f2dbd7eaa518d03f02a8c1a0e9f69a5d8ff6de010f9912837f9c59`.
- Dedicated publication tests: 5 passed.
- Affected publication, release, pilot, approval, client, cache, identity, and storage set: 107
  passed in 2.03 seconds.
- Ruff: pass.
- Strict mypy for implementation and tests: pass.
- DOC 1.64: pass.

All publisher calls in tests use an in-process spy. The positive fixture uses a synthetic candidate,
TG-06 record, decision, and deployment result to validate the contract only.

## Required next action

Complete S6-09, pass TG-06 on the same immutable candidate, and obtain an authorized fresh release
decision. Only then may the production publisher adapter be configured and invoked. Preserve the
PUBLISHED_PENDING_SMOKE record, run the live post-publication checks within the approved window,
and mark complete only on a safe exact result; otherwise execute the approved rollback.
