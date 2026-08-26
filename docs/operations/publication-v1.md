# Commercial Publication and Post-Publication Verification V1

## Preconditions

Use only the exact sealed S6-09 candidate after complete RELEASE and TG-06 PASS. Obtain an immutable
authorized decision that binds the candidate, artifact set, gate evidence, commercial target,
approver identity, role, permission version, decision time, expiry, and residual-risk acceptance.
Resolve both records from the application-owned immutable publication-authority store by hash.
Treat request-supplied records only as comparison copies; reject missing, changed, revoked, stale,
cross-target, or no-longer-authorized authority records before acquiring publisher credentials.

## Publication

Run preflight before acquiring publisher credentials. Use one idempotency key for the exact
candidate, decision, and target. Verify that the publisher returns the same candidate hash and an
immutable deployment reference. Preserve the publication record in PUBLISHED_PENDING_SMOKE state.

## Post-publication smoke

Within the approved window, run live health, identity, tenant-isolation, task-stream, review,
approval-control, cache-isolation, tool-denial, and artifact/version checks. Bind evidence to the
publication and candidate. Mark COMPLETE only when all checks pass and unsafe counts are zero.

A mismatch, unsafe count, or failed check sets ROLLBACK_REQUIRED and invokes the separately approved
rollback procedure. Local injected publishers and synthetic checks never authorize or perform a
commercial release.
