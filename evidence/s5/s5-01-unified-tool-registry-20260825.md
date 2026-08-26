# S5-01 Unified Tool Registry Evidence

## Result

`PASS` for the local S5-01 task profile. This is not TG-05 or immutable PR evidence.

## Scope

This record covers the S5-01 extension of the shared S1-12 Tool Registry. Contract schema `1.1.0`
adds unified application-owned metadata and deterministic authorized exposure for internal, Bash,
Function Calling, Web Search, MCP, instrument, and AI-model tools. It does not enable a live
provider, network request, MCP server, model inference, or physical instrument action.

## Candidate identity

- Branch: `codex/s5-unified-tools`
- Base commit: `16c0c6871b23be6fc03416bdec38adfc85d7d1b9`
- Immutable build: none; the workspace contains preserved uncommitted S4 work and the S5-01 change
- Registry source SHA-256: `fbcf18018d1033f32bca7402df4e5d0d36af62baa6d16703ee1d895db7ce50e4`
- File-gateway source SHA-256: `28f15520b9e2896133feefa6cc3e9ab4f1a46ee20eb4382ba4105c7603a058bb`
- Dedicated-test SHA-256: `739b1dd8509a407a002380f084389b37eeb62cdaab3aaecee147d741c3bb4c1e`
- Contract-document SHA-256: `e01c7a88008a665f3d5a18945d75c5da68b5f6e029bf07b8a3a7e97af464f1c2`

## Implemented boundary

- Seven explicit capability kinds and registered transports.
- Tenant, project, or task data scope plus local, tenant-managed, or approved-external destination.
- Family-specific publication validation and required test groups.
- Plaintext credential-field denial in strict input schemas.
- Deterministic minimal exposure manifests with validated content hashes.
- Six-tool default and twelve-tool hard exposure limits.
- One-namespace default and two-namespace MCP hard limits across every MCP transport.
- Permission, secret-purpose, network, destination, side-effect, and approval exposure policy.
- Exact scope, task, run, policy, registry, tool, and input approval bindings.
- Declared adapter error enforcement, retryability validation, and explicit attempt bounds.
- AI-model definitions stop before the physical-tool meter and require the later S5-07 gateway.
- S3-02 file definitions migrated to explicit Bash, local, task-scoped, recovery, error, and owner
  metadata without bypassing the shared registry.

## Reproducible verification

Environment: local Windows, CPython 3.12.13, uv 0.11.20.

Dedicated and inherited tool boundary:

```text
uv run ruff format --check src/ndt_agents/tools tests/tools
uv run ruff check src/ndt_agents/tools tests/tools
uv run mypy src/ndt_agents/tools tests/tools
uv run pytest tests/tools/test_unified_tool_registry.py tests/tools/test_tool_registry.py tests/tools/test_file_gateway.py
```

Result: Ruff, format, and strict mypy passed; 58 tests passed and one test skipped.

Task profile:

```text
uv run pytest tests/tools tests/orchestration/test_budget.py tests/observability/test_audit_tracing.py tests/security/test_platform_security.py tests/models
```

Result: 136 tests passed and one test skipped.

Complete QUICK and regression profile:

```text
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
uv run python tools/check_controlled_docs.py
uv run pytest
```

Result: Ruff passed; all 150 Python files were formatted; strict mypy passed; `DOC` passed at
version 1.46 for four ASCII controlled documents and seven gates; all 638 tests passed with one
skip. `git diff --check` passed.

The skip was reproduced explicitly:

```text
uv run pytest tests/tools/test_file_gateway.py -rs
```

Result: 25 passed and one skipped because the Windows file system could not create the
control-character filename. The historical S3-02 Ubuntu immutable run covered that file-gateway
case, but the exact S5-01 candidate has not been rerun in protected Linux CI.

## Code graph

The incremental refresh completed without errors and re-parsed nine tracked Python files. Verified
graph totals are 145 files, 2,228 nodes, and 19,579 edges. Change analysis reported medium risk and
27 heuristic test gaps because the new untracked S5 test file is not indexed before an immutable
commit. Direct tests cover the prioritized `_authorize_definition` and secret-schema paths, and the
complete 638-test regression passed. Immutable PR review must repeat graph analysis after the new
test file is tracked.

## Test groups

- `UNIT-TOOLREG`
- `INT-FUNCTION`
- `SEC-TOOLS`
- affected `BUDGET` and `OBS-AUDIT`
- inherited S3-02 `INT-BASH`
- `QUICK`
- `DOC`

## Remaining limitations

- No live Function Calling provider, Web Search provider, MCP server, model, instrument, or device
  call ran or was enabled.
- S5-02 through S5-08 remain pending, and TG-05 remains `NOT_RUN`.
- S5-06 canonical inspection data and S5-07 inference remain unfinished.
- There is no immutable S5-01 build, protected PR CI result, or exact-candidate Linux rerun.
- Existing phase-gate and accountable approval blockers remain unchanged.
