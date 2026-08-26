# S4-05 method-Skill pack local evidence

## Scope

- Task: `S4-05`
- Branch: `codex/s4-professional-capabilities`
- Environment: local Windows, CPython 3.12.13, uv 0.11.20
- Runtime: deterministic S4-04 requests/candidates and read-only six-method registry
- External algorithm, instrument, model, network, approval, publication, and retry calls: zero

## Implemented boundary

- exact ordered V1 method registry for AE, GPR, IE, MV, RT, and UT;
- stable version and canonical definition hash for every method skeleton;
- ontology-bounded structures and materials;
- method-specific acquisition settings, calibration kinds, input dimensions and units, processing
  parameter names, output observation families, limitations, safety notes, and origin policy;
- exact request/candidate scope and method binding;
- deterministic missing-metadata, applicability, calibration, input, parameter, origin, successful-
  output, and observation-family rejection;
- stable definition, request, candidate, and result hashes;
- explicit simulated/laboratory/production provenance and production-report policy;
- mandatory review and literal zero side-effect counters;
- six independent versioned Skill files plus one shared control prompt and contract.

## Commands and results

```text
uv run pytest tests/professional/test_method_skills.py tests/professional/test_data_processing.py tests/orchestration/test_review.py tests/identity
57 passed in 1.56s

uv run pytest --collect-only -q tests/professional/test_method_skills.py
11 tests collected

uv run ruff check src tools tests
All checks passed

uv run ruff format --check src tools tests
144 files already formatted

uv run mypy
Success: no issues found in 144 source files

uv run python tools/check_controlled_docs.py
DOC=PASS version=1.45 files=4 gates=7 ascii=true

git diff --check
PASS
```

## Result

The local `S4-05` TASK profile passes. An omitted or duplicate method, unknown method, cross-scope
candidate, changed method, missing metadata/calibration/parameter, unsupported applicability,
incompatible input, unregistered observation, empty successful output, or non-production source
cannot obtain production-report permission from the method registry.

## Remaining gate blockers

These are control skeletons, not implemented algorithms, standards, procedures, acceptance
criteria, or expert interpretations. Authorized calibrated real-device samples, production
adapters, licensed standards, qualified-expert gold answers, accountable review, and immutable CI
remain required under R-008 and R-009 before `TG-04` can pass.
