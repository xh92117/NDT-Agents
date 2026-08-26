# S6-10 publication-authority repair evidence

- Run ID: `S6-10-REPAIR-20260826-01`
- Date: 2026-08-26
- Branch: `codex/s6-clients`
- Build state: mutable local workspace; no commercial publisher was called
- Defect: `DEF-REL-002`

## Change

Publication preflight now resolves TG-06 evidence and the authorized release decision from an
application-owned `PublicationAuthority`. Request-supplied copies must exactly match immutable
stored records, and a revoked decision is denied before release assessment or publisher execution.
The publication service also retains the S6-09 trusted release-key registry requirement.

## Verification

- `uv run pytest`: 1002 passed, 1 skipped in 73.97 seconds.
- S6-09 and S6-10 focused tests: 18 passed.
- `uv run python -m ruff check .`: PASS.
- `uv run python -m ruff format --check .`: PASS; 377 files already formatted.
- `uv run mypy`: PASS over 186 source files.
- `uv run python tools/check_controlled_docs.py`: `DOC=PASS version=1.65 files=4 gates=7 ascii=true`.
- `git diff --check`: PASS.

Attack coverage rejects missing authority records, revoked decisions, and a substituted decision
even when request fields and self-generated hashes are internally consistent. The publisher call
count remains zero for each denial.

## Source hashes

- `publication.py`: `2b31b10e25c0cf2373c689d83a41cb2b801760efe49ce18bdd5a238e6ed24810`
- `test_publication.py`: `3e0b15e0fa686d51e6a2c0767e6968118661a1dc6345d23d5e71fc2ef8b2303c`

## Remaining blockers

This closes the local code defect only. S6-10 remains blocked by an approved durable authority
adapter, current identity and permission revalidation, a sealed S6-09 candidate, TG-06 PASS,
production publisher credentials, live deployment, and post-publication smoke evidence.
