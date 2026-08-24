# S2-07 Cache Service Evidence

Status: PASS for the isolated local task profile; TG-02 and live PostgreSQL are not claimed.

- Sixteen dedicated cache tests and affected migration tests passed.
- All 379 repository tests completed with one known Windows file-name skip.
- `DOC=PASS version=1.34 files=4 gates=7 ascii=true`.
- Final S2 regression: all 413 tests completed with one known Windows file-name skip; DOC 1.35,
  Ruff, format, strict mypy, deterministic generation, dependency audit, and diff checks passed.
- Five classes, TTLs, integrity, stale rejection, bypass, metrics, poisoning denial, refresh, unsafe
  data and side effects, semantic restrictions, forced RLS, and rollback are covered.
