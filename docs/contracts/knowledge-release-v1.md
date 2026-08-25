# Knowledge Release Workflow V1

**Contract version:** 1.0.0

**Task:** S3-09

**Required tests:** INT-KNOWLEDGE, INT-REVIEW, INT-APPROVAL, EVAL-RETRIEVAL, SEC-TENANT,
RES-CHECKPOINT, QUICK, DOC

## 1. Candidate and incremental diff

A candidate binds its UUID, exact `TenantScope`, task and request, corpus, corpus version, index and
embedding versions, current base publication, complete draft snapshots, deterministic document and
chunk diff, and SHA-256. Exact create replay returns the existing aggregate. A conflicting ID,
cross-scope snapshot, or stale base fails before storage.

The diff records added, updated, and removed document IDs plus added and removed chunk IDs. The
candidate retains immutable input snapshots and progresses through a contiguous UTC transition
history beginning `DRAFT`.

## 2. Deterministic validation and independent review

Validation records `DRAFT -> VALIDATING -> REVIEW_REQUIRED` on success and
`DRAFT -> VALIDATING -> FAILED` on failure. It checks the unchanged base, exact scope, draft index
state, corpus/index/embedding versions, unique documents and chunks, strict locator and hash
contracts, registered same-scope standard bindings, current or restricted lifecycle, usable rights
with evidence, required roles, and supersession. Failure codes are stable and hash-bound.

Approval cannot be requested from raw or merely validated output. The service requires one
aggregation-ready, non-partial S1-09 professional `ReviewWorkflowResult` with no skipped
assignment. Its passed reviewed `AgentResult` must carry the exact candidate ID, candidate SHA-256,
and validation-report SHA-256. Review outputs, reviewer versions, reviewed result, and the validated
S1-09 workflow manifest are captured in immutable review evidence.

## 3. Human approval and publication

Publication creates an S1-13 `KNOWLEDGE` checkpoint for `knowledge.publish`. The checkpoint binds
the candidate, diff, validation, and review hashes. Only the exact approved resume grant may enter
the repository commit. The commit rechecks the current base, marks prior snapshots and publication
superseded, marks the candidate snapshots published, updates the corpus head, and records the
candidate publication transition as one atomic operation. Draft, superseded, and withdrawn
snapshots remain outside S3-07 scoring.

Exact publication replay returns the same record. Wrong kind, action, target, candidate hash,
scope, base, state, approval, or review fails before mutation. An injected pre-commit fault consumes
no index, head, publication, or candidate mutation; the exact approved resume can be retried.

## 4. Withdrawal and rollback

Withdrawal and rollback each create a distinct S1-13 `KNOWLEDGE` checkpoint with a separate action
hash and approval grant. Withdrawal applies only to the current publication and atomically marks
its snapshots withdrawn and clears the corpus head. Rollback targets a preserved prior
publication, supersedes the current publication, republishes the preserved snapshots under a new
publication UUID, and records both the replaced and restored publication IDs. Neither operation
deletes or rewrites historical content or approval evidence.

## 5. Persistence boundary

The local reference repository uses locked copy-and-swap batches. Migration
`0011_s3_knowledge_release` defines exact-scope PostgreSQL release events, publication records, and
the atomic corpus head with forced RLS and an append-only event trigger. A production adapter must
commit publication state, index visibility, the head pointer, and release events in one database
transaction and retain the exact hash and approval semantics. Live PostgreSQL, vector/full-text
indexes, licensed standards, accountable approvers, and immutable CI remain TG-03 requirements.
