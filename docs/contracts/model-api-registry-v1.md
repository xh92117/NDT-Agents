# Model API Registry V1

**Task:** S5-07 model API control plane and metered inference gateway

**Contract version:** 1.0.0

**Required tests:** UNIT-MODELREG, SEC-TOOLS, PROVIDER-SMOKE, OBS-AUDIT, QUICK, DOC

## 1. Boundary

This contract manages multiple model API configurations without coupling domain code to a provider
SDK. It publishes provider and model metadata, binds one provider to one tenant/project and
environment, resolves a policy-checked route, registers inspection-model profiles, and executes one
separately metered provider-neutral inference attempt. It never reveals or serializes a plaintext
secret. S5-01 provides application-owned AI-model capability metadata but deliberately denies model
execution through the physical-tool meter; S5-07 uses the distinct physical LLM-call/token meter.

The implementation is `ndt_agents.models`. The initial non-secret catalog is
`config/model-providers/deepseek-v4.v1.json`; the startup example is
`config/runtime/model-bindings.example.yaml`.

## 2. Three separate objects

1. `ModelCatalogManifest` contains application-owned provider, endpoint, model, capability, limit,
   lifecycle, compliance-verification, and official-source metadata. It contains no tenant secret.
2. `ProviderBinding` chooses a catalog provider, endpoint, default model, fallbacks, data classes,
   permission, budgets, and exact environment/tenant/project scope. Its credential field is an
   S1-11 `SecretSelector`, never a value.
3. `ResolvedModelRoute` is the result of authorization. It contains the immutable registry hash,
   selected model snapshot, endpoint, bounded limits, permission version, and the same secret
   selector. A later adapter may request a short-lived secret lease only after this resolution.

Catalog content and bindings form one deterministic registry SHA-256. Any provider, endpoint,
model, capability, policy, limit, secret selector, or binding change creates a different snapshot.

## 3. Resolution order

The registry validates, in order:

1. expected registry SHA-256;
2. published and enabled binding;
3. exact environment, tenant, project, and permission version;
4. explicit network permission and required RBAC permission;
5. allowed data class and input/output token limits;
6. requested or default/fallback model and required capabilities;
7. exact provider, endpoint protocol, model version, and catalog limits.

Every allow or deny decision emits one hash-only `MODEL` audit event. A failure has a stable error
code, retryability flag, and required next action. Configuration-only resolution makes no physical
provider call and consumes no API quota.

## 4. Startup configuration bootstrap

`NDT_MODEL_CONFIG` selects one explicit strict YAML document. The checked-in example contains only
catalog paths, provider/model policy, exact tenant/project/environment scope, budgets, and an
environment-variable name plus immutable secret version. It never contains the API key. Local
copies use `config/runtime/*.local.yaml` and are ignored by Git.

`NDT_MODEL_ENV_FILE` may explicitly select an ignored literal `NAME=VALUE` file for local or CI
development. The file is not auto-discovered and supports no shell expansion, `export`, duplicate
variables, YAML anchors, or aliases. The process environment has precedence over that file. Reads
are bounded and require UTF-8 without BOM. Enabled bindings require a non-empty referenced secret;
disabled bindings may assemble without one. Staging and production reject this environment-backed
secret source and require a later managed adapter.

Startup builds a typed `ConfiguredModelRuntime`, validates that catalogs and bindings produce one
registry hash, retains secret material only in a non-serializable read-only provider, and exposes
only non-secret counts and hashes in status. `build_registry(audit)` is the future audited execution
boundary. Bootstrap itself makes no provider-network call.

## 5. Inspection-model profiles and inference

`InspectionModelProfile@1.0.0` binds an exact catalog provider, model, and snapshot to sorted NDT
method, structure, and material applicability; the S5-06 input schema hash; one strict local-only
output schema and hash; training and validation evidence scope; Decimal quality thresholds;
runtime and resource bounds; declared provider failures; and report eligibility. A formal profile
requires explicit validation evidence and still requires independent review and qualified human
confirmation.

`ModelInferenceRequest@1.0.0` binds exact scope/task/run/call/request, API and profile registry
hashes, profile, canonical manifest, application-owned instruction identity/version/hash, bounded
canonical parameters, data class, capabilities, network authorization, token reservations, and
formal-use intent. Preflight denial makes zero provider calls. An accepted request reserves one LLM
call and total tokens, invokes one injected provider at most once, completes actual token telemetry,
and never increments the physical-tool counter or performs an implicit fallback call.

Provider replies are untrusted. Exact identity, token usage, immutable artifacts, strict output
schema, declared failures, retryability, and quality thresholds are validated before output reaches
agent context. Timeout, cancellation, refusal, incomplete, rate limit, provider failure, malformed
reply, usage overflow, schema failure, threshold failure, and budget overrun remain typed. Evidence
and hash-only MODEL audit bind exact route, provider, endpoint, model snapshot, profile, canonical
input, instruction, parameters, output, artifacts, usage, latency, confidence, metrics, status, and
call count without storing a plaintext secret or full canonical payload.

## 6. DeepSeek V4 candidate

The catalog records the official OpenAI-compatible base URL and current model IDs checked on
2026-08-24. The personal-development binding policy is:

- provisional default: `deepseek-v4-pro`;
- configurable fallback: `deepseek-v4-flash`;
- experimental vision entry: `deepseek-v4-flash-vision-exp`, not in the default binding;
- data classes: public and synthetic only;
- production eligibility: false;
- processing region, retention, training use, and commercial terms: unverified;
- physical model calls: disabled until the remaining policy, secret, gateway, and smoke conditions
  are met.

Current pricing is deliberately not hardcoded in the registry. A later cost policy must reference a
dated provider source and version because prices can change independently of code.

## 7. Adding another API

To add a provider without changing domain code:

1. add one strict catalog entry with official HTTPS sources and compliance-verification states;
2. add exact model IDs, snapshots, protocols, capabilities, and provider limits;
3. create a tenant/project binding containing only a scoped secret selector;
4. run `UNIT-MODELREG`, `SEC-TOOLS`, `PROVIDER-SMOKE`, and `OBS-AUDIT`;
5. publish the new registry snapshot and invalidate contexts or caches that reference the old hash;
6. enable the binding only after its secret reference, data policy, and environment are approved.

Do not place an API key in chat, source, JSON, Markdown, committed environment examples, logs,
traces, evidence, or exception text. The local/CI read-only environment adapter is implemented;
production secret-provider selection remains a separate S1-11 operational concern.

## 8. Deferred live integration

Before the first DeepSeek call, complete or explicitly approve:

- provider processing/storage region, retention, training-use, and commercial/exit terms;
- a production managed secret-provider binding and rotation test;
- an approved live provider adapter that resolves a short-lived secret lease only after S5-07 route
  authorization and never exposes the value to a contract, log, exception, or evidence record;
- synthetic live `PROVIDER-SMOKE` with usage, latency, model snapshot, endpoint, and evidence hashes;
- fallback rules that cannot move confidential or restricted data to another provider.

Until then, the deterministic fake remains the only selected executable model route.
