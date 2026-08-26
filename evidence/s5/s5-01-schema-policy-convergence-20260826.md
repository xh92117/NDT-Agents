# S5-01 shared schema-policy convergence evidence

- Run ID: `S5-01-CONVERGENCE-20260826-01`
- Finding: `CCR-20260826-001`
- Date: 2026-08-26
- Branch: `codex/s6-clients`
- Build state: mutable local workspace

## Safety case

Before the change, Tool Registry, Adapter SDK, and MCP each owned the same normalized sensitive
property-name set and recursive JSON Schema traversal. Their public constructors rejected the same
plaintext credential shapes but maintained three independent policy copies.

The protected behavior is unchanged: nested sensitive properties are rejected during model
validation, before registry publication or provider execution, and each boundary preserves its
existing validation message contract. Public models, schemas, error codes, permissions, audits,
budgets, and side effects are unchanged.

## Change

`ndt_agents.tools.schema_policy` is now the single internal authority for the sensitive property set
and recursive schema scan. Tool Registry, Adapter SDK, and MCP import that function directly. No
compatibility wrapper remains, and searches find no prior private scanner or duplicate constant.

## Verification

- Pre-change guard: 10 focused tests passed, covering 9 normalized names across all three public
  validation boundaries.
- Related tool suites: 115 passed.
- Full regression: 1012 passed, 1 skipped in 36.31 seconds.
- `uv run python -m ruff check .`: PASS.
- `uv run python -m ruff format --check .`: PASS; 380 files already formatted.
- `uv run mypy`: PASS over 187 source files.
- `uv run python tools/check_controlled_docs.py`: `DOC=PASS version=1.65 files=4 gates=7 ascii=true`.
- `git diff --check`: PASS.

## Source hashes

- `schema_policy.py`: `1ff0525f2272a5da716ac95aa8219190c3e0d22121c90bb16d77b014adc6f890`
- `registry.py`: `ac793dde44840e37555a48357b8870ad1cc3d6721562f4bf061be1f1bc6736d9`
- `adapter_sdk.py`: `b2b1214b79eca38ae2c6d93225ffbf74b0e4c720e495ae38a9f4444926d54875`
- `mcp_gateway.py`: `69e2c3f1479936a9c6bd0d15c3d6bccc97553fbe8b72135870db87faa9c73ac6`
- `test_unified_tool_registry.py`: `319eae51f58e87d5acba851b04543949b9c299472fab8320c6408ff8ae91e27a`

## Recovery boundary

The batch is limited to the new internal module, three imports/call sites, removal of three duplicate
private implementations, and one guard test. Reverting those exact edits restores the prior paths.
No external consumer of the removed private names was observed; unknown external consumers remain
possible but private-name compatibility is not part of the declared contract.
