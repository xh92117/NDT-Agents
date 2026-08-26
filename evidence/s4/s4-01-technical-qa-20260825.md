# S4-01 Technical QA local evidence

## Scope

- Task: `S4-01`
- Branch: `codex/s4-professional-capabilities`
- Environment: local Windows, CPython 3.12.13, uv 0.11.20
- Runtime: deterministic S3-07 retrieval and in-memory exact-scope index
- External model, network, publication, approval, and instrument calls: zero

## Implemented boundary

- strict request, candidate, claim, support, citation, and result contracts;
- V1 method, structure, and material preflight with typed missing-input and out-of-domain stops;
- exact-scope S3-07 retrieval and revalidation of published state, roles, permission version,
  corpus/index/embedding versions, metadata, and immutable evidence identity;
- exact quote and canonical claim-to-quote support-term validation;
- rebuilt citations that bind snapshot, artifact, source, document, chunk, content hash, parser,
  normalizer, page, locator, and quote;
- stable claim and result hashes;
- explicit partial or human-required output for unrelated, stale, absent, critical, or formal claims;
- versioned product Skill and prompt assets.

## Commands and results

```text
uv run pytest tests/professional/test_technical_qa.py tests/knowledge/test_retrieval.py tests/orchestration/test_review.py tests/identity
62 passed in 1.55s

uv run pytest --collect-only -q tests/professional/test_technical_qa.py
12 tests collected

uv run ruff check src tools tests
All checks passed

uv run ruff format --check src tools tests
134 files already formatted

uv run mypy
Success: no issues found in 134 source files

uv run python tools/check_controlled_docs.py
DOC=PASS version=1.45 files=4 gates=7 ascii=true

git diff --check
PASS
```

## Result

The local `S4-01` TASK profile passes. The Technical QA boundary rejects missing applicability,
out-of-domain input, absent candidates, unrelated evidence, stale or non-published evidence,
unsupported critical claims, and unapproved formal conclusions without a user-delivery bypass.

## Remaining gate blockers

This evidence does not satisfy `TG-04`. The technical QA benchmark remains synthetic and marked
`PENDING_DOMAIN_EXPERT_GOLD`. Licensed standards, real calibrated six-method data, qualified expert
answers, independent adjudication, approved rubrics, production retrieval infrastructure, and
protected immutable CI evidence remain required under R-008 and R-009.
