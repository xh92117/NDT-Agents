# S1-01 API Scaffold Local Evidence

**Run ID:** S1-01-TASK-20260821-01  
**Task:** S1-01  
**Environment:** local Windows, isolated synthetic test environment  
**Result:** PASS for the isolated task; not phase-gate or production-approval evidence

## Candidate identity

- Workspace state: Git repository without an immutable commit.
- Python: CPython 3.12.13.
- uv: 0.11.20, build `9252ba6b5`.
- Runtime API contract: 1.0.0.
- Controlled-document version: 1.6.
- Configuration SHA-256: `0a14246cc5fb04a7c42f9c8041c338f1ef32c7c49a1544c7f52af6052defb959`.
- `uv.lock` SHA-256: `6c392de698c2084f37b57ff65ab8131556f9a3e83d1a00a8536bec4928683d62`.
- SBOM SHA-256: `8acb03c6abfecb9b0021b47f7e75527466fca969be73cd5606ab2dbddc6f00d9`.
- Locked runtime additions: FastAPI 0.141.1 and Uvicorn 0.52.4.
- Locked test-client addition: HTTPX2 2.12.0.
- SBOM inventory: 72 components; every component remains `PENDING_HUMAN_REVIEW` in the license
  decision inventory.

The configuration hash is SHA-256 over a sorted manifest of individual file hashes for
`pyproject.toml`, `uv.lock`, the Runtime API V1 document, the runtime source package, and the
runtime tests.

## Reproducible task profile

Started at `2026-08-21T22:52:31.0353683+08:00` and ended at
`2026-08-21T22:52:38.5014627+08:00`.

```text
uv run pytest tests/runtime tests/contracts tests/baseline/test_sbom.py
uv run ruff check src tools tests
uv run mypy
uv run python tools/check_controlled_docs.py
$env:PYTHONUTF8='1'
uv run pip-audit --local --progress-spinner off
```

Results:

- task tests: 39 passed in 0.71 seconds;
- Ruff: passed;
- strict mypy: passed across 24 source files;
- DOC: passed for four version 1.6 controlled documents and seven gates;
- dependency audit: no known vulnerabilities found.

The immediately preceding complete QUICK run also passed 62 tests in 1.12 seconds, Ruff, strict
mypy, DOC, and the same dependency audit.

## Acceptance evidence

- The application factory was created while socket connection attempts were denied; creation made
  no external call.
- Liveness and readiness returned strict schema-version 1.0.0 payloads.
- Startup settings are immutable and accept only the documented `NDT_` allowlist.
- Unknown, invalid, and unsafe settings returned stable non-disclosing configuration codes.
- API docs were disabled by default and rejected for production configuration.
- Safe incoming request IDs were correlated; malformed values were replaced.
- JSON log messages and structured string fields redacted credential patterns.
- An injected unhandled exception returned typed `INTERNAL_ERROR` output without exception detail.
- Health and error responses carried no-store, request-correlation, and content-type hardening
  headers.
- No database, cache, object-store, model, provider credential, or network service was configured.

## Limitations and next action

This is local isolated S1 evidence only. TG-00 remains blocked by R-001, R-003, R-005, and R-007
through R-009. R-010 requires revalidation of the exact runtime, policy, dependency, license, and
build hashes after those decisions close. Storage readiness begins in S1-02. This run does not
satisfy TG-00, TG-01, production security approval, or commercial license approval.
