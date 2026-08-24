# Approval Service V1

## Scope

S1-13 supplies one generic approval checkpoint for knowledge changes, inspection plans, formal
reports, critical findings, high-impact instrument commands, destructive operations, and software
release publication. Domain workflows configure this core in later phases.

## Candidate and pause

A candidate binds its tenant and project, task and request, requester, action, target ID and version,
candidate SHA-256, policy version, preview, creation time, and expiry. Creation appends the first
immutable event and returns `PENDING`; no protected operation is performed by this service.

## Authority and decisions

Each checkpoint kind maps to required human roles and an approval count. Release publication needs
distinct Security Owner and Quality Owner decisions. The requester cannot approve the candidate.
Delegation is disabled unless its rule explicitly permits a bounded, scope-bound delegation event.

Approve, reject, request-change, expire, and cancel decisions bind an exact current candidate hash.
Reject, request-change, expiry, and cancellation are terminal. Approval remains pending until every
required role condition is satisfied. Duplicate IDs with exact content are idempotent; a conflicting
ID, duplicate actor, stale hash, unauthorized actor, cross-scope request, or decision after a
terminal state is denied.

## Resume and recovery

Only an approved current candidate may create a resume grant. The grant binds one stable resume ID,
approval ID, candidate hash, policy, scope, and immutable decision hashes. Exact replay returns the
same grant; a second conflicting resume is denied. Candidate, delegation, decision, and resume
events are monotonic and hash-chained. A new service instance reconstructs state from the same
repository after verifying the event chain.

Migration `0005_s1_approval` provides one forced-RLS append-only PostgreSQL event journal. The local
reference repository is deterministic and restart-testable; live identity, database, policy-owner,
and production workflow probes remain TG-01 or later-phase requirements.
