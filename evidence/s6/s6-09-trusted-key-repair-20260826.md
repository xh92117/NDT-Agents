# S6-09 trusted release-key repair evidence

- Run ID: `S6-09-REPAIR-20260826-01`
- Date: 2026-08-26
- Branch: `codex/s6-clients`
- Build state: mutable local workspace; not an immutable release candidate
- Defect: `DEF-REL-001`

## Change

Release qualification now resolves the signing-key reference through an application-owned
`ReleaseKeyRegistry`. Qualification requires an approved, enabled, non-revoked external key with
the `RELEASE_SIGNING` purpose. The trusted public-key identity must exactly match the candidate
signature, and signature verification uses the trusted registry key. Candidate-supplied approval
and environment fields cannot establish trust.

The publication service requires the same registry and cannot assess a candidate without it.

## Verification

- `uv run pytest`: 1000 passed, 1 skipped in 62.99 seconds.
- S6-09 and S6-10 focused tests: 16 passed.
- `uv run python -m ruff check .`: PASS.
- `uv run python -m ruff format --check .`: PASS; 376 files already formatted.
- `uv run mypy`: PASS over 186 source files.
- `uv run python tools/check_controlled_docs.py`: `DOC=PASS version=1.65 files=4 gates=7 ascii=true`.
- `git diff --check`: PASS.

Attack coverage rejects an unknown key reference, revoked key, disabled key, wrong-purpose key,
and public-key substitution under an approved reference. The publisher is not called when release
qualification is blocked.

## Source hashes

- `release.py`: `e4c9e0de2b4dbd99d5fcaf01072f621b077d5eece0316bc60b0e4b6bb85f1fd5`
- `publication.py`: `20cf396e7614ae32767b3824a0a81fc73da6a94fbb849b2ce680ee3f9c97402c`
- `test_release_candidate.py`: `8ade9ca8f8880609ce92db2df6dc2a69fe548c341325cd6db15aba0a6982a5ac`
- `test_publication.py`: `9a070cac906b3e99987291e976e001276980a38493ac5cf157201d51b97eb388`

## Remaining blockers

This closes the local code defect only. S6-09 remains blocked by S6-08, immutable protected-CI
artifacts, an approved external key registry and signing service, live migration and rollback,
production-like smoke evidence, complete RELEASE, and TG-06.
