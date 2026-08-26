# S6-09 Release Candidate Evidence

## Status

`BLOCKED`

The immutable manifest, migration/rollback evidence, Ed25519 signing, signature verification, and
release-smoke qualification contracts are implemented. No V1.0 release candidate was built or
signed because S6-08 and earlier gates are blocked and the working tree is mutable.

## Implemented boundary

- Canonical V1.0 manifest for one 40-character Git commit and one build SHA-256.
- Stable immutable artifact set for source, dependency lock, SBOM, schemas, configuration, server,
  Web client, migrations, prompts, Skills, tool registry, model registry, and release evidence.
- Exact S6-01 through S6-08 and TG-00 through TG-05 prerequisite evidence bindings.
- Production-like live upgrade/downgrade evidence with restored schema hash and unchanged protected
  data hashes.
- Mandatory health, identity, tenant-isolation, task-stream, review, approval-denial,
  cache-isolation, tool-denial, backup-readiness, migration-state, and rollback-readiness smoke
  checks.
- Zero P0/P1, tenant leak, duplicate committed side effect, correctness failure, and isolation
  failure qualification.
- Ed25519 signature over the canonical candidate hash, public-key hash verification, external key
  reference, approved signing-environment state, and no serialized private key material.
- Typed blocked state for test keys, synthetic migration/smoke, unapproved environment, or failed
  prerequisite; typed failure for unsafe, migration, rollback, or smoke results.

## Verification

- Implementation SHA-256: `5c94f8a9f9d2c7f5ea2a3a825e30ec17f4ce342b9517b81f95bf5b9dc0aff3d6`.
- Dedicated release-contract tests: 6 passed.
- Affected release, identity, storage migration, pilot, assurance, performance, and calibration set:
  63 passed in 2.12 seconds.
- PostgreSQL Alembic upgrade-to-head and head-to-base rollback SQL compiled and retained the existing
  RLS, append-only, storage, memory, cache, lifecycle, and knowledge-release assertions.
- Ruff: pass.
- Strict mypy for implementation and tests: pass.
- DOC 1.63: pass.

The positive signing and external-environment unit fixture validates only the contract with an
ephemeral generated key. It is not an approved key, signature, immutable artifact, release build,
or TG-06 result.

## Required next action

Complete S6-08 and all prerequisite gates for one immutable commit. Build the exact artifacts in
protected CI, run live migration and rollback on a production-like copy, run the complete RELEASE
profile and pre-publication smoke, sign through the approved external key service, and independently
verify the sealed candidate. Until then there is no V1.0 candidate hash to publish.
