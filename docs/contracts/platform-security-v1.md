# Platform Security V1

**Status:** S1-11 isolated local implementation contract  
**Owner:** Platform Security Owner  
**Related tasks:** S0-10, S1-02, S1-03, S1-10, S1-11  
**Required tests:** SEC-PLATFORM, SEC-TENANT, OBS-AUDIT, rotation recovery, storage, QUICK, DOC

## 1. Boundary

S1-11 adds one small provider-neutral boundary for secret references, transport policy, envelope
encryption, key lifecycle, and security audit hooks. It does not select or emulate a production
vault, HSM, KMS, certificate authority, or cloud encryption service.

Local and CI tests use deterministic in-memory secret and key providers. Model startup may also use
the read-only `EnvironmentSecretProvider`, which accepts only explicitly allowlisted variable names
and exact scoped selectors. These adapters cannot be enabled as production providers. Production
selection remains blocked by the unapproved
S0-10 baseline and the provider, license, endpoint, certificate, region, and operations decisions in
`plan.md`.

## 2. Secret contracts

A `SecretSelector` identifies an environment, tenant, project, purpose, and stable secret ID. A
`SecretRef` adds one immutable version. Neither contains raw secret material. `SecretLease` is a
bounded in-process value with an exact reference, accessor identity, issue time, expiry time, and a
Pydantic secret value that is excluded from serialization and safe representation.

Rules:

- access requires exact environment, tenant, project, user, and permission context;
- resolution returns the current active version only;
- a version-specific stale, revoked, expired, wrong-scope, or unavailable request fails explicitly;
- rotation atomically activates the new version and revokes the old version for new retrieval;
- revocation never falls back to an environment variable, embedded value, file, or prior lease;
- lease duration is bounded and a lease is revalidated before use;
- audit input and output hashes cover reference and decision metadata, never secret bytes.

The environment adapter is limited to local and CI. It snapshots only explicitly referenced
non-empty values, wraps each value as `SecretStr`, reveals it only for the exact current
`SecretRef`, and provides no rotate or revoke mutation. Changing a value requires an external
environment update, an incremented configured version, and process restart. Process variables take
precedence over an explicitly selected ignored local environment file. There is no implicit dotenv
discovery or fallback after a missing, stale, or wrong-scope request.

## 3. Transport policy

The minimum version is TLS 1.2 and TLS 1.3 is preferred. Certificate and hostname validation are
mandatory. Plaintext is permitted only for an explicit local or CI policy and a loopback host.

- HTTP endpoints outside that exception are denied; HTTPS verification cannot be disabled.
- PostgreSQL outside that exception requires `sslmode=verify-full`.
- Redis outside that exception requires `rediss` and `ssl_cert_reqs=required`.
- A malformed or credential-bearing endpoint is rejected before connection.

The local task validates configuration and does not claim a live TLS handshake. Approved
certificates, trust stores, expiry monitoring, revocation, and live endpoint probes remain TG-01.

## 4. At-rest encryption and key lifecycle

The local reference provider uses AES-256-GCM. Every envelope contains only schema version,
algorithm, key reference, nonce, ciphertext, and authenticated-data SHA-256. The authenticated data
binds environment, tenant, project, purpose, and caller-supplied stable context. A fresh 96-bit nonce
is required for every encryption.

Key states are `ACTIVE`, `DECRYPT_ONLY`, and `REVOKED`. Rotation requires the same environment,
scope, and purpose: the new version becomes active, the predecessor becomes decrypt-only, and new
writes cannot use the predecessor. Decrypt-only preserves recovery of existing authorized data.
Revoked material cannot encrypt or decrypt. Cross-scope access, altered ciphertext, altered
authenticated data, invalid key length, missing key, and unavailable provider state return typed
failures with no plaintext result.

Raw test key material is accepted only by the explicitly named in-memory test provider and is never
returned by its public encryption interface. A production adapter must use managed encrypt/decrypt
or data-key APIs and must not expose a long-lived master key to application code.

## 5. Storage connection resolution

Managed PostgreSQL and Redis settings store a `SecretSelector`, pool and timeout values, and
transport policy only. They resolve one short-lived current lease immediately before adapter
construction and discard the transient plaintext after constructing the underlying client. Direct
DSN or URL settings are local/CI compatibility inputs and are rejected for staging or production.

## 6. Audit hook

Every secret resolve, rotate, revoke, transport decision, encrypt, decrypt, key rotate, key revoke,
and provider-unavailable decision emits an S1-10 `SECURITY` event inside an active trace. The event
contains actor and scope, operation and target reference, policy version, decision, outcome, request
and task IDs, and hashes of nonsecret inputs and outputs. It contains no secret, key, nonce,
ciphertext, DSN, URL credentials, or plaintext.

An audit write failure is explicit. A protected mutation, key operation, or credential release must
not be represented as successful when its mandatory audit event cannot be preserved.
Secret and key rotation or revocation first append an `ALLOW` plus `PARTIAL` authorization event,
then mutate the provider, then append the terminal success event. If the first audit append fails,
the provider is not called. A provider failure after authorization appends a denial event and never
becomes a terminal success.

## 7. Failure codes

- `SECURITY_SCOPE_MISMATCH`
- `SECRET_NOT_FOUND`
- `SECRET_VERSION_STALE`
- `SECRET_REVOKED`
- `SECRET_VALUE_INVALID`
- `SECRET_LEASE_EXPIRED`
- `SECRET_PROVIDER_UNAVAILABLE`
- `TLS_POLICY_DENIED`
- `KEY_NOT_FOUND`
- `KEY_VERSION_STALE`
- `KEY_REVOKED`
- `KEY_PROVIDER_UNAVAILABLE`
- `ENCRYPTION_FAILED`
- `DECRYPTION_FAILED`
- `SECURITY_AUDIT_FAILED`

Every error states the cause and next action. No error may expose raw material.

## 8. Deferred production evidence

Before TG-01, bind this contract to approved managed secret and key services and approved PostgreSQL,
Redis, object, queue, vector, backup, and artifact endpoints. Verify real certificate chains and
hostname checks, at-rest service settings, short-lived identity credentials, provider IAM, tenant
key policy where required, concurrent rotation, process restart, provider outage, audit durability,
backup recovery, certificate and key revocation, and operational alerts. Revalidate the exact policy,
dependency, SBOM, license, container, and immutable build hashes after S0 approval.
