# S6-02 Web Stability Evidence

**Date:** 2026-08-28
**Task:** S6-02-WEB-STABILITY
**Branch:** `codex/s6-02-live-professional`
**Base commit:** `0cd079b`
**Evidence class:** mutable local deterministic qualification

## Scope and outcome

The authenticated local Web workbench now completes both installed execution routes without adding
a second business path:

- G0 reaches Main-to-General aggregation with three contiguous terminal events.
- P1 reaches Technical QA, mandatory independent Review, and Main aggregation with five contiguous
  terminal events and a visible `Passed` review state.
- Server `error_code`, sanitized `message`, and `next_action` fields are rendered as text in one
  actionable panel. A review failure is displayed as `Stopped`.
- Event reads are bounded to one request for initial load or one explicit resume action. There is no
  timer, hidden polling loop, retry, fallback, or correction path.
- The client ignores an already acknowledged duplicate, stops on an invalid sequence, gap, or cursor
  mismatch, and preserves the last acknowledged cursor for the next explicit resume.
- Separate creation and event-read guards prevent duplicate task submission and concurrent resume
  requests. The empty timeline state is removed after the first rendered event.

No physical model, external network, tool, customer-data, correction, formal-conclusion,
publication, release, or desktop action was used or enabled by this qualification.

## Browser evidence

An ephemeral loopback FastAPI service on `127.0.0.1:8765` used injected deterministic General and
Professional/Review providers. The in-app browser observed:

- authenticated capabilities exposed exactly G0 and P1;
- G0 completed with three events, `SUCCEEDED`, and `Rules path`;
- P1 completed with five events, `SUCCEEDED`, mandatory independent Review, and `Passed`;
- a duplicate success criterion returned the real typed `REQUEST_VALIDATION_FAILED` problem and its
  next action in the visible action panel;
- at an effective 469-pixel viewport the layout used one column, showed no horizontal overflow, and
  moved the result-panel divider to the top;
- after the final CSS correction, a P1 success showed five events with both the empty-state and action
  panel hidden;
- the browser console contained zero warnings and zero errors.

The tab and temporary service were closed after capture, and port 8765 was confirmed closed.

## Reproducible verification

Environment: Windows, CPython 3.12.13, uv 0.11.20, Node.js 24.19.0.

| Check | Result |
|---|---|
| `node --test tests/client/web-workbench.test.js` | PASS: 4 tests |
| focused Web/runtime Python profile | PASS: 26 tests |
| `uv run pytest` | PASS: 1,160 passed, 1 skipped in 153.40 seconds |
| `uv run ruff check src tools tests` | PASS |
| `uv run ruff format --check src tools tests` | PASS: 220 files formatted |
| `uv run mypy` | PASS: 220 source files |
| `node --check src/ndt_agents/client/web/assets/workbench.js` | PASS |
| `git diff --check` and `git diff --cached --check` | PASS; line-ending warnings only |
| code-review graph incremental refresh | PASS: 241 files, 4,058 nodes, 37,162 edges, zero errors |
| convergence audit | PASS: no duplicate polling path, hidden retry, stale timer, or blocking maintainability finding |

The first complete-regression attempt was interrupted externally at 43 percent and produced no test
failure. The recorded qualification result is the immediate clean rerun shown above.

## Regression coverage

The deterministic tests verify typed failed-review presentation, typed capability denial, one-request
resume from the acknowledged cursor, duplicate event suppression, concurrent-resume suppression,
event-gap stop behavior, terminal replay without a second model or review call, exact G0 and P1 event
order, mandatory Review before P1 success, and stable same-idempotency replay.

## Residual boundaries

This is local mutable evidence over an in-memory single-process repository and injected providers. It
does not qualify durable multi-process streaming, proxy behavior, production identity, assistive
technology matrices, external provider behavior, customer data, desktop packaging, immutable CI,
formal use, publication, or release. S6-02 desktop remains paused until the user explicitly
reprioritizes it.
