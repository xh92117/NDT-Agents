# Tool Registry V1

## Scope

S1-12 provides the immutable shared registry and validated invocation boundary. S5-01 upgrades the
registry contract to schema `1.1.0` so the same application-owned boundary can describe internal,
Bash, Function Calling, Web Search, MCP, instrument, and AI-model capabilities. S3-02 file tools are
the first production-shaped adapter family migrated to the extended contract.

S5-01 publishes and authorizes metadata only. It does not enable a Function Calling provider, Web
Search provider, MCP server, physical instrument, or model inference. Concrete gateways and
adapters remain assigned to S5-02 through S5-08.

## Publication

Only application-owned `ToolDefinition` values may be published. A definition declares:

- stable name, semantic version, capability kind, transport, and namespace for MCP transport;
- strict Draft 2020-12 input and output schemas;
- tenant, project, or task data scope and local, tenant-managed, or approved-external destination;
- side-effect, idempotency, approval, retry, and recovery policy;
- permissions, secret purposes, network policy, timeout, concurrency, byte, token, and attempt limits;
- declared adapter error codes, audit owner, test owner, and mandatory test groups.

Input schemas cannot declare common plaintext credential fields. They must use a separately scoped
S1-11 secret reference. Every family has deterministic registration rules. Bash is local and
network-free. Web Search is read-only approved-external HTTP. Every MCP transport requires one
namespace. Instruments use only registered adapter transports. AI-model capabilities require a
positive token budget and are not executable through the physical-tool meter. Irreversible tools
require human approval, serial execution, idempotency, and human-review recovery.

The family-to-test mapping is enforced at publication: Bash requires `INT-BASH`, `SEC-BASH`, and
`SEC-TOOLS`; Function Calling requires `INT-FUNCTION` and `SEC-TOOLS`; Web Search requires `INT-WEB`
and `SEC-TOOLS`; MCP requires `INT-MCP` and `SEC-TOOLS`; instruments require `INT-INSTRUMENT` and
`SEC-TOOLS`; and AI models additionally require `UNIT-MODELREG`.

A registry snapshot is immutable. Its version is the SHA-256 of the sorted canonical definitions.
Replacing one name or version publishes a new snapshot and invalidates contexts and caches bound to
the prior registry version. Every published definition still requires exactly one injected adapter;
the model adapter can be used only by the separately metered S5-07 model gateway.

## Authorized exposure

`ToolRegistry.expose` creates a strict minimal manifest for one `ToolInvocationContext`. It resolves
only an exact published version or one unambiguous name, validates registry version, allowlist,
permission, secret-purpose, network, and data-destination authority, and returns only name, version,
kind, namespace, purpose, side-effect and approval flags, and the strict input schema. It excludes
output schemas, secret purposes, transports, adapters, and adapter state.

The default exposure limit is six tools and the hard limit is twelve. The default MCP namespace
limit is one and the hard limit is two. Side-effecting and approval-gated tools require explicit
exposure-policy permission. Exposure performs zero adapter, provider, network, model, MCP, or device
calls. Success and denial create correlated hash-only `TOOL` audit events, and the returned manifest
has a validated deterministic SHA-256.

## Invocation

The gateway performs these checks before an adapter call:

1. resolve an application-owned definition from the published snapshot;
2. match the expected registry version and exact task and identity scope;
3. enforce allowed tool, permissions, secret purposes, network, and data destination;
4. require an exact scope, task, run, registry, policy, tool, and input hash approval binding when
   the definition is approval-gated;
5. validate attempt and retry state, side-effect idempotency, input bytes, and strict arguments;
6. reserve one physical tool call through the S1-08 budget guard.

AI-model definitions stop before the physical-tool budget and require the later S5-07 model gateway,
which must use the separate physical LLM-call and token meters. This prevents a model call from being
misclassified as a tool call.

The adapter returns a V1 `ToolResult`. The gateway validates call, task, run, scope, tool, version,
input hash, idempotency key, status, output hash, bytes, and output schema. A non-success result must
use a declared error code or the registry-owned timeout code. Retryable output is accepted only for
a read-only definition with `RETRY_READ_ONLY` recovery. Timeouts use the declared recovery policy and
never pretend to satisfy a successful output schema.

Every invocation success, replay, denial, timeout, and invalid adapter result records a correlated
hash-only S1-10 `TOOL` audit event. Preflight denial performs zero physical calls.

S5-02 consumes only the authorized exposure manifest through the separate
[Function Gateway contract](./function-gateway-v1.md). The model-visible function schema does not
replace this registry contract and cannot select a tool version, adapter, retry, idempotency key,
approval, scope, or budget.

S5-03 registers the separate [Web Search contract](./web-search-v1.md) as one read-only restricted
network tool. Source policy, query/page sub-budgets, candidate evidence, citations, and retrieval
cache state remain adapter output, while this registry continues to enforce the enclosing permission,
network, destination, timeout, retry, physical-tool budget, result, and audit boundary.

S5-04 registers every [MCP Gateway contract](./mcp-gateway-v1.md) discovery, capability invocation,
poll, and cancel action as a separate tool. Static server and capability registration hashes are
bound into the definition schema; exact discovery, post-authorization credential issuance, scoped
async state, stream and artifact validation, and disconnect recovery remain gateway behavior while
this registry remains the enclosing authorization, budget, idempotency, timeout, result, and audit
boundary.

S5-05 maps each [Adapter SDK contract](./adapter-sdk-v1.md) registration to one exact instrument or
AI-model definition. The output-schema metadata binds the adapter registration hash. Instrument
execution continues through this registry; AI-model definitions remain denied here and move to the
separately metered S5-07 inference gateway.

## Security and recovery limits

Definitions contain secret purposes, never credential values. Side effects are serial and require a
stable idempotency key. An approval binding proves that an upstream approval workflow authorized one
exact input; S5-01 does not mint approvals. The core keeps a deterministic in-memory committed-result
journal for local replay tests. Durable side-effect reconciliation remains the adapter and S1-07
recovery boundary's responsibility.

The S5-01 tests use injected deterministic adapters only. Live provider policy, credential leases,
network destinations, MCP disconnect and async recovery, instrument calibration and device identity,
canonical inspection data, model inference, and durable approval integration remain required by
their assigned S5 tasks and TG-05.
