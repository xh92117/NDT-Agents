# S6-02-LOCAL-APP Local Web Composition Evidence

## Status

`PASS` for the mutable local candidate on branch `codex/s6-02-local-workbench`, based on commit
`798b539` plus the recorded working-tree change. This is local task evidence, not immutable PR or
release evidence.

## Scope

The project now installs its `src` package with pinned `uv_build==0.11.20`, exposes the
`ndt-agents` console entry point, and keeps the default application health-only. The explicit
local setting composes the existing General delegate, Workbench runtime, exact-scope ephemeral
identity, and Web shell on `127.0.0.1` only. The browser receives an HttpOnly SameSite session
cookie and never receives a configured provider secret.

The authenticated `GET /v1/workbench/capabilities` response is the server authority for enabled
task classes. The ordinary local composition reports `GENERAL_LOCAL` and only `G0`; the Web shell
constructs its selector from that response and does not publish P2, P3, or K1 routes.

## Verification

Environment: Windows, CPython 3.12.13, uv 0.11.20, zero physical model, tool, or network calls.

| Check | Command or method | Result |
|---|---|---|
| Focused task tests | `uv run pytest tests/runtime/test_local_workbench_app.py tests/client/test_web_workbench.py tests/client/test_general_model_workbench.py tests/client/test_professional_workbench.py tests/tools/test_deepseek_workbench_live_server.py -q` | PASS, 25 tests |
| Complete regression | `uv run pytest -q` and collection count | PASS, all 1149 collected tests; one documented Windows skip because control-character filenames are unavailable |
| Format | `uv run ruff format --check src tools tests` | PASS, 217 files |
| Lint | `uv run ruff check src tools tests` | PASS |
| Type safety | `uv run mypy src tools tests --strict` | PASS, 217 source files |
| Controlled docs | `uv run python tools/check_controlled_docs.py` | PASS, version 1.93, four ASCII files, seven gates |
| Packaging | `uv build` | PASS, source distribution and wheel |
| Wheel assets | inspected the wheel ZIP for `index.html`, `workbench.js`, and `workbench.css` | PASS, all three required assets |
| Default console check | `uv run ndt-agents --check` | PASS, health-only and local mode false |
| Local startup smoke | started `uv run ndt-agents`, requested the local session, shell, and capability endpoints, then stopped the server | PASS; 303 session redirect, HttpOnly SameSite cookie, 200 shell, `GENERAL_LOCAL`, G0 only |
| Dependency audit | `PYTHONUTF8=1 uv run pip-audit` | PASS, no known vulnerability; the local package is not present on PyPI and was skipped |
| License and SBOM binding | refreshed official PyPI metadata, generated CycloneDX, and ran `tests/baseline/test_license_evidence.py` | PASS; 109 components, including pinned development build backend `uv-build` |
| Code graph | `code-review-graph update` and `status` at the exact repository root | PASS, 237 files, 3999 nodes, 36478 edges |
| Convergence audit | audit mode, convergence focus over changed entry points, configuration, routes, source, tests, and startup evidence | PASS, no actionable redundant, unreachable, stale-flag, compatibility, or unused-dependency finding |
| Diff integrity | `git diff --check` | PASS; informational Git line-ending notices only |

The first complete regression exposed one stale hash in the pending S0 approval packet after the
new build dependency changed the SBOM. The packet was versioned to 1.5.0 and rebound to the exact
SBOM, license evidence, decision, and lock hashes; the focused license test and the complete
regression then passed.

## Acceptance result

- Package installation, console startup, local composition, authenticated capabilities, and
  frontend route filtering meet the S6-02-LOCAL-APP acceptance criteria.
- Unsafe host, non-local environment, disabled delegate, missing session, and unsupported task
  classes fail closed in deterministic tests.
- No professional live delegate, Review Agent model call, tool, customer data, formal conclusion,
  publication, native desktop grant, production identity, or release path was enabled.

## Remaining boundary

The local identity, task store, and session are process-local and intentionally disappear on
restart. The current directly usable frontend path is the synthetic G0 General slice. Live P1
Technical QA and Review Agent model delegates are the next functional integration step. Provider
policy approval, managed identity and secrets, durable storage, immutable protected CI, desktop
permission, production qualification, and commercial release remain separate blockers.
