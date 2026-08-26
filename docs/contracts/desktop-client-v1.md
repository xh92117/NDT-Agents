# S6 Desktop Client Contract V1

## Status

S6-02 local scaffold, contract version `1.0.0`. The desktop package is default-deny and does not
approve production deployment, formal conclusions, physical actions, signing, or publication.

## Dependency and package boundary

The local candidate pins Rust `1.98.0`, Tauri CLI `2.11.4`, Tauri `2.11.5`, tauri-build `2.6.3`,
and every direct Rust dependency. npm and Cargo lock files bind transitive resolution. The only
packaged origin is the application-owned local frontend. No remote origin receives IPC access.

The local task profile builds an unpackaged executable. Windows signing, installer production,
upgrade, rollback, and release-candidate qualification remain separate external evidence.

## Capability boundary

One exact window label, `main`, receives one generated application permission:
`allow-desktop-bridge-status`. The build manifest also declares `desktop_bridge_invoke`, but the
capability does not grant it. No core, shell, process, filesystem, dialog, HTTP, updater, or plugin
permission is enabled.

The content security policy blocks network connections, objects, frames, base rewrites, and form
submission. The frontend stores no credential or session data and can query readiness only.

## Native bridge contract

The Rust boundary accepts a strict versioned request with an opaque session handle, task and run
UUIDs, registry version, one exact compiled reference-adapter name and version, bounded JSON object,
and bounded idempotency key. Unknown fields, nil identities, changed versions, unknown tools,
non-object arguments, and oversized input fail before any executor action.

The frontend cannot supply tenant scope, permissions, approval bindings, executable identity, path,
network destination, retry policy, or budget authority. Those values must be resolved by a future
application-owned authenticated session and registry adapter.

The scaffold returns `DESKTOP_SESSION_REQUIRED` after request validation and makes zero adapter,
process, shell, file, network, instrument, model, approval, or publication action. If a session is
installed without a qualified fixed executor, the required next state is
`DESKTOP_EXECUTOR_UNAVAILABLE`.

## Remaining acceptance work

S6-02 remains in progress until the application-owned session and registry executor are installed,
the invoke permission is enabled only for the exact qualified command, and malformed IPC, path,
tenant, permission, approval, audit, package, signing, upgrade, rollback, and desktop E2E tests pass.
