# Identity and Isolation V1

**Contract version:** 1.0.0  
**Migration revision:** 0002_s1_identity_rls  
**Task:** S1-03  
**Status:** isolated security candidate under proposed S0-10 policy

## OIDC validation

`OidcJwtVerifier` receives an immutable `OidcSettings` and a preloaded JWKS. It performs no OIDC
discovery or key download. The caller must obtain, validate, version, and refresh provider metadata
through an approved adapter before constructing the verifier.

The verifier requires:

- an exact HTTPS issuer and exact audience;
- an explicit non-empty `RS256` or `ES256` algorithm allowlist;
- a unique allowed signing key ID with `use=sig`;
- valid signature, issued-at, not-before, expiry, and bounded clock skew;
- subject, user UUID, tenant UUID, at least one project UUID, at least one role, permission version,
  and token ID claims.

Unknown keys, disallowed algorithms, malformed claims, invalid issuer/audience, and expired tokens
return stable non-disclosing authentication errors. Raw credentials and claims are not returned or
logged.

## Request scope

Health resources are public. Every `/v1/` resource is protected when an `IdentityRuntime` is
installed. A request must provide a bearer credential, `X-Tenant-ID`, and `X-Project-ID`. The
headers select a scope but never authorize it: the selected tenant must equal the signed tenant
claim and the selected project must appear in the signed project list.

The middleware creates an immutable `TenantScope` containing tenant, project, user, role codes,
and permission version. The scope is stored only on the active request. Missing or malformed scope,
tenant mismatch, and project mismatch are denied before a protected handler runs.

`GET /v1/runtime/scope` is the first protected diagnostic resource. It returns only the active
scope identifiers and security-policy versions. It exists only when identity middleware is
installed.

## Default-deny RBAC

RBAC and route permissions are separate immutable versioned policies. Each protected method/path
must map to one permission. An unregistered route is denied even when the credential and role are
otherwise valid. A role grants only its explicit permission set. Unknown roles grant nothing.

The initial permission is `runtime:scope:read`. S3-01 adds the narrow
`knowledge:import:start` permission for `POST /v1/knowledge/imports`. Business permissions are
added with their owning tasks and tests; a wildcard permission is not defined.

## Cache authorization scope

Before any future cache lookup, the authorization component is serialized from tenant, project,
user, permission version, RBAC policy version, and route policy version. An unauthorized project
cannot produce a cache authorization scope. S2 cache keys must include this value plus the other
versions required by the platform cache contract.

## PostgreSQL RLS

Migration `0002_s1_identity_rls` adds tenant and project registries and scoped tenant/project
membership tables. It enables and forces row-level security on those tables and every S1 runtime,
checkpoint, artifact, and embedding table. Policies use transaction-local `app.tenant_id` and,
where applicable, `app.project_id` settings for both `USING` and `WITH CHECK`.

`PostgresStorage.transaction` requires a `TenantScope` and sets transaction-local tenant, project,
user, and permission-version values before yielding the connection. There is no unscoped business
transaction method. The migration downgrade removes policies, disables RLS, and removes membership
tables before the prior storage downgrade runs.

RLS is defense in depth and does not replace API authorization. The production application role
must be verified not to have PostgreSQL `BYPASSRLS` or superuser privileges during live SEC-TENANT
tests.

## Deferred production controls

Live provider discovery, JWKS refresh, membership synchronization, administrator-role boundaries,
identity audit persistence, revocation feeds, approved managed-secret providers, and live
PostgreSQL RLS probes remain pending production integration and the approved S0 security policy.
S1-10 and S1-11 provide isolated local audit and managed-secret contracts only. This candidate must
not be enabled for production identity traffic.
