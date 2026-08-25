# TG-03 Local Assessment

## Decision

The S3 local automated subset passes, and S3-01 through S3-09 are locally complete. TG-03 remains
`BLOCKED`; synthetic fakes, offline DDL, and a local Git commit cannot replace the required real
parser/OCR corpus, licensed standards, live persistence and index transaction, accountable human
approval, and immutable protected CI evidence.

## Assessed candidate

- Branch: `codex/s3-knowledge-pipeline`.
- Code commit: `a5008908c24970033f196b534b5009d853aac556`.
- Git tree: `8d291bcde6d7af76907a4d13ba0e0c7a267b10f0`.
- Tree-manifest SHA-256: `78d48e279a8bb9efd2e8d7e432b6b950beebfc34a57ec629d886455eecce980c`.
- Environment: local Windows, CPython 3.12.13, uv 0.11.20.
- Run: `TG-03-LOCAL-20260825-01`.

## Automated result

The dedicated phase command covered all knowledge tests, the Bash file gateway, approval,
independent review, and offline storage migration. It completed 201 passes with one Windows-only
skip. A subsequent Code Graph review identified the release boundary and migration as the highest
risk area. Follow-up commit `a500890` added exact approval-scope verification, duplicate snapshot
validation, and user/permission fields to release primary keys; its 18 affected release/storage
tests passed.

The exact follow-up code commit then passed:

- 538 tests with one known Windows control-character filename skip;
- Ruff lint and format over 254 files;
- strict mypy over 124 source files;
- DOC 1.43 and clean diff/status checks;
- four deterministic generators with zero drift;
- dependency audit with no known vulnerabilities after one bounded UTF-8 subprocess retry;
- frozen synthetic retrieval Recall@6, nDCG@10, citation correctness, and traceability of 1.00;
- migration `0011_s3_knowledge_release` offline upgrade and downgrade compilation.

The refreshed Code Graph contains 1,997 nodes, 17,332 edges, and 137 Python files, has no build
errors, and reports exact head match at `a5008908c249`. Its broad S3 delta risk is high because the
change crosses intake, process execution, retrieval authorization, approval, and publication. The
reported heuristic gaps include Alembic entry functions even though the offline storage suite
executes their upgrade and downgrade SQL; those heuristics are retained as review guidance rather
than promoted to test results.

## Commands

```text
uv run pytest tests/knowledge tests/tools/test_file_gateway.py \
  tests/approval/test_approval_service.py tests/orchestration/test_review.py \
  tests/storage/test_storage_services.py
uv run pytest tests/knowledge/test_release.py tests/storage/test_storage_services.py
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python tools/check_controlled_docs.py
uv run python tools/generate_schemas.py
uv run python tools/generate_fixture_catalog.py
uv run python tools/generate_benchmarks.py
uv run python tools/generate_sbom.py
uv run pip-audit
code-review-graph status --repo "D:\program flies\...\NDT Agents"
```

## Blocking evidence

TG-03 cannot pass until all of the following exist for one exact immutable candidate:

1. A pinned real MinerU runtime parses the approved born-digital and scanned frozen corpus and
   demonstrates clean-file success at least 98 percent, scanned usable text at least 95 percent,
   and approved table/formula baselines.
2. Real MinerU OCR and one independent OCR engine pass the labeled fallback, merge, timeout, and
   low-confidence corpus with recorded engine and container hashes.
3. Licensed standards and an approved rights register replace synthetic text; accountable
   Knowledge and qualified approvers sign the exact publication hashes.
4. Live PostgreSQL, full-text/vector index, and object storage prove concurrent RLS isolation,
   atomic publication/head/index updates, rollback, restart recovery, and zero stale retrieval.
5. The complete Chinese path corpus passes on the current immutable candidate with zero skip,
   including the control-character and newline filename denial available on Linux.
6. The approved production embedding and frozen retrieval corpus meet the TG-03 quality thresholds
   without synthetic-only evidence.
7. Protected CI runs every assigned TG-03 group against the exact commit/tree and publishes an
   immutable evidence artifact. Existing S3-02 remote Bash evidence predates this complete S3 tree.

No local failure was hidden or waived. S4 must not treat TG-03 as passed until these blockers close.
