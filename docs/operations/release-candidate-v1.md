# V1.0 Release Candidate Runbook

## Entry conditions

S6-01 through S6-08 and TG-00 through TG-05 must PASS for one immutable commit. The approved
reference profiles, seven-day ledger, expert reviews, source, lock, SBOM, schemas, configuration,
packages, migrations, prompts, Skills, tools, and models must be frozen and hash-addressed.

## Candidate construction

Build packages in clean protected CI. Record each immutable artifact identity, media type, size, and
SHA-256. Create the canonical candidate manifest, run complete RELEASE tests, perform live migration
and rollback on a production-like copy, and run pre-publication smoke against the exact artifacts.

## Signing

Use the approved external signing service and key reference. Sign the canonical candidate SHA-256.
Do not export or record private key material. Resolve the key reference through the application-owned
trusted-key registry and require an approved, enabled, non-revoked external key whose purpose is
`RELEASE_SIGNING`. Verify the Ed25519 signature with that resolved public key and reject an unknown,
ineligible, identity-mismatched, or candidate-substituted key. Candidate-supplied environment and
approval fields are descriptive only and never establish trust. Preserve the signature, registry
snapshot identity, verification evidence, and signer authorization.

## Stop conditions

Stop for a missing prerequisite, mutable artifact, hash or size mismatch, migration or rollback
failure, protected-data change, smoke failure, invalid signature, P0/P1, tenant leak, duplicate
committed side effect, correctness failure, or isolation failure. Do not create a release-qualified
manifest from local generated keys, offline SQL compilation, synthetic smoke, or an uncommitted tree.
