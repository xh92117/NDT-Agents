# Budget Guard V1 Contract

**Contract version:** 1.0.0  
**Implementation task:** S1-08  
**Status:** isolated local runtime safety candidate

## Purpose

`BudgetGuard` is the single runtime authority for one exact versioned `BudgetPolicy`. It keeps
limits, reservations, actual usage, degradation decisions, retry and failure metrics, and trace
events in one typed state. A scheduler or adapter must use the same guard instance for the complete
task; creating a fresh guard inside a child or retry would be a contract violation.

`default_budget_policy` is the only initial factory. Its G0, P1, P2, P3, and K1 defaults and hard
ceilings match the quantitative table in `development-spec.md`. A K1 file-derived tool limit is
bounded at 400. An active limit may rise only through `elevate_budget_policy`, a distinct policy ID,
and either a deterministic risk-policy or human-approval reference. No elevation can exceed the
hard limit.

## Counting model

The guard keeps these dimensions independent:

- ReAct graph actions and reserved graph actions;
- terminal transitions and terminal transitions caused by a budget stop;
- physical LLM calls, actual tokens, and reserved tokens;
- physical tool calls and logical actions;
- retry, LLM failure, and tool failure counts;
- cache lookups and cache hits;
- review and correction rounds;
- current and peak professional concurrency;
- elapsed task time and every allow, record, and denial event.

A failed physical call and a retry still count. A cache lookup is a graph action but is not a
physical provider or tool call. Terminal transitions are traced separately so a required typed stop
does not attempt to spend an already exhausted graph step.

## Pre-call reservation and completion

An LLM adapter calls `begin_llm_call` with its maximum total-token cap before contacting a provider,
then calls `complete_llm_call` with actual input and output tokens. A reservation denial makes zero
physical calls. Provider usage above the reservation is a typed stop and preserves the actual
telemetry.

A tool adapter calls `begin_tool_call` with the stable tool name, version, canonical JSON arguments,
and current observation SHA-256. The same tool identity and normalized arguments cannot run again
against the same observation. A different observation may permit the call if all other limits allow
it. The adapter records success or failure through `complete_tool_call`.

Professional work acquires `professional_slot` before execution. The lease always releases in the
context-manager cleanup path, including failures. Scheduler validation also requires the guard
policy to equal every child-context policy.

## Durable graph attempts

Recovery reserves at most four non-terminal child transitions per assignment before it persists a
`RUNNING` checkpoint. Each observed `Observe -> Plan -> Act -> Verify` action consumes one reserved
step. A returned scheduler result releases unused reservation capacity and is checkpointed before
fault injection or terminalization.

If a process ends while a reservation is outstanding, `BudgetGuard.from_telemetry` restores the
exact policy, counters, elapsed time, events, and tool repetition history. The runtime
conservatively charges the outstanding reservation as one failed attempt before it considers a new
reservation. It never resets usage. Recovery rejects telemetry with an active professional lease or
in-flight LLM-token reservation. Recovery state schema 1.1.0 makes the telemetry mandatory.

## Degradation and stop behavior

The maximum utilization ratio across active graph, LLM, tool, token, time, review, and correction
limits selects the stage:

- below 70 percent: normal actions;
- at least 70 percent: deny low-value actions;
- at least 85 percent: also deny query expansion;
- at least 95 percent: allow only validation and finalization;
- at 100 percent: stop new standard actions.

Active and hard ceilings are checked before a guarded call starts. A denial raises `BudgetExceeded`
with a stable error code and can be converted to `BudgetStop`, which states cause, completed work,
impact, next action, and complete telemetry. Recovery converts pre-execution exhaustion into a typed
failed schedule with zero executor calls.

## Current limitations

- S1-08 provides the provider-neutral guard and scheduler/recovery integration. Later registered
  LLM and Tool Registry adapters must call the reservation APIs at their physical boundaries.
- The local wall-time clock preserves already observed elapsed time across recovery; production
  worker and queue timing awaits the approved SLO and distributed runtime tasks.
- Review and correction counters exist, while S1-09 owns Review Agent state transitions.
- Immutable audit publication and correlation are S1-10 work; S1-08 telemetry is typed checkpoint
  evidence, not the final audit store.
