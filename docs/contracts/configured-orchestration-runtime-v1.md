# Configured Orchestration Runtime V1

## Purpose

S1-15 connects the strict S1-14 agent configuration to the existing Main Graph, child context,
LangGraph execution, scheduler, and restart-recovery contracts.

## Assembly contract

The configured runtime:

1. runs the deterministic Main Graph with typed route signals;
2. stops blocked, failed, or human-required routes before child construction or execution;
3. builds the Agent Registry only from the immutable configured profiles;
4. prepares one minimal private child context per verified assignment;
5. binds each assignment by `agent_type` to one configured LangGraph child executor;
6. uses the existing synchronous or queued-asynchronous scheduler decision; and
7. returns only existing typed Main Graph, schedule, child, and recovery contracts.

The delegate catalog must contain every configured profile exactly once and no unknown profile.
The exact configuration hash is copied into each private child context and protected by its context
manifest and recovery request hash. Delegate bindings are application-owned objects; they are not
selected by user input and are not stored in checkpoints or public contracts.

## Recovery contract

A recoverable binder rebuilds assignment executors from the persisted `ChildTaskContext` values.
It validates the current configuration against every context before execution and passes the
existing `RecoveryControl` only to the matching recoverable delegate. The S1-07 runtime continues
to own checkpoint integrity, output replay, side-effect reconciliation, interrupts, budgets, and
terminal state.

## Safety boundaries

- General work remains one dependency-free synchronous child.
- Professional work remains review required and is never aggregation ready before S1-09 review.
- Human-required work is not scheduled.
- Missing, extra, stale, wrong-kind, or wrong-version bindings fail before a delegate call.
- No model provider, credential, network call, dynamic import, retry loop, publication, physical
  action, or direct child-to-user delivery is enabled by this assembly layer.
- Optional LangGraph checkpoint storage is injected by the application and is not selected here.

## Verification

`tests/orchestration/test_configured_runtime.py` covers General execution, professional queued
execution, strict delegate catalogs, stale context denial, human-required stopping, and configured
restart rebinding without duplicate calls.
