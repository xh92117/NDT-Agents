# Child Subgraphs V1

**Contract version:** 1.0.0  
**Task:** S1-05  
**Status:** isolated single-child execution candidate

## Topology boundary

The General Agent is a child execution path. Professional work also executes only through a child
subgraph. Neither child type receives a user response channel, invokes Main aggregation, reads the
parent's private dependency data, or reads another child's scratch namespace.

`AgentRegistry` contains exactly one `general` definition plus explicitly registered professional
definitions. Each definition fixes child kind, maximum tool allowlist, Skill version, prompt
version, and model version. Unknown types and General/professional kind mismatch are rejected before
context construction. This registry is an agent-definition registry, not the shared Tool Registry
implemented by S1-12.

## Minimal child context

`ChildContextFactory` produces immutable `ChildTaskContext` version 1.0.0 values. Each value contains
only:

- parent task ID, unique run ID, assignment ID, child kind, and registered agent type;
- tenant, project, user, roles, and permission version;
- child goal and child success criteria;
- selected authorized artifact references and declared dependency assignment IDs;
- explicit read-only or mutating side-effect classification for scheduler policy;
- the intersection of requested, parent-authorized, and agent-authorized tools;
- exact Skill, prompt, model, knowledge, budget, output-schema, and review versions;
- one private `scratch://tenant/project/task/run` namespace;
- a SHA-256 manifest of the exact child context.

The context has no parent `dependency_data`, raw conversation history, user delivery capability, or
other child namespace. General work may receive the simple parent goal and its authorized artifacts.
Professional work requires exactly one explicit `ChildInput` for each verified assignment and may
receive only the artifact IDs selected for that assignment.

## Child state machine

One prepared child records:

```text
PREPARED -> OBSERVE -> PLAN -> ACT -> VERIFY -> COMPLETED
```

S1-05 calls one injected `ChildExecutor` once. The executor returns an untrusted mapping which is
validated as strict V1 `AgentResult`. Parent task ID, run ID, tenant/project scope of result
artifacts, terminal fields, and extra-field rejection are verified before completion. Executor
failure, invalid schema, identity mismatch, or result-scope mismatch returns a typed failed outcome
with a required next action and no result.

General completed results become eligible for Main aggregation. Professional completed results are
always marked `review_required=true` and `aggregation_ready=false`. Every child outcome fixes
`user_delivery_allowed=false`.

## Separate scheduling and review

This subgraph contract still executes one prepared child at a time. The separate S1-06
`TaskScheduler` now owns multi-child ordering, bounded parallelism, explicit queued asynchronous
completion, and pre-start cancellation. S1-07 owns checkpoint recovery. S1-08 now counts the four
non-terminal ReAct actions through one parent-bound guard and records terminal transitions
separately, including typed zero-call budget stops. S1-09 implements review transitions.

S1-09 now sends each completed professional result through the independent read-only Review Graph.
Only a hash-bound `PASS` may become aggregation eligible. `REVISE` returns actionable findings to
the responsible child through a minimal correction context; child scratch and user delivery remain
absent. Interacting professional results also require cross-result review.
