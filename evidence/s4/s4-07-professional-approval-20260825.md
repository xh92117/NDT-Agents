# S4-07 professional approval local evidence

## Scope

- Task: `S4-07`
- Branch: `codex/s4-professional-capabilities`
- Environment: local Windows, CPython 3.12.13, uv 0.11.20
- Runtime: deterministic S4-02/S4-03/S4-06 results plus actual S1-09 and S1-13 workflows
- External model, tool, network, publication, mutation, and user-delivery calls: zero

## Implemented boundary

- professional S1-13 policy with separate plan, report, and critical-finding qualified roles;
- strict clean-plan and clean preliminary-report preconditions;
- exact PASS S4-06 assessment and aggregation-ready S1-09 manifest binding;
- critical-report denial from the ordinary report path;
- exact critical-finding IDs and statement, observation, calculation, plan-basis, limitation, and
  evidence hashes;
- exact S4-06 and S1-09 HUMAN_REQUIRED pause for critical-finding confirmation;
- canonical scope/task/action/target/result/content/review/finding subject hash;
- hash-only generic approval preview and rehydratable professional binding;
- core S1-13 role, separation-of-duty, scope, hash, terminal, event, audit, and resume enforcement;
- idempotent exact creation/decision/resume and denial of a second resume grant;
- explicit non-formal boundary: plan approval does not approve reports and report approval does not
  change formal-release state.

## Commands and results

```text
uv run pytest tests/professional tests/approval tests/orchestration/test_review.py tests/identity
131 passed in 1.93s

uv run pytest --collect-only -q tests/professional/test_professional_approval.py
9 tests collected

uv run ruff check src tools tests
All checks passed

uv run ruff format --check src tools tests
148 files already formatted

uv run mypy
Success: no issues found in 148 source files

uv run python tools/check_controlled_docs.py
DOC=PASS version=1.45 files=4 gates=7 ascii=true

git diff --check
PASS
```

## Result

The local `S4-07` TASK profile passes. Clean plan and report candidates pause for the correct
qualified role. Critical findings bind the exact human-required evidence. Wrong role/scope/hash,
stale review, tampered result, rejection, changed subject, ordinary critical-report approval, and
resume replay cannot continue the protected workflow.

## Remaining gate blockers

Local actors and repositories are deterministic test identities and in-memory journals. The
formal-report/accreditation boundary remains unapproved under R-004. Accountable qualified owners,
live identity and durable approval storage, expert review/gold evidence, real calibrated data, and
immutable CI remain required under R-008 and R-009 before `TG-04` can pass.
