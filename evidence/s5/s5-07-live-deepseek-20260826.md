# S5-07-LIVE DeepSeek Provider Evidence

Status: PASS for the bounded local adapter and one explicitly acknowledged synthetic live smoke

The DeepSeek API key presence check passed without reading or emitting the value. The ignored local
`personal-deepseek` binding is enabled for PUBLIC and SYNTHETIC data only. Strict configuration
loading reported one enabled and one provisioned binding across two catalogs and eleven bindings;
it emitted only counts and the registry-hash prefix and made zero network calls.

Implemented boundaries:

- one exact DeepSeek Chat Completions HTTPS route and cataloged V4 model;
- route validation before scoped secret resolution;
- TLS default trust validation, redirect denial, one bounded non-streaming POST, and no retry;
- hash-bound instruction, canonical input, output JSON Schema, and required metrics;
- duplicate-safe bounded response parsing, exact model and usage checks, typed finish reasons, and
  documented HTTP error mapping;
- no secret in request body, provider reply, exception message, evidence, or audit contract.

Focused offline evidence on 2026-08-26:

- `uv run pytest tests/models/test_deepseek_provider.py -q`: 24 passed, zero network;
- `uv run pytest tests/models/test_deepseek_provider.py tests/models/test_model_inference.py -q`:
  66 passed after adding stable unordered-request hashing coverage;
- Ruff and strict mypy passed for the adapter and dedicated tests;
- ignored `.env` and binding preflight: `CONFIGURED`, two catalogs, eleven bindings, one enabled,
  one provisioned, zero secret output, zero network.

Final local evidence:

- complete regression before live execution: 1111 passed and one existing Windows
  control-character filename skip;
- Ruff and format before live execution: 202 files passed;
- strict mypy before live execution: 202 source files passed;
- controlled documentation: `DOC=PASS version=1.77 files=4 gates=7 ascii=true`;
- full code-graph build completed without errors; verified graph status reports 210 files, 3577
  nodes, 32540 edges, and Python, JavaScript, and Rust languages.

Before acknowledgement, the physical smoke call did not run. Processing region, retention,
training use, and commercial terms remain `UNVERIFIED` in the application-owned catalog.

## Live-smoke acknowledgement

On 2026-08-26, the operator explicitly acknowledged the unverified provider-policy states and
authorized exactly one fixed synthetic DeepSeek smoke. The approved bounds are one endpoint, model
`deepseek-v4-pro`, one physical network call, no retry, no fallback, a 256-token output cap, and
sanitized hash/identity/usage evidence only. The acknowledgement-denial preflight was executed first
and returned zero physical network calls.

## Live-smoke result

The approved command executed once and exited successfully in 7.3 seconds. It made no retry or
fallback. Sanitized result evidence:

- status: `SUCCESS`;
- provider and route: `deepseek`, `openai-chat`, `deepseek-v4-pro`;
- catalog snapshot: `DeepSeek-V4-Pro-0813`;
- finish reason: `stop`;
- output contract: valid fixed synthetic JSON;
- usage: 2697 input tokens and 196 output tokens;
- physical counts: one LLM call, zero tool calls, and one network call;
- output SHA-256: `c2f922776cfc0777b0da23bbf715866069a2a590e8c1781242a27a46b099d46e`;
- evidence SHA-256: `b5b692d1a4bbad440c0acacaf89ec34feb76519a2c30796a0699235be85c739a`;
- result SHA-256: `7a6f6f1a29a8ef5e10f9ffe070c0afd987e58b0b404410b95d40fd1313228ff4`;
- review required: true; formal-use candidate: false; secret output: false.

This smoke verifies the bounded technical path only. It does not change the provider's unverified
policy metadata, `production_eligible: false`, PUBLIC/SYNTHETIC data limit, review requirement, or
formal-use boundary.

Post-smoke verification was entirely offline: 68 provider/gateway/harness cases passed, then 1113
complete-regression cases passed with the one existing Windows filename skip. Ruff and format passed
over 204 files, strict mypy passed over 204 source files, and DOC 1.77 passed. No post-smoke test made
another DeepSeek request.
