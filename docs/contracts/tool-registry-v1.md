# Tool Registry V1

## Scope

S1-12 provides the smallest shared registry and invocation boundary needed by later tool adapters.
It does not implement Bash, Function Calling, Web Search, MCP, instruments, or model adapters.

## Publication

Only application-owned `ToolDefinition` values may be published. A definition declares its stable
name and semantic version, strict Draft 2020-12 input and output schemas, side-effect class,
permissions, tenant and project scope requirements, timeout, retry and concurrency limits, byte and
token budgets, idempotency policy, secret purposes, network policy, audit owner, and test groups.

A registry snapshot is immutable. Its version is the SHA-256 of the sorted canonical definitions.
Replacing one name and version requires publication of a new snapshot. Callers bind the expected
registry version; a changed snapshot invalidates dependent contexts and cache manifests.

## Invocation

The gateway performs these checks before an adapter call:

1. resolve an application-owned definition from the published snapshot;
2. match the expected registry version and exact task and identity scope;
3. enforce permissions, allowed tools, secret purposes, network policy, and side-effect idempotency;
4. validate arguments against the strict declared schema;
5. reserve one physical tool call through the S1-08 budget guard.

The adapter returns a V1 `ToolResult`. The gateway validates its call, task, run, scope, tool,
version, input hash, idempotency key, status, output hash, and declared output schema before the
result enters agent context. Timeouts and contract failures are typed and never disguised as valid
tool output. Each decision records a correlated hash-only S1-10 `TOOL` audit event.

## Security and recovery limits

Definitions contain secret purposes and network policy, never credential values. Side effects are
serial and require a stable idempotency key. The core keeps a deterministic in-memory committed
result journal for local replay tests; durable external reconciliation remains the adapter and
S1-07 recovery boundary's responsibility. Concrete production adapters and live service evidence
remain required in their assigned later phases and at the applicable gates.
