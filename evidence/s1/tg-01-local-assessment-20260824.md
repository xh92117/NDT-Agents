# TG-01 Local Assessment

Status: BLOCKED. The local automated subset passes, but this is not phase-gate evidence.

## Candidate identity

- Run ID: `TG-01-LOCAL-20260824-01`
- Source, migration, test, and locked-configuration SHA-256:
  `3317a625876bd727334cb6fb39abd301e98984cc121108381ffd877957669074`
- Workspace: Git repository without an immutable commit or CI build identifier.
- Environment: local Windows, CPython 3.12.13, deterministic in-memory adapters, and offline
  PostgreSQL DDL compilation.

## Local automated result

```text
uv run ruff format --check <changed S1 files>
uv run ruff check .
uv run mypy
uv run python tools/check_controlled_docs.py
uv run pytest -q
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 uv run python -X utf8 -m pip_audit --local --progress-spinner off
uv run python tools/generate_sbom.py
```

- All 215 repository tests passed.
- The local mappings for `UNIT-CORE`, `INT-ORCH`, `SEC-TENANT`, `RES-CHECKPOINT`, `BUDGET`,
  `OBS-AUDIT`, `SEC-PLATFORM`, `UNIT-TOOLREG`, and `INT-APPROVAL` passed.
- All six PostgreSQL migrations compile forward and backward. Forced RLS and append-only triggers
  are asserted for audit, approval, and review-recovery journals.
- Ruff lint, changed-file format, strict mypy, and DOC 1.21 passed.
- Dependency audit found no known vulnerabilities.
- The deterministic 87-component SBOM has SHA-256
  `9994b8c2b40ea3a51dc4977889688a69cc4271c2e795755f3387d9821a97f7dc`.
- S1-01 through S1-13 are `DONE`. The internal R-012 review-recovery gap is closed.

## Blocking gate evidence

TG-01 remains `BLOCKED` for the following non-local evidence:

- an immutable commit or CI-produced build and remote CI results for that exact candidate;
- approved and live OIDC, PostgreSQL/pgvector, Redis, and object-storage integration, including
  non-BYPASSRLS roles, concurrency, restart, revocation, and isolation probes;
- approved Vault or equivalent secret service, KMS or HSM, certificates, trust stores, encrypted
  endpoints, rotation, revocation, and recovery evidence;
- an approved OTLP endpoint and collector with live audit persistence, retention, sampling, and
  failure-mode evidence;
- accountable approval of the security, retention, SLO, SBOM, and third-party license baselines;
- revalidation of exact dependency, policy, provider, and build hashes after those decisions.

These blockers are tracked by R-005, R-007, and R-010. Production deployment and S2 phase entry are
not authorized by this local result.
