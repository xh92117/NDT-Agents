# S2-06 Memory Restore Evidence

Status: PASS for the isolated local task profile; TG-02 and live PostgreSQL are not claimed.

- Nine dedicated restore tests and affected migration tests passed.
- All 363 repository tests completed with one known Windows file-name skip.
- `DOC=PASS version=1.34 files=4 gates=7 ascii=true`.
- Final S2 regression: all 413 tests completed with one known Windows file-name skip; DOC 1.35,
  Ruff, format, strict mypy, deterministic generation, dependency audit, and diff checks passed.
- Direct and intent preview, thresholds, ambiguity, exact scope, versions, artifacts, injection
  limits, tamper rejection, terminal decisions, and new-branch-only restore are covered.
