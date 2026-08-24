# V1 Boundary Contracts

## 1. Status and scope

This document freezes the V1 boundary contracts created by task `S0-04`. The executable
definitions are in `src/ndt_agents/contracts/v1.py`; the generated JSON Schemas and their
SHA-256 values are listed in `schemas/v1/manifest.json`.

The contract version is `1.0.0`. A breaking field, meaning, enum, invariant, or schema change
requires a new major contract version and a migration decision. Generated files must be updated
only by `uv run python tools/generate_schemas.py`.

## 2. Frozen contracts

| Contract | Boundary purpose |
|---|---|
| `TenantScope` | tenant, project, user, role, and permission-version authorization scope |
| `BudgetPolicy` | default, active, and hard limits for task execution |
| `ArtifactRef` | immutable or versioned large-object reference with hash and classification |
| `CitationRef` | claim-to-source traceability with an exact source locator |
| `TaskContext` | minimal permission-filtered context supplied to a child agent |
| `AgentResult` | typed child-agent result, evidence, confidence, issues, and failure state |
| `ToolResult` | typed tool outcome with scope, hashes, output limits, and structured failure |
| `Checkpoint` | recoverable graph-state reference and committed side-effect identifiers |
| `MemoryRecord` | scoped memory candidate or approved record with provenance and expiry |
| `CacheEntry` | scoped cache value with permission and component version bindings |
| `ReviewResult` | independent review decision and bounded correction count |
| `ApprovalRecord` | immutable human decision bound to the exact target version and hash |

## 3. Invariants

- Every boundary model rejects unknown fields.
- Boundary values are immutable after validation.
- Every persistent or executable scope includes tenant, project, user, role, and permission version.
- Every hash represented as SHA-256 uses exactly 64 lowercase hexadecimal characters.
- Budget limits satisfy `default <= active <= hard`.
- A failed or blocked agent result requires a stable failure code.
- A failed, blocked, or denied tool result requires a stable error code.
- A successful agent result cannot carry a failure code.
- Contract examples use synthetic identifiers and contain no production credentials or data.

## 4. Verification

`tests/contracts/test_contracts_v1.py` validates every checked-in valid example against JSON
Schema Draft 2020-12, rejects unknown fields, and exercises cross-field Pydantic invariants.
Static checks cover formatting, imports, and strict Python typing.

The checked-in schema manifest is the portable discovery entry point for later services and
clients. Runtime code must not trust a model-supplied contract name or schema as registry data.
