# S1-12 Tool Registry Evidence

Status: PASS for the local S1-12 task profile.

## Configuration

- Task: `S1-12-TASK-20260824-01`
- Configuration SHA-256: `90b2d14b8bfa6ac346efe91c54c38896c49f122126acc08f9be9cd055d91b1ef`
- Environment: local Windows, CPython 3.12.13, deterministic injected adapters, S1-08 budget
  guard, in-memory S1-10 audit repository, and synchronous trace exporter.

## Commands and results

```text
uv run ruff format --check src/ndt_agents/tools tests/tools
uv run ruff check .
uv run mypy
uv run python tools/check_controlled_docs.py
uv run pytest tests/tools tests/orchestration/test_budget.py tests/observability/test_audit_tracing.py tests/security -q
uv run pytest -q
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 uv run python -X utf8 -m pip_audit --local --progress-spinner off
uv run python tools/generate_sbom.py
```

- 13 dedicated `UNIT-TOOLREG` tests passed.
- 58 affected tool, budget, audit, and security tests passed.
- 195 complete repository tests passed.
- Ruff lint, changed-file format, strict mypy, and DOC 1.18 passed.
- Dependency audit found no known vulnerabilities.
- Deterministic SBOM contains 87 components and has SHA-256
  `9994b8c2b40ea3a51dc4977889688a69cc4271c2e795755f3387d9821a97f7dc`.

## Verified behavior

- Only strict application-owned definitions are publishable and each adapter has one exact binding.
- Registry snapshots have deterministic content-derived versions and stale callers are denied.
- Task allowlists, permissions, secret purposes, network declarations, input bytes, and strict Draft
  2020-12 schemas are checked before a physical adapter call.
- S1-08 counts each physical call and rejects an identical call without a new observation.
- Side effects are serial, require stable idempotency, replay committed results, reject conflicting
  input, and stop for reconciliation after an ambiguous timeout.
- V1 `ToolResult` identity, scope, input/output hashes, byte limits, and output schema are validated
  before return. Timeouts are typed.
- Success, replay, timeout, unregistered calls, and every preflight denial produce correlated,
  hash-only S1-10 `TOOL` audit events.

## Limits

This task does not claim concrete Bash, Function Calling, Web, MCP, instrument, or model adapters.
The local side-effect journal is not durable production persistence. Live policy and service probes,
an immutable build, and accountable license approval remain required by later tasks or TG-01.
