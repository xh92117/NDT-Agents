# S3-06 Canonical Normalization Evidence

## Result

S3-06 passes its local TASK profile. It transforms only quality-passed parsed documents into a
deterministic canonical element and chunk model. No external call occurs.

## Candidate

- Branch: `codex/s3-knowledge-pipeline`.
- Parent: `86c3339`.
- Configuration SHA-256: `dd00e818ce04124338b58366ed655e0aafa48b67a58c2a790cec530c4326e1df`.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.
- Run: `S3-06-TASK-20260825-01`.

## Verified behavior

- Input must be S3-05 `READY`, final quality `PASS`, and exact scope.
- Parsed block orders must be unique and contiguous, and every block maps exactly once.
- Headings, numeric clauses, paragraphs, tables, formulas, figures, lists, code, and auxiliary
  content retain source order, page, coordinates, section path, locator, exact text, and hashes.
- Markdown and bounded simple HTML tables become rectangular cells without executing markup.
- Chinese text, formulas, figure paths, numeric constraints, and units remain exact.
- Metadata keys and values are bounded, sorted, and treated as untrusted data.
- Identical input reproduces document, element, and chunk identities; metadata change changes the
  document hash.
- Chunks are no more than 1,200 characters; concatenating a long element's chunks exactly recovers
  its text.
- Non-ready, cross-scope, non-contiguous, malformed-table, and invalid-metadata inputs fail with
  typed next actions.
- Physical calls are fixed at zero.

## Commands and results

```text
uv run pytest tests/knowledge/test_normalization.py tests/knowledge/test_fallback.py
```

Result: 18 passed, comprising eight S3-06 cases and ten inherited fallback cases.

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python tools/check_controlled_docs.py
git diff --check
```

Result: 484 passed and one known platform skip; Ruff passed; 240 files were formatted; strict mypy
passed over 118 source files; DOC 1.40 and diff checks passed.

## Remaining boundary

S3-07 owns scoped full-text/vector retrieval and reranking. The full frozen normalization corpus and
immutable PR CI remain TG-03 work.
