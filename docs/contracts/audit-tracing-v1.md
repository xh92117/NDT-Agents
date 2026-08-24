# Audit and Tracing V1

**Status:** S1-10 local implementation contract  
**Owner:** Runtime Observability and Audit Owner  
**Related tasks:** S1-03, S1-07, S1-08, S1-09, S1-10  
**Required tests:** OBS-AUDIT, SEC-TENANT, migration upgrade and rollback, QUICK, DOC

## 1. Boundary

S1-10 adds one small observability boundary with two responsibilities:

1. create and propagate OpenTelemetry spans through a narrow application port;
2. append immutable, scoped audit events correlated to the active span.

The domain contract does not depend on an OTLP collector, database driver, or model provider.
Local tests use the standard OpenTelemetry SDK in-memory exporter and an in-memory audit repository.
The PostgreSQL schema is the production persistence contract; its live adapter and collector endpoint
remain TG-01 integration work.

## 2. Audit event

Each event is strict and immutable and contains:

- schema and event versions;
- event ID and per-tenant/project sequence;
- tenant, project, actor, role, and permission scope;
- event kind, action, target type, and target ID;
- policy version, decision, and outcome;
- input and output SHA-256 values;
- request ID, trace ID, and span ID;
- UTC occurrence time;
- previous event SHA-256 and canonical event SHA-256.

The event payload contains no raw credential, prompt, business document, tool output, or unrestricted
attribute map. Context is represented by stable IDs, versions, decisions, and hashes.

Supported event kinds are authorization, task, agent, checkpoint, budget, review, correction, model,
tool, cache, artifact, knowledge, approval, and security. Later tasks may use an existing kind but
must not add an unversioned free-form kind.

## 3. Append and read rules

- The repository assigns the next per-scope sequence and previous hash atomically.
- Reusing an event ID with the exact canonical request returns the existing event.
- Reusing an event ID with different content returns `AUDIT_IDEMPOTENCY_CONFLICT`.
- Reading requires the exact tenant and project scope.
- Sequence gaps, previous-hash mismatch, recomputed-hash mismatch, or mutation produce a typed error.
- PostgreSQL forces RLS and denies update and delete; correction is a new superseding event.
- Repository or exporter failure is explicit and must not be represented as successful audit.

## 4. Trace rules

- Trace IDs are 32 lowercase hexadecimal characters and span IDs are 16.
- Incoming and outgoing propagation uses W3C `traceparent`.
- A child span retains its parent trace ID and receives a new span ID.
- Only allowlisted low-cardinality scalar attributes may be exported.
- Credential-like keys and raw prompt, payload, document, or tool-output keys are denied.
- An audit event created inside a span records that active trace and span.
- A malformed external trace context is rejected; the caller may then start an explicit local root
  span, but the malformed context is never treated as trusted state.

## 5. Required-event completeness

The evaluator receives an explicit set of required event kinds for a workflow and the persisted
events for the same exact tenant, project, task, and request. Its metric is:

```text
present required event kinds / declared required event kinds
```

An empty required set is invalid. S1-10 tests cover authorization, task, agent, checkpoint, budget,
review, correction, model, tool, and cache kinds and require 100 percent completeness.

## 6. Failure codes

- `AUDIT_SCOPE_MISMATCH`
- `AUDIT_IDEMPOTENCY_CONFLICT`
- `AUDIT_CHAIN_INVALID`
- `AUDIT_EVENT_INVALID`
- `AUDIT_PERSIST_FAILED`
- `TRACE_CONTEXT_INVALID`
- `TRACE_ATTRIBUTE_DENIED`
- `TRACE_EXPORT_FAILED`

Every error states the cause and next required action. No failure may be hidden behind a fluent
success response.

## 7. Deferred production evidence

Before TG-01, run the same contract against approved PostgreSQL and an approved OpenTelemetry
collector or OTLP endpoint. Verify application-role RLS, append-only triggers, restart durability,
collector outage behavior, retention, clock synchronization, sampling policy, and end-to-end trace
correlation. Local deterministic evidence does not satisfy those production checks.
