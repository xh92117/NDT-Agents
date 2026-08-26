# S5-02 Function Gateway Evidence

## Result

`PASS` for the local S5-02 task profile. This is not TG-05 or immutable PR evidence.

Evidence ID: `S5-02-TASK-20260825-01`

## Scope

This record covers the provider-neutral Function Calling catalog and invocation gateway over the
S5-01 shared Tool Registry. It does not enable or contact an LLM provider, Web Search provider, MCP
server, Bash process, model, network destination, instrument, or device.

## Candidate identity

- Branch: `codex/s5-unified-tools`
- Base commit: `16c0c6871b23be6fc03416bdec38adfc85d7d1b9`
- Immutable build: none; the workspace contains preserved uncommitted S4 work plus S5-01 and S5-02
- Function-gateway source SHA-256: `73793b0498439fdad19f025087b07dd75e51e28aeeba4ddb8411de0e11315cfc`
- Dedicated-test SHA-256: `e74d334984162d95a7242914fccd0ffafe5970401a5ff04ccbc18631fcfb5b07`
- Contract-document SHA-256: `021cd4965b77a1c83d3f507b5aae376530e3cf4d7914eba7a082a1556d22a7b6`
- Registry source SHA-256: `fbcf18018d1033f32bca7402df4e5d0d36af62baa6d16703ee1d895db7ce50e4`

## Implemented boundary

- Catalog loading starts only from the S5-01 authorized exposure manifest.
- Deterministic model-visible schemas contain only name, description, strict parameters, and the
  strict flag; exact tool mapping remains in the orchestration-owned catalog.
- Function names bind the exact registered tool name and semantic version and are checked for
  collisions.
- Catalog hashes bind the contract, registry, exposure, sorted authorization context, and every
  internal binding. An ephemeral gateway-owned HMAC attestation rejects caller-minted catalogs.
- Only resolvable same-document JSON Pointer schema references are allowed. External, relative,
  unresolved, and named-anchor references fail without retrieval.
- Calls are bounded UTF-8 JSON with duplicate-key, non-finite-number, safe-parser, strict-type,
  unknown-field, function-name, and argument-schema checks.
- Retry state, attempt number, idempotency key, approval evidence, budget, scope, version, and adapter
  selection remain trusted orchestration inputs and cannot appear in the model call envelope.
- Invalid calls and catalogs are hash-only audited before adapter execution and before the physical
  tool-call meter.
- Valid calls use the exact S5-01 permission, destination, approval, idempotency, concurrency,
  timeout, result identity, output hash, output schema, error, retryability, and audit path.
- The gateway returns the validated V1 `ToolResult` unchanged and performs no hidden retry.

## Reproducible verification

Environment: local Windows, CPython 3.12.13, uv 0.11.20.

Dedicated S5-02 boundary:

```text
uv run pytest tests/tools/test_function_gateway.py -q
```

Result: 27 tests passed.

Mapped task profile:

```text
uv run pytest tests/tools tests/orchestration/test_budget.py tests/observability/test_audit_tracing.py tests/security/test_platform_security.py tests/models -q
```

Result: 163 tests passed and one test skipped.

Complete QUICK and regression profile:

```text
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
uv run python tools/check_controlled_docs.py
uv run pytest
git diff --check
```

Result: Ruff passed; all 152 Python files were formatted; strict mypy passed over 152 source files;
`DOC` passed at version 1.47 for four ASCII controlled documents and seven gates; all 665 tests
passed with one skip; the diff check passed.

The skip is the inherited S3-02 Windows control-character filename limitation. The historical S3-02
Ubuntu immutable run covers that fixture behavior, but the exact S5-02 candidate has not run in
protected Linux CI.

## Code graph

The incremental refresh completed without errors and the verified graph contains 145 files, 2,228
nodes, and 19,580 edges. Explicit change analysis reported medium risk `0.60` and 27 heuristic test
gaps. The dedicated S5-02 test file is untracked in this mutable workspace, so it is not part of the
persisted graph snapshot; direct execution covers catalog, schema, authorization, idempotency,
timeout, result, and audit paths. Immutable PR review must repeat graph analysis after the files are
tracked.

## Test groups

- `UNIT-TOOLREG`
- `INT-FUNCTION`
- `SEC-TOOLS`
- affected `BUDGET` and `OBS-AUDIT`
- `QUICK`
- `DOC`

## Remaining limitations

- No live Function Calling provider or model inference ran or was enabled.
- No Web Search provider, MCP server, Bash process, instrument, device, or network destination was
  contacted.
- S5-03 through S5-08 remain pending, and TG-05 remains `NOT_RUN`.
- S5-06 canonical inspection data and complete S5-07 inference remain unfinished.
- There is no immutable S5-02 build, protected PR CI result, or exact-candidate Linux rerun.
- Existing phase-gate, external-service, real-data, expert-gold, and accountable-approval blockers
  remain unchanged.
