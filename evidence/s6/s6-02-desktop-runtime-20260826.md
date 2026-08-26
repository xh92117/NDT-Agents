# S6-02 Desktop Runtime Evidence

## Result

The application-owned desktop session and Tool Registry service boundary is implemented and locally
verified on branch `codex/s6-02-desktop-runtime` from base `51754d4e8613`. S6-02 remains
`IN_PROGRESS`; this evidence does not enable the native Tauri invoke permission or qualify release.

## Implemented boundary

- Strict desktop requests contain only an opaque session handle, task and run IDs, registry and tool
  identities, bounded arguments, and an idempotency key.
- Tenant, project, user, role, permission, policy, allowlist, approval, budget, observation, expiry,
  destination, and network authority cannot be supplied by the desktop request.
- Raw session handles are hashed before in-memory lookup and can be revoked or expired.
- Exact task, run, registry, and allowed-tool bindings are checked before Tool Registry execution.
- The existing Tool Registry remains the only adapter execution path and owns permission, approval,
  destination, strict schema, budget, idempotency, typed ToolResult, and hash-only audit enforcement.
- A same-scope idempotent replay returns the committed result without a second provider call.
- The Tauri capability remains status-only and the Rust invoke path remains zero-action.

## Test-first record

The new desktop runtime test initially failed because the application desktop module did not exist.
After implementation, a missing trace boundary was exposed and repaired by making each registry call
run inside an application trace span before audit emission.

## Verification

| Command or group | Result |
|---|---|
| `uv run pytest tests/client/test_desktop_runtime.py -q` | PASS; 9 tests |
| desktop, Tool Registry, reference adapter, budget, and audit affected set | PASS; 106 tests |
| `uv run pytest -q` | PASS; 1122 collected cases with one documented Windows skip |
| `uv run ruff check src tools tests` | PASS |
| `uv run ruff format --check src tools tests` | PASS; 206 files |
| `uv run mypy` | PASS; 206 source files |
| `uv run python tools/check_controlled_docs.py` | PASS; DOC 1.78 |
| `git diff --check` | PASS |

The deterministic UT reference provider executed once for the authorized request, zero times for
missing, expired, mismatched, stale, disallowed, and permission-denied requests, and once total across
an original plus idempotent replay. The shared audit repository recorded the authorized execution and
registry denial inside exact trace context.

## Remaining boundary

The Rust command is not yet bound to this Python application service. A fixed qualified ABI, native
session installation, generated invoke permission, malformed cross-language IPC, cancellation,
reconciliation, installer signing, package identity, upgrade, rollback, live desktop E2E, protected
CI, TG-06, and release evidence remain required. No production credential, network provider, real
instrument, physical action, approval, publication, or commercial release occurred.
