# Adapter SDK Contract V1

**Contract version:** 1.0.0
**Task:** S5-05
**Status:** active local implementation

## Purpose

This contract defines one provider-neutral SDK for instrument, engineering-application, and AI-model
adapters. It binds registered Bash/CLI, HTTP API, SDK, DLL, file-exchange, MCP, and simulator
transports to the shared Tool Registry and a common result/evidence envelope. It does not execute or
authorize a real transport, provider, instrument, model, or device.

## Transport binding

Each transport uses only the minimum stable application-owned identity:

- Bash/CLI: registered command ID and executable SHA-256, never raw command text or a dynamic path;
- HTTP API: canonical safe HTTPS base endpoint, never credentials, literal IP, fragments, query, or
  an unapproved port;
- SDK: pinned package name/version/hash and fixed entry point;
- DLL: pinned library ID/version/hash and fixed entry point, never a caller path;
- file exchange: application-owned root ID and fixed media type, never an arbitrary path;
- MCP: exact MCP server-registration SHA-256 and namespace;
- simulator: pinned simulator ID/version/fixture SHA-256, explicitly local and simulated.

Unused transport fields and invalid combinations fail before registration. Simulator, Bash/CLI,
DLL, and file-exchange bindings are local and network-free. Remote HTTP requires restricted network
and approved-external destination. MCP and SDK policy remains explicit in the registration and
cannot be inferred or expanded by provider output.

## Registration and Tool Registry mapping

An immutable adapter registration fixes capability family, origin, purpose, operation, strict input
and output schemas, transport binding, data scope and destination, permissions, secret purposes,
network, side effect, approval, idempotency, timeout, attempts, concurrency, input/output/token
budgets, device/calibration/model provenance requirements, declared errors, recovery, owners, and a
canonical SHA-256. Plaintext credential fields are forbidden.

The generated Tool Registry definition binds the registration hash in its schema metadata and maps
instrument and engineering-application adapters to `INSTRUMENT`. AI-model adapters map to
`AI_MODEL`, require a positive token budget, and remain non-executable through physical-tool
invocation; S5-07 is the only inference gateway.

## Execution and evidence

The runtime wrapper is a Tool Registry adapter, not a dynamic loader. It receives one exact trusted
invocation, builds a credential-free request containing only registered transport identity and
scope/task/run/call/input bindings, and invokes one injected provider once. It performs no hidden
retry or transport discovery.

The provider reply is strict and must bind the exact adapter and request. The wrapper validates
status, output schema, declared error and retryability, immutable exact-scope artifacts, and required
device, calibration, or model provenance. It constructs an explicitly `UNTRUSTED`, review-required
output envelope and evidence binding exact scope, task, run, call, registration, transport, origin,
input/output hashes, artifact hashes, provider operation, device, calibration, model, bytes,
duration, and one provider call. Evidence and envelope hashes are recomputed before the result enters
agent context.

## Failure boundary

Stable errors distinguish registration, transport, provider identity, provider unavailable, generic
provider failure, malformed response, output schema, provenance, artifact, and declared provider
failure. Shared registry permission, secret-purpose, network, destination, approval, idempotency,
attempt, retry, timeout, concurrency, byte/token budget, final result, and audit enforcement remains
authoritative. Errors contain no provider internals, payload, command, path, credential, or device
secret.

The S5-05 tests use injected deterministic providers and execute zero commands, network requests,
SDKs, DLLs, file exchanges, MCP calls, simulator processes, instruments, models, or devices.
