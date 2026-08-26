# S4-04 data-processing-control local evidence

## Scope

- Task: `S4-04`
- Branch: `codex/s4-professional-capabilities`
- Environment: local Windows, CPython 3.12.13, uv 0.11.20
- Runtime: deterministic source-data processing control and S4-03 report-evidence bridge
- External model, network, approval, publication, algorithm, and instrument calls: zero

## Implemented boundary

- strict source manifest, processing request, processing candidate, and result contracts;
- exact tenant, project, user, permission, source artifact, dataset, method, structure,
  component, location, coordinate, channel, sample-rate, unit, acquisition, instrument,
  calibration, operator, adapter, parser, algorithm, schema, parameter, and quality binding;
- separate stable source, dataset, parameter, candidate output, and result hashes;
- bounded one-attempt and one-adapter-call accounting with zero model, network, and physical calls;
- calibration, method, unit, dimension, observation, figure, quality, timeout, and output checks;
- explicit simulated, laboratory, and production provenance;
- typed complete, partial, and failed results preserving cause, impact, evidence, and next action;
- production-only report eligibility and deterministic conversion to S4-03 evidence;
- immutable review-required output with no retry, conclusion, approval, or publication behavior.

## Commands and results

```text
uv run pytest tests/professional/test_data_processing.py tests/professional/test_inspection_report.py tests/orchestration/test_review.py tests/orchestration/test_budget.py tests/identity
88 passed in 1.75s

uv run pytest --collect-only -q tests/professional/test_data_processing.py
13 tests collected

uv run ruff check src tools tests
All checks passed

uv run ruff format --check src tools tests
142 files already formatted

uv run mypy
Success: no issues found in 142 source files

uv run python tools/check_controlled_docs.py
DOC=PASS version=1.45 files=4 gates=7 ascii=true

git diff --check
PASS
```

## Result

The local `S4-04` TASK profile passes. Cross-scope data, stale calibration, method or unit mismatch,
unbounded parameters, incomplete traceability, low quality, hidden retry, excess budget, external
action, malformed partial failure, and non-production provenance cannot become report-eligible.

## Remaining gate blockers

This evidence does not satisfy `TG-04`. The source-data cases are deterministic synthetic fixtures.
Authorized six-method real-device samples, calibration and de-identification provenance, expert
processing gold answers, production adapters, accountable review, and immutable CI evidence remain
required under R-008 and R-009.
