# Function Gateway Contract V1

**Contract version:** 1.0.0
**Task:** S5-02
**Status:** active local implementation

## Purpose

This contract defines a provider-neutral Function Calling boundary over the immutable shared Tool
Registry. It creates a minimal authorized function catalog and maps one validated model-produced call
to one exact registered tool version. It does not implement or contact an LLM provider.

## Trusted inputs

The application supplies the current `ToolRegistry`, `ToolInvocationContext`, `ToolExposurePolicy`,
`BudgetGuard`, trace and audit services, observation hash, retry state, attempt number, and optional
idempotency key. These values never come from the function-call JSON.

Catalog loading first calls `ToolRegistry.expose`. Each exposed tool becomes one internal binding and
one model-visible function schema. References are limited to resolvable same-document JSON Pointers;
external, relative-resource, unresolved, and named-anchor references fail without retrieval. The
model-visible schema contains only:

- `name`;
- `description`;
- strict Draft 2020-12 `parameters`;
- `strict: true`.

The internal binding additionally carries the exact tool name and version, kind, side-effect class,
approval requirement, and schema hash. These fields do not enter the model-visible schema.

## Function names and catalog binding

A function name is derived from the normalized tool name plus the first twelve hexadecimal characters
of a SHA-256 digest over the exact tool name and semantic version. Names use lower-case letters,
digits, and underscores, start with a letter, and are at most 64 characters. Duplicate generated names
fail catalog loading.

The catalog records and validates:

- contract version;
- exact Tool Registry version;
- exact exposure-manifest hash;
- SHA-256 over the complete authorization context;
- ordered internal bindings and their schema hashes;
- a content-derived catalog SHA-256;
- an HMAC-SHA-256 attestation created with an ephemeral gateway-owned key.

Any registry, exposure, permission, scope, destination, network, approval-binding, request, or policy
change requires a newly loaded catalog. A caller can recompute public content hashes but cannot mint a
valid gateway attestation; catalogs do not survive a gateway restart and must be reloaded.

## Call envelope

The untrusted call is one bounded UTF-8 JSON object with exactly three fields:

```json
{
  "call_id": "provider-call-1",
  "name": "fixture_echo_0123456789ab",
  "arguments": {"value": "example"}
}
```

`call_id` is correlation data only. It grants no authority. Retry state, attempt number, idempotency
key, approval evidence, registry identity, budget, tenant scope, tool version, and adapter selection
are forbidden in this envelope.

## Validation and execution

The gateway performs these ordered checks before calling the registry:

1. enforce the active and hard payload-byte limits;
2. decode UTF-8 without replacement;
3. reject duplicate JSON keys and non-finite numbers;
4. validate the exact envelope with strict types and no unknown fields;
5. revalidate catalog integrity and exact registry and context bindings;
6. resolve one exact internal binding by generated function name;
7. validate arguments against the bound strict input schema;
8. invoke the exact registered tool version through `ToolRegistry.invoke`.

The shared registry remains authoritative for permissions, scope, destination, network, secret
purpose, approval, attempt, retry, idempotency, concurrency, timeout, byte budget, physical-call
budget, output schema, result identity, result hash, declared errors, and audit. A successful gateway
call returns the validated `ToolResult` unchanged. No hidden retry is permitted.

## Errors and audit

Gateway validation failures use stable `FUNCTION_*` error codes with retryability and next action.
They create hash-only `function.deny` audit evidence and consume zero physical tool calls. Registry
denials retain stable `TOOL_*` codes and registry audit evidence. Successful execution creates both
the registry execution event and a hash-only `function.execute` correlation event.

Raw arguments, secrets, adapter state, and untrusted response text are never written to audit fields.

## Limits

The default function-call payload limit is 65,536 bytes and the hard limit is 1,000,000 bytes.
Catalog size and MCP namespace limits remain six and one by default, with hard limits of twelve and
two. Read-only concurrency and serial side effects remain the declared registry limits.

No live Function Calling provider, model inference, Web Search, MCP discovery, instrument action, or
network call is enabled by this task.
