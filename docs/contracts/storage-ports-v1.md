# Storage Ports V1

**Contract version:** 1.0.0  
**Migration revisions:** 0001_s1_storage through 0003_s1_recovery  
**Task:** S1-02  
**Status:** isolated local candidate; live service and production approval pending

## Boundaries

S1-02 provides four boundaries:

- `PostgresStorage`: a lazy SQLAlchemy async engine using only the asyncpg PostgreSQL driver;
- `RedisStateStore`: scope-prefixed bounded state operations over a Redis-compatible key/value port;
- `ArtifactStorageService`: immutable SHA-256-verified artifacts over an object-storage port;
- dependency readiness probes injected into the Runtime API without changing process liveness.

Constructing a client or application does not connect. Calls use configured operation timeouts and
map dependency failures to `StorageError`, which carries a stable code, retryability, and operator
next action without backend exception text.

## PostgreSQL and pgvector

Alembic revision `0001_s1_storage` creates the `vector` extension and these tables:

| Table | Purpose | Scope key |
|---|---|---|
| `runtime_task` | initial persisted task envelope | tenant, project, task |
| `runtime_checkpoint` | ordered recoverable state references | tenant, project, checkpoint |
| `artifact_record` | immutable object metadata | tenant, project, artifact, version |
| `knowledge_embedding` | initial 1,536-dimension pgvector boundary | tenant, project, embedding |

Every project-scoped business table includes `tenant_id` and `project_id`. Unique constraints also
include scope.
The migration has an offline-compilable PostgreSQL upgrade and a reverse-order downgrade. It does
not drop the shared `vector` extension during downgrade. S1-03 migration `0002_s1_identity_rls`
adds membership tables and forces row-level security under the
[Identity and Isolation V1](./identity-isolation-v1.md) contract.

S1-07 migration `0003_s1_recovery` adds `graph_version` to checkpoint metadata plus scoped
`runtime_assignment_output`, `runtime_side_effect`, and `runtime_interrupt` journals. Each new
table enables and forces the same tenant/project row-level security policy. Their runtime contract
is defined by [Recovery Runtime V1](./recovery-runtime-v1.md).

`PostgresSettings.dsn` and `RedisSettings.url` are Pydantic secret values limited to loopback local
or CI compatibility. `ManagedPostgresSettings` and `ManagedRedisSettings` contain nonsecret
endpoints plus exact `SecretSelector` references. S1-11 resolves a short-lived lease immediately
before client construction, validates transport policy, and does not serialize the resolved value.
Managed PostgreSQL uses the system trust store, hostname verification, certificate validation, and
TLS 1.2 minimum. Managed Redis requires `rediss`, certificate validation, and TLS 1.2 minimum.
Production still requires approved providers, endpoints, certificates, and live probes.

## Redis state

Keys use this fixed form:

```text
ndt:v1:tenant:{tenant_id}:project:{project_id}:{namespace}:{logical_key}
```

Namespaces and logical keys accept only bounded safe characters. TTL is mandatory and limited to
1 second through 30 days. The Redis adapter uses bounded connection and operation timeouts. The
in-memory backend is deterministic test support only and is never a production fallback.

## Artifact objects

The object key is derived, not caller supplied:

```text
tenants/{tenant_id}/projects/{project_id}/artifacts/{artifact_id}/versions/{artifact_version}
```

Writes use a backend `put_if_absent` operation and reject an existing logical version. Reads require
the active tenant and project, reconstruct the expected URI, and validate content size, SHA-256,
and stored scope/version/classification metadata. An integrity failure requires quarantine and
verified restoration. An S3-compatible backend implementation and live service test remain pending
approved endpoints, credentials, and supply-chain decisions.

## Readiness

`GET /health/live` remains independent of storage. `GET /health/ready` evaluates only injected
dependency probes. A failed probe returns HTTP 503, overall `FAIL`, and a stable per-check error
code. Probe exceptions that are not typed storage failures become `DEPENDENCY_CHECK_FAILED`.

## Local verification boundary

Local storage integration uses deterministic in-memory key/value and object backends plus offline
PostgreSQL/pgvector migration compilation. This proves contracts, scope keys, immutability,
integrity, timeout configuration, lazy construction, readiness behavior, and rollback SQL. It is
not evidence that a live PostgreSQL, Redis, or S3-compatible deployment is healthy. Live tests are
required before TG-01.
