# S2-09 Data Lifecycle Evidence

Status: PASS for the isolated local task profile; full TG-02 and production use are not claimed.

## Delivered boundary

- A strict lifecycle service registers exact-scope, classified, hash-bound governed objects with
  bounded retention and optional object-unique encryption keys.
- Export produces an authorization-filtered canonical manifest. Deletion uses an exact hash-bound
  preview and approval, is idempotent, and retains content-free tombstone evidence.
- Exact approvals apply and release legal holds. Active holds prevent deletion and erasure.
- Cryptographic erasure requires retention expiry, an object-unique key, successful revocation,
  and exact approval before content removal.
- Migration `0010_s2_lifecycle` adds forced-RLS object, hold, and append-only event tables with a
  reversible downgrade.

## Verification

- Ten dedicated lifecycle cases and the affected storage and migration tests passed.
- All 413 repository tests completed with one known Windows file-name capability skip.
- Four deterministic generators produced no drift.
- `DOC=PASS version=1.35 files=4 gates=7 ascii=true`.
- Ruff lint and format, strict mypy over 113 source files, dependency audit, and diff checks passed.

## Limits

Live PostgreSQL, backup expiry, cache and index invalidation, distributed partial-failure recovery,
immutable CI, and accountable retention/security approval were unavailable. These remain explicit
TG-02 blockers and are not represented as passing production evidence.
