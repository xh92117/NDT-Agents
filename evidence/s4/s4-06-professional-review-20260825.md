# S4-06 professional review local evidence

## Scope

- Task: `S4-06`
- Branch: `codex/s4-professional-capabilities`
- Environment: local Windows, CPython 3.12.13, uv 0.11.20
- Runtime: deterministic S4-01 through S4-05 outputs plus the S1-09 review contracts
- External model, tool, network, correction, approval, publication, and user-delivery calls: zero

## Implemented boundary

- five stable versioned checklists for Technical QA, inspection plan, data processing, method
  validation, and inspection report;
- exact scope/task/run/type result envelopes with payload and envelope hashes;
- strict result rehydration and internal hash revalidation;
- per-result status, issue, citation, traceability, review/approval/formal, human, and side-effect
  checks;
- deterministic PASS, REVISE, HUMAN_REQUIRED, and FAILED classification;
- cross-result QA-to-plan claim/chunk, plan-to-report hash, processing-to-report source/run/version/
  output/observation, and method-to-processing request/candidate validation;
- duplicate, stale, changed, cross-scope, and relationship conflict denial;
- hash-bound zero-call assessment and strict S1-09 `ReviewResult` adapter;
- unchanged S1-09 responsibility for correction, re-review, recovery, and Main-only aggregation.

## Commands and results

```text
uv run pytest tests/professional tests/orchestration/test_review.py tests/identity
103 passed in 1.75s

uv run pytest --collect-only -q tests/professional/test_professional_review.py
9 tests collected

uv run ruff check src tools tests
All checks passed

uv run ruff format --check src tools tests
146 files already formatted

uv run mypy
Success: no issues found in 146 source files

uv run python tools/check_controlled_docs.py
DOC=PASS version=1.45 files=4 gates=7 ascii=true

git diff --check
PASS
```

## Result

The local `S4-06` TASK profile passes. Clean professional results and the complete interacting
chain pass deterministically. Payload tampering, scope/task/run mismatch, human-required output,
plan/report conflict, processing/report conflict, and method/processing conflict cannot become
aggregation-ready. The adapter returns an exact S1-09 target run/hash and reviewer version.

## Remaining gate blockers

The checklists establish deterministic contract consistency, not expert technical correctness.
Licensed standards, real calibrated-device evidence, adjudicated QA/plan/report gold answers,
qualified reviewer evidence, measured correction quality, and immutable CI remain required under
R-008 and R-009 before `TG-04` can pass.
