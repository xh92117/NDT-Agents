# Main Graph V1

**Contract version:** 1.0.0  
**Task:** S1-04  
**Status:** isolated deterministic runtime candidate

## Boundary

The Main Graph receives a V1 `TaskContext` and explicit V1 `RouteSignals`. Route signals state
whether the task is general, list at most four minimal professional assignments and their
dependencies, and state whether a qualified human is required. They do not contain an expected
route label, benchmark case identifier, split, model answer, tool output, or private child state.

Untrusted dictionaries enter through `MainGraph.run_payload`. Strict validation failure returns a
typed `ROUTE_SIGNALS_INVALID` blocked result. Task-ID mismatch, dependency cycle, and topology
invariant failure also return typed terminal results with a required next action.

## Rules-first routing

`RulesFirstRouter` uses these ordered deterministic rules:

1. explicit general eligibility routes to the General Agent synchronously;
2. explicit human requirement routes one or more responsible professionals, review, and a human
   checkpoint;
3. one professional routes synchronously and requires review;
4. multiple professionals with no dependencies route asynchronously as independent work;
5. multiple professionals with dependencies route asynchronously in dependency order.

Dependencies must refer to declared assignments and form a directed acyclic graph. The router starts
the minimum explicitly declared professional set. No LLM or provider is called in V1 routing. A
future classifier may run only after rules are unable to decide, within the task budget, and must
not override a deterministic safety or permission rule.

## State machine and topology

Successful routing records these transitions:

```text
RECEIVED -> OBSERVE -> PLAN -> ACT -> VERIFY -> DISPATCH_READY
```

The dispatch plan is strict and immutable. It identifies either the General child path or the
professional assignments. Every professional dispatch requires review. The Main Agent tool
allowlist is the empty tuple and its LLM-call count is fixed at zero for this route-only graph.
S1-05 supplies child execution; S1-06 supplies scheduling; S1-09 supplies review execution. Until
then, this graph stops at `DISPATCH_READY`.

## Routing benchmark V1 repair

The original synthetic routing cases used non-discriminative request text. The versioned generator
was corrected to add explicit machine-readable route signals and distinct request intent while
preserving 1,000 project-generated, training-excluded cases and the five balanced route classes.
The router consumes only `route_signals`, never the case ID, request number, split, or expected
label. The repaired routing dataset SHA-256 is
`129ea5fbd73408670cd3257db376230d16d584130a1b63e6c6cf756eef66f453`.
