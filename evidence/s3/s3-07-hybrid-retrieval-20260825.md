# S3-07 Hybrid Retrieval Evidence

## Result

S3-07 passes its local TASK profile. It builds immutable candidate snapshots and retrieves only
exact-scope, published, version-compatible records through bounded hybrid ranking.

## Candidate

- Branch: `codex/s3-knowledge-pipeline`.
- Parent: `b9f49b5`.
- Configuration SHA-256: `44da1cac2561349fdd0e08e1e9d87d4f8cb01c8f79cf467c42fddd8ff8417905`.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.
- Run: `S3-07-TASK-20260825-01`.

## Verified behavior

- Every canonical chunk becomes one immutable record with exact source, parser, normalizer,
  document, artifact, locator, hash, corpus, index, role, metadata, and embedding versions.
- The repository identity includes tenant, project, user, role tuple, permission version, corpus,
  index, and document, preventing cross-scope replacement.
- Exact scope, publication state, versions, roles, and metadata are filtered before any scoring.
- Draft, superseded, withdrawn, stale, unauthorized, and cross-scope records are absent from
  candidates and hits.
- Latin words, decimal numbers, Chinese characters, and Chinese bigrams feed BM25 and one explicit
  fixed-dimension embedding port.
- Cosine rank, reciprocal-rank fusion, deterministic rerank, and identity tie-breaking are stable.
- Candidate count is at most 100, top-k is at most ten, and the default is six.
- Every hit returns exact text and a complete, hash-bound citation chain.
- The six-case frozen synthetic set achieved Recall@6 1.00, nDCG@10 1.00, citation correctness
  1.00, and traceability 1.00.
- The deterministic hash embedding is explicitly limited to offline development and testing.

## Commands and results

```text
uv run pytest tests/knowledge/test_retrieval.py
```

Result: 17 passed, including scope parameterization and frozen metric assertions.

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python tools/check_controlled_docs.py
git diff --check
```

Result: 501 passed and one known platform skip; Ruff passed; 244 files were formatted; strict mypy
passed over 120 source files; DOC 1.41 and diff checks passed.

## Remaining boundary

S3-08 owns typed standard applicability policy. S3-09 owns validation, independent review, human
approval, atomic publication, withdrawal, and rollback. Licensed standards, an approved production
embedding, live database/vector infrastructure, and immutable CI remain TG-03 requirements.
