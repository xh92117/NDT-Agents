# S1-13 Approval Service Evidence

Status: PASS for the local S1-13 task profile.

## Configuration

- Task: `S1-13-TASK-20260824-01`
- Configuration SHA-256: `0f799143f700dc5c25fb040b81eae4c0cebb9c628b64cba51e1a0570dfc9f56a`
- Environment: local Windows, CPython 3.12.13, deterministic clock, append-only approval and
  audit repositories, synchronous trace exporter, and offline PostgreSQL DDL compilation.

## Commands and results

```text
uv run ruff format --check src/ndt_agents/approval tests/approval migrations/versions/0005_s1_approval.py tests/storage/test_storage_services.py
uv run ruff check .
uv run mypy
uv run python tools/check_controlled_docs.py
uv run pytest tests/approval tests/security tests/identity tests/orchestration/test_recovery.py tests/observability/test_audit_tracing.py tests/storage/test_storage_services.py -q
uv run pytest -q
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 uv run python -X utf8 -m pip_audit --local --progress-spinner off
uv run python tools/generate_sbom.py
```

- 19 dedicated `INT-APPROVAL` tests passed.
- 63 affected approval, platform security, tenant, recovery, audit, and migration tests passed.
- 211 complete repository tests passed.
- Ruff lint, changed-file format, strict mypy, DOC 1.19, and migration upgrade/rollback passed.
- Dependency audit found no known vulnerabilities after one bounded retry for a transient PyPI TLS
  EOF. No dependency changed during the retry.
- Deterministic SBOM contains 87 components and has SHA-256
  `9994b8c2b40ea3a51dc4977889688a69cc4271c2e795755f3387d9821a97f7dc`.

## Verified behavior

- Knowledge, plan, report, critical-finding, instrument, destructive, and release candidates all
  create the same exact-scope paused checkpoint.
- Candidate preview, target identity, version, SHA-256, requester, policy, task, and expiry are bound
  before any decision or resume.
- Requester self-approval, wrong scope or permission version, unauthorized role, stale candidate,
  duplicate actor, conflicting event ID, terminal replay, and second resume are denied.
- Release requires distinct Security Owner and Quality Owner decisions. Delegation works only for a
  policy that enables it and remains role-, candidate-, scope-, and expiry-bound.
- Reject, request-change, expiry, and cancellation are immutable terminal decisions.
- Exact decision and resume retries are idempotent. A restart over the same repository reconstructs
  the approved state after event sequence, payload hash, previous hash, and event hash validation.
- Success and denial paths emit correlated hash-only S1-10 `APPROVAL` audit events.
- Migration `0005_s1_approval` compiles forward and backward with forced project RLS and an
  append-only update/delete trigger.

## Limits

The local repository and offline PostgreSQL DDL are not live production evidence. TG-01 still needs
approved production roles and policies, live identity and database concurrency probes, immutable
build evidence, and accountable security and license approval.
