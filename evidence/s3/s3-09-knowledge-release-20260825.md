# S3-09 Knowledge Release Evidence

## Result

S3-09 passes its local TASK profile. It provides a hash-bound incremental candidate, deterministic
validation, actual S1-09 independent professional review, S1-13 human approval, atomic publication,
approved withdrawal, and approved rollback with preserved history.

## Candidate

- Branch: `codex/s3-knowledge-pipeline`.
- Parent: `c4951b5`.
- Configuration SHA-256: `81182fe0b1b73aae51e3b6f5a97455e9e91066b0b90fd5291077a6aefee33de3`.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.
- Run: `S3-09-TASK-20260825-01`.

## Verified behavior

- Candidate SHA-256 binds exact scope, task/request, versions, base publication, draft snapshots,
  and deterministic added/updated/removed document and chunk diff.
- Exact creation is idempotent; conflict, cross-scope input, and stale base fail before storage.
- Validation records `DRAFT`, `VALIDATING`, `REVIEW_REQUIRED`, or typed `FAILED` transitions and
  checks status, versions, uniqueness, standard registration, lifecycle, rights, evidence, roles,
  supersession, and current base.
- The test workflow executes an actual professional child and S1-09 `ReviewWorkflow`; publication
  rejects stale candidate bindings and non-approved review results.
- S1-13 `KNOWLEDGE` checkpoints separately bind publication, withdrawal, and rollback actions.
  Unapproved resume is rejected by the shared approval service.
- First publication exposes only published snapshots. Incremental publication supersedes the prior
  publication, preserves it, records changed and removed documents, and updates visibility.
- An injected pre-commit failure leaves the index, head, publication, and candidate unchanged; the
  same approved resume ID succeeds on exact retry.
- Withdrawal requires its own approval, marks current snapshots withdrawn, and clears the head.
- Rollback requires its own approval, creates a new publication ID from preserved prior snapshots,
  supersedes the current publication, and retains all three history records.
- Migration `0011_s3_knowledge_release` creates forced-RLS event, publication, and corpus-head tables
  and an append-only event trigger; offline upgrade and downgrade compile.

## Commands and results

```text
uv run pytest tests/knowledge/test_release.py tests/knowledge/test_standards.py \
  tests/knowledge/test_retrieval.py tests/orchestration/test_review.py \
  tests/approval/test_approval_service.py
uv run pytest tests/storage/test_storage_services.py tests/knowledge/test_release.py
```

Result: 96 affected review, approval, retrieval, policy, and release cases passed; the storage and
release migration run passed 18 cases.

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python tools/check_controlled_docs.py
git diff --check
```

Result: 538 passed and one known platform skip; Ruff passed; 253 files were formatted; strict mypy
passed over 124 source files; DOC 1.43 and diff checks passed.

## Remaining boundary

The local repository and offline PostgreSQL DDL prove deterministic behavior but are not a live
multi-session PostgreSQL/vector transaction. Licensed standard content, accountable human rights
and publication approval, real MinerU/OCR, live index infrastructure, immutable CI, and the exact
TG-03 candidate remain phase-gate requirements.

Post-task Code Graph review produced follow-up hardening commit `a500890`: approval checkpoints now
must match the complete release scope, duplicate candidate snapshot IDs fail validation, and the
release event/publication primary keys include user and permission scope. The exact 18 affected
tests and the complete 539-test collection passed; the local TG-03 assessment records this final
code candidate separately from the original task configuration hash.
