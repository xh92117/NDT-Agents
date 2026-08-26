# S5-08 Reference Adapter Evidence

## Result

`PASS` for the local S5-08 task profile. This is not real-instrument, TG-05, immutable PR, hardware-
lab, or production evidence.

Evidence ID: `S5-08-TASK-20260825-01`

This task uses application-owned in-process deterministic fixtures only. It cannot satisfy real
instrument, vendor SDK, parser qualification, calibration, hardware-lab, production, immutable CI,
or TG-05 evidence requirements.

## Candidate identity

- Branch: `codex/s5-unified-tools`
- Base commit: `16c0c6871b23be6fc03416bdec38adfc85d7d1b9`
- Immutable build: none; the workspace contains preserved uncommitted S4 and S5 work
- Reference-adapter source SHA-256: `7ffc225aa67261124b0c21b2b52d334a5deda8790adf9cf96c54af9e96e19c0b`
- Dedicated-test SHA-256: `abf549bcff8c5691515e9917962de1dee5d82d0875c0ffc011df8b3dd8f54c30`
- Contract-document SHA-256: `784a98dd9a933b9ac76f20a6c05eb19b930d7e7efe1593f44e4a1d6a45e2fe2e`

## Implemented boundary

- One immutable registry contains exactly AE, GPR, IE, MV, RT, and UT in stable order. Every profile
  binds its S4-05 method-definition hash, S5-05 simulator binding and registration hashes,
  deterministic fixture hash, S5-06 version, signal, calibration, acquisition settings, parser,
  instrument, device, and calibration identities.
- All registrations are local, network-free, credential-free, task-scoped, permission-gated,
  read-only, one-attempt, serial, bounded, and application-owned. The caller can select only the
  exact registered fixture identity; method, transport, parser, device, calibration, and output
  identities are outside the model-visible input.
- One authorized call consumes one physical-tool call, invokes one in-process deterministic provider
  once, and returns a strict S5-05 untrusted envelope. It consumes zero physical LLM calls and makes
  zero network, secret, command, subprocess, real-device, approval, publication, or retry actions.
- The consumer re-parses canonical UTF-8 through S5-06 and verifies exact scope, method, simulated
  origin, profile, fixture, registration, manifest, adapter, device, calibration, parser, signal,
  unit, and acquisition identities. Every method is processing-eligible and formally ineligible.
- Repeated execution produces byte-identical canonical payloads. Chinese, whitespace, leading-dash,
  and newline source metadata round-trip exactly.
- Stale registry/profile/fixture, unknown method, wrong permission/tool/destination, budget denial,
  caller-added fields, provider identity/error/generic failure/timeout, oversized output,
  non-canonical JSON, hash tampering, production-origin injection, and cross-scope canonical output
  remain typed. Preflight denial makes zero provider calls; post-call failure has no hidden retry.
- Successful calls create the shared `tool.execute` audit plus a separate
  `reference.adapter.validate` audit. Both are hash-only and exclude the canonical payload.

## Reproducible checks

Dedicated S5-08 boundary:

```text
uv run pytest tests/tools/test_reference_adapters.py -q
```

Result: 42 tests passed.

Mapped task profile:

```text
uv run pytest tests/tools/test_reference_adapters.py tests/tools/test_adapter_sdk.py tests/contracts/test_canonical_inspection_data.py tests/professional/test_method_skills.py tests/tools/test_unified_tool_registry.py tests/tools/test_tool_registry.py tests/identity/test_identity_isolation.py tests/orchestration/test_budget.py tests/observability/test_audit_tracing.py -ra
```

Result: 246 tests passed.

Complete regression:

```text
uv run pytest -ra
```

Result: 922 tests passed and one test skipped. The inherited Windows skip is
`tests/tools/test_file_gateway.py:190`; this file system cannot create the control-character
filename. Historical S3-02 protected Ubuntu evidence covers that fixture, but not this exact S5
candidate.

Static, documentation, and diff checks:

```text
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
uv run python tools/check_controlled_docs.py
git diff --check
```

Result: Ruff passed; all 165 Python files were formatted; strict mypy passed over 165 source files;
`DOC` passed at version 1.54 for four ASCII controlled documents and seven gates; the diff check
passed.

## Code graph

`code-review-graph update` and `status` completed at the exact repository root. The persisted graph
reports 145 files, 2,228 nodes, and 19,585 edges at base commit `16c0c6871b23`. The S4 and S5 source
and tests are preserved untracked, so the graph cannot ingest the new reference module or tests.
Direct static analysis and all dedicated, mapped, and complete tests cover the local boundary;
immutable PR review must refresh graph analysis after the files are tracked.

## Remaining limitations

- The in-process providers are deterministic contract fixtures, not simulator processes, signal
  algorithms, vendor protocols, SDKs, DLLs, file exchanges, MCP servers, or instruments.
- No authorized calibrated real-device data, production parser, hardware-lab run, vendor license,
  qualified expert gold result, or formal-use evidence was available.
- The [TG-05 local assessment](./tg-05-local-assessment-20260825.md) is complete. Its assigned local
  profile passes, but the formal gate remains blocked on immutable and external evidence.
- There is no immutable build, protected PR CI result, or exact-candidate Linux rerun.
- Existing security, license, rights, live-service, real-data, and accountable-approval blockers
  remain unchanged.
