# TG-05 Local Assessment

## Result

`BLOCKED` for the formal TG-05 phase gate. All S5 implementation tasks are locally complete and the
assigned deterministic test groups pass, but local uncommitted evidence cannot satisfy a phase
gate.

Evidence ID: `TG-05-LOCAL-20260825-01`

## Candidate identity

- Branch: `codex/s5-unified-tools`
- Base commit: `16c0c6871b23be6fc03416bdec38adfc85d7d1b9`
- Immutable build: none; the candidate includes preserved uncommitted S4 and S5 work
- Environment: local Windows, CPython 3.12.13, uv 0.11.20
- External calls: none
- Live credentials, devices, providers, and production adapters: none

S5 task source identities recorded by the task evidence are:

- S5-01 unified registry: `fbcf18018d1033f32bca7402df4e5d0d36af62baa6d16703ee1d895db7ce50e4`
- S5-02 function gateway: `73793b0498439fdad19f025087b07dd75e51e28aeeba4ddb8411de0e11315cfc`
- S5-03 Web gateway: `000d061392d53dc89b27fba4a8990f988e266c47d4d78d868509f3e0987bb63e`
- S5-04 MCP gateway: `4d24d31f4cbf535adb57e69714def8783426974905b10bf2f518e36270797426`
- S5-05 adapter SDK: `e476a15ac2b5ff6567e6ec8eab1737734dab2eae0a7687d352021f70bb012cf6`
- S5-06 canonical inspection data: `27a8c911a04c47b21a38248acd82bbd1ec05ee55024825ca982fd38a87741a94`
- S5-07 inference gateway: `473c8a7fe6568ec0cca5b93113d6cb7eb8bf17c923d5ec10dd2eae71ae9de044`
- S5-07 model profiles: `3c21d042832f41cdb41a64d69e2e618f6d5b79a6527d9032286a11084a4a9e7e`
- S5-08 reference adapters: `7ffc225aa67261124b0c21b2b52d334a5deda8790adf9cf96c54af9e96e19c0b`

These hashes identify task files, not an immutable aggregate build.

## Assigned local gate profile

The command below covers `UNIT-MODELREG`, `INT-FUNCTION`, `INT-WEB`, `INT-MCP`,
`INT-INSTRUMENT`, and `SEC-TOOLS`, plus the affected tenant, cache, budget, audit, canonical-data,
and method-Skill boundaries:

```text
uv run pytest tests/tools tests/models tests/contracts/test_canonical_inspection_data.py tests/professional/test_method_skills.py tests/security/test_platform_security.py tests/identity/test_identity_isolation.py tests/orchestration/test_budget.py tests/observability/test_audit_tracing.py tests/cache -ra
```

- Started: `2026-08-25T15:29:57.7905385+08:00`
- Ended: `2026-08-25T15:30:21.3413157+08:00`
- Result: 481 passed, 1 skipped, exit code 0
- Skip: `tests/tools/test_file_gateway.py:190`; this Windows file system cannot create the required
  control-character filename. Historical S3-02 protected Ubuntu evidence covers that fixture, but
  not this exact S5 candidate.

## Complete local validation

```text
uv run pytest -ra
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src tests
uv run python tools/check_controlled_docs.py
git diff --check
```

Results:

- Complete regression: 922 passed and the same one Windows path case skipped.
- Ruff: passed.
- Format: 337 files already formatted.
- Strict mypy: no issues in 157 source files.
- DOC: passed at controlled-document version 1.55 for four ASCII documents and seven gates.
- Diff check: passed.

The S5-08 mapped TASK profile was also rerun after its final audit-boundary change: 246 tests passed.

## Verified local boundary

- Shared registration, permission, scope, schema, network, secret, destination, approval, timeout,
  retry, byte/token, concurrency, budget, typed-result, and hash-only audit controls cover Function
  Calling, Web Search, MCP, instruments, simulators, and AI-model inference.
- Invalid inputs and unauthorized routes fail before a physical call. Accepted deterministic paths
  make the declared single call and perform no hidden retry or provider fallback.
- Exact provider/model/profile/catalog/canonical-input bindings and separate LLM, token, and
  physical-tool meters are enforced.
- The six reference methods AE, GPR, IE, MV, RT, and UT return byte-deterministic S5-06 canonical
  data through the shared Tool Registry path with exact simulated provenance.
- Canonical round trip and provenance completeness are 100 percent for the local fixtures. Invalid
  calibration and simulated origin block formal use.
- All provider and fixture output remains untrusted and review-required. No local test publishes a
  report, approval, knowledge item, or formal inspection conclusion.

## Formal TG-05 blockers

TG-05 remains blocked until the exact candidate is immutable and all applicable external evidence
is available and revalidated:

- protected CI and an exact-candidate Linux rerun;
- live Function Calling, Web Search, MCP, and model-provider probes with approved managed-secret,
  network, region, retention, training-use, and commercial-policy evidence;
- live registered command, API, SDK, DLL, file-exchange, MCP, or simulator-process adapter evidence
  as applicable, including vendor interface and commercial-license decisions;
- qualified production parser and model evaluation against approved frozen data;
- authorized calibrated real-device samples, hardware-lab runs, calibration records, and qualified
  expert-gold adjudication for all applicable methods;
- accountable security, data-rights, standards-license, provider, production, and formal-use
  approvals.

Open risks include R-002, R-003, R-005, R-007, R-008, R-009, and R-010. The local assessment does
not close or waive them. S6 has not started, and no production integration is enabled.
