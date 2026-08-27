# S6 Desktop Client Contract V1

## Status

S6-02 application runtime candidate, contract version `1.2.0`. The desktop package is default-deny and does not
approve production deployment, formal conclusions, physical actions, signing, or publication.

## Dependency and package boundary

The local candidate pins Rust `1.98.0`, Tauri CLI `2.11.4`, Tauri `2.11.5`, tauri-build `2.6.3`,
and every direct Rust dependency. npm and Cargo lock files bind transitive resolution. The only
packaged origin is the application-owned local frontend. No remote origin receives IPC access.

The local task profile builds an unpackaged executable. Windows signing, installer production,
upgrade, rollback, and release-candidate qualification remain separate external evidence.

## Capability boundary

One exact window label, `main`, receives one generated application permission:
`allow-desktop-bridge-status`. The build manifest also declares `desktop_bridge_invoke` and
`desktop_bridge_cancel`, but the capability grants neither command. No core, shell, process,
filesystem, dialog, HTTP, updater, or plugin permission is enabled.

The content security policy blocks network connections, objects, frames, base rewrites, and form
submission. The frontend stores no credential or session data and can query readiness only.

## Native bridge contract

The Rust boundary and Python service share checked-in camelCase golden JSON for invoke, cancel, and
typed error envelopes. Both compute SHA-256 over the same compact, recursively key-sorted UTF-8 JSON.
Invoke accepts an opaque session handle, task and run UUIDs, exact lowercase SHA-256 registry
version, one exact compiled reference-adapter name and version, bounded JSON object, and bounded
idempotency key. Cancel is a distinct envelope bound to the same session, task, run, and registry,
the exact target request hash, and a 512-byte UTF-8 reason. Unknown fields, nil identities, malformed
hashes, changed versions, unknown tools, non-object arguments, and oversized input fail before any
executor action.

The frontend cannot supply tenant scope, permissions, approval bindings, executable identity, path,
network destination, retry policy, or budget authority. The application-owned desktop service hashes
rather than persists the opaque handle, resolves exact task, run, tenant, project, user, permission,
policy, registry, allowlist, observation, budget, and expiry state, and then uses the existing shared
Tool Registry invocation path. Registry permission, approval, destination, schema, budget,
idempotency, ToolResult, and hash-only audit controls remain authoritative. Missing, expired,
mismatched, stale, or unauthorized sessions stop before the provider, and replay uses the committed
same-scope registry result without a second physical call.

A valid cancellation request is checked against application-owned session, task, run, and registry
authority and records a hash-only denial audit. Until a qualified cancellation adapter is installed,
it returns `DESKTOP_CANCEL_UNAVAILABLE`; accepting the request never implies that a provider or
physical device stopped.

The native scaffold returns `DESKTOP_SESSION_REQUIRED` for invoke and
`DESKTOP_CANCEL_UNAVAILABLE` for cancel after request validation and makes zero
adapter, process, shell, file, network, instrument, model, approval, or publication action. The Rust
command is not yet bound to the application service. If a session is installed without that qualified
fixed executor, the required next state is `DESKTOP_EXECUTOR_UNAVAILABLE`.

## Remaining acceptance work

S6-02 remains in progress until the qualified ABI is bound to one fixed application service process,
the invoke and cancel permissions are enabled only for exact qualified commands, and malformed IPC,
path, tenant, permission, approval, audit, package, signing, upgrade, rollback, and desktop E2E tests
pass.
