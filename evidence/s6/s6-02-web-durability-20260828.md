# S6-02-WEB-DURABILITY Evidence

## Decision

- Date: 2026-08-28
- Task: `S6-02-WEB-DURABILITY`
- Result: `PASS` for local Web development qualification
- Branch: `codex/s6-02-live-professional`
- Mutable base commit: `0cd079b50c0bc8af59ad98469e0f35af94280fb2`
- Environment: local Windows, CPython 3.12.13, uv 0.11.20

This evidence qualifies restart-safe local Web task and event persistence only. It does not qualify
desktop packaging, PostgreSQL, row-level security, encryption, backup, multi-host execution,
production identity, customer data, formal conclusions, publication, immutable CI, or release.

## Implemented boundary

- One `TaskRepository` port owns task creation, exact-scope task reads, event replay, and event append.
- The deterministic in-memory adapter remains available for contract tests and explicit ephemeral
  runtimes.
- A local-only SQLite schema at version 1 stores task snapshots, events, and idempotency bindings.
- Task creation, the accepted event, and the idempotency binding commit in one write transaction.
- Event append validates the shared state-transition and review rules before the event and updated
  task snapshot commit in one write transaction.
- Reads use exact tenant, project, user, ordered role codes, and permission-version scope.
- Reopening the same database replays terminal G0 and reviewed P1 results without invoking an
  executor or provider.
- Unknown schema versions, malformed or inconsistent persisted records, locked storage, unavailable
  paths, concurrent same-sequence writes, and changed-input idempotency fail with stable typed errors.
- The local application selects SQLite only through an explicit absolute state path. Initialization
  or operation failure has no hidden retry, fallback, or in-memory substitution.

## Verification

| Check | Command | Result |
|---|---|---|
| Focused durability and Web restart | `uv run pytest tests/client/test_sqlite_workbench_repository.py tests/client/test_web_stability.py tests/runtime/test_local_workbench_app.py -q` | PASS, 16 tests |
| Client and runtime boundary slice | `uv run pytest tests/client tests/runtime/test_local_workbench_app.py tests/runtime/test_api_scaffold.py -q` | PASS, 62 tests |
| Complete regression | `uv run pytest -q` | PASS, 1,171 passed and 1 documented Windows skip; 1,172 collected |
| Lint | `uv run ruff check src tools tests` | PASS |
| Format | `uv run ruff format --check src tools tests` | PASS, 222 files |
| Types | `uv run mypy` | PASS, 222 source files |
| Controlled documents | `uv run python tools/check_controlled_docs.py` | PASS at version 2.07 |
| Working diff syntax | `git diff --check` and `git diff --cached --check` | PASS; existing line-ending notices only |

All test providers were deterministic injected implementations. This task made zero physical model,
network, tool, correction, publication, or release calls and used no customer data.

## Integrity and convergence review

- The full code graph refresh completed at 241 indexed files, 4,067 nodes, and 37,246 edges.
- Graph impact analysis reported 15 affected tracked flows and a 0.85 cumulative working-tree risk
  score. The score includes earlier staged and unstaged S6-02 work on the same dirty branch, so source
  review and focused tests were used to isolate this task.
- The new SQLite adapter and its direct test were still untracked at review time. The graph tool
  indexes Git-tracked content and therefore did not include those two files even after a full rebuild;
  they were reviewed directly and covered by focused tests, Ruff, formatting, mypy, and the complete
  regression suite. No files were staged merely to change graph visibility.
- Creation and append rules have one authoritative implementation shared by both adapters. Runtime
  composition has one explicit adapter selection point. No duplicate repository path, hidden retry,
  fallback, unreachable compatibility branch, or open convergence finding remains in task scope.

## Residual limits and next work

- SQLite is a local single-host development store. Cross-process executor ownership, durable
  background jobs, database migrations beyond schema version 1, encryption, backup, and production
  recovery remain unqualified.
- HTTP event delivery remains user-controlled bounded resume rather than a durable asynchronous
  worker or push stream.
- Desktop work remains paused until the user explicitly reprioritizes it.
