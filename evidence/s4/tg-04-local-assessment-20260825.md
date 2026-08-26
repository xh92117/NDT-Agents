# TG-04 local assessment

## Scope

- Phase: `S4`
- Tasks: `S4-01` through `S4-07`
- Branch: `codex/s4-professional-capabilities`
- Environment: local Windows, CPython 3.12.13, uv 0.11.20
- Candidate type: provider-neutral deterministic local implementation
- Immutable release or pull-request build: unavailable

## Implemented capabilities

- Technical QA with exact published-evidence citations, applicability, limitations, uncertainty,
  and typed critical or formal-conclusion escalation.
- Inspection planning with a versioned 17-section template, ontology and unit validation, explicit
  unresolved inputs, and review and approval boundaries.
- Inspection reporting with a versioned 15-section template, exact source and plan traceability,
  deterministic Decimal calculations, revision control, and a non-formal conclusion boundary.
- Source-data processing control with exact source, calibration, method, parameter, output, quality,
  budget, provenance, and report-eligibility bindings.
- Six method Skill skeletons for UT, GPR, IE, RT, AE, and MV with stable typed applicability,
  metadata, calibration, input, parameter, output, limitation, safety, and provenance contracts.
- Per-result and cross-result professional review integrated through the S1-09 review workflow.
- Plan, report, and critical-finding human approval boundaries integrated through the S1-13
  approval and exact-resume workflow.

## Commands and results

```text
uv run pytest tests/professional tests/orchestration/test_review.py tests/approval tests/identity tests/baseline/test_fixture_catalog.py
140 passed in 2.47s

uv run pytest -rs
618 passed, 1 skipped in 21.28s

skip: tests/tools/test_file_gateway.py:177
reason: control-character filenames are unavailable on this file system

uv run ruff check src tools tests
All checks passed

uv run ruff format --check src tools tests
149 files already formatted

uv run mypy
Success: no issues found in 149 source files

uv run python tools/check_controlled_docs.py
DOC=PASS version=1.45 files=4 gates=7 ascii=true

git diff --check
PASS
```

The schema, fixture, benchmark, and SBOM generators were run against before and after SHA-256
manifests for their tracked output roots. All four reproduced exactly:

```text
GENERATOR_DRIFT=ZERO generators=4
```

The required code graph was fully refreshed and then incrementally synchronized after the final
generator-coverage test. Its verified state is:

```text
branch=codex/s4-professional-capabilities
head_matches_build=true
files=145
nodes=2211
edges=19387
tests=392
tested_by_edges=3183
direct_generate_templates_tests=1
generator_test_gaps=0
```

## Assessment

All seven S4 task deliverables and their local task profiles are complete. The local assigned-group
profile, complete repository regression, deterministic generator checks, static checks, controlled
documentation checks, and graph coverage checks pass.

`TG-04` is `BLOCKED`, not passed. Local synthetic and deterministic checks do not demonstrate the
required expert correctness, real-device validity, accountable approval, or immutable build state.

## Blocking evidence

- R-004: the formal-report and accreditation responsibility boundary lacks accountable Product and
  Quality Owner approval.
- R-008: licensed standards and de-identified calibrated real-device samples for all six methods are
  unavailable.
- R-009: authorized expert gold answers, adjudication rubrics, independent review, and measured
  quality evidence for QA, plans, and reports are unavailable.
- Qualified accountable plan, report, and critical-finding approvers have not been established in a
  live identity system with durable approval storage.
- The exact S4 candidate has not been committed, built, and revalidated in protected immutable CI.
- TG-03 remains blocked; this local S4 work neither promotes TG-03 nor turns its synthetic retrieval
  and knowledge evidence into production evidence.

## Required next action

Close R-004, R-008, and R-009; provision qualified approvers, live identity, and durable approval
storage; commit the exact candidate; then rerun the full TG-04 groups against the approved licensed
corpus, calibrated real-device samples, adjudicated expert gold set, and immutable CI artifact.
