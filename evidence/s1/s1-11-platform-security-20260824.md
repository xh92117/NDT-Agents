# S1-11 Platform Security Local Evidence

**Run ID:** S1-11-TASK-20260824-01  
**Task:** S1-11  
**Environment:** local Windows with deterministic in-memory secret/key providers and no network  
**Result:** PASS for isolated platform security controls

## Candidate identity

- Workspace state: Git repository without an immutable commit.
- Platform Security contract: 1.0.0.
- AES-GCM implementation: cryptography 50.0.0.
- Controlled-document version: 1.17.
- Configuration SHA-256: `c25f10a2547234a9ad7ebc89c4443c2ee3924bbdb45c3f8a4d52c015df6c27da`.
- SBOM SHA-256: `9994b8c2b40ea3a51dc4977889688a69cc4271c2e795755f3387d9821a97f7dc`.
- Python: CPython 3.12.13.
- uv: 0.11.20, build `9252ba6b5`.

The configuration hash covers sorted path-and-file hashes for three affected contracts, six security
source files, PostgreSQL, Redis, logging, two affected test files, exact dependency inputs, the
87-component SBOM, and the license-decision inventory, for 18 files total.

## Reproducible task profile

The final evidence run ended at `2026-08-24T09:38:25.8124733+08:00`.

```text
uv lock --check
uv run python tools/generate_sbom.py
uv run pytest tests/security tests/storage tests/identity tests/observability tests/runtime \
  tests/baseline/test_security_baseline.py tests/baseline/test_sbom.py
uv run ruff format --check <S1-11 changed Python files>
uv run ruff check .
uv run mypy
uv run pytest
uv run python tools/check_controlled_docs.py
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 uv run python -X utf8 -m pip_audit
```

Results:

- S1-11 task and affected-boundary tests: 52 passed in 1.61 seconds;
- complete tests: 179 passed in 3.05 seconds;
- dedicated `SEC-PLATFORM` tests: 8 passed;
- Ruff lint passed for the complete repository;
- Ruff format check passed for all eleven changed Python files;
- strict mypy passed across 67 source files;
- DOC passed for four version 1.17 controlled documents and seven gates;
- SBOM generation was deterministic across two runs and covered 87 components;
- dependency audit found no known vulnerabilities.

## Acceptance evidence

- `SecretSelector` and `SecretRef` contain environment, tenant, project, purpose, ID, and version but
  no raw value. A lease binds the exact reference, accessor user, permission version, policy version,
  issue time, and bounded expiry. Its `SecretStr` value is excluded from serialization and safe
  representation.
- Secret resolution, use, expiry, policy or permission change, cross-project access, rotation,
  stale version, revocation, and provider outage produce typed outcomes. A new manager over the same
  provider recovers the rotated current version. Stale and revoked versions have no fallback.
- Secret values are non-empty and bounded. Managed PostgreSQL and Redis settings store selectors,
  not credentials. They resolve and revalidate a short-lived lease immediately before client
  construction, and construction performs no network access.
- Direct PostgreSQL and Redis credential settings are restricted to loopback local or CI use.
  Production policy rejects credentials embedded in nonsecret endpoints and rejects plaintext or
  incomplete TLS settings.
- HTTPS requires certificate validation outside the loopback exception. Managed PostgreSQL creates
  a system-trust `SSLContext` with hostname checking, `CERT_REQUIRED`, and TLS 1.2 minimum after
  requiring `sslmode=verify-full`. Managed Redis requires `rediss`, `ssl_cert_reqs=required`, and
  TLS 1.2 minimum.
- The envelope service uses AES-256-GCM through cryptography 50.0.0. It generates a fresh 96-bit
  nonce and authenticates environment, tenant, project, key purpose, and stable caller context.
  Same plaintext produces distinct envelopes. Cross-scope access, modified ciphertext, modified
  authenticated context, invalid key size, missing key, revoked key, and provider outage fail with
  no plaintext result.
- Rotation makes the predecessor decrypt-only and the new version active. New writes use only the
  new version. A restarted service can decrypt old authorized data while the predecessor is
  decrypt-only; explicit revocation then denies it while the new version remains available.
- Every allow and denial creates an S1-10 `SECURITY` event correlated to the active trace. Events
  contain only references, decisions, policy versions, and hashes. They contain no secret, key,
  plaintext, ciphertext, nonce, DSN, or credential-bearing URL.
- Rotation and revocation append an `ALLOW` plus `PARTIAL` authorization event before provider
  mutation and a terminal event afterward. If the mandatory pre-mutation audit fails, the provider
  is not called. Secret or plaintext release likewise occurs only after successful audit.
- Structured log redaction now covers credential-bearing HTTP, PostgreSQL, Redis, and Redis-TLS
  URLs in addition to named authorization, password, secret, token, and API-key values.
- cryptography 50.0.0 is now an exact direct runtime dependency. It remains in the generated SBOM
  and pending license-decision inventory; automated inventory is not represented as legal approval.

## Simplicity and efficiency review

The implementation uses one standard AEAD primitive, one secret-provider port, one key-provider
port, one transport-policy service, and the existing S1-10 audit boundary. It adds no vault client,
KMS SDK, TLS proxy, daemon, queue, retry loop, or network call. Reference models store IDs and
versions instead of copied credentials. Encryption and secret operations are synchronous and
bounded; provider selection and distributed lifecycle behavior remain outside the local scaffold.

## Limitations and next action

This is local task evidence, not TG-01 or production approval. The S0-10 security baseline remains
proposed under R-007, and R-010 requires exact-candidate revalidation. Before TG-01, select approved
managed secret and key services and run live IAM, HSM or KMS, certificate-chain, hostname, revocation,
concurrent rotation, restart, outage, database, Redis, object, queue, vector, backup, artifact,
retention, alerting, and audit-durability tests. Service-side encryption settings and key ownership
must be independently verified; the in-memory providers cannot satisfy them. cryptography license
approval remains pending under R-005 and R-007. S1-12 is next and must use these policy and secret
references in the shared Tool Registry without exposing raw material.
