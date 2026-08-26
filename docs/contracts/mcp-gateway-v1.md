# MCP Gateway Contract V1

**Contract version:** 1.0.0
**Task:** S5-04
**Status:** active local implementation

## Purpose

This contract defines a provider-neutral gateway for application-approved local and remote MCP
servers. All discovery, capability invocation, polling, and cancellation operations execute as
separate tools through the shared Tool Registry. The contract does not authorize a live server,
network endpoint, subprocess, or external credential provider.

## Registration and discovery

A server registration fixes one safe endpoint, deployment class, namespace, audience, credential
policy, server version, and policy version. A capability registration fixes the exact name, version,
strict input/output schemas and hashes, permission, side-effect class, destination, timeout,
streaming bounds, async support, and recovery behavior. Remote endpoints require HTTPS, restricted
egress, and short-lived brokered credentials. Local endpoints use the application-owned
`mcp+local` scheme and cannot be redirected or upgraded to a remote destination.
The registry definition binds the exact server and capability registration hashes so an endpoint,
audience, schema, policy, or capability change produces a different registry snapshot.

Discovery is a separate read-only MCP definition and physical call. Its response is untrusted and
bounded. The gateway canonicalizes it and requires an exact match to the static application
allowlist. Discovery cannot add tools, permissions, schemas, side effects, destinations, async
support, or streaming support and cannot mutate the Tool Registry. Changed or malformed manifests
invalidate invocation until an application-approved registration version is published.
Discovery manifests have an application-bounded lifetime of at most one hour; the local default is
five minutes. A new invocation requires the current unexpired exact manifest. Prior manifests remain
available only to poll or cancel already-bound asynchronous work, so a safe refresh cannot orphan a
running handle or authorize new work against stale discovery.

## Authorization and credentials

The Tool Registry authorizes exact tool, scope, permission, secret purpose, network, destination,
approval, idempotency, timeout, retry, and budget state before the gateway issues a credential or
contacts a transport. A remote lease is short-lived, least privilege, and bound to tenant, project,
user, permission version, server audience, capability permission, and policy version. The secret
value is excluded from serialization and is visible only to the injected transport for that exact
operation. Local servers use no credential lease.

Caller-supplied tokens, credentials in endpoints or schemas, discovered authorization expansion,
cross-namespace routing, literal-IP remote endpoints, fragments, and non-HTTPS remote routes fail
closed. Credential values never enter model context, arguments, state, artifacts, result payloads,
errors, logs, or audit events.

## Execution and asynchronous state

Invocation, polling, and cancellation are separate registered MCP definitions. Synchronous
completion returns a bounded validated output. An accepted asynchronous response creates an opaque
local handle bound to the exact tenant, project, user, permission version, original task and run,
server and capability versions, and canonical input hash. The remote task identifier remains
application state and is never an authorization token.
Launching asynchronous work is a reversible operational side effect even when the remote capability
only reads business data, so the launch is serial, idempotency-keyed, and reconciliation-only.

Poll and cancel require the original binding. Wrong scope, user, task, run, server, capability, or
terminal-state replay fails before credential or transport use. State transitions are monotonic.
Cancellation is idempotent for the same bound pending task. A disconnect or malformed response does
not advance or corrupt the last valid state.

## Streaming, artifacts, and failure

Streaming chunks require contiguous indexes, stable media type, and bounded chunk count and total
bytes. Inline completed output and summary remain bounded. A result above the inline threshold must
carry immutable same-scope artifact references with exact size and SHA-256; the gateway returns only
the summary and references.

Stable errors distinguish endpoint, registration, discovery, schema-change, credential, scope,
state, stream, artifact, malformed response, disconnect, provider, timeout, and cancellation
conditions. Errors contain no fabricated output or credential material. The shared Tool Registry
continues to validate the final `ToolResult`, declared errors, retryability, identity, output hash,
byte budget, and hash-only audit record.

All provider summaries, outputs, and stream content remain explicitly `UNTRUSTED` data and cannot
change instructions, permissions, routing, registrations, or approval state. An artifact reference
must be immutable, exact-scope, and bind the canonical completed payload size and SHA-256.

The S5-04 test transport and credential broker are deterministic in-memory fakes and perform zero
live MCP, network, subprocess, or external secret operations.
