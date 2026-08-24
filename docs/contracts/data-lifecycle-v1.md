# Data Lifecycle V1

Status: implemented by S2-09 for the provider-neutral local runtime.

## Boundary

`DataLifecycleService` is the single governed boundary for registering, exporting, deleting,
holding, and cryptographically erasing scoped data. Every call requires a `MemoryAccess` carrying
the exact tenant, project, user, permission version, permissions, and classification clearance.
The service returns strict versioned models and typed `LifecycleError` failures.

## Records and retention

A `GovernedObject` binds its exact scope, classification, object and schema versions, canonical
content SHA-256, retention deadline, state, and optional `KeyRef`. Registration rejects duplicate
IDs and retention outside 1 through 3650 days. The policy defaults ordinary records to 365 days
and audit records to 2555 days. Content hashes remain on tombstones after content removal.

Exports include only active, authorized records and bind their canonical records to one manifest
SHA-256. Cross-scope, insufficient-clearance, duplicate-target, and inactive-object requests fail
closed.

## Deletion and legal hold

Deletion first creates a deterministic preview containing the exact object IDs, content hashes,
scope, retention mode, time, and policy version. The mutation requires a current `ApprovalRecord`
for that preview hash. Deletion before retention expiry uses the distinct `data.delete.force`
action. A successful mutation removes content, writes a non-content tombstone, appends an event,
and is idempotent for the same preview.

Applying and releasing a legal hold each require a current approval for the exact object or hold
hash. An active hold blocks deletion preview and cryptographic erasure. Release is append-only and
idempotent; the prior hold evidence remains represented by the released record and events.

## Cryptographic erasure

Cryptographic erasure requires retention expiry, no active hold, a current exact-object approval,
and an object-unique key whose purpose is `object-<object UUID hex>`. The key provider must confirm
revocation before content is removed. Shared keys, unavailable key providers, stale approvals, and
repeated or conflicting operations return typed failures without representing erasure as complete.

## Persistence and audit

Migration `0010_s2_lifecycle` creates governed-object, legal-hold, and append-only lifecycle-event
tables. All three tables carry tenant and project scope, enable and force PostgreSQL RLS, and have
reversible downgrade operations. The event table rejects update and delete. Each service event
binds the action, target IDs, input and outcome hashes, optional approval ID, scope, and time.

This S2 implementation does not claim live PostgreSQL, backup-expiry, cache/index invalidation,
distributed partial-failure, or immutable release evidence. Those integrations remain phase-gate
requirements under `INT-DATA-LIFECYCLE` and the blocked production baseline.
