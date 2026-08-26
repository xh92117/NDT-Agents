# S6-01 Web Workbench Evidence

## Candidate

- Date: 2026-08-25
- Branch: `codex/s6-clients`
- Base commit: `16c0c6871b23be6fc03416bdec38adfc85d7d1b9`
- Build state: local mutable working tree; not a phase-gate candidate
- Contract: [S6 Client API Contract V1](../../docs/contracts/client-api-v1.md)

## Delivered boundary

- Strict task-create, task-read, task-event, task-state, and SSE batch contracts.
- Exact tenant, project, user, role, and permission-version scope binding from authenticated requests.
- Default-deny permissions for create, task read, and event read on fixed routes.
- Server-owned task/event identities, exact idempotency, contiguous sequences, monotonic state,
  mandatory professional review before success, terminal-state immutability, and resumable replay.
- Responsive Web shell with CSP, safe text rendering, semantic landmarks, labels, keyboard focus,
  polite live status, reduced-motion behavior, and no browser token storage.
- In-memory deterministic repository only; zero provider, model, tool, instrument, storage, approval,
  publication, formal-use, or external network action.

## Source hashes

| File | SHA-256 |
|---|---|
| `src/ndt_agents/client/models.py` | `a57ff00dc46464f717b39465dd78ae9590ba31ce64b85bb7116860193202ca61` |
| `src/ndt_agents/client/service.py` | `3061ab7d50be026325726c2042bc9b4d77f3910b81fae0825f369e26d5fdcacd` |
| `src/ndt_agents/runtime/app.py` | `8fdb9c0ca27220b0601517090e3ce9b94ad2410123f1b6f3f5a892416ba51f7e` |
| `src/ndt_agents/identity/rbac.py` | `83fe375187f314b5c16d54e9143d03f34206e6c8d903a54a0b691dff8dfef6f4` |
| `src/ndt_agents/client/web/index.html` | `d90a262c3e04dcce38343937bfa6fe3a2368420c8beba845bb9e06697bcc36c9` |
| `src/ndt_agents/client/web/assets/workbench.js` | `eb80896161f14262ff11f7a4ae4f534622f9a46e5f8abf5e91b8f72ddba2f28f` |
| `src/ndt_agents/client/web/assets/workbench.css` | `b6464e358688024baf5b10e7a141056c1ad31d511f2586d8c40a932515a36c62` |

## Verification

| Profile | Command | Result |
|---|---|---|
| dedicated S6-01 | `.venv/Scripts/python.exe -m pytest tests/client/test_web_workbench.py -q` | 6 passed |
| affected boundary | `.venv/Scripts/python.exe -m pytest tests/client/test_web_workbench.py tests/runtime/test_api_scaffold.py tests/identity/test_identity_isolation.py -q` | 25 passed |
| full regression | `.venv/Scripts/python.exe -m pytest -q` | 929 collected; 928 passed, 1 documented Windows path skip |
| lint | `.venv/Scripts/python.exe -m ruff check .` | passed |
| format | `.venv/Scripts/python.exe -m ruff format --check .` | 343 files formatted |
| typing | `.venv/Scripts/python.exe -m mypy` | passed over 169 source files |
| documentation | `.venv/Scripts/python.exe tools/check_controlled_docs.py` | DOC 1.56 passed |
| whitespace | `git diff --check` | passed |

The code graph full refresh completed without parser errors: 147 files parsed, 2,262 raw nodes and
19,785 raw edges before post-processing; verified aggregate statistics reported 145 indexed Python
files, 2,234 nodes, 19,630 edges, 197 flows, and 20 communities. The graph tool does not index
untracked client files until they enter Git, so its changed-file test-gap warning is not treated as
coverage evidence; direct tests and full regression are authoritative for this mutable candidate.

## Remaining limits

- No durable event store, queue, multi-process stream fan-out, proxy qualification, or 100-user load.
- No live browser matrix, screen-reader audit, production OIDC session adapter, or penetration test.
- No immutable commit, protected CI, TG-05 clearance, TG-06 evidence, release approval, or deployment.
- S6-02 through S6-10 remain separate tasks; S6-08 requires seven real elapsed days.
