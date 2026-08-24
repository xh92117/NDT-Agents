# Model API Registry V1

**Task:** S5-07 isolated API-management control plane

**Contract version:** 1.0.0

**Required tests:** UNIT-MODELREG, SEC-TOOLS, PROVIDER-SMOKE, OBS-AUDIT, QUICK, DOC

## 1. Boundary

This contract manages multiple hosted model API configurations without coupling domain code to a
provider SDK. It publishes provider and model metadata, binds one provider to one tenant/project and
environment, and resolves a policy-checked route. It does not execute inference, reveal a secret,
or complete the S5-01 unified tool gateway and S5-06 canonical inspection-data dependencies.

The implementation is `ndt_agents.models`. The initial non-secret catalog is
`config/model-providers/deepseek-v4.v1.json`.

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

## 4. DeepSeek V4 candidate

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

## 5. Adding another API

To add a provider without changing domain code:

1. add one strict catalog entry with official HTTPS sources and compliance-verification states;
2. add exact model IDs, snapshots, protocols, capabilities, and provider limits;
3. create a tenant/project binding containing only a scoped secret selector;
4. run `UNIT-MODELREG`, `SEC-TOOLS`, `PROVIDER-SMOKE`, and `OBS-AUDIT`;
5. publish the new registry snapshot and invalidate contexts or caches that reference the old hash;
6. enable the binding only after its secret reference, data policy, and environment are approved.

Do not place an API key in chat, source, JSON, Markdown, environment examples committed to Git,
logs, traces, evidence, or exception text. Local and production secret-provider adapters remain a
separate S1-11 operational concern.

## 6. Deferred live integration

Before the first DeepSeek call, complete or explicitly approve:

- provider processing/storage region, retention, training-use, and commercial/exit terms;
- a local managed secret-provider binding and rotation test;
- S5-01 model execution through the shared Tool Registry and S1-08 physical-call budget;
- strict request/response, tool-call, timeout, rate-limit, cancellation, and incomplete-state
  mapping;
- synthetic live `PROVIDER-SMOKE` with usage, latency, model snapshot, endpoint, and evidence hashes;
- fallback rules that cannot move confidential or restricted data to another provider.

Until then, the deterministic fake remains the only selected executable model route.
