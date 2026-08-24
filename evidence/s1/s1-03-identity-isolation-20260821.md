# S1-03 Identity and Isolation Local Evidence

**Run ID:** S1-03-TASK-20260821-01  
**Task:** S1-03  
**Environment:** local Windows with generated test signing key and offline PostgreSQL SQL  
**Result:** PASS for the isolated task; live identity/RLS and audit evidence pending

## Candidate identity

- Workspace state: Git repository without an immutable commit.
- Python: CPython 3.12.13.
- uv: 0.11.20, build `9252ba6b5`.
- Identity contract: 1.0.0.
- Alembic revision: `0002_s1_identity_rls`.
- Controlled-document version: 1.8.
- Configuration SHA-256: `e18285e25a5051dea2d34e5237a0fcd9d8ee3e0b26ce32365c5dde5ee80fa174`.
- `uv.lock` SHA-256: `ee2a86b8bc14ad5d91f9fd2a618f22fba01bcf979d3fd3e69ad2c7c1859b0517`.
- SBOM SHA-256: `0dcb2916495bc6d568ea93b0050ccee5ba89ffd0ad555ba6b995b3ebc8bca0dc`.
- SBOM inventory: 84 components with pending human license review.
- Locked identity addition: PyJWT 2.13.0 with Cryptography 50.0.0.

The configuration hash covers sorted hashes for dependencies, Alembic configuration, the identity
contract, identity source/tests, runtime integration, scoped PostgreSQL adapter/schema, and the RLS
migration.

## Reproducible task profile

Started at `2026-08-21T23:16:53.4571664+08:00` and ended at
`2026-08-21T23:17:03.4612215+08:00`.

```text
uv run pytest tests/identity tests/storage tests/runtime tests/contracts tests/baseline/test_sbom.py
uv run ruff check src tools tests migrations
uv run mypy
uv run python tools/check_controlled_docs.py
$env:PYTHONUTF8='1'
uv run pip-audit --local --progress-spinner off
```

Results:

- task tests: 57 passed in 1.81 seconds;
- Ruff: passed;
- strict mypy: passed across 38 source files;
- DOC: passed for four version 1.8 controlled documents and seven gates;
- dependency audit: no known vulnerabilities found.

The immediately preceding complete QUICK run passed 80 tests in 2.19 seconds with the same static,
documentation, SBOM/license, and dependency-audit controls.

## Acceptance evidence

- Generated RSA credentials validated the pinned issuer, audience, RS256 allowlist, key ID,
  signature, issued-at, not-before, expiry, and mandatory scope claims.
- Missing, expired, unknown-key, forged-project, insufficient-role, and unregistered-route requests
  were denied with typed non-disclosing responses.
- Health stayed public while the protected scope resource required bearer identity and explicit
  authorized tenant/project selection.
- Valid claims produced an immutable `TenantScope` and returned both permission-policy versions.
- Cache authorization components changed with project and permission version and included tenant,
  project, user, permission, RBAC, and route-policy versions; unauthorized projects were denied.
- Offline PostgreSQL SQL enabled and forced RLS and created `USING` plus `WITH CHECK` policies on all
  eight current identity/storage tables; downgrade removed policies and tables.
- Database scope binding set tenant, project, user, and permission version through transaction-local
  `set_config` calls before business queries.

## Limitations and next action

The JWKS was explicitly injected and the RSA key was generated only for tests. No live OIDC
discovery, provider metadata, revocation, membership synchronization, administrator boundary, or
live PostgreSQL role/RLS probe ran. S1-10 must add immutable audit events for all denials before the
SEC-TENANT gate can pass. S1-11 must replace direct secret material and verify the production role
has neither `BYPASSRLS` nor superuser privilege. R-007 and R-010 require approved-policy and exact-
candidate revalidation. This result does not satisfy TG-00 or TG-01.
