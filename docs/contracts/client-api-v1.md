# S6 Client API Contract V1

## Status

S6-01 local candidate, contract version `1.0.0`. This contract is provider-neutral and does not
approve production deployment, formal conclusions, physical actions, or publication.

## Routes

| Method | Exact route | Permission | Result |
|---|---|---|---|
| `POST` | `/v1/workbench/tasks` | `workbench:task:create` | creates or replays one exact-scope task |
| `GET` | `/v1/workbench/task` | `workbench:task:read` | reads one task selected by validated `task_id` query data |
| `GET` | `/v1/workbench/events` | `workbench:event:read` | returns an SSE event batch after `after_sequence` |

The identity middleware derives scope from an approved bearer identity and exact tenant/project
headers. Client bodies cannot provide or override scope, user, roles, permission version, task ID,
state, event sequence, review, approval, result, or formal-use state.

## Task creation

Input is strict JSON with schema version `1.0.0`, one registered task class, a trimmed goal of at most
8,000 characters, 1 to 20 unique trimmed success criteria, and a bounded idempotency key. Reusing an
idempotency key with the same exact scope and request returns the original task. Reuse with changed
input returns `CLIENT_IDEMPOTENCY_CONFLICT` and makes no change.

Every new task starts at sequence 1 and state `ACCEPTED` with the message that Main Agent routing is
pending. By default this boundary does not dispatch a child or call an LLM, tool, provider,
instrument, review, approval, publication, or formal conclusion service.

In the explicitly acknowledged, local-only S6-02-APP profile, an authenticated G0 task continues
synchronously through `RUNNING` and one terminal event after Main routing, one configured General
child, one bounded model-gateway attempt, and Main aggregation. Idempotent replay returns the same
terminal task without another provider call. Non-G0 tasks, wrong-scope model bindings, missing
configuration, and budget denial fail before the provider; provider or schema failure makes at most
one call and emits a typed failed event. The displayed result always states that the input is
SYNTHETIC, the model evidence remains review-required, and formal use is forbidden.

## Event replay

Events are immutable and sequence-contiguous. A client reconnects with the last acknowledged
sequence and receives only later events. A cursor beyond the current sequence returns
`CLIENT_EVENT_CURSOR_INVALID`. Each response ends with a `stream-state` control event carrying the
current last sequence and terminal flag; a non-terminal client may reconnect after a bounded delay.
Terminal history is replayable and no event route performs a side effect.

The in-memory repository is test-only and single-process. Durable append-only persistence,
multi-process notification, proxy timeout qualification, and production load evidence are assigned
to later S6 work.

## Web shell

The application-owned shell uses same-origin resources, a restrictive content security policy, no
inline script, no token storage, no untrusted HTML insertion, semantic landmarks, labels, keyboard
focus, a live status region, reduced-motion behavior, and a responsive one-column narrow layout.
Authentication headers may be supplied only by an approved host session adapter at request time.
