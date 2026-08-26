# S6-02 Desktop Scaffold Evidence

## Scope

- Task: `S6-02`
- Branch: `codex/s6-02-tauri`
- Environment: local Windows 10.0.26200 x86_64
- Candidate state: mutable local scaffold, not an immutable release candidate
- Toolchain: Rust and Cargo 1.98.0, Tauri CLI 2.11.4, Tauri 2.11.5,
  tauri-build 2.6.3, Visual Studio Build Tools 17.14.39, Windows SDK 26100

## Implemented boundary

- Added exact npm, Cargo, and Rust toolchain pins plus lock files.
- Packaged one application-owned local frontend into one exact Tauri window.
- Granted only generated `allow-desktop-bridge-status` permission to the local window.
- Registered but did not grant `desktop_bridge_invoke`.
- Added a strict native request envelope with fixed schema, tool, version, identity,
  JSON-object, byte-budget, and idempotency validation.
- Returned `DESKTOP_SESSION_REQUIRED` after validation with zero executor or external action.
- Added a restrictive content security policy with network connections disabled.
- Reused the existing Web workbench SVG to generate deterministic desktop icon resources.

## Test-first record

Before the scaffold existed, `uv run pytest tests/client/test_desktop_client.py -q`
failed all five new tests because the package, capability, bridge, frontend, and contract
files did not exist. After implementation and generated permission validation, the same
profile passed all five tests.

## Local verification

| Command | Result |
|---|---|
| `cargo test --locked` | PASS; 3 Rust unit tests passed; doctests are disabled because this cdylib has no documentation examples and local Windows application control blocks `rustdoc.exe` |
| `cargo clippy --locked --all-targets -- -D warnings` | PASS |
| `cargo fmt --all -- --check` | PASS |
| `uv run pytest tests/client/test_desktop_client.py -q` | PASS; 5 tests |
| `npm run desktop:test` | PASS; 2 status behavior tests cover protected readiness and non-disclosing IPC denial |
| `uv run pytest` | PASS; 1025 tests passed and one documented Windows control-character filename case skipped |
| `uv run ruff check src tools tests` | PASS |
| `uv run ruff format --check src tools tests` | PASS; 188 files formatted |
| `uv run mypy` | PASS; 188 source files |
| `uv run python tools/check_controlled_docs.py` | PASS; DOC 1.71, four ASCII controlled files, seven gates |
| controlled artifact regeneration and `git diff --check` | PASS; no generated drift or whitespace error |
| code graph update and status | PASS; 210 files, 3575 nodes, and 32475 edges on commit `1d170440bd52`; JavaScript, Python, and Rust detected |
| `npm run desktop:check` with the rustup bin path exposed to the inherited process | PASS; exact Rust, Cargo, rustup, Tauri, WebView2, and MSVC detected |
| `npm run desktop:build` with the rustup bin path exposed to the inherited process | PASS; release no-bundle executable generated at `clients/desktop/src-tauri/target/release/ndt-agent-desktop.exe` |

The initial release build completed in 7 minutes 28 seconds. The target directory is ignored
and the executable is local build evidence only.

The pre-commit MCP refresh initially missed staged Rust files. The required post-commit CLI refresh
parsed Rust and bound the graph to commit `1d170440bd52`. The Rust bridge, build manifest, generated
permissions, and capability were also reviewed directly and validated by Rust unit tests, strict
Clippy, formatting, static security assertions, and the Tauri release build.

## Security result

The packaged frontend can query readiness only. It has no invoke call, fetch, token storage,
unsafe HTML insertion, shell, process, filesystem write, network client, permission grant,
approval, review, formal-use, or publication path. The ungranted native invoke command validates
input and then stops before an executor because no application-owned authenticated session exists.
Change review found no remaining high-, medium-, or low-severity defect. Its initial frontend behavior
test gap was closed with two dependency-free Node tests before this evidence was finalized.

## Remaining work

`S6-02` remains `IN_PROGRESS`. This evidence does not qualify an authenticated session or
registry executor, exact tenant/project/user/permission binding, approval and budget authority,
idempotent execution, result/audit binding, path safety, installer, signing identity, upgrade,
rollback, live desktop E2E, immutable protected CI, `TG-06`, or commercial release.
