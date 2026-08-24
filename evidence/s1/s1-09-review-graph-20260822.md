# S1-09 Review Graph Local Evidence

**Run ID:** S1-09-TASK-20260822-01  
**Task:** S1-09  
**Environment:** local Windows with deterministic child, reviewer, and corrector executors  
**Result:** PASS for isolated review topology and bounded correction

## Candidate identity

- Workspace state: Git repository without an immutable commit.
- Review Graph contract: 1.0.0.
- Public ReviewResult contract: 1.0.0.
- Controlled-document version: 1.14.
- Configuration SHA-256: `43edebd8983a84917625271e03e4597e357dbd0499ba382090267b8cc61e3605`.
- Python: CPython 3.12.13.
- uv: 0.11.20, build `9252ba6b5`.

The configuration hash covers sorted path-and-file hashes for the Review Graph and child-subgraph
contracts, all eleven orchestration source files, and all seven orchestration test files, for 20
files total.

## Reproducible task profile

Started at `2026-08-22T00:45:19.5722100+08:00` and ended at
`2026-08-22T00:45:27.7161923+08:00` before the separate dependency audit completed.

```text
uv run pytest tests/orchestration tests/contracts tests/identity -o addopts='' -ra
uv run pytest -o addopts='' -ra
uv run ruff check src tools tests migrations
uv run ruff format --check src/ndt_agents/orchestration/__init__.py \
  src/ndt_agents/orchestration/review.py tests/orchestration/test_review.py
uv run mypy
uv run python tools/check_controlled_docs.py
PYTHONUTF8=1 uv run pip-audit --local --progress-spinner off
```

Results:

- task tests: 120 passed in 2.25 seconds;
- complete tests: 163 passed in 3.22 seconds;
- S1-09 Review Graph tests: 19 passed;
- Ruff lint: passed;
- Ruff format check: three changed Python files passed;
- strict mypy: passed across 56 source files;
- DOC: passed for four version 1.14 controlled documents and seven gates;
- dependency audit: no known vulnerabilities found.

## Acceptance evidence

- A General schedule was rejected by Review Graph before any reviewer call. The Main aggregation
  gate accepted its verified direct child outcome instead.
- Every completed professional result entered with `review_required=true` and
  `aggregation_ready=false`. Tampered context manifests and non-review-pending shapes were denied.
- The immutable reviewer context contained complete identity scope, exact current result evidence,
  result or aggregate hashes, checklist, and registered versions. It exposed no child scratch,
  mutation tool, Main history, or user-delivery path.
- Reviewer output was strictly validated for schema, task, run, target hash, reviewer version,
  correction count, severity, and actionable findings. Extra fields and identity, hash, version, or
  correction-count changes produced typed failures.
- `PASS` enabled aggregation only after the complete required review path. `CONFLICT`,
  `HUMAN_REQUIRED`, and `FAILED` preserved findings and blocked all workflow aggregation.
- `REVISE` invoked only the responsible child corrector with one minimal targeted context. It
  rejected malformed, cross-scope, wrong-identity, unsuccessful, timed-out, and byte-equivalent
  unchanged correction results.
- A repaired result was re-reviewed while unchanged passed results were not rerun. Review and
  correction rounds used the exact task guard, and active exhaustion stopped before another
  reviewer or corrector call.
- Dependent professional results received individual reviews first and a cross-result review only
  after all individual passes. Explicit cross-review bypass was denied.
- Independent results skipped cross review by default and entered it when explicitly required.
- A cross-result repair named `assignment:beta`; only beta was corrected and re-reviewed, then the
  complete current result set was cross-reviewed again. Alpha was neither corrected nor re-reviewed.
- The Main aggregation gate rejected raw professional output and every unresolved workflow. It
  accepted only a passing professional workflow with a validated SHA-256 review manifest.
- The manifest bound all current result hashes, per-result and cross-result histories, correction
  counts, scope, schedule, task, and terminal status. Identical bound inputs produced the same hash,
  and direct manifest tampering failed validation.

## Limitations and next action

Reviewer and corrector executors are provider-neutral injected ports. Later registered model and
tool adapters must apply physical call and token reservations within those ports. Domain rubrics
and measured correction-quality thresholds remain S4 work. R-010 and the external TG-00/TG-01
blockers remain open, so this evidence is not phase-gate evidence.

## 2026-08-24 R-012 corrective evidence

Configuration SHA-256:
`b569726d04ee382ba31788aa18ecf388631e2e5ebb2a971d0b5c92131afca63f`.

`RecoverableReviewWorkflow` now binds the exact schedule, isolated contexts, reviewer versions,
corrector identities, cross-review choice, scope, and initial budget telemetry to an append-only
hash chain. It persists each strict reviewer or corrector output by context SHA-256 and commits the
terminal result and review manifest before Main aggregation. Restart reconstructs the deterministic
graph while cached outputs prevent another completed physical executor call; a committed terminal
result returns without any executor call.

Fault injection passed before review, after the first completed review call in a correction path,
and after manifest commit but before Main aggregation. Conflicting input, cross-project restore,
payload tampering, sequence or previous-hash corruption, and manifest mismatch are denied. Migration
`0006_s1_review_recovery` compiles forward and backward with forced RLS and an append-only trigger.

The corrective profile passed 23 Review Graph tests, 103 affected orchestration, observability, and
storage tests, and 215 complete repository tests. Ruff, changed-file format, strict mypy, DOC 1.20,
the 87-component deterministic SBOM, migration round trip, and dependency audit passed. R-012 is
closed. A live PostgreSQL/distributed process-loss probe and immutable approved build remain TG-01
external integration work under R-010.
