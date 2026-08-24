# Review Graph V1 Contract

**Contract version:** 1.0.0  
**Implementation task:** S1-09  
**Status:** isolated local review candidate

## Purpose and topology

`ReviewWorkflow` is the only aggregation gate for completed professional child results. General
results do not enter this graph. A professional result starts with `review_required=true` and
`aggregation_ready=false`; only a successful workflow result can make the reviewed result eligible
for Main Agent aggregation. The reviewer and corrector have no user-delivery path.

The graph is deterministic:

```text
Prepared
  -> per-result review for every completed professional result
      -> targeted correction -> re-review only changed results
      -> conflict, human-required, or failed stop
  -> cross-result review when results interact
      -> targeted correction -> changed per-result review -> cross-result re-review
      -> conflict, human-required, or failed stop
  -> hash-bound review manifest -> Main aggregation eligibility
```

Cross-result review is mandatory when any professional assignment depends on another. A caller may
also require it for independent outputs that interact semantically. It cannot explicitly disable
cross review for a dependency graph.

## Independent review context

`ReviewContext` contains only:

- parent task, schedule, and complete tenant/project/user/permission scope;
- one current result for per-result review or the current interacting result set for cross review;
- exact result and aggregate hashes;
- the bounded review checklist;
- reviewer, prompt, and model versions;
- applied correction count and a context-manifest hash.

The context is immutable, read-only, has an empty tool list, and prohibits user delivery. It does
not contain Main history, child scratch namespaces, another child's private state, mutation tools,
or hidden executor objects. Cross review receives typed child outputs, not private work state.

The reviewer must return public `ReviewResult` contract version 1.0.0. The graph revalidates task,
target run, exact target hash, reviewer version, correction count, strict schema, and findings.
`PASS` cannot contain error or critical findings. Every non-pass decision requires at least one
finding with an explicit next action.

## Decisions and aggregation

- `PASS`: the current result passed its independent review.
- `REVISE`: only the named responsible child may receive a bounded correction request.
- `CONFLICT`: stop aggregation and return the evidence to Main for at most one separately governed
  replan.
- `HUMAN_REQUIRED`: pause aggregation for a qualified reviewer.
- `FAILED`: preserve the target and findings and state the next required action.

All per-result reviews must pass before cross-result review. A cross-result `REVISE` finding must
identify each target as `assignment:<assignment_id>`. An unresolved individual or cross decision
makes the complete workflow non-aggregatable, including individually passed outputs.

## Targeted correction

`CorrectionContext` returns only structured findings, a bounded targeted instruction, the current
result and hash, the responsible child's goal and output contract, and, only for a cross-result
repair, the other current public result targets required to understand the conflict. It excludes
all scratch and user-delivery state.

The responsible corrector returns a strict `AgentResult` for the same task and run. The graph
rejects invalid schema, task/run mismatch, cross-scope artifacts, unsuccessful status, timeout,
exception, or a byte-equivalent unchanged result. It re-reviews only the changed result and then
repeats cross review if required. There is no hidden full-task retry.

## Budgets, transitions, and manifest

The graph uses the exact parent-bound S1-08 `BudgetGuard`. One initial set of per-result reviews and
its optional cross review count as one review round. A repair cycle counts one correction round;
re-review uses the next review round. Graph transitions, review rounds, correction rounds, terminal
states, and budget stops are traced. Active and hard exhaustion stop before another reviewer or
corrector call.

`ReviewWorkflowResult` records every current result and hash, per-result review history, cross-review
history, correction count, skipped failed schedule assignments, transitions, physical reviewer and
corrector call counts, budget telemetry, aggregation state, and an SHA-256 manifest over all bound
results and reviews. The manifest is deterministic for identical bound inputs and reviews.

`MainAggregationGate` is the executable Main-only boundary. Its General method accepts exactly one
completed General child outcome whose existing child invariant already permits direct aggregation.
Its professional method accepts only an aggregatable `ReviewWorkflowResult` with a validated review
manifest. Passing a raw professional child or any unresolved review state returns a typed denial.

## Durable review recovery

`RecoverableReviewWorkflow` claims one exact schedule, context, reviewer-definition, and
cross-review request. Its append-only journal checkpoints the prepared boundary, each strict
reviewer or corrector output by context SHA-256, and the terminal workflow result and manifest.
A restart deterministically replays the graph from the same initial budget state while cached
completed calls prevent another physical executor call. Once the terminal result is committed, a
restart returns it directly before Main aggregation. Sequence and payload hashes, scope, contract
version, and the previous-event chain are validated on every load. Migration
`0006_s1_review_recovery` provides forced-RLS append-only PostgreSQL event storage support.

## Current limitations

- Review and correction executors are injected provider-neutral ports. Later model and Tool
  Registry adapters must apply their physical-call and token reservations inside those ports.
- Domain-specific review rubrics and measured correction-quality thresholds are S4 work. S1-09
  enforces topology, contracts, state, budgets, and explicit failure, not expert correctness.
