# S5-07 Metered Inference Gateway Evidence

## Result

`PASS` for the local S5-07 task profile. This is not live provider, TG-05, immutable PR, or
production evidence.

Evidence ID: `S5-07-TASK-20260825-01`

This local task uses only an injected deterministic provider and cannot satisfy live
`PROVIDER-SMOKE`, production provider policy, managed-secret, hardware, or immutable protected-CI
requirements.

## Candidate identity

- Branch: `codex/s5-unified-tools`
- Base commit: `16c0c6871b23be6fc03416bdec38adfc85d7d1b9`
- Immutable build: none; the workspace contains preserved uncommitted S4 and S5 work
- Profile source SHA-256: `3c21d042832f41cdb41a64d69e2e618f6d5b79a6527d9032286a11084a4a9e7e`
- Inference source SHA-256: `473c8a7fe6568ec0cca5b93113d6cb7eb8bf17c923d5ec10dd2eae71ae9de044`
- Model package export SHA-256: `6fa54fe8cc6c122877c420a2d913f7cdf3a5ca2cc3ee6df2305e78b5254e60d0`
- Dedicated-test SHA-256: `72817d3c054d385d45663cf02ce4087cebcd3aed5a657e4d10a2ab13a56b8305`
- Contract-document SHA-256: `10d877035eed0ee1c6fc9cc1b8af92970fcb0a8c1306f042ac288f557420de99`

## Implemented boundary

- Application-owned inspection-model profiles bind the exact provider/model snapshot, canonical
  S5-06 input-schema hash, method/structure/material applicability, strict local-only resolved
  output schema, training and validation scope, Decimal thresholds, pinned runtime/resources,
  declared provider errors, retryability, and report eligibility.
- Profile, registry, request, provider request, evidence, and result identities are deterministic
  content hashes. Unknown, stale, duplicate, untrusted, cross-catalog, unresolved-schema, tampered,
  unbounded, or unsupported profiles fail closed.
- One request binds the exact scope, task, run, call, API and profile registry versions, canonical
  manifest, application instruction, parameters, data class, capabilities, network decision, token
  reservations, and formal-use intent.
- Route, profile, instruction, canonical processing/formal eligibility, applicability, resource,
  permission, network, token, and budget checks complete before provider execution. Denial performs
  zero provider calls.
- One authorized attempt reserves and completes exactly one physical LLM call and actual input and
  output tokens. It never increments the physical-tool counter, retries, or falls back after a
  physical attempt.
- Success, refusal, incomplete, rate limit, cancellation, timeout, typed and generic provider
  failure, malformed reply, identity and artifact mismatch, usage overflow, schema failure, quality
  threshold failure, and budget overrun remain typed and preserve bounded evidence.
- Provider output is untrusted and review-required. Formal-use candidates require an independently
  validated profile, formal-eligible production canonical data, and qualified human confirmation.
  No report conclusion, approval, publication, instrument, device, or model action occurs locally.
- Evidence and correlated hash-only MODEL audit bind the exact route, model, profile, canonical
  manifest, instruction, parameters, output, artifacts, token usage, latency, confidence, metrics,
  status, and call count. Plaintext secrets, full canonical payloads, provider diagnostics, and
  provider-supplied failure prose are excluded.

## Reproducible checks

Dedicated S5-07 boundary:

```text
uv run pytest tests/models/test_model_inference.py -q
```

Result: 41 tests passed.

Mapped task profile:

```text
uv run pytest tests/models tests/contracts/test_canonical_inspection_data.py tests/tools/test_adapter_sdk.py tests/tools/test_tool_registry.py tests/tools/test_unified_tool_registry.py tests/security/test_platform_security.py tests/identity/test_identity_isolation.py tests/orchestration/test_budget.py tests/observability/test_audit_tracing.py -ra
```

Result: 275 tests passed.

Complete regression:

```text
uv run pytest -ra
```

Result: 880 tests passed and one test skipped. The inherited Windows skip is
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

Result: Ruff passed; all 163 Python files were formatted; strict mypy passed over 163 source files;
`DOC` passed at version 1.53 for four ASCII controlled documents and seven gates; the diff check
passed.

## Code graph

The verified persisted graph remains the exact repository snapshot at base commit
`16c0c6871b23`: 145 files, 2,228 nodes, and 19,583 edges. The new S5 source and tests are untracked
in the preserved mutable workspace, so the graph cannot ingest them until they are tracked. Direct
static analysis, contract tests, task tests, and complete execution cover this local boundary;
immutable PR review must refresh the graph after tracking the files.

## Remaining limitations

- No live provider call, network transfer, managed secret lease, production model, or hardware
  benchmark ran. Provider region, retention, training-use, and commercial metadata remain
  unapproved.
- No authorized real-device data, production parser, qualified expert gold result, or formal-use
  profile evidence was available.
- S5-08 and TG-05 remain pending.
- There is no immutable build, protected PR CI result, or exact-candidate Linux rerun.
- Existing phase-gate, security, license, rights, live-service, and accountable-approval blockers
  remain unchanged.
