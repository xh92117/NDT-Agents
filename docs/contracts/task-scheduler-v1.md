# Task Scheduler V1 Contract

**Contract version:** 1.0.0  
**Implementation task:** S1-06  
**Status:** isolated local scaffold

## Purpose

`TaskScheduler` executes prepared `ChildTaskContext` values without changing the mandatory agent
topology. It does not route, assemble child context, review professional output, aggregate a user
response, persist checkpoints, or start background workers.

## Public operations

- `run_sync` validates and completes one schedule before returning a `ScheduleResult`.
- `enqueue` validates and stores one in-process schedule, then returns a scoped `ScheduleHandle`.
- `advance` requires the original parent task and complete identity scope, starts one queued
  schedule explicitly, and returns a terminal `ScheduleResult`.
- `cancel` requires the same binding and cancels a queued schedule before any executor call.
- `cancel_assignment` marks one queued assignment as cancelled; its dependents are later blocked.
- `schedule` selects `run_sync` or `enqueue` from an explicit asynchronous flag.

Calling `enqueue` performs zero child executor calls. Calling `advance` again after terminal
completion returns the same typed result and performs no duplicate call. The scheduler's direct
in-process queue is not restart durable; the separate S1-07 recovery runtime adds immutable
checkpoints, idempotency, interrupts, and restart-safe output replay around this scheduler.

## Pre-execution validation

The scheduler rejects the entire schedule before any child starts when:

- the schedule is empty or contains more than four children;
- parent task or complete tenant, project, user, role, permission scope differs;
- assignment IDs are duplicated;
- authorized executors do not match assignment IDs exactly;
- a dependency is unknown, self-referential, or cyclic;
- General work is mixed with professional work or has a dependency;
- professional child budget policies differ;
- active professional concurrency is zero or above the configured ceiling;
- the policy hard concurrency exceeds the configured non-overridable ceiling.

Rejections use `SchedulerError` with a stable code, non-sensitive message, and required next action.

## Ordering and concurrency

The dependency graph is converted into deterministic topological waves using input order. Within
one wave:

1. independent `READ_ONLY` assignments run in bounded batches no larger than the active
   professional-concurrency limit;
2. every `MUTATING` assignment runs serially and never overlaps another assignment;
3. a dependent wave starts only after its prerequisite wave has terminal results.

Every launched assignment calls its injected executor exactly once through `ChildSubgraph`. There
is no scheduler retry. If a prerequisite fails or returns a blocking terminal result, its dependent
assignment receives `SCHEDULE_PREREQUISITE_FAILED`, records zero execution calls, and is not
launched.

## Typed states

An asynchronous handle is `QUEUED`. Terminal schedule states are:

- `COMPLETED`: every assignment completed;
- `PARTIAL`: at least one assignment completed and at least one failed or was blocked;
- `FAILED`: no assignment completed;
- `CANCELLED`: the queued schedule was cancelled before execution.

Each `ScheduledAssignment` contains its assignment and run identities, topological wave, terminal
status, zero-or-one execution count, optional verified `ChildRunOutcome`, and an actionable error
when it did not complete. A professional `ChildRunOutcome` remains review-pending; scheduling does
not bypass review.

## Current limitations

- Direct queue state and executor bindings exist only in the current process; use the recovery
  runtime when restart recovery is required.
- Cancellation is supported only before `advance` starts execution.
- There is no distributed claim, lease, worker heartbeat, checkpoint, or restart recovery.
- S1-08 adds one exact-policy `BudgetGuard`; the scheduler leases professional slots, passes the
  guard into every child subgraph, and returns a typed zero-call assignment when a pre-start budget
  or concurrency check denies execution.
- S1-09 will add per-result and cross-result review transitions.
