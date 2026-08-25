# S3-05 Parser Fallback Evidence

## Result

S3-05 passes its local TASK profile. It adds deterministic parser quality decisions, a fixed
three-stage fallback chain, page-level merge lineage, and explicit manual review after exhaustion.
The independent OCR engine is a registered provider-neutral port tested with a deterministic fake;
no production OCR engine or frozen scanned corpus is claimed.

## Candidate

- Branch: `codex/s3-knowledge-pipeline`.
- Parent: `248d1f9`.
- Configuration SHA-256: `7a4c22f9e1d9d4c63c92756dc1954d2c777bb4dfc623dc303613210fd81cfd94`.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.
- Run: `S3-05-TASK-20260825-01`.

## Verified behavior

- The quality gate measures expected page coverage, meaningful characters per non-drawing page,
  corrupted-character ratio, and expected table and formula coverage.
- Drawing pages are explicit expectation data and do not fail text density.
- The fixed sequence invokes MinerU text, MinerU OCR, and independent OCR at most once each.
- Every stage reuses exact scope, artifact, source path, size, MIME, and SHA-256.
- Failed pages are replaced from the next valid document; earlier good pages remain, and merge
  lineage hashes both source documents and the replacement page list.
- Every selected or merged result passes the same quality gate.
- Attempts preserve parser, version, method, document hash, quality evidence, or a typed error.
- Malformed independent pages, timeout, source change, scope mismatch, parser failure, and all-stage
  low quality produce manual review without a publishable document.
- The physical call count never exceeds three and no stage repeats.

## Commands and results

```text
uv run pytest tests/knowledge/test_fallback.py tests/knowledge/test_mineru.py
```

Result: 24 passed, comprising ten S3-05 cases and 14 inherited MinerU cases.

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python tools/check_controlled_docs.py
git diff --check
```

Result: 476 passed and one known platform skip; Ruff passed; 236 files were formatted; strict mypy
passed over 116 source files; DOC 1.39 and diff checks passed.

## Remaining boundary

S3-06 owns canonical clauses, tables, formulas, figures, and metadata. Real MinerU and independent
OCR runtimes, frozen scanned documents, throughput, and quality thresholds remain TG-03 work.
