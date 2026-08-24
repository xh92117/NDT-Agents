# Recovery Runtime V1 Contract

**Contract version:** 1.0.0  
**Implementation task:** S1-07  
**Status:** isolated local recovery candidate

## Purpose

`TaskRecoveryRuntime` adds immutable checkpoints, exact-request idempotency, cooperative
interrupts, and restart-safe assignment-output replay around `TaskScheduler`. It preserves the
mandatory Main-to-child topology and never adds a child-to-user path.

The runtime uses two injected ports:

- `RecoveryBackend` atomically owns idempotency claims, ordered checkpoint metadata, interrupt
  state, durable assignment outputs, and the side-effect journal;
- `ArtifactStorageService` owns immutable checkpoint payloads and validates object identity, scope,
  length, metadata, and SHA-256 on every restore.

`InMemoryRecoveryBackend` plus `InMemoryObjectBackend` is the deterministic restart-test reference,
not production persistence. Migration `0003_s1_recovery` adds the PostgreSQL metadata tables and
forced tenant/project RLS required by a live adapter. Live PostgreSQL and object-store recovery
evidence is still required before TG-01.

## Submission and idempotency

`submit` first applies the complete S1-06 schedule validation and then hashes the exact ordered
child contexts with the recovery graph and state-schema versions. An idempotency claim is scoped by
the complete tenant, project, user, roles, and permission version.

- A new key creates one recovery ID and sequence-zero `QUEUED` checkpoint.
- The same key plus the same parent task and request hash returns the existing recovery run.
- The same key with different input returns `IDEMPOTENCY_CONFLICT` before execution.
- A claim whose first checkpoint has not committed returns `RECOVERY_INITIALIZING`; the runtime does
  not guess, duplicate, or silently replace incomplete accepted work.

Executor objects are never serialized. A restarted process must explicitly rebind exactly one
authorized executor per assignment.

## Immutable checkpoint

Every accepted recovery transition appends the next integer sequence. A checkpoint contains:

- recovery, parent-task, and full identity-scope binding;
- exact idempotency request hash;
- graph and state-schema versions;
- immutable child contexts and their individual manifest hashes;
- current recovery phase and optional typed scheduler result;
- the exact S1-08 policy, counters, reservations, elapsed time, degradation stage, and trace events;
- sorted committed side-effect IDs;
- immutable state artifact reference and matching payload SHA-256.

Restore rejects a task or full-scope mismatch, sequence or metadata mismatch, incompatible graph or
state version, mutable or mismatched artifact reference, corrupt artifact, invalid snapshot schema,
or invalid child context manifest. No recovered result reaches execution before these checks pass.
The public recovery contract remains version 1.0.0; the persisted snapshot schema is 1.1.0 because
budget telemetry is now required.

## Assignment output replay

Each assignment execution key contains assignment ID, run ID, and child-context manifest. The
recoverable executor wrapper:

1. checks the scoped durable output journal;
2. revalidates and returns an existing hash-verified output when present;
3. otherwise makes one physical executor call;
4. canonicalizes and commits its JSON output before returning it to `TaskScheduler`.

The runtime persists a post-execution `RUNNING` checkpoint containing the scheduler result and
updated budget telemetry before fault injection or terminalization. If the process ends after the
assignment output commit but before that checkpoint, a new runtime reconstructs the scheduler
result from durable outputs with zero repeated physical child calls. If the post-execution
checkpoint exists, recovery terminalizes it directly without invoking an executor. The child
subgraph validates a replayed `AgentResult` again.

Before each scheduler attempt, recovery reserves four graph actions per child and persists the
reservation. A process loss conservatively charges an outstanding reservation before a retry. A
returned result releases unused reservation capacity. If another attempt would exceed the active or
hard limit, recovery writes a typed failed schedule with zero executor calls. Counters and tool-call
history are restored; they are never reset by process restart.

## Side effects

A recoverable child receives `RecoveryControl`. Every external side effect must use
`execute_side_effect` with a stable UUID and SHA-256 of the exact request.

- `NEW` records `STARTED` before invoking the operation.
- A successful operation commits a hash-verified JSON result and becomes `COMMITTED`.
- A later use of the same ID and hash returns the committed result without invoking the operation.
- Reuse with a different request returns `SIDE_EFFECT_IDEMPOTENCY_CONFLICT`.
- A prior `STARTED` record without a committed result returns
  `SIDE_EFFECT_RECONCILIATION_REQUIRED` and never repeats the external operation.

The ambiguous case is deliberately a typed stop, because automatically repeating an operation
whose external commit is unknown could duplicate a physical or user-visible effect. An authorized
adapter or human must reconcile the stable side-effect ID against the external system.

## Interrupt and resume

Interrupts are cooperative and checked at checkpoint-safe boundaries. A requested interrupt before
execution creates an `INTERRUPTED` checkpoint with no child call. An interrupt requested while a
child is running allows that bounded call and output commit to finish, then checkpoints the typed
scheduler result as interrupted. Explicit `resume` clears the request. If the result was already
committed, resume finalizes it without another executor call; otherwise it continues from the last
committed checkpoint.

## Recovery phases

```text
QUEUED -> RUNNING -> COMPLETED | PARTIAL | FAILED | CANCELLED
   |         |
   +---------+-> INTERRUPTED -> RUNNING or terminal finalization
```

Process termination is not converted to a fluent child failure. The last immutable checkpoint,
assignment-output journal, and side-effect journal remain authoritative for the next runtime.

## Current limitations

- The repository port has a deterministic in-memory implementation; the PostgreSQL migration is
  present but the live repository adapter and service recovery probe await approved infrastructure.
- Interrupts take effect at cooperative boundaries; hard worker termination and distributed leases
  are not implemented in this task.
- A side effect with unknown external outcome requires reconciliation instead of automatic retry.
- S1-09 returns an immutable hash-bound review manifest. `TaskRecoveryRuntime` still checkpoints
  scheduler state only; durable resume inside a review/correction round remains TG-01 integration
  work tracked in `plan.md`.
- S1-10 adds immutable audit events and trace correlation.
