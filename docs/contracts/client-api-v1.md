# S6 Client API Contract V1

## Status

S6-01 local candidate, contract version `1.0.0`. This contract is provider-neutral and does not
approve production deployment, formal conclusions, physical actions, or publication.

## Routes

| Method | Exact route | Permission | Result |
|---|---|---|---|
| `POST` | `/v1/workbench/tasks` | `workbench:task:create` | persists and schedules, or replays, one exact-scope task |
| `GET` | `/v1/workbench/task` | `workbench:task:read` | reads one task selected by validated `task_id` query data |
| `GET` | `/v1/workbench/events` | `workbench:event:read` | incrementally streams bounded SSE batches after `after_sequence` |
| `GET` | `/v1/workbench/capabilities` | `workbench:capability:read` | returns server-owned enabled task classes and limitations |

The identity middleware derives scope from an approved bearer identity and exact tenant/project
headers. Client bodies cannot provide or override scope, user, roles, permission version, task ID,
state, event sequence, review, approval, result, or formal-use state.

## Task creation

Input is strict JSON with schema version `1.0.0`, one registered task class, a trimmed goal of at most
8,000 characters, 1 to 20 unique trimmed success criteria, and a bounded idempotency key. Reusing an
idempotency key with the same exact scope and request returns the original task. Reuse with changed
input returns `CLIENT_IDEMPOTENCY_CONFLICT` and makes no change.

Every new task starts at sequence 1 and state `ACCEPTED` with the message that Main Agent routing is
pending. Task, accepted event, idempotency binding, and pending execution record commit atomically.
The POST response returns that durable accepted state without waiting for executor completion. By
default this boundary does not call an LLM, tool, provider, instrument, review, approval,
publication, or formal conclusion service.

In the explicitly acknowledged, local-only S6-02-APP profile, one bounded in-process coordinator
claims accepted work and continues it in the background through `RUNNING` and one terminal event
after Main routing, one configured General child, one bounded model-gateway attempt, and Main
aggregation. Idempotent replay returns the same task and never schedules a second execution.
Non-G0 tasks, wrong-scope model bindings, missing
configuration, and budget denial fail before the provider; provider or schema failure makes at most
one call and emits a typed failed event. The displayed result always states that the input is
SYNTHETIC, the model evidence remains review-required, and formal use is forbidden.

The default-off S6-02-LOCAL-APP composition installs the package and console entry point, binds only
to the exact loopback host, creates one ephemeral same-origin HttpOnly session in memory, and grants
only the four Workbench permissions above. It requires the existing local General delegate and exact
provider-policy acknowledgement. The capability response is derived from installed executors rather
than client input. The initial local composition reports only G0. When the separately default-off
professional model composition is enabled, the reviewed application composition reports G0 and P1;
P1 success requires one Technical QA model result, one independent Review Agent PASS, a bound review
manifest, and reviewed-professional Main aggregation. P2, P3, and K1 are not advertised. Startup
and `--check` make no provider call.

## Event replay

Events are immutable and sequence-contiguous. A client reconnects with the last acknowledged
sequence and receives only later events. A cursor beyond the current sequence returns
`CLIENT_EVENT_CURSOR_INVALID`. The server preflights the cursor before opening the response, then
waits on committed repository notifications and pushes each later batch without repository polling.
The stream closes when the task is terminal or a configured wait, total-duration, or batch bound is
reached. Each batch is followed by a `stream-state` control event carrying the current last sequence
and terminal flag. The Web shell decodes response-body chunks incrementally, including split UTF-8
characters, and renders complete SSE blocks before the connection closes. It ignores an already
acknowledged duplicate, stops on a sequence gap or cursor mismatch, and offers one explicit
user-controlled resume action from the last rendered sequence after a bounded nonterminal close. It
does not use an unbounded polling or retry loop. Terminal history is replayable and no event route
performs a side effect.

The in-memory repository remains deterministic test and contract-only support. The explicit local
Web composition may instead use SQLite persistence format version 2 through one shared repository
port. Version 1 databases migrate atomically at startup. Task creation, its accepted event,
idempotency binding, and pending execution record commit in one transaction. Event append, task
replacement, and terminal execution completion commit in one transaction, while event replay reads
task metadata and events from one snapshot. An execution claim contains an exact owner and bounded
lease. Exact tenant, project, user, role, and permission-version scope is stored and checked on every
object.

Reopening the same database preserves the task, contiguous event history, terminal state,
same-input idempotency, and execution ownership. An expired claim whose task remains `ACCEPTED` may
be reclaimed by the one local coordinator and executed once. An expired claim whose task already
advanced to `RUNNING`, `REVIEW_REQUIRED`, or `HUMAN_REQUIRED` becomes `BLOCKED` with
`CLIENT_EXECUTION_RECOVERY_REQUIRED` and makes zero executor or provider calls. This avoids guessing
whether an interrupted external action already happened. Process shutdown cancellation preserves
the last committed nonterminal state and claim instead of fabricating a terminal event. A terminal
replay never dispatches the executor again. Changed-input replay,
cross-scope access, invalid sequence or transition, review bypass, concurrent same-sequence append,
unsupported schema version, malformed persisted payload, database lock, and unavailable filesystem
fail with stable non-disclosing errors. The adapter makes no hidden retry and never falls back to the
in-memory repository. Its path is an explicit local-only startup setting and is never returned by a
Workbench route.

SQLite is local restart-recovery evidence only. Recovery sweeps, batch size, concurrent owned tasks,
SSE wait, SSE duration, and SSE batch count are bounded by one versioned policy. This local
qualification assumes one application process and one coordinator; it provides neither lease
renewal for long-running distributed work nor an unknown-outcome retry policy. Distributed queues,
PostgreSQL integration, RLS, encryption, backup, multi-host notification, proxy timeout
qualification, and production load evidence remain later S6 work. Customer data is not permitted in
the local composition.

## Web shell

The application-owned shell uses same-origin resources, a restrictive content security policy, no
inline script, no token storage, no untrusted HTML insertion, semantic landmarks, labels, keyboard
focus, a live status region, reduced-motion behavior, and a responsive one-column narrow layout.
Authentication headers may be supplied only by an approved host session adapter at request time.
The shell loads the authenticated capability response before enabling task creation and constructs
its route selector from the returned task classes. It does not display disabled future task types.
Typed task and request failures display the stable error code, sanitized message, and next action by
text insertion only. A failed review is shown as stopped rather than completed. A local creation guard
and a separate event-read guard prevent duplicate submission or concurrent resume calls.
