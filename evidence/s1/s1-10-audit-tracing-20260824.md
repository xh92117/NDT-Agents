# S1-10 Audit and Tracing Local Evidence

**Run ID:** S1-10-TASK-20260824-01  
**Task:** S1-10  
**Environment:** local Windows with in-memory audit repository and synchronous in-memory span exporter  
**Result:** PASS for isolated immutable audit and OpenTelemetry correlation

## Candidate identity

- Workspace state: Git repository without an immutable commit.
- Audit and tracing contract: 1.0.0.
- OpenTelemetry API and SDK: 1.44.0.
- Controlled-document version: 1.16.
- Configuration SHA-256: `30071813e5965739ec284c05b07350cc2dd5cf0113d27c74b80c0cead0445ed8`.
- SBOM SHA-256: `82defa0a949628764fb5af515a8b49b2cc625de440a2ad126050bca4c08177eb`.
- Python: CPython 3.12.13.
- uv: 0.11.20, build `9252ba6b5`.

The configuration hash covers sorted path-and-file hashes for the audit contract, three
observability source files, storage metadata, the audit migration, three affected test files, exact
dependency inputs, the 87-component SBOM, and the license-decision inventory, for 13 files total.

## Reproducible task profile

The final evidence run ended at `2026-08-24T09:21:17.6974255+08:00`.

```text
uv lock --check
uv run python tools/generate_sbom.py
uv run pytest tests/observability tests/storage/test_storage_services.py \
  tests/identity/test_identity_isolation.py tests/baseline/test_sbom.py
uv run python tools/check_controlled_docs.py
uv run ruff format --check <S1-10 changed Python files>
uv run ruff check .
uv run mypy
uv run pytest
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 uv run python -X utf8 -m pip_audit
```

Results:

- S1-10 task and affected-boundary tests: 29 passed in 1.76 seconds;
- complete tests: 171 passed in 3.25 seconds;
- dedicated `OBS-AUDIT` tests: 8 passed;
- PostgreSQL migration upgrade and rollback compiled offline;
- Ruff lint passed for the complete repository;
- Ruff format check passed for all eight changed Python files;
- strict mypy passed across 60 source files;
- DOC passed for four version 1.16 controlled documents and seven gates;
- SBOM generation was deterministic across two runs and covered 87 components;
- dependency audit found no known vulnerabilities.

The first dependency-audit invocation failed before auditing because `pip-api` decoded the Chinese
workspace path with UTF-8 while its child process emitted the Windows legacy code page. The exact
same locked environment passed when the Python process encoding was explicitly set to UTF-8. This
tooling failure did not produce or replace a vulnerability result.

## Acceptance evidence

- `TraceService` uses the pinned standard OpenTelemetry API and SDK through one narrow adapter. It
  creates parent and child spans, injects and extracts W3C `traceparent`, preserves the trace ID,
  allocates distinct span IDs, and exports without starting a network or background worker.
- Malformed or zero trace context, absent active context, non-allowlisted attribute keys, and
  overlength attribute values return typed failures. The synchronous processor converts exporter
  rejection or exception into `TRACE_EXPORT_FAILED` after span end instead of hiding it.
- `AuditRecord` and `AuditEvent` reject unknown fields and bind exact tenant, project, actor, role,
  permission, action, target, policy, decision, outcome, request, task, time, input and output hashes,
  trace ID, and span ID. Raw prompt or arbitrary attribute fields cannot enter the strict model.
- The repository assigns a monotonic sequence and previous hash per tenant/project scope under one
  lock. Canonical event hashes verify the complete stored event. Direct payload tampering, sequence
  changes, or previous-hash changes fail chain validation.
- Exact repeated append of one event ID is idempotent. Reuse with changed content returns
  `AUDIT_IDEMPOTENCY_CONFLICT`; cross-project read returns `AUDIT_SCOPE_MISMATCH`; scoped list never
  returns another project's events.
- The completeness evaluator filters by exact scope, request, and task. The declared S1 set covers
  authorization, task, agent, checkpoint, budget, review, correction, model, tool, and cache events
  and reached 10/10, or 100 percent. An empty required set is invalid.
- PostgreSQL metadata and migration add `runtime_audit_event` with explicit tenant/project scope,
  actor and correlation fields, unique per-scope sequence and event hashes, forced RLS, and a
  database trigger that denies update and delete. Upgrade and complete rollback SQL compile.
- OpenTelemetry API, SDK, and semantic-conventions packages are exact in the lock and present in the
  generated SBOM and pending license-decision inventory. Pending legal approval is not represented
  as production approval.

## Simplicity and efficiency review

The change adds two focused runtime modules and one database table. Audit data is stable IDs,
versions, decisions, and hashes rather than duplicated business payloads. The trace adapter uses
the standard SDK extension points instead of a custom tracing protocol. Local export is synchronous
and deterministic, so no queue, worker, collector, network client, or retry loop was introduced.
The only new abstraction is the audit repository protocol required for the existing in-memory and
future PostgreSQL adapters.

## Limitations and next action

This is local task evidence, not TG-01 gate evidence. Before TG-01, the contract must run against an
approved PostgreSQL application role and approved OpenTelemetry collector or OTLP endpoint. Required
checks include live forced RLS, append-only trigger behavior, restart durability, collector outage,
retention, clock synchronization, sampling, end-to-end boundary instrumentation, and matching
immutable authorization-denial events. OpenTelemetry license decisions remain pending under R-007
and R-010. R-012 still requires durable review/correction checkpoints bound to these audit events.
S1-11 is next and must add approved secrets, TLS, encryption, and platform policy hooks without
placing secret material in audit events or spans.
