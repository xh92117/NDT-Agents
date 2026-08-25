# S3-08 Standard Applicability Evidence

## Result

S3-08 passes its local TASK profile. It provides immutable typed standard versions, validated
replacement lineage, explicit rights policy, and pre-score applicability admission.

## Candidate

- Branch: `codex/s3-knowledge-pipeline`.
- Parent: `4f501eb`.
- Configuration SHA-256: `d23e2f91828869b09803c3cfde2d34fd00bc0d20c79963a80d2dea04073c6af2`.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.
- Run: `S3-08-TASK-20260825-01`.

## Verified behavior

- The standard version hash binds exact scope, standard lineage, edition, dates, regions,
  lifecycle, rights, evidence, roles, and replacements; payload tampering fails validation.
- Dates must be ordered; regions, roles, and replacements must be canonical; `GLOBAL` is exclusive.
- Usable public-domain, licensed, and owner-authorized rights require evidence. Unknown, expired,
  and prohibited rights are explicitly denied.
- Catalog registration is immutable and idempotent only for an equal payload.
- Replacement targets must exist in the same exact scope and standard lineage; cross-scope,
  cross-lineage, and cyclic links fail.
- Applicability checks scope, lifecycle, effective/expiry date, region, type, rights, roles, and
  supersession with stable reason codes.
- Current and authorized restricted standards can pass; draft, replaced, withdrawn, future,
  expired, wrong-region, wrong-type, role-denied, rights-denied, and superseded standards cannot.
- The retrieval wrapper rejects missing or unregistered standard bindings and non-published index
  snapshots, then copies only applicable snapshots into the repository used for hybrid scoring.
- No model, network, approval, publication, side-effect, or retry call occurs.

## Commands and results

```text
uv run pytest tests/knowledge/test_standards.py tests/knowledge/test_retrieval.py
```

Result: 44 passed, comprising 27 S3-08 cases and 17 inherited retrieval cases.

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python tools/check_controlled_docs.py
git diff --check
```

Result: 528 passed and one known platform skip; Ruff passed; 248 files were formatted; strict mypy
passed over 122 source files; DOC 1.42 passed. The first diff check identified the three newly
edited Markdown hard-break spaces; they were removed and the bounded diff check passed.

## Remaining boundary

S3-09 owns candidate validation, independent review, human approval, atomic publication,
withdrawal, supersession, and rollback. Licensed standard content, accountable rights decisions,
live persistence/vector infrastructure, and immutable CI remain TG-03 requirements.
