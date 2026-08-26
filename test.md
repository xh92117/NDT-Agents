# Civil Infrastructure NDT Agent Platform Test Plan

**Version:** 1.69
**Updated:** 2026-08-26
**Development plan:** [plan.md](./plan.md)  
**Development rules:** [AGENTS.md](./AGENTS.md)  
**System specification:** [development-spec.md](./development-spec.md)

## 1. Purpose

This file is the living test schedule for development. It records:

- what must be tested;
- when each test must run;
- which change triggers each test;
- which result blocks task, phase, or release completion;
- where evidence and defects must be recorded.

It is not a record of assumed success. A test is `PASS` only after a reproducible run has produced evidence.

## 2. Status and severity

Allowed test states are:

- `NOT_RUN`: scheduled but no valid evidence exists;
- `RUNNING`: execution is in progress;
- `PASS`: all required assertions passed;
- `FAIL`: at least one required assertion failed;
- `BLOCKED`: an external dependency prevents execution;
- `WAIVED`: a named approver accepted a documented exception and expiry date.

Defect severity is:

- `P0`: tenant leak, destructive unauthorized action, fabricated critical evidence, or unrecoverable data loss;
- `P1`: mandatory topology bypass, incorrect formal artifact, repeated side effect, or failed recovery;
- `P2`: degraded function with a safe workaround;
- `P3`: cosmetic, documentation, or low-impact issue.

No open `P0` or `P1` defect is allowed at a phase gate or release gate. A `WAIVED` security or tenant-isolation test cannot satisfy a commercial release gate.

## 3. Test options and when to run them

The developer selects the smallest profile that covers the change. The profiles are cumulative where stated.

| Profile | What it contains | When it runs | Blocking scope | Target duration |
|---|---|---|---|---:|
| `QUICK` | lint, format, type checks, changed unit tests, document link checks, and changed-code simplicity and efficiency review | after each local change and before each commit | current change | <= 5 min |
| `TASK` | `QUICK` plus all tests mapped to the task acceptance criteria | before changing a task to `DONE` | task | <= 20 min |
| `PR` | `TASK` plus affected integration, security, and regression tests | on every merge request or protected-branch update | merge | <= 30 min |
| `NIGHTLY` | complete unit and integration suites, benchmark sample, isolation sample, parser corpus sample | once every 24 hours when the branch changed | next development day | <= 2 h |
| `PHASE_GATE` | every group assigned to the phase in Section 5 | before closing S0 through S6 | phase | <= 8 h except load tests |
| `RELEASE` | full functional, security, resilience, evaluation, performance, migration, and rollback suites | for every release candidate | release | <= 24 h |
| `CHANGE_TRIGGERED` | specialized suite selected by the trigger matrix in Section 4 | immediately after a high-risk configuration or behavior change | affected task or release | suite-specific |

If a profile exceeds its duration target, it may be split into parallel CI jobs, but no required assertion may be omitted.

## 4. Change-triggered test matrix

| Change | Required test groups before merge | Additional required timing |
|---|---|---|
| Agent graph, router, or state transition | `UNIT-CORE`, `INT-ORCH`, `INT-REVIEW`, `BUDGET` | run `E2E` nightly |
| System prompt, Agent Skill, or model version | affected business evaluation plus `EVAL-QA`, `EVAL-TOKEN` | run on frozen data before and after the change |
| Tool schema, tool implementation, or allowlist | affected tool integration group, `SEC-TOOLS`, `BUDGET` | run before registry publication |
| Bash command, path, or encoding logic | `INT-BASH`, `SEC-BASH` | run Chinese path corpus on every change |
| Context assembly or compression | `UNIT-CONTEXT`, `EVAL-COMPRESSION`, `EVAL-QA` | compare answer quality and token use with baseline |
| Memory schema, distillation, or restore | `INT-MEMORY`, `SEC-CACHE`, `RES-CHECKPOINT` | run cross-tenant and snapshot compatibility cases |
| Cache key, namespace, TTL, or serializer | `SEC-CACHE`, `EVAL-TOKEN`, affected integration groups | cold-cache and warm-cache runs are both required |
| Embedding model, chunking, reranker, or retrieval filter | `EVAL-RETRIEVAL`, `EVAL-QA`, `SEC-TENANT` | rebuild an isolated candidate index first |
| MinerU, OCR, or document normalization | `INT-MINERU`, `INT-OCR`, `INT-KNOWLEDGE` | run the complete parser regression corpus |
| Database migration or tenant policy | `SCHEMA`, `SEC-TENANT`, `SEC-CACHE`, migration and rollback tests | run on an anonymized production-like copy |
| MCP server or instrument adapter | `INT-MCP`, `INT-INSTRUMENT`, `SEC-TOOLS`, `RES-ALL` | run disconnected and malformed-response cases |
| Web Search provider or citation policy | `INT-WEB`, `EVAL-QA`, `EVAL-TOKEN` | run cached and uncached cases |
| Model provider catalog, binding, endpoint, capability, selection policy, YAML bootstrap, or secret source | `UNIT-MODELREG`, `UNIT-CORE` startup, `SEC-PLATFORM`, `SEC-TOOLS`, `PROVIDER-SMOKE`, `OBS-AUDIT` | run before publishing the registry snapshot, enabling a binding, or changing startup configuration |
| Client API or event contract | `SCHEMA`, `E2E` | run against Web, desktop, and PWA contract clients |
| Dependency or operating-system image | `QUICK`, full unit suite, dependency scan | run `NIGHTLY` before promotion |
| Threat model, data classification, encryption, secret, retention, SLO, SBOM, or license policy | `SEC-BASELINE`, affected security and lifecycle groups | run before approving the policy or dependent architecture decision |
| Release packaging, migration, signing, or publication workflow | complete `RELEASE`, artifact-hash verification, `DOC` | validate the immutable candidate before TG-06 and publication |

## 5. Phase gate schedule

Each group is defined in Section 8. A phase is complete only when every assigned group passes and the evidence is entered in Section 11.

| Gate | Development phase | What must pass | When to run |
|---|---|---|---|
| `TG-00` | S0 requirements and baseline | `DOC`, `SCHEMA`, `DATASET`, `SEC-BASELINE`, `PROVIDER-SMOKE` | after S0-01 through S0-10 and before S1 starts |
| `TG-01` | S1 lightweight runtime | `UNIT-CORE`, `INT-ORCH`, `SEC-TENANT`, `RES-CHECKPOINT`, `BUDGET`, `OBS-AUDIT`, `SEC-PLATFORM`, `UNIT-TOOLREG`, `INT-APPROVAL` | after S1-01 through S1-13 and before S2 starts |
| `TG-02` | S2 context, memory, and cache | `UNIT-CONTEXT`, `EVAL-COMPRESSION`, `INT-MEMORY`, `SEC-CACHE`, `INT-DATA-LIFECYCLE` | after S2-01 through S2-09 and before S3 starts |
| `TG-03` | S3 files and knowledge | `INT-MINERU`, `INT-OCR`, `INT-KNOWLEDGE`, `INT-BASH`, `EVAL-RETRIEVAL`, `SEC-BASH` | after S3-01 through S3-09 and before S4 starts |
| `TG-04` | S4 professional capabilities | `EVAL-QA`, `EVAL-PLAN`, `EVAL-REPORT`, `INT-REVIEW` | after S4-01 through S4-07 and before S5 starts |
| `TG-05` | S5 tools and instruments | `UNIT-MODELREG`, `INT-FUNCTION`, `INT-WEB`, `INT-MCP`, `INT-INSTRUMENT`, `SEC-TOOLS` | after S5-01 through S5-08 and before S6 starts |
| `TG-06` | S6 clients and release | complete `RELEASE`, including `E2E`, `SEC-ALL`, `PERF`, `RES-ALL`, `EVAL-TOKEN`, migration, rollback, signing, release-smoke, and candidate-hash checks | after S6-01 through S6-09 and before S6-10 publication |

## 6. Development task to test mapping

This table determines the minimum `TASK` profile. Add more groups when a change crosses boundaries.

| Tasks | Minimum test groups before `DONE` |
|---|---|
| S0-01 to S0-03 | `DOC`, deterministic role, ontology, data-model, and cross-reference consistency checks |
| S0-04 | `SCHEMA`, `UNIT-CORE` contract tests |
| S0-05 | `DOC`, `PROVIDER-SMOKE` |
| S0-06 to S0-07 | `DATASET`, rights and de-identification checks |
| S0-08 | `DOC`, `SEC-BASELINE`, SBOM and license scan, CI smoke test |
| S0-09 | `DOC` |
| S0-10 | `DOC`, `SEC-BASELINE` |
| S1-01 to S1-02 | `UNIT-CORE`, storage integration tests |
| S1-03 | `SEC-TENANT`, `SEC-CACHE` |
| S1-04 to S1-06 | `UNIT-CORE`, `INT-ORCH`, `BUDGET` |
| S1-07 | `RES-CHECKPOINT`, `INT-ORCH` |
| S1-08 | `BUDGET`, `RES-ALL` budget-stop cases |
| S1-09 | `INT-REVIEW`, `INT-ORCH` |
| S1-10 | `OBS-AUDIT`, `SEC-TENANT` audit scope, migration upgrade and rollback tests |
| S1-11 | `SEC-PLATFORM`, `SEC-TENANT`, recovery tests for key and secret rotation |
| S1-12 | `UNIT-TOOLREG`, `SEC-TOOLS`, `BUDGET` |
| S1-13 | `INT-APPROVAL`, `SEC-PLATFORM`, `RES-CHECKPOINT` |
| S2-01 to S2-03 | `UNIT-CONTEXT`, `EVAL-COMPRESSION` |
| S2-04 to S2-06 | `INT-MEMORY`, `SEC-CACHE`, `RES-CHECKPOINT` |
| S2-07 to S2-08 | `SEC-CACHE`, `EVAL-TOKEN` |
| S2-09 | `INT-DATA-LIFECYCLE`, `SEC-TENANT`, backup-expiry tests |
| S3-01 | `INT-KNOWLEDGE`, `INT-ORCH` |
| S3-02 to S3-03 | `INT-BASH`, `SEC-BASH` |
| S3-04 | `INT-MINERU` |
| S3-05 | `INT-MINERU`, `INT-OCR` |
| S3-06 | `INT-MINERU`, `INT-OCR`, normalization regression |
| S3-07 to S3-08 | `EVAL-RETRIEVAL`, `SEC-TENANT` |
| S3-09 | `INT-KNOWLEDGE`, `INT-APPROVAL`, rollback and audit tests |
| S4-01 | `EVAL-QA`, `INT-REVIEW` |
| S4-02 | `EVAL-PLAN`, `INT-REVIEW` |
| S4-03 | `EVAL-REPORT`, `INT-REVIEW` |
| S4-04 to S4-05 | source-data golden tests, `INT-REVIEW` |
| S4-06 | `INT-REVIEW` |
| S4-07 | `INT-REVIEW`, `INT-APPROVAL`, approval and permission tests |
| S5-01 to S5-02 | `UNIT-TOOLREG`, `INT-FUNCTION`, `SEC-TOOLS` |
| S5-03 | `INT-WEB`, `EVAL-QA`, `EVAL-TOKEN` |
| S5-04 | `INT-MCP`, `SEC-TOOLS`, `RES-ALL` |
| S5-05 to S5-06 and S5-08 | `INT-INSTRUMENT`, `SEC-TOOLS`, method golden tests |
| S5-07 | `UNIT-MODELREG`, `INT-INSTRUMENT`, `SEC-TOOLS`, `PROVIDER-SMOKE`, `OBS-AUDIT` model events |
| S6-01 to S6-03 | `E2E`, client contract, concurrent event sequence/snapshot, and accessibility tests |
| S6-04 to S6-05 | `SEC-ALL`, `RES-ALL` |
| S6-06 to S6-07 | `PERF`, `EVAL-TOKEN` |
| S6-08 | `E2E`, `SEC-ALL`, `RES-ALL`, `PERF`, `EVAL-TOKEN`, and pilot acceptance |
| S6-09 | complete `RELEASE` profile, including migration, rollback, trusted-key substitution/revocation/purpose checks, artifact-signing, release-smoke, and immutable candidate-hash tests |
| S6-10 | application-owned TG-06 and release-decision authority lookup, substitution/revocation verification, gated-hash equality, publication audit, and post-publication smoke tests |

## 7. Required test data

All frozen sets must be versioned, licensed or authorized, de-identified, and separated from training data.

| Data set | Minimum size | Required coverage | Created by | First required |
|---|---:|---|---|---|
| Routing set | 1,000 requests | direct General path, one subagent, multiple subagents, sync, async, review | S0-07 | `TG-01` |
| Technical QA set | 288 questions | six priority methods, all six declared structure classes, declared materials, applicability, limitations, citations | S0-07 | `TG-04` |
| Inspection-plan set | 60 tasks | new build, operation, incident, acceptance, missing inputs, conflicting constraints | S0-07 | `TG-04` |
| Report set | 40 tasks | templates, tables, findings, limitations, traceable source data | S0-07 | `TG-04` |
| Document parser set | 192 files | PDF, DOCX, XLSX, PPTX, MD, TXT, scans, tables, formulas, images, and optional legacy Office when enabled | S0-06 | `TG-03` |
| Raw inspection set | 60 samples | ultrasonic, radar, impact echo, rebound, acoustic emission, machine vision | S0-06 | `TG-04` |
| Compression set | 200 conversations | long tasks, protected constraints, citations, unresolved questions | S0-07 | `TG-02` |
| Bash and encoding set | 300 cases | spaces, Chinese names and text, UTF-8, BOM, GBK, GB18030, UTF-16, malformed bytes | S0-07 | `TG-03` |
| Fault set | 120 cases | timeouts, invalid schema, process crash, MCP loss, storage loss, partial output | S0-07 | `TG-01` |
| Tenant isolation set | 1,000 probes | API, SQL, vector, cache, artifact, log, task, memory, restored snapshot | S0-07 | `TG-01` |

Every set requires a manifest containing record ID, origin, rights, checksum, expected result, review owner, and version.

### 7.1 Metric registry and statistical protocol

Every gate metric has a stable ID and version. Its definition records the formula, numerator, denominator, unit, population, exclusions, sampling and stratification rules, minimum sample size, random seed where applicable, confidence interval or tolerance, baseline version, human-adjudication rubric, tie-breaking process, and evidence format. Frozen sets must report results by structure class, inspection method, material, risk level, and other declared critical strata; an aggregate pass cannot hide a failed mandatory stratum.

The terms `usable text`, `parse success`, `expert pass`, `citation correctness`, `critical workflow`, `recovery`, and `quality degradation` require approved metric definitions before their thresholds can satisfy a gate. Performance and resilience results must reference the hardware profile and approved SLO version.

## 8. Test catalog: what is tested and when

### 8.1 `DOC` - Documentation consistency

Test options:

- verify that `development-spec.md`, `plan.md`, `test.md`, and `AGENTS.md` exist;
- verify all local Markdown links resolve;
- verify Markdown code fences are balanced;
- verify task IDs and phase gates are unique and cross-referenced;
- verify document filenames and contents contain ASCII only;
- verify quantitative defaults do not conflict across documents.
- verify high-risk operation boundaries, approval requirements, task dependencies, release timing, and shared-infrastructure ordering do not conflict across documents;

Run with `QUICK` after any Markdown change, at `TG-00`, and in every `RELEASE` profile.

Acceptance: zero broken links, zero duplicate task IDs, zero unmapped gates, zero non-ASCII bytes in the four controlled Markdown files, zero unresolved numeric or policy conflicts, and no shared mandatory infrastructure scheduled after its first consumer.

### 8.2 `SCHEMA` - Contracts and migrations

Test `TaskContext`, `AgentResult`, `ToolResult`, artifact, citation, checkpoint, memory, cache, tenant, and review-state schemas. Include valid, missing, extra, incompatible-version, and malicious payload cases. Test forward migration and rollback.

Run after a schema or migration change, before any dependent task is `DONE`, at `TG-00`, and in `RELEASE`.

Acceptance: 100 percent valid fixtures accepted, 100 percent invalid fixtures rejected with stable error codes, and migration round trips preserve required fields.

### 8.3 `DATASET` - Fixture quality and governance

Test checksums, manifests, licensing, de-identification, class coverage, frozen-set access, duplicate leakage, and expected-answer review.

Run when fixtures are added or changed, at `TG-00`, and before every model or prompt evaluation.

Acceptance: 100 percent manifest completeness, zero unauthorized source, zero known train-test leakage, and all minimum counts in Section 7 met.

### 8.4 `UNIT-CORE` - Router, state, and result contracts

Test the API application factory, immutable environment configuration, structured redacted logs,
request correlation, liveness/readiness contracts, typed non-disclosing API errors, rules-first
routing, isolated agent state, direct General path, professional path, sync/async selection, result
aggregation, error classes, idempotency keys, and terminal states.

Rules-first routing tests consume only explicit route signals, never benchmark case ID, request
number, split, or expected labels. They cover General, one professional, multiple independent,
multiple dependent, and human-required routes; invalid input; task mismatch; unknown dependencies;
cycles; review invariants; and the zero-tool, zero-LLM Main route budget.

Child-subgraph tests require the General path to use a child definition, reject unregistered or
kind-mismatched agents, and verify exact tenant/project scope propagation. For professional work,
require one minimal input per assignment, selected authorized artifacts only, intersected tool
permissions, explicit dependency IDs, distinct scratch namespaces and context manifests, and no
parent-private or other-child data. Execute one injected child call, validate strict result schema,
task/run identity and artifact scope, deny extra fields, expose no user delivery, return General
results only to Main aggregation, and keep every professional result review-pending.

Scheduler tests require synchronous completion and explicit queued asynchronous advancement; no
background execution may occur on enqueue. Validate task and scope binding, unique assignments,
known acyclic dependencies, active and hard professional-concurrency limits, deterministic
topological waves, parallel execution only for independent read-only work, serial execution for
dependencies or side effects, cancellation before start, and typed blocking of dependents after a
failed or cancelled prerequisite. Assert each launched assignment calls its injected executor once,
blocked assignments call it zero times, and no hidden retry occurs.

For S1-02, compile the upgrade and downgrade with the PostgreSQL dialect; verify the pgvector
extension and type; require tenant/project scope on every business table and key; exercise Redis
TTL and isolation with a deterministic backend; exercise artifact immutability, scope denial, URI
derivation, and content/metadata integrity; prove client construction does not connect; and verify
that dependency failure degrades readiness without changing liveness. Approved live PostgreSQL,
Redis, and S3-compatible smoke tests run before TG-01.

Run on every affected code change, in `PR`, nightly, and at `TG-01`.

Acceptance: the application imports and starts with zero external dependency access; invalid or
unknown settings fail with stable non-disclosing codes; API probes and failures conform to their
versioned strict schemas; logs and responses expose zero credential or exception detail; routing
Macro-F1 >= 0.97 on the frozen set; 100 percent topology-invariant enforcement; zero child-to-user
direct response; zero untyped terminal result. Storage migration upgrade and rollback must compile;
scope must be present on 100 percent of business tables and derived keys; cross-scope simulated
reads and writes must be zero; immutable overwrite and corrupted artifact acceptance must be zero;
and live dependency smoke tests must pass before TG-01.

### 8.5 `INT-ORCH` - Mandatory orchestration path

Test these paths end to end:

1. User -> Main Agent -> General Agent -> Main Agent -> user.
2. User -> Main Agent -> one professional subagent -> Review Agent -> Main Agent -> user.
3. User -> Main Agent -> parallel professional subagents -> per-result review -> cross-result review -> Main Agent -> user.
4. User -> Main Agent -> asynchronous child tasks -> checkpoint -> resume -> review -> Main Agent -> user.
5. A failed child is retried, repaired, or returned as a typed failure without bypassing review.

Run after graph, router, scheduler, review, or state changes; nightly; and at `TG-01`.

Acceptance: 100 percent mandatory path compliance, zero cross-agent private-state access, and zero duplicate external side effect.

### 8.6 `BUDGET` - Loop and tool-call limits

Test the quantitative limits defined in `development-spec.md`: normal and hard ReAct iterations, LLM calls, tool calls, repeated identical calls, concurrent subagents, review rounds, correction rounds, timeouts, token ceilings, and graceful budget exhaustion.

For S1-08, compare every central default and hard limit with the task-class table. Test active below
hard, active equal to hard, deterministic elevation rejection, pre-call graph/LLM/tool/token/time
denial, actual-token commitment, reservation overrun, failed physical-call counting, retry counting,
separate cache lookup/hit and logical-action metrics, review and correction limits, and concurrency
lease cleanup on failure. Exercise exact normalized tool repetition with unchanged evidence and
allow it only after a new observation. At 70, 85, and 95 percent, verify the documented action-class
restrictions. Every denial must append a trace event and produce a typed stop containing completed
work, impact, next action, counters, elapsed time, and peak concurrency. Guarded scheduler tests
must prove the configured active and hard concurrency are never exceeded and a graph-step stop can
occur before an executor call. Persist and restore budget telemetry at recovery boundaries; verify
that tool repetition history survives restart, an outstanding graph reservation is charged before
retry, a committed scheduler result is terminalized without another executor call, and repeated
process loss exhausts the active graph budget with a typed zero-call schedule rather than resetting
usage.

Run after a graph, model, tool, or budget change; in `PR`; and at `TG-01`.

Acceptance: 100 percent hard-limit enforcement, no hidden retry beyond the limit, typed partial result on exhaustion, and complete budget telemetry.

### 8.7 `SEC-TENANT` - Tenant and project isolation

Probe OIDC signature, issuer, audience, time claims, algorithm and key allowlists; API tenant/project
selection; default-deny route and role policy; SQL row-level security; vector retrieval; cache keys;
artifacts; logs; tasks; memory; snapshots; queues; and observability. Include missing credentials,
forged IDs, expired credentials, unknown keys, invalid roles, permission-version change, and
administrator-role boundaries. Compile RLS upgrade and rollback locally; against live PostgreSQL,
verify forced policies, transaction-local scope, cross-scope denial, and an application role with
neither `BYPASSRLS` nor superuser privilege.

Run after identity, storage, retrieval, cache, artifact, or migration changes; nightly sample; full suite at `TG-01` and `RELEASE`.

Acceptance: zero cross-tenant or cross-project read/write, zero unscoped business query, zero
protected unregistered route execution, zero accepted invalid or expired credential, and 100
percent denied attempts audited. Local S1-03 tests may verify denial behavior before S1-10 audit
persistence exists, but TG-01 requires the matching immutable audit events.

### 8.8 `RES-CHECKPOINT` - Checkpoint and task recovery

Inject process termination before and after a tool side effect, while a child is running, before review, and during final aggregation. Resume from the last committed state.

For S1-07, verify monotonically sequenced immutable snapshots, artifact and payload hashes, exact
task and full identity-scope binding, graph/state compatibility, child-context manifest validation,
same-request idempotency reuse, different-request idempotency conflict, cooperative interrupt and
explicit resume, and restart from a new runtime instance over the same repository. Inject loss after
the running checkpoint, during a child call, and after durable assignment output but before the
terminal checkpoint. A durable output must prevent another physical child call. A committed side
effect must return its stored result; a started but uncommitted side effect must require typed
reconciliation and must not run again. Corrupt or cross-scope checkpoints must never restore.

Run after state, queue, checkpoint, tool, or idempotency changes; nightly; and at `TG-01`.

Acceptance: checkpoint recovery = 100 percent, zero repeated committed side effect, and no state transition skipped.

### 8.9 `UNIT-CONTEXT` - Context assembly and protection

Test relevance selection, permission filtering, deduplication, source labeling, protected fields, size estimation, and deterministic assembly.

For S2-01, `tests/context/test_context_assembly.py` must cover exact tenant, project, user
visibility, permission-version, role, permission, classification, artifact, and tool denial;
source- and trust-labeled lossless deduplication; protected overflow; stable authorization-bound
manifests; bounded candidate input; General-child handoff; explicit professional-entry selection;
and manifest and selected-content tamper rejection. Its C0 baseline verifies lossless selection
only. For S2-02, `tests/context/test_context_compression.py` must cover the C0/C1/C2/C3 pressure
boundaries; zero semantic calls for C0/C1; recoverable log references; exact raw-event integrity,
ordering, task, and tenant scope; six recent C2 turns; protected raw-event retention; representative
token reduction; the two-call semantic limit; exact semantic source attestation; C2/C3 output
limits; non-reducing candidate rejection; C3 checkpoint presence and scope; and summary-on-summary
rejection. Field-level comparison and fallback remain S2-03 work.

Run after context, permission, retrieval, or prompt changes; in `PR`; and at `TG-02`.

Acceptance: 100 percent permission filtering and protected-field retention; deterministic input produces a stable context manifest.

### 8.10 `EVAL-COMPRESSION` - C0 to C3 compression

Compare each compression level with uncompressed baselines. Measure retained constraints, numbers, units, citations, decisions, unresolved issues, quality, and token reduction. Include automatic rollback to a less aggressive level.

S2-02 tests the deterministic level policy, raw-event and checkpoint preconditions, adapter
boundary, semantic-call and output limits, protected raw-event retention, and representative C2
token reduction. C2/C3 output is deliberately validation-required and not execution-ready. The
full benchmark retention, quality comparison, C3 median, unsafe-output rejection, and automatic
fallback acceptance remain blocked on S2-03.

For S2-03, `tests/context/test_context_validation.py` must verify exact task, scope, raw-manifest,
and one-time source coverage; 100 percent critical retention; the 98 percent confirmed
non-critical threshold; measured quality degradation no greater than three points; hash-bound
execution readiness; missing-quality rejection; C2-to-C1 and C3-to-C2-to-C1 fallback from raw
events; and enforcement of the existing two-semantic-call limit.

Run after compression model, prompt, threshold, or context format changes; nightly sample; and at `TG-02`.

Acceptance: 100 percent critical-field retention; confirmed non-critical fact retention >= 98 percent; answer-quality degradation <= 3 percentage points; median token reduction >= 50 percent for C2 and C3 cases; unsafe compression always rejected or rolled back.

### 8.11 `INT-MEMORY` - Distillation and restore

Test runtime, session, user, project, and audit memory; candidate creation; conflict handling; deduplication; confidence; TTL; snapshot creation; direct-click restore; intent-based restore; preview; confirmation; cancel; branch restore; and version compatibility.

For S2-04, `tests/memory/test_memory_store.py` must verify all five distinct scopes, exact user and
project visibility, permission-version rejection, explicit project sharing, read/write and
candidate permissions, classification clearance, approval state, TTL, content integrity,
immutable IDs, protected audit records, and the forced-RLS reversible memory migration.

For S2-05, `tests/memory/test_distillation.py` must verify every trigger, recent and protected raw
retention, exact source attestation, the 800-token digest limit, the 30-project-fact limit, distinct
fact/inference/preference candidates, stable IDs, provenance, confidence, expiry, sensitive and
durable candidate state, pre-persistence deduplication, and explicit no-overwrite conflicts.

For S2-06, `tests/memory/test_restore.py` must verify immutable snapshot integrity, direct preview,
intent candidate limits, the 0.90 confidence and 0.12 margin thresholds, ambiguous selection,
exact scope and permission version, compatibility and artifact checks, 6,000/20/10/6 injection
limits, preview tamper rejection, confirm/cancel idempotency, conflicting terminal decisions, and
branch-only restore with no current-state overwrite. Migration tests must cover forced RLS and
append-only snapshot and decision tables.

Run after memory, distillation, snapshot, intent, or restore changes; nightly; and at `TG-02`.

Acceptance: 100 percent tenant isolation and protected-memory retention; intent-restore false-trigger rate <= 0.5 percent; direct snapshot restore success >= 99.9 percent; no silent overwrite of conflicting memory; restored tasks reproduce the committed state.

### 8.12 `SEC-CACHE` - Cache correctness and isolation

Test exact, retrieval, tool, parse, and semantic caches with tenant, project, user, permission, RBAC
policy, route policy, model, prompt, Skill, tool, knowledge, and schema versions in keys. Before the
cache service exists, identity changes must at least prove that every security-version or scope
change produces a distinct authorization component and that an unauthorized project cannot produce
one. Test TTL, invalidation, collisions, poisoning, and authorization changes.

Run after any cache, identity, model, prompt, Skill, tool, or knowledge version change; nightly sample; and at `TG-02`.

Acceptance: zero cross-scope hits, zero stale authorized result after revocation, and cache-hit output semantically equivalent to uncached output.

For S2-07, `tests/cache/test_cache_service.py` must cover all five cache classes, class TTLs,
expiry, value integrity, provenance, version staleness, current-information bypass, hit/miss/stale/
bypass/saved-token metrics, invalidation, collision poisoning, explicit refresh, secret and
authorization-decision denial, unsafe side effects, pure-tool restriction, and G0/P1 plus 0.95
semantic restrictions. Migration tests must cover the scoped forced-RLS cache table.

For S2-08, `tests/cache/test_cache_keys.py` must prove deterministic normalization and order
independence plus distinct keys for tenant, project, user, roles, permission, RBAC, request,
parameters, task, class, model, prompt, Skill, graph, route, tool, adapter, knowledge corpus,
knowledge document, schema, parser, context policy, and extra dimensions. It must test control and
unknown-field rejection, complete-version stale rejection, revocation, and zero cross-user,
cross-project, or cross-tenant hits even when an external digest is reused.

### 8.13 `INT-MINERU` - Primary document parsing

Test MinerU conversion to Markdown and structured output for born-digital and scanned documents. Verify headings, pages, clauses, tables, formulas, figures, captions, coordinates, source hashes, and parser version.

Run after MinerU, file intake, normalization, or container changes; complete corpus at `TG-03`.

Acceptance: clean-file parse success >= 98 percent, scanned-PDF usable text >= 95 percent, table and formula scores meet the frozen baseline, and every extracted element is traceable to source and page.

For S3-04, `tests/knowledge/test_mineru.py` must validate the exact pinned CLI argument array and
zero-shell process port, same-scope accepted-intake binding, working-root isolation, bounded
Markdown, `content_list.json`, and `middle.json`, strict duplicate-key rejection, backend and parser
version binding, page and block traceability, coordinate and image-path safety, output hashes,
zero-call Markdown/text passthrough, legacy Office conversion requirement, and typed timeout,
process, missing-output, malformed-output, source-tamper, path-escape, and scope failures.

### 8.14 `INT-OCR` - Parser fallback chain

Force each stage: MinerU primary, MinerU OCR, and independent OCR. Test quality-gate thresholds, reason codes, retry limits, page-level fallback, merge behavior, and manual-review routing.

Run after OCR engine, quality gate, preprocessing, or parser orchestration changes; complete corpus at `TG-03`.

Acceptance: 100 percent correct fallback selection in labeled cases, no infinite retry, and low-confidence output is never silently published.

For S3-05, `tests/knowledge/test_fallback.py` must exercise primary pass, MinerU OCR selection,
independent OCR selection, page-level replacement and lineage, drawing-page exclusion, page coverage,
meaningful-character, corrupted-character, table, and formula thresholds, source and scope binding,
malformed independent output, adapter timeout or failure, all-stage quality failure, exact reason
codes, preserved attempts, and the three-call hard limit with no repeated identical stage.

For S3-06, `tests/knowledge/test_normalization.py` must cover every canonical element type, heading
hierarchy, numeric clauses, Chinese text, Markdown and simple HTML tables, formulas, figures and
safe assets, auxiliary content, bounded untrusted metadata, stable IDs and hashes, change
sensitivity, deterministic chunking, long-element splitting without numeric or unit loss, complete
source-block coverage, exact page and coordinate locators, non-ready and cross-scope denial,
duplicate or non-contiguous block order, malformed tables, invalid metadata, and zero external
calls.

### 8.15 `INT-KNOWLEDGE` - Knowledge lifecycle

Test explicit button and intent entry, upload, parsing, normalization, chunking, metadata, embedding, indexing, human review, publish, replacement, withdrawal, rollback, incremental update, and audit. Include standards by region, type, date, status, and rights.

For S3-01, verify that typed explicit user intent and the authenticated UI action create one
scope-bound asynchronous `K1` Knowledge dispatch, while a normal question creates no Knowledge
dispatch or physical call. Verify source-artifact membership and hard file limits, minimal child
context, mandatory professional review, zero Main tools and LLM calls, default-deny UI route
authorization, cross-scope and stale-permission denial, and exact approved-candidate binding for an
administrator job. Parsing and publication assertions remain scheduled for S3-03 through S3-09.

Run after Knowledge Agent, parser, chunker, embedding, index, metadata, or publication changes; nightly sample; and at `TG-03`.

Acceptance: 100 percent version traceability; unpublished or withdrawn content is not retrieved; failed update leaves the previous published version available.

### 8.16 `INT-BASH` - Local files and Chinese encoding

The product runtime exposes controlled Bash-backed actions for local files. At minimum, execute these test classes:

1. `ls` and `find` list files whose names contain Chinese characters, spaces, brackets, and leading dashes.
2. `grep` searches Chinese UTF-8 text and returns file, line, match, exit code, stdout, and stderr.
3. `cat`, `head`, `tail`, and `sed -n` read complete or bounded text without truncating a multibyte character.
4. UTF-8 without BOM, UTF-8 with BOM, GBK, GB18030, and UTF-16 are detected or explicitly selected, then normalized to UTF-8.
5. Invalid byte sequences produce a typed error or review request instead of silent replacement.
6. Write actions round-trip Chinese content and filenames without data loss.
7. Edit actions create a version, preserve line endings according to policy, and support rollback.
8. Exit code, stdout, stderr, command ID, encoding, path, actor, tenant, and timestamp are captured.
9. Locale differences do not change the canonical UTF-8 result.
10. NUL-delimited path handling prevents whitespace and newline splitting.
11. POSIX absolute paths plus Windows drive-qualified, drive-relative, rooted, UNC, and traversal
    forms are rejected by the same lexical policy on Windows and Linux before any existence check.

Run after any Bash tool, command allowlist, path, locale, encoding, read, write, or edit change; in `PR`; full corpus at `TG-03` and `RELEASE`.

Acceptance: 100 percent round-trip equality for valid samples; zero garbled Chinese output; zero silent lossy conversion; zero unintended file modification during read/search tests.

For S3-03, `tests/knowledge/test_intake.py` must cover signature-first MIME detection for every V1
type, exact path and scope binding through the S3-02 root policy, streaming size and SHA-256,
immutable-source enforcement, Office ZIP safety without extraction, declared MIME mismatch,
executable and unsupported content denial, UTF-8 with and without BOM, GB18030, GBK, UTF-16LE and
UTF-16BE, invalid and ambiguous bytes, UTF-8 normalization hashes and conversion logs, batch hard
limits, duplicate source handling, symlink escape, and unchanged original bytes.

### 8.17 `SEC-BASH` - Bash sandbox and file safety

Test rejection of:

- unrestricted `bash -c`, command substitution, arbitrary pipelines, and unregistered executables;
- path traversal, symlink escape, absolute paths outside the allowed root, and tenant-root substitution;
- host-foreign absolute, drive-relative, rooted, UNC, and traversal syntax regardless of worker OS;
- unauthorized write, overwrite, delete, move, permission change, process launch, and network access;
- direct edit of immutable raw input or published artifact;
- option injection through filenames beginning with `-`;
- malicious filenames containing newline, control characters, wildcard syntax, or shell metacharacters.

Run after the Bash gateway, allowlist, root policy, authorization, or artifact policy changes; nightly sample; and at `TG-03`.

Acceptance: 100 percent malicious cases denied, zero sandbox escape, zero unauthorized mutation, and every denial audited.

### 8.18 `EVAL-RETRIEVAL` - Hybrid retrieval and citations

Test full-text, vector, metadata filters, reranking, standard validity, supersession, region, effective date, tenant/project scope, and citation reconstruction.

Run after an embedding, chunking, reranking, index, filter, or corpus change; before knowledge publication; and at `TG-03`.

Acceptance: Recall@6 >= 0.92, nDCG@10 >= 0.85, citation correctness >= 0.95, citation traceability = 100 percent, and invalid or unauthorized standards never appear.

For S3-07, `tests/knowledge/test_retrieval.py` must cover canonical snapshot construction, fixed
embedding dimension and versions, Latin/numeric and Chinese tokenization, full-text and vector
ranking, reciprocal-rank fusion, deterministic reranking, stable ties, top-k and candidate bounds,
exact chunk reconstruction, all citation fields, metadata filters, exact role and permission-version
filtering, cross-user/project/tenant denial, draft/superseded/withdrawn exclusion, repository scope
isolation, stale index or corpus versions, and a frozen labeled corpus reporting all four acceptance
metrics.

For S3-08, `tests/knowledge/test_standards.py` must cover stable standard-version identity; strict
date ordering; canonical regions and roles; immutable duplicate registration; same-scope and
same-lineage replacement targets; replacement-cycle denial; exact tenant, project, user, roles,
and permission-version isolation; current and authorized restricted states; draft, replaced, and
withdrawn exclusion; future-effective and expired exclusion; exact region and GLOBAL matching;
standard-type filters; usable public-domain, licensed, and owner-authorized rights; unknown,
expired, or prohibited-rights denial; rights-evidence requirements; supersession; stable reason
codes; mandatory `standard_version_id` snapshot binding; and proof that only applicable records
enter the repository before hybrid scoring.

For S3-09, `tests/knowledge/test_release.py` must cover immutable candidate and diff identity;
idempotent create and conflict; exact-scope and stale-base rejection; deterministic validation and
all failure classes; `DRAFT`, `VALIDATING`, `REVIEW_REQUIRED`, `PUBLISHED`, `SUPERSEDED`,
`WITHDRAWN`, and `FAILED` transitions; an actual aggregation-ready S1-09 professional review bound
to the candidate and validation hashes; non-pass, raw, stale, cross-scope, or mismatched review
denial; S1-13 `KNOWLEDGE` checkpoint creation, self/role/scope/hash denial inherited from the
approval suite, and exact resume; atomic first publication and incremental replacement; removed
snapshot exclusion; distinct approved withdrawal; approved rollback as a new publication from
preserved history; idempotent replay; stale current, wrong action, wrong hash, approval replay, and
pre-commit fault denial with zero partial mutation; and retrieval visibility for only the current
published snapshot set.

### 8.19 `EVAL-QA` - Technical answers

Expert-score correctness, applicability, limits, uncertainty, evidence, citation validity, and safe escalation across the declared domain and six priority methods.

For S4-01, validate the strict request, candidate, claim, support, citation, and result contracts;
stable request, claim, and result hashes; exact reconstruction of source, artifact, document, chunk,
parser, normalizer, content hash, page, and locator evidence; exact-scope, published-state, role,
permission, version, and metadata revalidation; claim-to-quote support terms; and zero candidate-
trusted citation metadata. Force missing applicability inputs, out-of-domain values, missing
candidate, duplicate claim, unrelated or non-exact quote, missing chunk, stale index, draft,
withdrawn, cross-scope, unsupported critical claim, and evidence-backed formal-conclusion cases.
The deterministic boundary must return typed partial, user-input, or human-required results without
a model, network, approval, publication, instrument action, or hidden retry.

Run after model, prompt, Skill, retrieval, standard, review, or context changes; nightly sample; and at `TG-04`.

Acceptance: expert pass rate >= 90 percent, citation validity >= 98 percent, unsupported critical claims = 0, and unsafe definitive conclusions = 0.

### 8.20 `EVAL-PLAN` - Inspection plans

Test objective, scope, basis, methods, layout, equipment, calibration, procedure, sampling, acceptance, safety, data, quality, schedule, deliverables, limitations, and missing-input handling.

For S4-02, validate strict request, template, section, quantity, method, standard-basis, gap,
candidate, and result contracts. Require all seventeen generated template sections exactly once and
in order. Check registered method codes; quantity dimensions, units, non-negative values, and
ordered bounds; method-to-quantity and method-to-basis references; stable request, template, plan,
QA, and result hashes; explicit missing-input reason, impact, owner, and blocking state; and an
immutable review-required, approval-pending, non-formal result. Revalidate the QA result hash and
exact scope, reconstruct every citation from its published snapshot record and standard binding,
and rerun S3-08 date, region, type, lifecycle, rights, role, and supersession applicability. Force
missing/reordered/unknown sections, undeclared and blocking gaps, unsupported or omitted methods,
missing references, invalid units and ranges, wrong-region standards, cross-scope QA evidence, and
candidate approval-state injection.

Run after plan template, Skill, standard, model, prompt, or review change; at `TG-04`; and before publishing a production template.

Acceptance: required-section completeness >= 98 percent, numeric and standard conflicts = 0, and every unresolved required input is explicit.

### 8.21 `EVAL-REPORT` - Inspection reports

Test template fidelity, identity fields, traceable raw data, calculations, units, figures, findings, limitations, conclusion boundaries, approvals, and revision history.

For S4-03, validate strict request, template, source dataset, processing, observation, calculation,
figure, finding, conclusion, revision, candidate, and result contracts. Require all fifteen generated
template sections in order and stable template, request, plan, report, and result hashes. Revalidate
the plan scope/hash/status and approval-pending non-formal state. Trace every immutable source
artifact through method, instrument, valid calibration, operator, acquisition, processing versions,
parameter/output hashes, observations, locations, units, figures, findings, applicable plan bases,
and conclusion. Recompute allowlisted count, minimum, maximum, mean, range, and sum formulas with
exact Decimal arithmetic; reject missing inputs, incompatible dimensions/units, or differing output.
Force cross-scope source/processing/observations, invalid calibration and method, missing finding and
citation references, formal conclusion, tampered plan, skipped revision, invalid unit, and candidate
approval/formal-release injection. Output must remain review-required, approval-pending, and
non-formal without a model, network, approval, publication, instrument, or retry call.

Run after report template, Skill, parser, calculation, model, prompt, or review change; at `TG-04`; and before publishing a production template.

Acceptance: required-field completeness >= 99 percent, numeric consistency = 100 percent, fabricated data or citation = 0, and approval boundary bypass = 0.

S4 source-data golden controls: for S4-04, validate strict source manifest, request, budget, quality
policy, observation, figure, candidate, and result contracts. Bind exact scope, immutable source and
output artifacts, dataset/method/run identity, origin, structure/component/location, coordinate
reference, channels, sample count/rate, dimensions/units, acquisition settings, instrument,
calibration, operator, adapter/parser/algorithm/schema versions, canonical parameter hash, and
processing/result hashes. Force simulated, laboratory, and production origins; expired calibration;
cross-scope and source mismatch; version and parameter mismatch; duration/byte/count/call/attempt
budget excess; model/network/physical action; low completeness/quality and excessive corruption;
channel/sample overflow; missing figure observations; invalid units; and failed output missing cause,
impact, or next action. Require one adapter call, one attempt, explicit partial/failure evidence,
mandatory review, and report eligibility only for clean production output. Verify the deterministic
S4-03 evidence bridge preserves all source, processing, observation, hash, unit, and value fields.

For S4-05, require exactly six stable definition hashes in the canonical order AE, GPR, IE, MV,
RT, and UT. For every method, validate version, ontology-bounded structures and materials,
required acquisition metadata and calibration kinds, registered input dimensions and units,
required processing parameter names, output observation families, explicit source origins,
limitations, safety notes, and production-report policy. Execute one golden request/candidate pair
per method and force missing metadata, invalid calibration, unsupported applicability, missing
parameters, incompatible input, unregistered output, method mismatch, unknown method, cross-scope
data, and laboratory provenance. Require stable request/candidate/result hashes, mandatory review,
zero algorithm/instrument/model/network/approval/publication/retry actions, and no production-report
permission for simulated or laboratory evidence. Real calibrated-device validation and expert
correctness remain gate-blocking external evidence.

### 8.22 `INT-REVIEW` - Review and correction

Test per-result review, cross-result consistency, severity classification, fix instruction, targeted retry, re-review, human escalation, and final review manifest. Force correct, repairable, unrepairable, conflicting, and timeout cases.

For S1-09, reject General, mixed-scope, task/run/hash, non-review-pending, reviewer-version, and
correction-count mismatches before aggregation. Verify that the read-only reviewer context contains
only current result evidence, exact hashes, checklist, identity scope, and registered versions, with
no child scratch, Main history, mutation tools, or user-delivery path. Test every decision. A
`REVISE` result must include actionable findings, invoke only the responsible corrector, validate
the repaired result, and re-review only changed output. Invalid or timed-out review/correction,
missing corrector, and exhausted review/correction budgets must return typed failures. For multiple
dependent or explicitly interacting results, require every per-result `PASS` before cross-result
review; test a cross-result targeted repair and re-review. For independent results, skip cross review
unless explicitly required. Validate deterministic final-manifest hashing and zero aggregation for
any unresolved decision. The Main aggregation gate must accept a completed direct General outcome
and a passing professional manifest, but reject a raw professional outcome and every unresolved
review workflow.

For S4-06, require one stable versioned checklist for each of Technical QA, inspection plan, data
processing, method validation, and inspection report. Rehydrate every exact scope/task/run/type
envelope and rerun its strict hash validators. Force payload tampering, cross-scope/task/run input,
failed/partial/human-required status, unresolved findings, missing QA citation, review or approval
bypass, formal release, and prohibited side-effect counters. Require deterministic PASS for every
clean S4-01 through S4-05 result and strict `ReviewResult` adaptation with zero model/tool/correction
calls. Cross review must run only after per-result PASS and verify QA-to-plan claim/chunk identity,
plan-to-report hash, processing-to-report source/run/version/output/observation fields, method-to-
processing request/candidate hashes, method presence in report sources, and unit/value fidelity.
Force duplicate singular results, omitted scheduled targets through the S1-09 topology checks,
stale or changed hashes, plan/report mismatch, processing/report mismatch, and method/processing
mismatch. Every unresolved per-result or cross-result finding must keep aggregation false.

Run after a professional Skill, reviewer, rubric, graph, or result schema changes; nightly; and at `TG-04`.

Acceptance: 100 percent complex child results reviewed; correction success >= 90 percent for labeled repairable faults; hard correction limit enforced; unrepairable output states the cause and missing action.

### 8.23 `INT-FUNCTION` - Function Calling

Test schema discovery, argument validation, permission, idempotency, version, timeout, typed result, malformed output, and audit.

For S5-02, load schemas only through an authorized S5-01 exposure manifest and verify deterministic
collision-resistant function names, strict model-visible fields, registry/exposure/context hash
bindings, six/twelve exposure limits, and exact tool-version mapping. Test bounded UTF-8 JSON,
duplicate keys, non-finite numbers, unknown fields, wrong types, unknown functions, stale or tampered
catalogs, cross-context reuse, schema-invalid arguments, permission and approval denial, timeout,
malformed adapter output, caller-controlled retry metadata rejection, orchestration-controlled
idempotent replay, budget counting, result identity, and hash-only audit evidence. Invalid calls must
produce zero adapter calls and zero physical-tool-call count.

Run after function schema, registry, or gateway changes and at `TG-05`.

Acceptance: invalid calls rejected before execution, duplicate side effects = 0, and all results satisfy `ToolResult`.

### 8.24 `INT-WEB` - Web Search

Test source policy, time-sensitive queries, citations, result freshness, domain filters, cache, budget, timeout, prompt injection in pages, and offline degradation.

For S5-03, verify registry-only execution, exact HTTPS domain/subdomain rules, source-class ranking,
URL credential, literal-IP, scheme, port, fragment, domain-expansion, and redirect denial; two/four
active and four/eight hard budgets; normalized unique queries; page deduplication; exact publication
and access times; stable evidence, excerpt, citation, cache, and result hashes; current-request cache
bypass and no-store behavior; exact-scope/version cache keys, hit, miss, stale rejection, and
permission isolation; stale and undated current evidence rejection; untrusted instruction-like page
text without authority; malformed, oversized, offline, timeout, and provider failures; zero
fabricated citations; physical-tool, provider-query, and opened-page counts; and hash-only audit.

Run after provider, source policy, citation, cache, or prompt changes and at `TG-05`.

Acceptance: 100 percent cited factual web claims resolve to allowed sources, stale-result policy is enforced, and untrusted page instructions never gain tool authority.

### 8.25 `INT-MCP` - MCP integration

Test local and remote server registration, capability discovery, authorization, schema changes, timeout, cancellation, streaming, asynchronous completion, malformed payload, disconnect, and audit.

For S5-04, verify safe exact local and remote endpoint registration, namespace and audience binding,
remote-only restricted HTTPS, no credential-bearing endpoints, no literal-IP or fragment routing,
and rejection of plaintext-token input fields. Verify that discovery is a separately registered and
metered action, an untrusted manifest cannot add a capability or permission, and name, version,
schema hashes, side effect, streaming, and async declarations must match the static allowlist.
Verify credentials are issued only after registry permission, network, secret-purpose, and
destination checks and bind the exact scope, user, permission version, audience, capability
permission, policy, and expiry; raw credentials never serialize or enter audit or results.

Verify synchronous and asynchronous invocation, contiguous bounded streaming, immutable scoped
artifact enforcement for oversized completion, opaque local handle creation, exact original
task/run/scope/server/capability/input binding, authorized poll and cancel, idempotent cancellation,
terminal replay denial, and monotonic state. Permission, wrong-scope, wrong-user, wrong-task,
wrong-run, stale discovery, schema change, timeout, malformed payload, provider failure, and
disconnect cases must be typed; preflight denials make zero transport or credential calls and a
disconnect preserves the last valid async state.

Run for every MCP server or gateway change, before enabling a server for a tenant, and at `TG-05`.

Acceptance: unauthorized capability calls = 0, contract errors are typed, and disconnects do not corrupt task state.

### 8.26 `INT-INSTRUMENT` - Instruments and AI models

Test CLI, API, SDK, DLL, file, MCP, and simulator adapters; canonical inspection data; model registry; input hash; model version; device identity; calibration; evidence; confidence; and failure mapping.

For S5-05, verify exact transport binding for registered Bash/CLI command identity, safe HTTPS API,
pinned SDK package and entry point, pinned DLL identity and hash, application-owned file-exchange
root, exact MCP server registration and namespace, and explicitly simulated local fixture. Reject raw
command text, dynamic path, unsafe or credential-bearing URL, literal IP, unpinned package/library,
arbitrary file root, cross-namespace MCP, simulator network/secret use, unused transport fields, and
tampered registration hashes. Verify generated instrument and AI-model Tool Registry definitions
bind the exact adapter registration; AI-model definitions remain excluded from physical-tool
execution.

Verify registry permission, secret-purpose, network, destination, approval, idempotency, schema,
timeout, retry, and budget denial before provider execution. A valid instrument request invokes one
injected provider once and returns strict untrusted output plus evidence bound to exact scope, task,
run, call, adapter, transport, origin, input/output, artifacts, device, calibration, model, provider
operation, bytes, duration, and call count. Required device, calibration, or model provenance,
immutable same-scope artifacts, provider identity, output schema/hash, declared errors, and
retryability must fail closed. Typed and generic provider failures perform no hidden retry.

For S5-05 registration hashing, permute every set-valued permission, secret-purpose, and declared
error input before draft construction and validated reconstruction. Equivalent members must produce
one hash across repeated processes and worker operating systems; adding or removing a member must
change the hash. Run the full S5-08 reference profile and invocation suite under protected Linux CI.

For S5-06, round-trip one strict canonical manifest for each of UT, GPR, IE, RT, AE, and MV through
the deterministic UTF-8 codec with exact field and manifest-hash equality. Include Chinese source
names and metadata, spaces, a leading-dash name, registered coordinates, multiple contiguous
channels, exact sample counts/rates/time origins, typed sorted acquisition settings, immutable
same-scope source/channel/calibration artifacts, device/adapter identity, calibration validity and
status, operator qualifications, and parser/encoding provenance. Reject a BOM, malformed UTF-8,
duplicate JSON keys, non-finite numbers, unknown fields, tampered hashes, mutable or cross-scope
artifacts, overlapping or out-of-bounds byte ranges, missing/non-contiguous/duplicate channels,
invalid dimensions or units, non-UTC time, unsorted or duplicate settings and qualifications, lossy
normalization, unsupported methods, and incomplete provenance. Verify processing eligibility and
formal-use eligibility separately; invalid/revoked/expired/out-of-interval calibration,
non-production origin, or missing qualification must block formal use. Verify the S4-04 projection
and comparison preserve exact shared scope, dataset/source, method, topology, channel/sample, unit,
time, instrument, calibration, operator, and parser identity and execute zero external actions.

For S5-08, publish exactly six stable reference profiles in AE, GPR, IE, MV, RT, and UT order. Bind
each profile to the exact S4-05 method-definition hash, S5-05 simulator binding and registration
hashes, deterministic fixture identity/hash, and S5-06 contract. Verify one authorized shared-registry
invocation per method returns a canonical UTF-8 simulated payload whose exact scope, method,
manifest, fixture/profile/registration, adapter/device/calibration/parser provenance, processing
eligibility, and formal-use denial all pass. Each success consumes one physical-tool call and zero
LLM, network, secret, subprocess, real-device, approval, publication, or retry calls. Reject stale or
unknown fixture/profile/registration, caller-selected method or transport, wrong permission/scope/
task/run, changed output/manifest/method/origin/provenance, malformed or non-canonical payload,
cross-scope artifact, output limit, provider identity/error/timeout, and budget exhaustion with typed
evidence and no hidden fallback. Repeat each fixture to prove byte-for-byte determinism and validate
the method Skill's required acquisition settings, calibration kind, input signal dimension, and unit.

Run for every adapter or model version, against a simulator in `PR`, against authorized hardware before deployment, and at `TG-05`.

Acceptance: canonical-data round trip = 100 percent, provenance completeness = 100 percent, duplicate device action = 0, and invalid calibration blocks formal use.

### 8.27 `SEC-TOOLS` - Unified tool security

Test registry allowlist, least privilege, secret isolation, tenant authorization, input validation, output sanitization, prompt injection, SSRF, command injection, data exfiltration, rate limit, timeout, and audit for Bash, Function Calling, Web Search, MCP, instrument, and model tools.

Run after any tool or policy change, nightly sample, at `TG-05`, and in `RELEASE`.

Acceptance: zero unauthorized action or secret exposure; 100 percent high-risk calls have policy and audit evidence.

### 8.28 `E2E` - Complete user workflows

Test Web, desktop, and PWA flows for technical QA, plan generation, report generation, raw-data processing, memory restore, knowledge update, asynchronous tasks, review, human approval, export, and failure recovery.

For S6-01, validate the strict task-create, task-read, and task-event contracts against the
authenticated Web client. Verify exact tenant, project, user, and permission-version binding;
default-deny route permissions; bounded input; server-owned task identity and state; monotonic event
sequences; reconnect after an acknowledged sequence with no gap or duplicate; terminal replay;
cross-scope and unknown-task denial; cache prevention; typed non-disclosing failures; and zero direct
child, review, approval, tool, model, provider, instrument, publication, or formal-use bypass. Inspect
the Web shell for semantic landmarks, labels, keyboard access, visible focus, live-region status,
reduced-motion behavior, contrast-safe tokens, safe text rendering, and responsive narrow-screen
layout. Deterministic local contract tests do not count as a live browser, assistive-technology, or
production streaming qualification.

For S6-03, validate manifest identity, start URL, standalone presentation, icons, theme, safe-area
layout, install registration, and explicit connection status. Parse the service-worker policy and
exercise its route predicate: only public same-origin shell GETs may enter the versioned shell cache;
all `/v1/` routes, task/event traffic, authorization-bearing requests, non-GET requests, cross-origin
resources, payloads, credentials, and user data bypass storage. Offline behavior may render the shell
and limitations only and cannot queue a mutation or fabricate task progress or completion.

For S6-08, verify exactly seven consecutive UTC service dates, the hash chain, same immutable build
and assurance/performance/calibrated-budget/configuration bindings, approved production-like origin,
no future or duplicate date, and at least six elapsed 24-hour periods from first start to evaluation.
Each day must have nonzero authorized workload, PASS security/resilience/performance/token states,
zero P0/P1, leak, duplicate side effect, correctness, or isolation count, 100 percent critical
workflow pass rate, and at least 98 percent noncritical pass rate. Require the configured number of
distinct qualified expert acceptances bound to the exact ledger and rubric. Synthetic historical
fixtures validate only the state machine and cannot count as a live pilot day.

Run nightly as a smoke subset, after client/API changes, and as a full suite at `TG-06`.

Acceptance: critical workflow pass rate = 100 percent, noncritical workflow pass rate >= 98 percent, and no client can bypass Main Agent or review policy.

### 8.29 `SEC-ALL` - Commercial security suite

Run threat-model cases, SAST, dependency and image scanning, secret scanning, API fuzzing, tenant isolation, authorization, storage encryption checks, audit integrity, upload attacks, prompt injection, model/tool boundary abuse, and penetration tests.

For S6-05, publish a versioned required-case catalog and aggregate only exact evidence identities.
Fail the assessment on a missing required case, P0/P1 finding, tenant leak, duplicate committed side
effect, hard retry breach, incomplete unrepaired-failure explanation, stale or fabricated evidence,
or a live-required case supported only by simulation. Local SAST-like lint, dependency audit, secret
scan, deterministic API/input boundary tests, and injected provider/storage/process failures may form
a local assessment, but penetration, production isolation, live failover, and hardware cases remain
blocked until executed in their declared environments.

Run nightly automated subsets, monthly in active development, for every release candidate, and after a critical dependency or policy change.

Acceptance: zero open `P0` or `P1`, zero tenant leak, zero known critical exploitable dependency without an approved compensating control.

### 8.30 `RES-ALL` - Fault injection and self-repair

Inject LLM timeout, rate limit, malformed response, parser crash, Redis loss, database failover, object-store delay, process death, queue redelivery, MCP loss, instrument disconnect, disk-full condition, and partial network partition. Test diagnose -> bounded correction -> revalidation -> explicit failure.

For S6-04, verify exact-scope quota claims and release under concurrent tenant/user pressure, active
and hard denial, idempotent release, counter integrity, and cross-scope isolation. Verify canonical
backup-manifest hashes and chains, immutable store/artifact inventory, encryption-key references
without key material, source-to-restore hash equality, checkpoint and event counts, approval and
publication zero-loss after acknowledgement, measured RPO/RTO, rollback evidence, degraded modes,
and typed next actions. Synthetic or in-memory recovery may validate contracts but cannot PASS an
approved-policy or live-service recovery gate.

Run nightly subset, weekly full suite during S6, after recovery or infrastructure changes, and at `TG-06`.

Acceptance: service availability and recovery meet the approved SLO; committed side effects are not repeated; hard retry limits hold; unrepaired cases expose reason, completed work, impact, and required next action.

### 8.31 `PERF` - Performance and concurrency

Measure P50, P95, and P99 latency, throughput, queue delay, concurrent subagents, database load, vector search, parser throughput, artifact transfer, and client streaming using the selected reference hardware.

Run a sample nightly, after architecture or infrastructure changes, before and after budget calibration, and at `TG-06`.

Initial targets to validate and then calibrate:

- cached simple answer P95 <= 3 s;
- uncached simple answer first token P95 <= 5 s;
- ordinary tool task P95 <= 30 s excluding an external instrument's physical run time;
- asynchronous task enqueue P95 <= 1 s;
- no correctness or isolation failure at 100 concurrent active user tasks on reference hardware.

For S6-06, each metric series must bind the exact build, benchmark profile, workload, environment,
hardware, and configuration. Use deterministic nearest-rank P50, P95, and P99 over at least 20
samples for a local contract series and the profile-defined larger count for release evidence. Record
elapsed time, throughput, ordinary failures, correctness failures, and isolation failures. Reject
duplicate metric identities, insufficient or nonpositive samples, stale bindings, target breaches,
and any correctness or isolation failure. A local in-memory concurrency and serialization run cannot
satisfy database, vector, parser, artifact-transfer, provider, queue, production cache, or approved
reference-hardware requirements.

### 8.32 `EVAL-TOKEN` - Token and cache economics

Measure input, output, hidden orchestration, review, retry, cache-hit, and cache-miss tokens per task class. Compare rules-only route, direct General path, single subagent, multi-subagent, compressed context, and restored memory.

Run after model, prompt, Skill, compression, review, routing, cache, or knowledge changes; weekly; and at `TG-06`.

Initial acceptance targets:

- G0 General tasks: P95 total tokens <= 4,000 and hard limit = 8,000;
- P1 single-professional tasks: P95 total tokens <= 10,000 and hard limit = 20,000;
- P2 plan or report-section tasks: P95 total tokens <= 35,000 and hard limit = 60,000;
- P3 full-report or cross-method tasks: P95 total tokens <= 60,000 and hard limit = 120,000;
- K1 knowledge-import tasks: P95 total tokens <= 20,000 and hard limit = 40,000;
- C2 and C3 compression median input-token reduction >= 50 percent;
- repeated pilot workload median total-token reduction >= 25 percent;
- stable repeated-query cache hit rate >= 35 percent in the pilot workload;
- cache hits reduce LLM input tokens by >= 80 percent for exact eligible requests;
- quality thresholds in Sections 8.19 through 8.21 remain satisfied.

For S6-06, record integer input, output, hidden orchestration, review, retry, cache-hit, and cache-miss
tokens per repeated workload and preserve cold and warm runs separately. Compute reduction from exact
paired totals and the deterministic median across workloads. Estimated local counts validate only the
calculation contract; release evidence requires provider usage and the matching quality assessment.
Fail on a negative count, missing pair, changed workload or build binding, median reduction below 25
percent, stable-query hit rate below 35 percent, or exact eligible cache-hit input reduction below 80
percent.

For S6-07, provide exactly one P95/P99 observation for every task-class and budget-dimension pair.
Bind each observation to the accepted S6-06 build and profile, require the declared minimum sample
count, successful tasks only, zero correctness/isolation failures, and matching quality evidence.
Recompute `ceil(P95 * 1.15)` and `min(ceil(P99 * 1.25), product_global_limit)`, require default not
above hard, require active equal default, and prove no calibrated hard limit exceeds its V1 global
ceiling. Reject duplicates, missing dimensions, stale bindings, local-only or estimated evidence,
and mutation of the source default policies. Synthetic formula tests cannot PASS the production
profile.

### 8.33 `SEC-BASELINE` - Security, compliance, license, and SLO design

Review the threat model, trust boundaries, data classification, approval boundaries, retention and deletion rules, encryption and key-management policy, incident ownership, code-and-model SBOM, third-party license obligations, replacement plans, SLI/SLO definitions, error budgets, RPO, RTO, and degraded modes. Trace every mandatory control to an implementation task and test owner.

For each locked Python component, validate that a versioned evidence snapshot covers the exact
SBOM purl and dependency scope, binds the SBOM and lock-file hashes, records the official PyPI
version endpoint and response hash, and preserves either the author-declared SPDX expression or
the legacy/missing-metadata review state. The refresh tool may use the network only when explicitly
run; CI validation is offline. Automated evidence capture must leave every legal decision pending.

When a personal-project governance record exists, validate its exact baseline hash, provisional
jurisdiction, pre-commercial stage, accepted engineering targets, and source. Confirm the Security,
Legal, Operations, and Quality roles remain unassigned unless separately evidenced; independent
approval remains unsatisfied; R-005 and R-007 remain open; and production deployment, production
customer data, formal compliance claims, and commercial release remain blocked.

Run after any baseline policy or major architecture dependency changes, before the related architecture decision is approved, at `TG-00`, and in `RELEASE`.

Acceptance: 100 percent critical assets, trust boundaries, and locked components are covered;
every high-risk threat and license obligation has an owner and treatment; official metadata and
source-response hashes are complete; every required control maps to a task and test; SLO metrics
are versioned and measurable; unresolved legacy licenses, jurisdiction-specific decisions, and
authority mappings remain explicit; accountable human approval is required before the baseline
becomes effective.

### 8.34 `SEC-PLATFORM` - Platform secrets, encryption, and approval security

Test TLS enforcement, database/object/queue/backup encryption, secret retrieval and redaction, key separation, rotation, revocation, unavailable-key behavior, approval authentication, approval replay prevention, immutable decision records, audit hashes, and recovery after secret or key change.

For S1-11, verify strict reference-only secret and key contracts; exact environment, tenant, project,
user, permission, and purpose binding; bounded lease expiry; stale-version denial; unavailable-provider
failure; and zero raw value in representation, serialization, logs, traces, audit, or artifacts. Permit
plaintext transport only for loopback local/CI endpoints. Require HTTPS with certificate validation,
PostgreSQL `sslmode=verify-full`, and Redis TLS outside that exception. Encrypt with AES-256-GCM,
unique 96-bit nonces, and authenticated tenant/project/purpose context. Reject wrong scope, altered
ciphertext, altered authenticated data, revoked keys, and invalid key length. After rotation, new
writes use the new key and authorized old ciphertext remains readable only while the predecessor is
decrypt-only. Resolve managed PostgreSQL and Redis credentials transiently and reject direct secret
configuration outside local/CI. Every success and denial must correlate to a hash-only `SECURITY`
audit event; no plaintext fallback is allowed.

Run after identity, secret, key, encryption, approval, storage, or audit changes; nightly sample; at `TG-01`; and in `RELEASE`.

Acceptance: zero plaintext secret or protected artifact exposure; unauthorized or replayed approvals = 0; key rotation and revocation preserve authorized availability and deny stale credentials; 100 percent required operations carry traceable policy and audit evidence.

### 8.35 `UNIT-TOOLREG` - Shared Tool Registry contracts

Test stable tool names and versions, side-effect classes, typed input and `ToolResult` schemas, scope and permission requirements, budget metadata, idempotency, timeout, retry, secret and network declarations, test ownership, registry publication, version replacement, and rejection of model-produced or unregistered definitions.
Apply one shared nested-schema plaintext-secret field matrix to Tool Registry, Adapter SDK, and MCP
capability registration. Every boundary must reject the same normalized field names while preserving
its declared validation error contract.

For S1-12, also verify deterministic content-derived registry versions, stale expected-version
rejection, strict Draft 2020-12 schema checking before and after execution, exact task and full
identity-scope binding, stable idempotency keys for side effects, identity and SHA-256 binding of
every `ToolResult`, S1-08 physical-call accounting and identical-call denial, mandatory hash-only
S1-10 `TOOL` audit records, timeout conversion, and zero adapter calls for every preflight denial.

For S5-01, verify explicit internal, Bash, Function Calling, Web Search, MCP, instrument, and
AI-model families; transport, data-scope, destination, approval, error, recovery, audit-owner, and
test-owner declarations; family-specific invalid-combination rejection; deterministic authorized
exposure with no secret or adapter-state fields; the six-tool default and twelve-tool hard limit;
the one-namespace default and two-namespace MCP hard limit; exact registry-version, tool, permission,
network, secret-purpose, destination, and approval-grant filtering; S3-02 definition migration;
undeclared error and invalid retryability rejection; and zero physical calls for every exposure or
preflight denial. Use only injected deterministic adapters and make zero live provider, network,
MCP, model, or instrument calls.

Run after the core registry, any registry schema, or adapter-registration logic changes; in `PR`; at `TG-01`; and before any registered tool is enabled.

Acceptance: 100 percent registered definitions satisfy the versioned contract; invalid or unauthorized definitions are rejected; no tool executes outside the shared registry; registry-version changes invalidate dependent caches and contexts.

### 8.36 `INT-APPROVAL` - Human approval checkpoints

Test pause, preview, authorized approve, reject, request-change, expiry, cancellation, delegation policy, stale-candidate rejection, candidate-hash binding, resume, duplicate decision, audit, and recovery for knowledge, plans, reports, critical findings, high-impact instruments, destructive operations, and release publication.

For S1-13, verify exact tenant/project and permission-policy binding, separation of requester and
approver, distinct required release roles, bounded delegation records, monotonically sequenced
candidate/delegation/decision/resume events, previous-event and event SHA-256 verification, restart
from a new service over the same repository, exact-content decision and resume idempotency,
conflicting ID and duplicate-actor denial, forced-RLS append-only migration upgrade and rollback,
and correlated hash-only S1-10 `APPROVAL` audit events for every allow and denial.

For S4-07, verify separate `QUALIFIED_PLAN_APPROVER`, `QUALIFIED_REPORT_APPROVER`, and
`QUALIFIED_FINDING_APPROVER` rules. Plan and preliminary report checkpoints must revalidate strict
result/content hashes, exact scope/task, review-pending and approval-pending boundaries, PASS S4-06
assessment, and aggregation-ready S1-09 manifest bound to exactly one reviewed child envelope.
Critical-finding checkpoints must reject the ordinary report path and require an exact
HUMAN_REQUIRED report, non-empty sorted unique critical finding IDs, qualified-human flags, S4-06
HUMAN_REQUIRED assessment, and S1-09 human-required pause; hash every selected statement,
observation, calculation, plan basis, limitation, and evidence reference. Force changed result,
stale assessment/manifest, wrong result type/action/target/role/scope/permission/hash, self approval,
unresolved or fabricated review state, ordinary approval of a critical report, rejection, change,
expiry, conflicting IDs, duplicate actor, stale subject, and resume replay. Require exact
idempotency for unchanged creation/decision/resume, one resume grant, hash-only previews and audit,
and zero model/tool/network/publication/user-delivery actions. Plan approval must not imply report
or formal approval; report approval must not change formal-release state.

Run after approval policy, identity, checkpoint, publication, formal-artifact, or release workflow changes; nightly; at `TG-01`; in the affected later phase gate; and in `RELEASE`.

Acceptance: 100 percent mandatory checkpoints block until a valid decision; unauthorized, stale, replayed, or mismatched-hash approvals are rejected; decision and resume are idempotent; no protected operation bypasses approval.

### 8.37 `INT-DATA-LIFECYCLE` - Retention, export, deletion, and legal hold

Test scope-aware retention, user and project export, deletion request, legal hold, backup expiry, cache and index invalidation, artifact tombstones, cryptographic erasure, restore restrictions, immutable audit retention, cancellation, partial failure, and cross-tenant denial.

For S2-09, the local deterministic subset verifies 1 through 3650 day retention bounds, ordinary
and audit defaults, content and export-manifest hashes, exact scope and classification checks,
retention denial, hash-bound normal and forced deletion approvals, idempotent tombstones, legal-hold
application and release, object-unique-key cryptographic erasure, key-provider failure, permission
denial, forced-RLS lifecycle tables, append-only event DDL, and migration rollback. Live backup
expiry, cache/index invalidation, distributed partial failure, and immutable audit integration must
remain explicit blockers when the full group is assessed without approved services.

Run after memory, storage, artifact, backup, cache, index, retention, export, deletion, or legal-hold changes; nightly sample; at `TG-02`; and in `RELEASE`.

Acceptance: 100 percent eligible data is exported or deleted within the approved policy; held or immutable evidence is not destroyed; deleted data cannot be restored or retrieved outside the documented retention exception; cross-scope lifecycle action = 0; every action and denial is audited.

### 8.38 `OBS-AUDIT` - Audit completeness and trace correlation

Test strict event validation; required actor, scope, action, target, policy, SHA-256, UTC time,
outcome, request ID, trace ID, and span ID fields; exact-event idempotency; conflicting event IDs;
monotonic per-scope sequence; previous-event and event hash-chain verification; tamper detection;
cross-tenant and cross-project read denial; and append-only storage. Compile the PostgreSQL upgrade
and rollback and verify forced RLS plus database rejection of update and delete.

Create parent and child spans through the OpenTelemetry SDK, inject and extract W3C `traceparent`,
and prove that every audit event references the active trace and span. Reject malformed external
trace context and non-allowlisted or sensitive attributes. Exercise authorization, task, agent,
checkpoint, budget, review, correction, model, tool, and cache event kinds and calculate the security
baseline completeness formula from an explicit required-event set. Raw credentials, prompts,
business payloads, and unrestricted tool output must never enter an event or span attribute.

Run after audit schema, trace propagation, telemetry exporter, identity audit wiring, or required
event-set changes; in `PR`; and at `TG-01` and `RELEASE`.

Acceptance: audit completeness = 100 percent for the declared required set; trace correlation = 100
percent; hash-chain and append-only integrity = 100 percent; cross-scope reads and writes = 0; raw
secret or unrestricted business-content fields stored = 0.

### 8.39 `PROVIDER-SMOKE` - Model route and provider feasibility

For every selected or candidate model route, validate strict request and structured-output schemas,
allowlisted synthetic function arguments, output-token and timeout limits, typed cancellation,
timeout, refusal, incomplete, and rate-limit states, exact provider/model/endpoint/region/retention
metadata, credential redaction, and the applicable data and jurisdiction policy. Record physical
network calls separately from logical actions.

For the S5-07 local inference gateway, use one injected deterministic provider and verify one-call
success plus typed refusal, incomplete, rate-limit, timeout, cancellation, declared/generic failure,
malformed identity and usage, invalid output schema, failed quality threshold, and post-provider
budget overrun. Bind the exact S5-06 manifest, API/profile registry hashes, route, provider,
endpoint, model snapshot, instruction, parameters, output/artifacts, actual input/output tokens,
latency, confidence, metrics, status, and provider-call count into evidence and correlated MODEL
audit. Preflight registry, scope, applicability, canonical eligibility, formal-use, network,
permission, schema, and budget denials must make zero provider calls. The LLM-call and token meters
must increment exactly once while physical-tool calls remain zero. No plaintext secret, full
canonical payload, or unrestricted provider output may enter audit or error text.

The personal-development offline route must make zero network calls, accept only public or
synthetic data, and cannot claim production eligibility. A hosted candidate cannot run when the
current jurisdiction is outside the provider's official supported list, and a local candidate
cannot run until the exact model, weights, license, quantization, context, concurrency, and hardware
benchmark are frozen. Blocked candidates require a typed reason and next action; do not request or
store a credential for an ineligible route.

Run after model, provider, endpoint, region, retention, deployment, or reference-hardware changes;
before S0-05 completion; at `TG-00`; and in `RELEASE` for the exact release candidate.

Acceptance: every selected route passes all applicable checks; schema and unknown-field rejection
are deterministic; secrets in evidence or logs = 0; unauthorized data transfer = 0; unsupported or
unsized routes make zero physical calls and remain blocked; provider, model snapshot, region,
retention, latency, usage, and result evidence are complete for every physical call.

### 8.40 `UNIT-MODELREG` - Model API configuration registry

Test strict provider, endpoint, model, compliance, binding, selection, and resolved-route contracts;
deterministic publication hashes; duplicate and untrusted-definition rejection; exact environment,
tenant, project, permission, network, data-class, capability, and token-limit authorization; disabled
and production-ineligible routes; secret-reference-only serialization; typed recovery actions; and
hash-only MODEL audit events for allow and deny decisions.

Also test bounded UTF-8 YAML and environment-file parsing, safe relative catalog resolution,
unknown fields and YAML tags, duplicate environment variables, process-environment precedence,
enabled-versus-disabled missing-secret behavior, exact secret selector assembly, read-only local
secret resolution, configuration hashes that exclude secret values, application-state attachment,
non-secret readiness, zero-network startup, and stable non-disclosing failures.

For S5-07 completion, also test strict inspection-model profiles with exact provider/model snapshot,
sorted six-method/structure/material applicability, S5-06 input-schema hash, safe strict output
schema and hash, training/validation evidence scope, metric thresholds, runtime/resource bounds,
declared/retryable errors, report-eligibility class, and deterministic registry/profile hashes.
Reject untrusted, duplicate, unknown, cross-catalog, schema-changing, applicability-empty,
unvalidated formal, resource-unbounded, or hash-tampered profiles. Verify request hash and exact
canonical scope/manifest/profile bindings, reference-only credentials, one selected route, no
implicit model fallback after a physical attempt, and separate LLM/tool budget counters.

Run after any provider, model, endpoint, capability, secret-binding, fallback, or selection-policy
change; before a registry snapshot or binding is enabled; in `PR`; and at `TG-05` and `RELEASE`.

Acceptance: unknown fields and stale registry hashes are rejected deterministically; plaintext
secrets stored or serialized = 0; cross-scope routes = 0; unauthorized or production-ineligible
routes = 0; every resolution decision has one correlated MODEL audit event; registry hashes are
stable for identical content; and configuration-only tests make zero physical provider calls.

### 8.41 `RELEASE` - Immutable release-candidate qualification

For S6-09, require a canonical V1.0 manifest for one immutable Git commit. Verify exact hashes and
sizes for source, lock, SBOM, schema, configuration, server/client packages, migrations, prompts,
Skills, tools, models, S6-01 through S6-08 evidence, and every test artifact. Reject duplicate or
mutable artifacts, unknown fields, stale bindings, missing prerequisite PASS, and any unsafe count.

Run upgrade and downgrade on a production-like database copy and prove restored schema and protected
data hashes. Offline PostgreSQL SQL compilation is an additional local check, not live rollback
evidence. Sign only the canonical candidate hash with an approved Ed25519 key reference, store no
private key material, and resolve the verification key from an application-owned trust registry.
Reject an unknown, disabled, revoked, wrong-purpose, wrong-environment, identity-mismatched, or
candidate-substituted key before release qualification. Release smoke must cover
health, identity, tenant isolation, task creation and streaming, review, approval denial, cache
isolation, tool denial, backup readiness, migration state, and rollback readiness on the exact
candidate. A generated test key or synthetic smoke result validates only the contract.

Acceptance: all prerequisites and mandatory smoke checks PASS; migration and rollback preserve
protected data; artifact and candidate hashes match; signature verification passes; P0/P1, leak,
duplicate committed side effect, correctness failure, and isolation failure counts are zero.

For S6-10, verify that publication makes zero adapter calls unless the exact sealed candidate,
artifact set, PASS RELEASE assessment, PASS TG-06 evidence, and fresh authorized release decision
all match the commercial target. Verify exact-request idempotency, changed-request conflict, one-call
publisher execution, exact deployed-candidate identity, immutable deployment reference, and a
PUBLISHED_PENDING_SMOKE state. Post-publication checks must be live, timely, exact-publication bound,
complete, and have zero P0/P1, leak, duplicate side effect, correctness, or isolation failure. Any
mismatch or unsafe result becomes ROLLBACK_REQUIRED and cannot be described as a completed release.
Injected local publisher tests validate only the state machine and perform no external publication.

## 9. Test environment and evidence

Required environments are:

- `local`: developer tests with simulated external services;
- `ci`: clean, reproducible automated tests;
- `staging`: production-like identity, storage, queues, observability, and isolated synthetic data;
- `hardware-lab`: authorized instruments and reference samples;
- `shadow`: de-identified pilot traffic with no autonomous formal publication.

Every test run must record:

- test group and case IDs;
- plan task and commit or build ID;
- environment and configuration hash;
- model, prompt, Skill, tool, parser, knowledge, and schema versions where applicable;
- start and end time;
- data-set version;
- result and measured metrics;
- evidence location;
- defect IDs and owner;
- reviewer and approval time for a gate.

Secrets, raw credentials, unauthorized standards, and personal data must not appear in test logs.

An unversioned local workspace may use an explicit workspace build identifier for an early task check, but that result cannot satisfy a phase or release gate. Phase and release evidence requires a version-controlled commit or immutable build identifier produced by CI.

## 10. Stop and rollback rules

Stop the affected suite immediately when a test detects a `P0` condition. Quarantine the environment, preserve evidence, invalidate affected caches, and follow the incident runbook.

Rollback a candidate when:

- a mandatory phase group fails;
- a migration cannot restore the prior schema and data;
- quality drops below its gate threshold;
- P95 token use or latency regresses by more than 20 percent without approval;
- a new cross-tenant, duplicate-side-effect, or unsafe-tool condition appears.

## 11. Gate status and execution log

### 11.1 Current gate status

The S0 engineering baseline now has an immutable GitHub commit, passing remote CI evidence, and a
protected public `main` branch. TG-00 remains blocked because the required human approvals,
licensed standards, authorized real-device samples, expert gold answers, and production provider
decision do not yet exist. Synthetic build evidence is not promoted to phase-gate evidence for
those missing inputs.

| Gate | Current state | Blocking groups | Next scheduled time |
|---|---|---|---|
| `TG-00` | `BLOCKED` | `DATASET` rights/real-data/expert-gold approval; `SEC-BASELINE` human approval; provider smoke; legal license decisions | after R-001, R-003, R-005, and R-007 to R-009 close |
| `TG-01` | `BLOCKED` | local assigned-group and immutable baseline CI tests pass, but `SEC-TENANT`, `RES-CHECKPOINT`, `OBS-AUDIT`, `SEC-PLATFORM`, and `INT-APPROVAL` still require approved live-service probes; exact approved-candidate revalidation and accountable security and license approval are missing | after R-005, R-007, and R-010 close and the approved candidate is available |
| `TG-02` | `BLOCKED` | local automated assigned groups pass; immutable CI, approved live PostgreSQL and external services, full compression benchmark, backup expiry, cache/index invalidation, and accountable baseline approvals are missing | after external prerequisites are available and the exact candidate is revalidated |
| `TG-03` | `BLOCKED` | local synthetic/offline assigned groups pass; real pinned MinerU and independent OCR corpus, licensed standards and accountable approvals, approved production embedding/frozen retrieval corpus, live PostgreSQL/full-text/vector/object-store atomicity and recovery, zero-skip Linux path corpus, and protected immutable CI are missing | after the external evidence is available and exact candidate is revalidated |
| `TG-04` | `BLOCKED` | local assigned groups pass; formal/accreditation approval, licensed standards, calibrated real-device samples, authorized expert gold answers and adjudication, qualified accountable approvers, live identity and durable approval storage, and immutable CI revalidation are missing | after R-004, R-008, and R-009 close and the exact candidate is revalidated |
| `TG-05` | `BLOCKED` | local assigned groups pass; immutable protected CI, live Function Calling/Web/MCP/model provider and managed-secret evidence, production adapter/parser/model qualification, authorized calibrated real-device and hardware-lab data, expert gold, and accountable security, rights, license, provider-policy, and formal-use approvals are missing | after external prerequisites are available and the exact candidate is revalidated |
| `TG-06` | `NOT_RUN` | complete `RELEASE` profile and all assigned groups | after S6-01 through S6-09 and before S6-10 |

### 11.2 Execution log

Append one row per meaningful test run. Do not overwrite prior evidence.

| Run ID | Date | Task/build | Profile or group | Environment | Result | Evidence | Defects | Reviewer |
|---|---|---|---|---|---|---|---|---|
| S5-05-CI-REPAIR-20260826-01 | 2026-08-26 | S5-05 registration hash repair / commit `f25e4e840f2a029744c2954b2c7e9199ae56a491` / PR 8 | protected `quality`: controlled generation, DOC, full regression including S5-08, Ruff, strict mypy, dependency audit, and evidence upload | GitHub Actions Ubuntu 24.04 / CPython 3.12.14 / uv 0.11.20 | `PASS` | [run 32920295360](https://github.com/xh92117/NDT-Agents/actions/runs/32920295360) and [repair evidence](./evidence/s5/s5-05-registration-hash-repair-20260826.md); 1021 tests passed with zero skip; DOC 1.68, Ruff, strict mypy over 187 source files, and dependency audit passed | process-dependent registration-hash defect closed; no remaining S5-05 task defect | Codex |
| S5-05-CI-REPAIR-LOCAL-20260826-01 | 2026-08-26 | S5-05 registration hash repair / PR 8 / mutable follow-up workspace | registration set permutation and semantic-change test, S5-08 reference adapters, `INT-INSTRUMENT`, `SEC-TOOLS`, full regression, Ruff, format, strict mypy, DOC, and diff checks | local Windows / CPython 3.12.13 / uv 0.11.20 | `PASS` | [repair evidence](./evidence/s5/s5-05-registration-hash-repair-20260826.md); 92 focused and 1020 full-regression tests passed with one documented Windows skip; Ruff, format, strict mypy, DOC 1.68, and diff checks passed | Ubuntu run 32919785241 exposed process-dependent set-array ordering after the same source passed run 32919640865; repaired immutable Linux rerun pending | Codex |
| S3-02-CI-REPAIR-20260826-01 | 2026-08-26 | S3-02 cross-platform path repair / commit `3dab6601406cf66fd8b90dec9c7a8e0bf5ccf96b` / PR 8 | protected `quality`: controlled generation, DOC, full regression, Ruff, strict mypy, dependency audit, and evidence upload | GitHub Actions Ubuntu 24.04 / CPython 3.12.14 / uv 0.11.20 | `PASS` | [run 32919640865](https://github.com/xh92117/NDT-Agents/actions/runs/32919640865) and [repair evidence](./evidence/s3/s3-02-cross-platform-path-repair-20260826.md); 1020 tests passed with zero skip; DOC 1.66, Ruff, strict mypy over 187 source files, and dependency audit passed | first-run host-dependent path defect closed; no remaining S3-02 task defect | Codex |
| S3-02-CI-REPAIR-LOCAL-20260826-01 | 2026-08-26 | S3-02 cross-platform path repair / PR 8 / mutable follow-up workspace | direct path matrix, S3-03 intake reuse, `INT-BASH`, `SEC-BASH`, full regression, Ruff, format, strict mypy, DOC, and diff checks | local Windows / CPython 3.12.13 / uv 0.11.20 | `PASS` | [repair evidence](./evidence/s3/s3-02-cross-platform-path-repair-20260826.md); 62 focused and 1019 full-regression tests passed with one documented Windows skip; Ruff, format, strict mypy, DOC 1.66, and diff checks passed | first PR quality run 32919288909 reproduced `FILE_NOT_FOUND` for `C:/escape.txt` on Ubuntu; repaired immutable Linux rerun pending | Codex |
| S5-01-CONVERGENCE-20260826-01 | 2026-08-26 | S5-01 approved convergence finding `CCR-20260826-001` / branch `codex/s6-clients` / mutable workspace | guard matrix, `UNIT-TOOLREG`, affected Adapter SDK and MCP validation, `SEC-TOOLS`, full regression, Ruff, format, strict mypy, DOC, and diff checks | local Windows / deterministic schema fixtures / CPython 3.12.13 | `PASS` | [schema-policy convergence evidence](./evidence/s5/s5-01-schema-policy-convergence-20260826.md); 10 pre-change guard, 115 related tool, and 1012 full-regression tests passed with one documented Windows skip; one authority and three direct callers remain; Ruff, format, strict mypy, DOC 1.65, and diff checks passed | approved finding closed; no public contract or behavior change; private-name external consumers remain unknown | Codex |
| S6-01-REPAIR-20260826-01 | 2026-08-26 | S6-01 event atomicity repair / branch `codex/s6-clients` / mutable workspace | client race, E2E boundary, full local regression, Ruff, format, strict mypy, DOC, and diff checks | local Windows / in-memory repository with deterministic two-thread barrier / CPython 3.12.13 | `PASS` | [event atomicity repair evidence](./evidence/s6/s6-01-event-atomicity-repair-20260826.md); pre-repair reproduction committed the same sequence twice; repaired result commits once and rejects once; 9 client and 1003 full-regression tests passed with one documented Windows skip; Ruff, format, strict mypy, DOC 1.65, and diff checks passed | local `DEF-CLIENT-001` closed; durable multi-process transaction, fan-out, load, proxy, and immutable-CI evidence remain | Codex |
| S6-10-REPAIR-20260826-01 | 2026-08-26 | S6-10 publication-authority repair / branch `codex/s6-clients` / mutable workspace | S6-09 and S6-10 focused tests, full local regression, Ruff, format, strict mypy, DOC, and diff checks; not publication or complete RELEASE | local Windows / static authority and key registries with generated attack fixtures / CPython 3.12.13 | `PASS` | [publication-authority repair evidence](./evidence/s6/s6-10-publication-authority-repair-20260826.md); 18 focused and 1002 full-regression tests passed with one documented Windows skip; missing, revoked, and substituted authority records were denied with zero publisher calls; Ruff, format, strict mypy, DOC 1.65, and diff checks passed | local `DEF-REL-002` closed; S6-10 remains blocked by durable authority/identity adapters, sealed candidate, TG-06 PASS, publisher, deployment, and live smoke | Codex |
| S6-09-REPAIR-20260826-01 | 2026-08-26 | S6-09 trusted-key repair / branch `codex/s6-clients` / mutable workspace | S6-09 and S6-10 focused tests, full local regression, Ruff, format, strict mypy, DOC, and diff checks; not complete RELEASE | local Windows / static trusted-key registry and generated Ed25519 attack fixtures / CPython 3.12.13 | `PASS` | [trusted-key repair evidence](./evidence/s6/s6-09-trusted-key-repair-20260826.md); 16 focused and 1000 full-regression tests passed with one documented Windows skip; unknown, revoked, disabled, wrong-purpose, and substituted keys were rejected; Ruff, format, strict mypy, DOC 1.65, and diff checks passed | local `DEF-REL-001` closed; S6-09 remains blocked by external trust service, immutable artifacts, live migration/rollback/smoke, complete RELEASE, S6-08, and TG-06 | Codex |
| S6-LOCAL-ASSESSMENT-20260825-01 | 2026-08-25 | S6 local mutable workspace / branch `codex/s6-clients` / graph base `16c0c6871b23` | full local regression, Ruff, format, strict mypy, DOC, diff checks, graph update/status; not TG-06 or complete RELEASE | local Windows / CPython 3.12.13 / 12 logical CPUs / deterministic and injected providers only | `BLOCKED` | [S6 local assessment](./evidence/s6/s6-local-assessment-20260825.md); 995 passed and one documented Windows control-character filename case skipped in 30.82 seconds; Ruff passed; 375 files formatted; strict mypy passed over 186 source files; DOC 1.64 and diff checks passed; graph status reported 145 tracked files, 2235 nodes, and 19633 edges | S6-02 and S6-04 through S6-10 external prerequisites remain blocked; mutable/untracked workspace is not an immutable candidate; TG-06 and complete RELEASE not run; no commercial publication | Codex |
| S6-10-TASK-20260825-01 | 2026-08-25 | S6-10 local publication-guard contract / source `811bef7985f2dbd7eaa518d03f02a8c1a0e9f69a5d8ff6de010f9912837f9c59` / branch `codex/s6-clients` / mutable build | local release/TG-06/approval/idempotency/post-smoke/rollback contract, affected `SEC-ALL`, `RES-ALL`, `QUICK`, `DOC`; not publication or complete `RELEASE` | local Windows / injected publisher spy / synthetic decision and smoke / CPython 3.12.13 | `BLOCKED` | [S6-10 publication evidence](./evidence/s6/s6-10-publication-20260825.md); 5 dedicated and 107 affected tests passed; zero-call preflight denial, exact idempotency, one-call publish, deployed-hash denial, PUBLISHED_PENDING_SMOKE, COMPLETE, ROLLBACK_REQUIRED, Ruff, strict mypy, and DOC 1.64 passed | no S6-09 candidate, TG-06 PASS, authorized decision, production publisher, deployment, or live post-publication smoke; external calls made = 0 and commercial V1.0 remains unpublished | Codex |
| S6-09-TASK-20260825-01 | 2026-08-25 | S6-09 local release-gate contract / source `5c94f8a9f9d2c7f5ea2a3a825e30ec17f4ce342b9517b81f95bf5b9dc0aff3d6` / branch `codex/s6-clients` / mutable build | local release contract, offline migration/rollback, generated-key signing, synthetic smoke, affected `SEC-ALL`, `RES-ALL`, `PERF`, `EVAL-TOKEN`, `QUICK`, `DOC`; not complete `RELEASE` | local Windows / offline PostgreSQL SQL / ephemeral Ed25519 key / synthetic manifest / CPython 3.12.13 | `BLOCKED` | [S6-09 release-candidate evidence](./evidence/s6/s6-09-release-candidate-20260825.md); 6 dedicated and 63 affected tests passed; canonical artifacts/prerequisites, protected-data rollback, signature verification, smoke catalog, unsafe denial, Alembic head/base SQL, Ruff, strict mypy, and DOC 1.63 passed | S6-08 and gates blocked; mutable tree; no protected-CI packages, live database copy, full RELEASE profile, live smoke, approved external key/signature, immutable candidate, or candidate hash | Codex |
| S6-08-TASK-20260825-01 | 2026-08-25 | S6-08 local state-machine contract / source `d76a3cc56df44bc777400bfc852117392d3f1ec9984f1c9482bea45afaef3bbb` / branch `codex/s6-clients` / mutable build | local contract `E2E`, `SEC-ALL`, `RES-ALL`, `PERF`, `EVAL-TOKEN`, chain/time/gate/expert acceptance, `QUICK`, `DOC` | local Windows / synthetic historical contract fixtures / CPython 3.12.13 | `BLOCKED` | [S6-08 pilot evidence](./evidence/s6/s6-08-shadow-pilot-20260825.md); 11 dedicated and 54 affected tests passed; exact seven-date chain, 144-hour boundary, immutable bindings, daily zero-unsafe counts, workflow thresholds, two-expert acceptance, typed denial, Ruff, strict mypy, and DOC 1.62 passed | S6-05 to S6-07 blocked; no approved production-like deployment, immutable candidate, seven real service dates, 144 real elapsed hours, live daily evidence, or qualified expert acceptance; synthetic fixtures count as zero pilot days | Codex |
| S6-07-TASK-20260825-01 | 2026-08-25 | S6-07 local calibration contract / source `4346849a77ca35676708bf34a9cb8b8eab38d57ee94f48c654a99075badcace8` / branch `codex/s6-clients` / mutable build | `BUDGET`, local formula `PERF`, estimated `EVAL-TOKEN`, policy immutability and hash, `QUICK`, `DOC` | local Windows / synthetic observations / CPython 3.12.13 | `BLOCKED` | [S6-07 calibration evidence](./evidence/s6/s6-07-budget-calibration-20260825.md); 6 dedicated and 44 affected tests passed; all 40 pairs, exact formulas, V1 global ceilings, source immutability, provisional/production qualification, stale/missing/duplicate/quality failures, Ruff, strict mypy, and DOC 1.61 passed | S6-06 remains blocked; no complete exact-build approved-reference P95/P99 observations, provider-measured LLM/token usage, matching quality evidence, immutable candidate, or accountable production budget approval exists | Codex |
| S6-06-TASK-20260825-01 | 2026-08-25 | S6-06 local source candidate `d44ca022e96acaa36682b7ded703183ab4c2f19ccc11c9589a51bdc856255b5d` / branch `codex/s6-clients` / mutable build | local `PERF`, estimated `EVAL-TOKEN`, concurrency, affected `SEC-CACHE`, `BUDGET`, `QUICK`, `DOC` | local Windows 11 10.0.26200 / 12 logical CPUs / CPython 3.12.13 / in-memory runtime | `BLOCKED` | [S6-06 performance evidence](./evidence/s6/s6-06-performance-20260825.md); 9 dedicated and 86 affected cases passed; four local series used 200, 200, 200, and 100 samples; 100-concurrent exact-scope task creation had zero correctness or isolation failures; local median estimated token reduction 76.20 percent and calculated hit rate 80.00 percent; Ruff and changed-scope strict mypy passed | mutable local candidate; no approved reference hardware or live cache/provider/database/queue/vector/parser/artifact/client series; token counts are estimates without matching provider quality evidence; not production SLO or TG-06 evidence | Codex |
| S6-05-TASK-20260825-01 | 2026-08-25 | S6-05 local candidate / branch `codex/s6-clients` / mutable build | local `SEC-ALL`, local `RES-ALL`, `SEC-TENANT`, `SEC-PLATFORM`, `SEC-TOOLS`, `SEC-BASH`, `SEC-CACHE`, `OBS-AUDIT`, `INT-APPROVAL`, `INT-DATA-LIFECYCLE`, dependency and secret scans | local Windows / deterministic injected faults and in-memory stores / CPython 3.12.13 / uv 0.11.20 | `BLOCKED` | [S6-05 local assessment](./evidence/s6/s6-05-security-resilience-20260825.md); 13 catalog/aggregation tests and 474 selected cases completed with one documented Windows skip; `pip-audit` found no known vulnerability after UTF-8 environment correction; high-confidence secret patterns found zero; automated tenant leak, duplicate committed side effect, P0/P1, retry breach counts are zero | no live database/object/identity/KMS/queue/cache/index failover, authorized hardware disconnect, production isolation/encryption/network/disk faults, image/independent SAST/DAST/fuzzing, gitleaks, penetration test, immutable build, or accountable residual-risk approval | Codex |
| S6-04-TASK-20260825-01 | 2026-08-25 | S6-04 local operations candidate / branch `codex/s6-clients` / mutable build | `TASK`, local `SEC-ALL`, local `RES-ALL`, `SEC-TENANT`, quota concurrency/windows, backup integrity/chain, RPO/RTO, zero loss, rollback, degraded mode, `QUICK`, `DOC` | local Windows / in-memory quota and deterministic synthetic restore / CPython 3.12.13 / uv 0.11.20 | `BLOCKED` | [S6-04 local evidence](./evidence/s6/s6-04-operations-recovery-20260825.md); 15 dedicated and 90 affected-boundary tests passed; all 946 collected cases completed with one documented Windows skip; exact scope/window quotas, active/hard limits, canonical backup integrity, safe key references, typed restore validation, provisional-policy block, approved-production-like positive contract, Ruff, format over 351 files, strict mypy, DOC 1.58, diff checks, and graph refresh passed | local contracts are green, but no accountable approved profile, distributed atomic quota store, live database/object/audit/approval/KMS/queue/cache/index backup, failover, restore, rollback, expiry/legal-hold drill, or measured RPO/RTO and approval/publication zero-loss evidence exists | Codex |
| S6-03-TASK-20260825-01 | 2026-08-25 | S6-03 / branch `codex/s6-clients` / local mutable candidate | `TASK`, `E2E`, PWA manifest, service-worker cache policy, responsive and accessibility checks, affected `SEC-CACHE`, `QUICK`, `DOC` | local Windows / static shell and in-memory runtime / CPython 3.12.13 / uv 0.11.20 / Node 24.19.0 available but not required | `PASS` | [S6-03 durable evidence](./evidence/s6/s6-03-mobile-pwa-20260825.md); 27 affected-boundary tests passed and all 931 collected repository cases completed with one documented Windows skip; exact PWA identity and scope, safe-area layout, offline mutation denial, public-shell-only cache, protected API/authorization/mutation/cross-origin bypass, Ruff, format over 344 files, strict mypy, DOC 1.57, and diff checks passed | no live browser/install/screen-reader/offline-lifecycle/storage-eviction/proxy qualification, immutable CI, production identity, penetration test, TG-05 clearance, or TG-06 evidence | Codex |
| S6-02-TASK-20260825-01 | 2026-08-25 | S6-02 environment readiness / branch `codex/s6-clients` | desktop toolchain preflight | local Windows / Node 24.19.0 / npm 11.19.0 | `BLOCKED` | [S6-02 blocker evidence](./evidence/s6/s6-02-desktop-client-20260825.md); `cargo` and `rustc` are unavailable and no approved pinned Tauri manifest exists | cannot build, test, package, sign, upgrade, or roll back a Tauri client until an approved Rust/Tauri toolchain, dependency record, signing environment, and bridge threat model are supplied | Codex |
| S6-01-TASK-20260825-01 | 2026-08-25 | S6-01 / branch `codex/s6-clients` / local mutable candidate | `TASK`, `E2E`, client contract, authorization, reconnect, stream order, accessibility, responsive shell, affected `SCHEMA` and `SEC-TENANT`, `QUICK`, `DOC` | local Windows / in-memory task repository and deterministic event injection / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S6-01 durable evidence](./evidence/s6/s6-01-web-workbench-20260825.md); 6 dedicated and 25 affected-boundary tests passed; all 929 collected cases completed with one documented Windows skip; strict contracts, exact scope and idempotency, monotonic state, mandatory review before success, terminal protection, resumable SSE, default-deny RBAC, CSP, no token storage or unsafe HTML, semantic and responsive checks, Ruff, format over 343 files, strict mypy over 169 source files, DOC 1.56, diff checks, and graph refresh passed | no immutable CI, durable stream store, multi-process fan-out, live browser or assistive-technology matrix, production identity/session adapter, penetration test, proxy qualification, or load evidence; TG-05 remains blocked and TG-06 is not run | Codex |
| TG-05-LOCAL-20260825-01 | 2026-08-25 | S5 local candidate / branch `codex/s5-unified-tools` / base `16c0c6871b23be6fc03416bdec38adfc85d7d1b9` / no immutable build | `TG-05`, `UNIT-MODELREG`, `INT-FUNCTION`, `INT-WEB`, `INT-MCP`, `INT-INSTRUMENT`, `SEC-TOOLS`, affected `SEC-TENANT`, `SEC-CACHE`, `BUDGET`, `OBS-AUDIT`, canonical-data and method golden tests, full regression, static, `DOC` | local Windows / deterministic injected providers and in-process six-method fixtures / CPython 3.12.13 / uv 0.11.20 | `BLOCKED` | [TG-05 local assessment](./evidence/s5/tg-05-local-assessment-20260825.md); local gate subset started 2026-08-25T15:29:57.7905385+08:00 and ended 2026-08-25T15:30:21.3413157+08:00; 481 passed and one documented Windows path test skipped; all 922 repository tests passed with the same skip; Ruff, format over 337 files, strict mypy over 157 source files, DOC 1.55, and diff checks passed | local automated boundary is green, but the uncommitted candidate cannot satisfy a phase gate; no exact-candidate protected CI or Linux rerun, live Function/Web/MCP/model provider, managed secret, production network, vendor SDK/API/DLL/file exchange/simulator process, production parser/model qualification, authorized calibrated real-device data, hardware-lab, expert gold, or accountable approvals; R-002, R-003, R-005, R-007, R-008, R-009, and R-010 remain open | Codex |
| DOC-20260821-01 | 2026-08-21 | documentation baseline | `DOC` | local | `PASS` | ASCII, link, fence, task-ID, and gate-mapping checks | none | Codex |
| DOC-20260821-02 | 2026-08-21 | S0-09 / workspace-unversioned-20260821-v1.4 | `DOC` | local | `PASS` | Section 11.3, configuration `fa9e18dcbde68b83bdf617c541cb73bbfdbcd4a280b16bcddad5e1d6a492da05` | D-001 closed | Codex |
| DOC-20260821-03 | 2026-08-21 | S0 baseline / controlled documents v1.5 | `DOC` | local / Git repository without commit | `PASS` | `tools/check_controlled_docs.py`; 2026-08-21T22:37:54+08:00; four ASCII files, version 1.5, seven consistent gate mappings, balanced fences, and valid local links | no immutable commit/build; non-gating local evidence | Codex |
| S0-01-TASK-20260821-01 | 2026-08-21 | S0-01 / workspace-unversioned | `TASK` | local | `PASS` | role matrix; required role, scope, approval, denial, and liability terms present; QUICK-DOC passed | none | Codex |
| S0-02-TASK-20260821-01 | 2026-08-21 | S0-02 / workspace-unversioned | `TASK` | local | `PASS` | ontology JSON parsed; six structure classes, six method codes, five material classes, and eight invariants verified | none | Codex |
| S0-03-TASK-20260821-01 | 2026-08-21 | S0-03 / workspace-unversioned | `TASK` | local | `PASS` | data dictionary parsed; 28 unique entities, mandatory scope fields, and ten critical traceability links verified | none | Codex |
| S0-04-TASK-20260821-01 | 2026-08-21 | S0-04 / workspace-unversioned | `SCHEMA`, `UNIT-CORE` | local / CPython 3.12.13 | `PASS` | 12 strict V1 schemas generated; 27 contract tests passed; Ruff and strict mypy passed; dependencies pinned in `uv.lock` | none | Codex |
| S0-10-TASK-20260821-01 | 2026-08-21 | S0-10 / workspace-unversioned | `SEC-BASELINE` design check | local / CPython 3.12.13 | `PASS` | six deterministic tests passed; 12 critical asset groups, nine trust boundaries, four classifications, eight mapped controls, six measurable SLOs, and explicit pending-approval state verified | R-007 human approval remains external to automated testing | Codex |
| S0-05-TASK-20260821-01 | 2026-08-21 | S0-05 / workspace-unversioned | `DOC`, provider smoke specification | local / CPython 3.12.13 | `BLOCKED` | three ADR consistency tests passed; live provider test not run because no provider, region, contract, credential, model snapshot, hardware profile, or approved S0-10 policy is selected | R-003, R-005, R-007 | Codex |
| S0-06-TASK-20260821-01 | 2026-08-21 | S0-06 / workspace-unversioned | `DATASET` synthetic subset | local / CPython 3.12.13 | `BLOCKED` | reproducible catalog hash `DF25DB0FD930775945DF971327F0055DA657463E04B6F9EC596CC43EAAFEC43A`; five tests passed for 192 documents, 60 balanced six-method raw samples, two templates, hashes, rights, de-identification, and training exclusion | R-001 and R-008: licensed standards and authorized real device data missing | Codex |
| S0-07-TASK-20260821-01 | 2026-08-21 | S0-07 / workspace-unversioned | `DATASET` synthetic benchmark subset | local / CPython 3.12.13 | `BLOCKED` | 3,008 unique cases across eight planned sets; five count, hash, rights, split, coverage, and safety-outcome tests passed; deterministic manifest hash `1C8FAD35263B3B418EA1B57FA3583216FA6EFEB03F9C5DD69DFA57FA8276C3B3` | R-008 real-data gap and R-009 expert-gold gap | Codex |
| S0-08-TASK-20260821-01 | 2026-08-21 | S0-08 / Git repository without commit | `TASK`, `DOC`, SBOM/license, CI static smoke | local / CPython 3.12.13 / uv 0.11.20 | `BLOCKED` | 53 tests, Ruff, strict mypy, DOC, three CI workflow checks, and pip-audit passed; 61 locked components covered by SBOM and pending decisions; SBOM hash `1218DCD4BA4372D937380F2CD9BE2AFD731D52202E5237731770B695B629CF14` | R-005 and R-007; GitHub CI has not run; no immutable commit/build; legal/security license review pending | Codex |
| S0-BASELINE-20260821-01 | 2026-08-21 | S0 local engineering baseline / Git repository without commit | `QUICK`, `TASK`, local phase prerequisite check | local Windows / CPython 3.12.13 / uv 0.11.20 | `PASS` | [durable local evidence](./evidence/s0/local-baseline-20260821.md); generators stable across two runs; DOC 1.5, 53 tests, Ruff, strict mypy, and pip-audit passed | none in automated subset | Codex |
| TG-00-20260821-01 | 2026-08-21 | S0 / no immutable build | `PHASE_GATE` prerequisite assessment | local | `BLOCKED` | [S0 local evidence and blocker list](./evidence/s0/local-baseline-20260821.md) | R-001, R-003, R-005, R-007, R-008, R-009; no remote CI/immutable build | Codex |
| S1-01-TASK-20260821-01 | 2026-08-21 | S1-01 / configuration `0a14246cc5fb04a7c42f9c8041c338f1ef32c7c49a1544c7f52af6052defb959` | `TASK`, `UNIT-CORE`, API scaffold, `QUICK`, `DOC`, SBOM/license | local Windows / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S1-01 durable local evidence](./evidence/s1/s1-01-api-scaffold-20260821.md); 39 task tests, 62 complete tests, Ruff, strict mypy, DOC 1.6, SBOM/license checks, and dependency audit passed | R-010 requires later approved-candidate revalidation; not gate evidence | Codex |
| S1-02-TASK-20260821-01 | 2026-08-21 | S1-02 / configuration `0b37fc78defbe0d42a19fbe223d8463be8d1b3d821961159fc909303ade0aa87` | `TASK`, `UNIT-CORE`, storage integration, migration rollback, `QUICK`, `DOC`, SBOM/license | local Windows simulated services / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S1-02 durable local evidence](./evidence/s1/s1-02-storage-20260821.md); 47 task tests, 70 complete tests, Ruff, strict mypy, DOC 1.7, SBOM/license checks, and dependency audit passed | live PostgreSQL/pgvector, Redis, and S3-compatible smoke required before TG-01; R-010 | Codex |
| S1-03-TASK-20260821-01 | 2026-08-21 | S1-03 / configuration `e18285e25a5051dea2d34e5237a0fcd9d8ee3e0b26ce32365c5dde5ee80fa174` | `TASK`, `SEC-TENANT`, pre-cache `SEC-CACHE`, OIDC/RBAC, RLS migration rollback, `QUICK`, `DOC`, SBOM/license | local Windows / generated RSA key / offline PostgreSQL / CPython 3.12.13 | `PASS` | [S1-03 durable local evidence](./evidence/s1/s1-03-identity-isolation-20260821.md); 57 task tests, 80 complete tests, Ruff, strict mypy, DOC 1.8, SBOM/license checks, and dependency audit passed | live IdP, role/RLS, administrator, revocation, and S1-10 audit evidence required before TG-01; R-007 and R-010 | Codex |
| S1-04-TASK-20260821-01 | 2026-08-21 | S1-04 / configuration `a352309cde5ef6e046583c6a9c93f892fa2acd6dbaeaaecedd0a579694eb3792` | `TASK`, `UNIT-CORE`, `INT-ORCH` routing, `BUDGET` Main zero-call, `DATASET`, `QUICK`, `DOC` | local Windows / routing set SHA-256 `129ea5fbd73408670cd3257db376230d16d584130a1b63e6c6cf756eef66f453` | `PASS` | [S1-04 durable local evidence](./evidence/s1/s1-04-main-graph-20260821.md); routing Macro-F1 1.00; 37 task tests, 85 complete tests, Ruff, strict mypy, DOC 1.9, DATASET, and dependency audit passed | downstream child, scheduler, budget, and review execution remain S1-05, S1-06, S1-08, and S1-09; R-010 | Codex |
| S1-05-TASK-20260821-01 | 2026-08-21 | S1-05 / configuration `37c94ab4cffda37e720e64ee17aad8e3c106597c9cb5b6920e46b63dfb6dca00` | `TASK`, `UNIT-CORE`, `INT-ORCH` child paths, `BUDGET` one-call boundary, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic injected executors / CPython 3.12.13 | `PASS` | [S1-05 durable local evidence](./evidence/s1/s1-05-subgraphs-20260821.md); 49 task tests, 92 complete tests, Ruff, strict mypy, DOC 1.10, and dependency audit passed after one bounded TLS retry | scheduling, recovery, guards, and review remain S1-06 through S1-09; R-010 | Codex |
| S1-06-TASK-20260821-01 | 2026-08-21 | S1-06 / configuration `58a788d07ee3e436f6ec15c7fc4497081e5daf6a2626894004e2bc1bcd3e041e` | `TASK`, `UNIT-CORE`, `INT-ORCH` scheduler paths, `BUDGET` concurrency and no-hidden-retry, `QUICK`, `DOC` | local Windows / deterministic injected executors and in-process queue / CPython 3.12.13 | `PASS` | [S1-06 durable local evidence](./evidence/s1/s1-06-task-scheduler-20260821.md); 61 task tests, 104 complete tests, Ruff, strict mypy, DOC 1.11, and dependency audit passed | queue durability and recovery remain S1-07; complete guards and review remain S1-08 and S1-09; R-010 | Codex |
| S1-07-TASK-20260822-01 | 2026-08-22 | S1-07 / configuration `6e1cbe76ac867f7abd8eabd7439097061cf6ec0ad003f85fbe93f5e522b79e93` | `TASK`, `RES-CHECKPOINT`, `INT-ORCH` recovery, `SEC-TENANT` restore scope, migration rollback, `QUICK`, `DOC` | local Windows / deterministic recovery and object backends / CPython 3.12.13 | `PASS` | [S1-07 durable local evidence](./evidence/s1/s1-07-recovery-20260822.md); 79 task tests, 114 complete tests, Ruff, strict mypy, DOC 1.12, migration rollback, and dependency audit passed | live PostgreSQL/object-store restart and forced-RLS probes required before TG-01; guards, review, and audit remain S1-08 to S1-10; R-010 | Codex |
| S1-08-TASK-20260822-01 | 2026-08-22 | S1-08 / configuration `4e30acca0cb577b1c6ef8b01d4e8d7575afb9f95c159aeef8e8d926029d92ed4` | `TASK`, `BUDGET`, `RES-ALL` budget stops, `INT-ORCH` guarded child and recovery paths, `QUICK`, `DOC` | local Windows / deterministic clocks, executors, recovery, and object backends / CPython 3.12.13 | `PASS` | [S1-08 durable local evidence](./evidence/s1/s1-08-budget-guard-20260822.md); 101 task tests, 144 complete tests, 29 budget tests, 10 recovery tests, Ruff, changed-file format, strict mypy, DOC 1.13, and dependency audit passed | physical LLM/tool adapter integration remains in later tasks; live distributed timing and infrastructure evidence required before TG-01; R-010 | Codex |
| S1-09-TASK-20260822-01 | 2026-08-22 | S1-09 / configuration `43edebd8983a84917625271e03e4597e357dbd0499ba382090267b8cc61e3605` | `TASK`, `INT-REVIEW`, `INT-ORCH` reviewed professional and direct General paths, `BUDGET` review/correction limits, `QUICK`, `DOC` | local Windows / deterministic child, reviewer, and corrector executors / CPython 3.12.13 | `PASS` | [S1-09 durable local evidence](./evidence/s1/s1-09-review-graph-20260822.md); 120 task tests, 163 complete tests, 19 Review Graph tests, Ruff, changed-file format, strict mypy, DOC 1.14, and dependency audit passed | durable mid-review resume remains TG-01 integration work under R-012; domain rubric quality remains S4; R-010 | Codex |
| S1-10-TASK-20260824-01 | 2026-08-24 | S1-10 / configuration `30071813e5965739ec284c05b07350cc2dd5cf0113d27c74b80c0cead0445ed8` | `TASK`, `OBS-AUDIT`, `SEC-TENANT` audit scope, migration rollback, `QUICK`, `DOC`, SBOM/license | local Windows / in-memory audit and synchronous span exporter / CPython 3.12.13 | `PASS` | [S1-10 durable local evidence](./evidence/s1/s1-10-audit-tracing-20260824.md); 29 affected-boundary tests, 171 complete tests, 8 OBS-AUDIT tests, W3C correlation, hash chain, forced-RLS append-only migration, Ruff, changed-file format, strict mypy, DOC 1.16, deterministic 87-component SBOM, and dependency audit passed | live PostgreSQL/collector, retention, sampling, authorization-denial wiring, and license approval remain TG-01 work; R-007, R-010, and R-012 | Codex |
| S1-11-TASK-20260824-01 | 2026-08-24 | S1-11 / configuration `c25f10a2547234a9ad7ebc89c4443c2ee3924bbdb45c3f8a4d52c015df6c27da` | `TASK`, `SEC-PLATFORM`, `SEC-TENANT`, `OBS-AUDIT` security events, rotation recovery, storage, `QUICK`, `DOC`, SBOM/license | local Windows / deterministic in-memory secret and AES-GCM key providers / CPython 3.12.13 | `PASS` | [S1-11 durable local evidence](./evidence/s1/s1-11-platform-security-20260824.md); 52 affected-boundary tests, 179 complete tests, 8 SEC-PLATFORM tests, scoped secret leases, TLS 1.2/certificate policy, AES-256-GCM, rotation/revocation recovery, managed storage resolution, mandatory audit, Ruff, changed-file format, strict mypy, DOC 1.17, deterministic 87-component SBOM, and dependency audit passed | approved vault/KMS/HSM, live TLS and service encryption, concurrent rotation, operational alerts, immutable build, baseline and license approval remain TG-01 work; R-005, R-007, and R-010 | Codex |
| S1-12-TASK-20260824-01 | 2026-08-24 | S1-12 / configuration `90b2d14b8bfa6ac346efe91c54c38896c49f122126acc08f9be9cd055d91b1ef` | `TASK`, `UNIT-TOOLREG`, `SEC-TOOLS`, `BUDGET`, `OBS-AUDIT` tool events, `QUICK`, `DOC`, SBOM/license | local Windows / deterministic injected adapters, budget guard, audit repository, and synchronous span exporter / CPython 3.12.13 | `PASS` | [S1-12 durable local evidence](./evidence/s1/s1-12-tool-registry-20260824.md); 13 dedicated registry tests and 195 complete tests passed; immutable publication, strict schema and ToolResult validation, authorization, physical-call budget, idempotent replay, timeout, reconciliation, registry invalidation, mandatory audit, Ruff, changed-file format, strict mypy, DOC 1.18, deterministic 87-component SBOM, and dependency audit passed | concrete adapters, durable side-effect journal, live policy and service integration, immutable build, and license approval remain later-phase or TG-01 work; R-005, R-007, and R-010 | Codex |
| S1-13-TASK-20260824-01 | 2026-08-24 | S1-13 / configuration `0f799143f700dc5c25fb040b81eae4c0cebb9c628b64cba51e1a0570dfc9f56a` | `TASK`, `INT-APPROVAL`, `SEC-PLATFORM`, `RES-CHECKPOINT`, `SEC-TENANT`, migration upgrade/rollback, `OBS-AUDIT` approval events, `QUICK`, `DOC`, SBOM/license | local Windows / deterministic clock, append-only approval and audit repositories, synchronous span exporter, offline PostgreSQL DDL / CPython 3.12.13 | `PASS` | [S1-13 durable local evidence](./evidence/s1/s1-13-approval-service-20260824.md); 19 dedicated approval tests, 63 affected-boundary tests, and 211 complete tests passed; seven generic checkpoint kinds, separation of duty, role sets, bounded delegation, immutable decisions, exact resume, tamper rejection, restart recovery, mandatory audit, forced RLS, append-only migration, Ruff, changed-file format, strict mypy, DOC 1.19, deterministic 87-component SBOM, and dependency audit passed after one bounded TLS retry | live identity and PostgreSQL concurrency, accountable production policy owners, immutable build, baseline and license approval remain TG-01 work; R-005, R-007, and R-010 | Codex |
| S1-09-R012-20260824-01 | 2026-08-24 | S1-09 R-012 correction / configuration `b569726d04ee382ba31788aa18ecf388631e2e5ebb2a971d0b5c92131afca63f` | `TASK`, `RES-CHECKPOINT`, `INT-REVIEW`, `INT-ORCH`, `BUDGET`, migration upgrade/rollback, `QUICK`, `DOC`, SBOM/license | local Windows / deterministic reviewer, corrector, scheduler, append-only review journal, offline PostgreSQL DDL / CPython 3.12.13 | `PASS` | updated [S1-09 durable evidence](./evidence/s1/s1-09-review-graph-20260822.md); 23 Review Graph tests, 103 affected orchestration/audit/storage tests, and 215 complete tests passed; exact-input recovery, completed-call replay, manifest recovery, three fault points, tamper and scope rejection, forced RLS, append-only migration, Ruff, changed-file format, strict mypy, DOC 1.20, deterministic 87-component SBOM, and dependency audit passed | live PostgreSQL and distributed process-loss probe plus immutable build remain TG-01 work under R-010; R-012 closed | Codex |
| TG-01-LOCAL-20260824-01 | 2026-08-24 | S1 local candidate / configuration `3317a625876bd727334cb6fb39abd301e98984cc121108381ffd877957669074` / no immutable build | `PHASE_GATE` local automated subset: `UNIT-CORE`, `INT-ORCH`, `SEC-TENANT`, `RES-CHECKPOINT`, `BUDGET`, `OBS-AUDIT`, `SEC-PLATFORM`, `UNIT-TOOLREG`, `INT-APPROVAL`, migration rollback, `QUICK`, `DOC`, SBOM/license | local Windows / deterministic in-memory services and offline PostgreSQL DDL / CPython 3.12.13 | `BLOCKED` | [TG-01 local assessment](./evidence/s1/tg-01-local-assessment-20260824.md); all 215 tests, Ruff, changed-file format, strict mypy, DOC 1.21, six-migration upgrade/rollback, 87-component deterministic SBOM, and dependency audit passed; all S1 task rows are DONE and R-012 is closed | no immutable commit/build or remote CI; approved live IdP, PostgreSQL, Redis, object store, Vault/KMS/HSM, TLS endpoints, and OTLP collector unavailable; security baseline and license decisions unapproved; exact approved-candidate revalidation not possible; R-005, R-007, R-010 | Codex |
| S0-08-REMOTE-20260824-01 | 2026-08-24 | S0-08 / commit `2670546bd27d14216e8b67658c256bc848978c63` / tree `309bdfa0f3099065cd6313bae6c7e1b6a3def63a` | remote CI smoke: locked sync, controlled generation, drift rejection, `DOC`, tests, Ruff, strict mypy, dependency audit, evidence upload | GitHub Actions Ubuntu 24.04 / CPython 3.12.14 / uv 0.11.20 | `FAIL` | [run 32684912860](https://github.com/xh92117/NDT-Agents/actions/runs/32684912860) and [durable analysis](./evidence/s0/s0-08-remote-ci-20260824.md); setup, locked sync, and all generators completed; drift rejection detected platform-dependent Office ZIP metadata before later steps ran | D-002; force canonical ZIP creator system and permissions, regenerate, run local TASK, and rerun remote CI | Codex |
| S0-08-REMOTE-20260824-02 | 2026-08-24 | S0-08 / commit `c7432b485da7e34bcfef6bc3e23f673a95b80f65` / tree `c1248d21b5e5f933a1cc35fc35f6a68e117a37fe` | remote CI smoke: locked sync, controlled generation, drift rejection, `DOC`, tests, Ruff, strict mypy, dependency audit, evidence upload | GitHub Actions Ubuntu 24.04 / CPython 3.12.14 / uv 0.11.20 | `FAIL` | [run 32685410756](https://github.com/xh92117/NDT-Agents/actions/runs/32685410756) and [durable analysis](./evidence/s0/s0-08-remote-ci-20260824.md); canonical Office ZIP output produced zero drift, while the 24 Pillow-encoded PNG fixtures and their catalog hashes and sizes differed before later steps ran | D-002; replace provider-dependent PNG encoding with a deterministic project-owned encoder, regenerate, run local TASK, and rerun remote CI | Codex |
| S0-08-REMOTE-20260824-03 | 2026-08-24 | S0-08 / commit `d15c4a448d25222e667339831edf91b7bc8a7916` / tree `e0eb0aad0ee7090c2b155ed59f6426f760e664b3` | remote CI smoke: locked sync, controlled generation, drift rejection, `DOC`, 220 tests, Ruff, strict mypy, dependency audit, evidence upload | GitHub Actions Ubuntu 24.04 / CPython 3.12.14 / uv 0.11.20 | `PASS` | [run 32685686560](https://github.com/xh92117/NDT-Agents/actions/runs/32685686560) and [durable evidence](./evidence/s0/s0-08-remote-ci-20260824.md); all workflow steps passed in 52 seconds; artifact `s0-baseline-d15c4a448d25222e667339831edf91b7bc8a7916`, ID `9505578701`, 24,959 bytes, digest `a7a360e545066272d552d1cae25d7c83f512af061053b86f7620b36b2ce36145`, expires 2026-09-23 | D-002 closed; R-005 and R-007 approvals and the R-013 repository-protection decision remain external blockers | Codex |
| S0-08-PROTECTION-20260824-01 | 2026-08-24 | S0-08 / `main` at `8d27c42d70cad030c8c430d4a98b42e8a0633860` | repository governance configuration and API readback | GitHub public repository / owner-authorized visibility | `PASS` | [durable evidence](./evidence/s0/s0-08-remote-ci-20260824.md); `main` requires pull requests, strict `quality`, administrator enforcement, linear history, and resolved conversations; force pushes and deletion are disabled; approving-review count is zero for the single-owner repository | R-013 closed; R-005 and R-007 remain external blockers | Codex |
| S0-08-PROTECTION-LOCAL-20260824-01 | 2026-08-24 | S0-08 / `codex/s0-08-branch-protection` / controlled documents 1.26 | `QUICK`, `DOC` | local Windows / CPython 3.12.13 / uv 0.11.20 | `PASS` | [durable evidence](./evidence/s0/s0-08-remote-ci-20260824.md); DOC 1.26, all 220 tests, Ruff lint, Ruff format over 74 files, and strict mypy over 74 source files passed | R-005 and R-007 remain external blockers | Codex |
| S0-08-APPROVAL-READINESS-20260824-01 | 2026-08-24 | S0-08 / `codex/s0-08-approval-readiness` / license evidence `640e0aa63c0893d67d50ccf1e6b42172d1aae87348133aa01cedafe83386b00e` | `TASK`, `SEC-BASELINE`, SBOM/license, `QUICK`, `DOC`, dependency audit | local Windows / official PyPI snapshot / CPython 3.12.13 / uv 0.11.20 | `PASS` | [approval-readiness evidence](./evidence/s0/s0-08-approval-readiness-20260824.md); 87 of 87 components captured, 56 SPDX expressions, 30 legacy records, one missing metadata record, 20 targeted checks and all 226 tests passed; four generators, DOC 1.27, Ruff, format over 76 files, strict mypy over 76 source files, and dependency audit passed | R-005 legal/security text review and component decisions; R-007 accountable identity, jurisdiction, retention, SLO, RPO/RTO, and environment decisions remain external blockers | Codex |
| S0-08-PERSONAL-GOVERNANCE-20260824-01 | 2026-08-24 | S0-08 / `codex/s0-08-personal-governance` / governance record `c649dfa59ec6cc94c2bd80ea8f9f24699a10d9af36e033a3bc87a80f9a63b083` | `TASK`, `SEC-BASELINE`, SBOM/license, `QUICK`, `DOC`, dependency audit | local Windows / CPython 3.12.13 / uv 0.11.20 | `PASS` | [approval-readiness evidence](./evidence/s0/s0-08-approval-readiness-20260824.md); 25 targeted checks and all 231 tests passed; four generators had zero drift; DOC 1.28, Ruff, format over 77 files, strict mypy over 77 source files, and dependency audit passed after one bounded UTF-8 environment retry | personal confirmation is non-approval; all four independent roles remain unassigned; production, customer-data, formal-compliance, and commercial paths remain blocked; R-005 and R-007 stay open | Codex |
| S0-05-PERSONAL-RUNTIME-20260824-01 | 2026-08-24 | S0-05 / `codex/s0-05-personal-runtime` / runtime candidate `adad384a90661d5a9e29d492a810520fc738cc99848494343a408b49b0ad879f` | `TASK`, `PROVIDER-SMOKE`, `QUICK`, `DOC`, dependency audit | local Windows / `PERSONAL-DEV-1` / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S0-05 personal runtime evidence](./evidence/s0/s0-05-personal-runtime-20260824.md); offline fake passed strict contracts, limits, typed failures, metadata, retention, redaction, and zero-network checks; 27 targeted and all 239 tests passed; four generators had zero drift; DOC 1.29, Ruff, format over 79 files, strict mypy over 79 source files, and dependency audit passed | live China-region provider awaits non-secret metadata and later secret reference; direct OpenAI is jurisdiction-blocked; local model/hardware is unfrozen; R-003, R-005, R-007, R-010 | Codex |
| S5-07-API-MANAGEMENT-20260824-01 | 2026-08-24 | S5-07 isolated control plane / `codex/s5-07-api-management` / configuration `689e4cf225d8ca4730e21a71479775d1266194d61223840461927b284d44d16a` | `TASK`, `UNIT-MODELREG`, `SEC-TOOLS`, `PROVIDER-SMOKE`, `OBS-AUDIT`, `QUICK`, `DOC`, dependency audit | local Windows / configuration-only DeepSeek candidate / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-07 durable evidence](./evidence/s5/s5-07-api-management-20260824.md); 14 dedicated and all 253 tests passed; deterministic registry, multiple bindings, reference-only secrets, scope/data/capability/budget denials, hash-only MODEL audit, zero physical calls, four generators, Ruff, format over 82 files, strict mypy over 82 source files, DOC 1.30, and dependency audit passed | S5-01, S5-06, hosted policy review, scoped secret provider, live smoke, and production approval remain blocked; S5-07 is not DONE | Codex |
| S5-07-CONFIG-BOOTSTRAP-20260824-01 | 2026-08-24 | S5-07 isolated startup bootstrap / `codex/s5-07-model-config-bootstrap` / runtime candidate `3259b8d6297fbea93e409ad8f20a2d401331ff8ea2dd83c8ddcafd033101da7f` | `TASK`, `UNIT-MODELREG`, `UNIT-CORE` startup, `SEC-PLATFORM`, `SEC-TOOLS`, `PROVIDER-SMOKE`, `OBS-AUDIT`, `QUICK`, `DOC`, dependency and SBOM checks | local Windows / strict YAML plus local read-only environment source / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-07 bootstrap evidence](./evidence/s5/s5-07-config-bootstrap-20260824.md); 19 dedicated configuration tests, 63 affected-boundary tests, and all 272 tests passed; four generators had zero drift; Ruff, format over 85 files, strict mypy over 85 source files, DOC 1.31, and dependency audit passed | physical inference, S5-01, S5-06, hosted policy review, live smoke, production managed secrets, and production approval remain blocked; S5-07 is not DONE | Codex |
| S3-02-BASH-GATEWAY-LOCAL-20260824-01 | 2026-08-24 | S3-02 / `codex/s3-02-bash-file-gateway` / controlled Bash file gateway 1.0.0 | `TASK`, `INT-BASH`, `SEC-BASH`, `UNIT-TOOLREG`, `SEC-TOOLS`, `BUDGET`, `OBS-AUDIT`, `QUICK`, `DOC`, dependency audit | local Windows / Git for Windows fixed executables / CPython 3.12.13 / uv 0.11.20 | `BLOCKED` | [S3-02 durable evidence](./evidence/s3/s3-02-bash-gateway-20260824.md); 25 dedicated tests passed and the control-character filename test skipped because the Windows file system did not create that name; 297 complete tests passed with the same one skip; four generators had zero drift; Ruff, format over 87 files, strict mypy over 87 source files, DOC 1.32, and dependency audit passed | GitHub Ubuntu must pass all 26 dedicated tests and protected quality before S3-02 becomes DONE | Codex |
| S3-02-BASH-GATEWAY-20260824-01 | 2026-08-24 | S3-02 / commit `e0998ad475a345e77d3e9058f43b817f6c4052d5` / controlled Bash file gateway 1.0.0 | PR `TASK`, `INT-BASH`, `SEC-BASH`, `UNIT-TOOLREG`, `SEC-TOOLS`, `BUDGET`, `OBS-AUDIT`, `QUICK`, `DOC`, dependency audit | GitHub Actions Ubuntu 24.04 / CPython 3.12.14 / uv 0.11.20 | `PASS` | [run 32699999214](https://github.com/xh92117/NDT-Agents/actions/runs/32699999214) and [durable evidence](./evidence/s3/s3-02-bash-gateway-20260824.md); all 298 tests passed with zero skip, including the NUL-delimited control-character filename denial; controlled generation had zero drift; DOC 1.32, Ruff, strict mypy, dependency audit, and evidence upload passed | TG-03 remains separate; S5-01 is now unblocked by S3-02 | Codex |
| S2-01-TASK-20260824-01 | 2026-08-24 | S2-01 / configuration `aef038c1d1c7e4465874a6cc9b3dc4b306027032b66e49b7ba5bd222e54918d2` / no immutable build | `TASK`, `UNIT-CONTEXT`, C0 `EVAL-COMPRESSION`, `SEC-TENANT`, affected `INT-ORCH`, `QUICK`, `DOC`, deterministic generation | local Windows / deterministic candidates and injected child registry / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S2-01 durable evidence](./evidence/s2/s2-01-context-assembly-20260824.md); 14 dedicated context tests and all 311 complete tests passed with one known Windows file-name skip; exact scope, permission, classification, provenance, lossless deduplication, protected overflow, stable manifests, bounded input, minimal child handoff, tamper rejection, four generators, Ruff, format over 91 files, strict mypy over 91 files, DOC 1.33, and diff checks passed | TG-01 remains blocked; S2-02 and S2-03 own lossy compression and field-level fallback; TG-02 not run; immutable PR CI pending | Codex |
| S2-02-TASK-20260824-01 | 2026-08-24 | S2-02 / configuration `ccca013612e6eef612e82ca92e5d84c4508429e5f8638da3942aef0123804ca7` / no immutable build | `TASK`, `UNIT-CONTEXT`, partial `EVAL-COMPRESSION`, `RES-CHECKPOINT`, `SEC-TENANT`, `QUICK`, `DOC`, deterministic generation | local Windows / deterministic fake semantic adapter and V1 checkpoint contract / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S2-02 durable evidence](./evidence/s2/s2-02-context-compression-20260824.md); 22 dedicated compression tests and all 334 collected tests completed with one known Windows file-name skip; C0-C3 boundaries, zero-call C0/C1, protected and recent-turn retention, representative C2 reduction, C3 checkpoint and scope, source attestation, semantic budgets, typed failures, four generators, Ruff, format over 94 files, strict mypy over 94 files, DOC 1.34, diff checks, and graph refresh passed | S2-03 field-level retention, full benchmark quality and C3 median, unsafe-candidate fallback, TG-02, immutable PR CI, and blocked TG-01 dependencies remain pending | Codex |
| S2-03-TASK-20260824-01 | 2026-08-24 | S2-03 / local S2 candidate / no immutable build | `TASK`, `UNIT-CONTEXT`, local `EVAL-COMPRESSION`, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic validation and semantic fakes / CPython 3.12.13 | `PASS` | [S2-03 evidence](./evidence/s2/s2-03-context-validation-20260824.md); seven dedicated validation tests and final 413-test regression passed with one platform skip | full frozen quality benchmark and immutable CI remain TG-02 blockers | Codex |
| S2-04-TASK-20260824-01 | 2026-08-24 | S2-04 / local S2 candidate / no immutable build | `TASK`, `INT-MEMORY`, `SEC-TENANT`, migration rollback, `QUICK`, `DOC` | local Windows / in-memory repository and offline PostgreSQL DDL / CPython 3.12.13 | `PASS` | [S2-04 evidence](./evidence/s2/s2-04-memory-store-20260824.md); seven dedicated memory tests and final 413-test regression passed with one platform skip | live PostgreSQL and immutable CI remain TG-02 blockers | Codex |
| S2-05-TASK-20260824-01 | 2026-08-24 | S2-05 / local S2 candidate / no immutable build | `TASK`, `INT-MEMORY`, `UNIT-CONTEXT`, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic distillation adapter / CPython 3.12.13 | `PASS` | [S2-05 evidence](./evidence/s2/s2-05-memory-distillation-20260824.md); six dedicated distillation tests and final 413-test regression passed with one platform skip | production model evaluation and immutable CI remain TG-02 blockers | Codex |
| S2-06-TASK-20260824-01 | 2026-08-24 | S2-06 / local S2 candidate / no immutable build | `TASK`, `INT-MEMORY`, `RES-CHECKPOINT`, `SEC-TENANT`, migration rollback, `QUICK`, `DOC` | local Windows / deterministic snapshots and branch restore / CPython 3.12.13 | `PASS` | [S2-06 evidence](./evidence/s2/s2-06-memory-restore-20260824.md); nine dedicated restore tests and final 413-test regression passed with one platform skip | frozen false-trigger corpus, live PostgreSQL, and immutable CI remain TG-02 blockers | Codex |
| S2-07-TASK-20260824-01 | 2026-08-24 | S2-07 / local S2 candidate / no immutable build | `TASK`, `SEC-CACHE`, `INT-MEMORY`, `SEC-TENANT`, migration rollback, `QUICK`, `DOC` | local Windows / deterministic cache clock and repository / CPython 3.12.13 | `PASS` | [S2-07 evidence](./evidence/s2/s2-07-cache-service-20260824.md); 16 dedicated cache tests and final 413-test regression passed with one platform skip | live cache service and immutable CI remain TG-02 blockers | Codex |
| S2-08-TASK-20260824-01 | 2026-08-24 | S2-08 / local S2 candidate / no immutable build | `TASK`, `SEC-CACHE`, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic canonical keys / CPython 3.12.13 | `PASS` | [S2-08 evidence](./evidence/s2/s2-08-cache-keys-20260824.md); 24 dedicated key tests and final 413-test regression passed with one platform skip | live revocation propagation and immutable CI remain TG-02 blockers | Codex |
| S2-09-TASK-20260824-01 | 2026-08-24 | S2-09 / local S2 candidate / no immutable build | `TASK`, local `INT-DATA-LIFECYCLE`, `SEC-TENANT`, `SEC-PLATFORM`, migration rollback, `QUICK`, `DOC` | local Windows / in-memory lifecycle and key revoker / offline PostgreSQL DDL / CPython 3.12.13 | `PASS` | [S2-09 evidence](./evidence/s2/s2-09-data-lifecycle-20260824.md); ten dedicated lifecycle cases, affected storage tests, and final 413-test regression passed with one platform skip | live backup expiry, cache/index invalidation, PostgreSQL, key provider, and immutable CI remain TG-02 blockers | Codex |
| TG-02-LOCAL-20260824-01 | 2026-08-24 | S2 local candidate / configuration `fa5721f2fc51a7d26d9c6ab93878d70f9bdfecd2f570c50c3e0c2e4b0e4f33df` / no immutable build | `PHASE_GATE` local automated subset: `UNIT-CONTEXT`, `EVAL-COMPRESSION`, `INT-MEMORY`, `SEC-CACHE`, `INT-DATA-LIFECYCLE`, affected security, storage, migration, `QUICK`, `DOC`, deterministic generation, dependency audit | local Windows / deterministic adapters and offline PostgreSQL DDL / CPython 3.12.13 / uv 0.11.20 | `BLOCKED` | [TG-02 local assessment](./evidence/s2/tg-02-local-assessment-20260824.md); all 413 tests completed with one platform skip; four generators had zero drift; DOC 1.35, Ruff, format over 113 files, strict mypy, dependency audit, and diff checks passed; S2-01 through S2-09 are DONE | no immutable candidate or CI; approved live services, full frozen compression benchmark, backup expiry, cache/index invalidation, and accountable security, retention, and license approvals are unavailable | Codex |
| S3-01-TASK-20260824-01 | 2026-08-24 | S3-01 / configuration `7f8167408ff7c74366014b6ba6098aa016c17bb46ca23516a93b98144a8c45f2` / no immutable build | `TASK`, `INT-KNOWLEDGE`, `INT-ORCH`, `SEC-TENANT`, administrator `INT-APPROVAL`, affected runtime and identity, `QUICK`, `DOC`, deterministic generation, dependency audit | local Windows / deterministic in-memory task repository and existing Main Graph, child registry, context manifest, and approval contracts / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S3-01 durable evidence](./evidence/s3/s3-01-knowledge-entry-20260824.md); 34 dedicated and routing tests and 135 affected-boundary tests passed; all 423 collected tests completed with one known Windows file-name skip; exact entry, scope, approval, K1 budget, immutable artifacts, 50-file bound, isolated child, asynchronous review, default-deny UI, zero Main and child physical calls, Code Graph impact review, four zero-drift generators, Ruff, format over 225 files, strict mypy over 110 source files, DOC 1.36, dependency audit, and diff checks passed | no parsing, OCR, indexing, publication, live service, immutable PR CI, or TG-03 evidence; TG-02 remains blocked | Codex |
| S3-03-TASK-20260825-01 | 2026-08-25 | S3-03 / configuration `a9d20ab1f77d21bb51fde28642ab1d3d69e64f0cc2498443f8666a4250e3e360` / no immutable build | `TASK`, `INT-BASH`, `SEC-BASH`, S3-03 `INT-KNOWLEDGE`, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / S3-02 root policy and deterministic source corpus / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S3-03 durable evidence](./evidence/s3/s3-03-secure-intake-20260825.md); 30 intake cases plus 26 inherited gateway cases completed with one platform skip; all 453 collected tests completed with one skip; original-byte invariance, streaming hash, MIME, Office safety, executable denial, strict UTF-8/GB18030/GBK/UTF-16, manual review, batch limits, duplicate handling, path and scope denial, Ruff, format over 228 files, strict mypy over 112 source files, DOC 1.37, and diff checks passed | no immutable PR CI or approved 2 GB production probe; TG-03 remains pending | Codex |
| S3-04-TASK-20260825-01 | 2026-08-25 | S3-04 / configuration `93401f4e14a69387273627784655775a7dfee1d9d2b6a85d118460b7ee28a736` / no immutable build | `TASK`, `INT-MINERU`, S3-04 `INT-KNOWLEDGE`, `SEC-BASH`, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic MinerU process fake and strict output corpus / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S3-04 durable evidence](./evidence/s3/s3-04-mineru-adapter-20260825.md); 14 dedicated cases and all 467 collected tests completed with one platform skip; pinned argument array, zero-shell process port, source re-attestation, run isolation, Markdown/content-list/middle JSON hashes, strict JSON, version, backend, pages, blocks, coordinates, paths, passthrough, conversion requirement, timeout and process failures, Ruff, format over 232 files, strict mypy over 114 source files, DOC 1.38, and diff checks passed | real MinerU executable/container and frozen clean/scanned corpus remain TG-03 evidence; no immutable PR CI | Codex |
| S3-05-TASK-20260825-01 | 2026-08-25 | S3-05 / configuration `7a4c22f9e1d9d4c63c92756dc1954d2c777bb4dfc623dc303613210fd81cfd94` / no immutable build | `TASK`, `INT-MINERU`, `INT-OCR`, S3-05 `INT-KNOWLEDGE`, `SEC-TENANT`, `BUDGET`, `QUICK`, `DOC` | local Windows / deterministic parser and independent OCR adapters / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S3-05 durable evidence](./evidence/s3/s3-05-parser-fallback-20260825.md); ten dedicated fallback cases plus 14 MinerU cases passed; all 477 collected tests completed with one skip; page, text, corruption, table and formula thresholds, drawing exclusion, one-shot MinerU OCR, independent OCR, failed-page merge, lineage, source/scope binding, malformed output, timeout, exhaustion and three-call cap, Ruff, format over 236 files, strict mypy over 116 source files, DOC 1.39, and diff checks passed | real OCR engines and frozen scanned corpus thresholds remain TG-03 evidence; no immutable PR CI | Codex |
| S3-06-TASK-20260825-01 | 2026-08-25 | S3-06 / configuration `dd00e818ce04124338b58366ed655e0aafa48b67a58c2a790cec530c4326e1df` / no immutable build | `TASK`, `INT-MINERU`, `INT-OCR`, normalization regression, S3-06 `INT-KNOWLEDGE`, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic canonical normalizer / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S3-06 durable evidence](./evidence/s3/s3-06-normalization-20260825.md); eight dedicated cases plus ten fallback cases passed; all 485 collected tests completed with one skip; element coverage, heading and clause hierarchy, Chinese text, Markdown and HTML tables, formulas, figures, lists, code, auxiliary content, metadata, stable and change-sensitive hashes, exact locators, long lossless chunks, invalid input, Ruff, format over 240 files, strict mypy over 118 source files, DOC 1.40, and diff checks passed | frozen normalization corpus and immutable PR CI remain TG-03 evidence | Codex |
| S3-07-TASK-20260825-01 | 2026-08-25 | S3-07 / configuration `44da1cac2561349fdd0e08e1e9d87d4f8cb01c8f79cf467c42fddd8ff8417905` / no immutable build | `TASK`, `EVAL-RETRIEVAL`, `SEC-TENANT`, S3-07 `INT-KNOWLEDGE`, `SEC-CACHE`, `QUICK`, `DOC` | local Windows / deterministic hash embedding and in-memory exact-scope index / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S3-07 durable evidence](./evidence/s3/s3-07-hybrid-retrieval-20260825.md); 17 dedicated cases and all 502 collected tests completed with one skip; exact pre-score authorization, version/status/role/metadata filters, Chinese/Latin/numeric tokens, bounded BM25/cosine/RRF/rerank, complete citations, stable ties, and frozen Recall@6, nDCG@10, citation correctness, and traceability of 1.00; Ruff, format over 244 files, strict mypy over 120 source files, DOC 1.41, and diff checks passed | licensed corpus, production embedding, live database/vector index, and immutable CI remain TG-03 evidence | Codex |
| S3-08-TASK-20260825-01 | 2026-08-25 | S3-08 / configuration `d23e2f91828869b09803c3cfde2d34fd00bc0d20c79963a80d2dea04073c6af2` / no immutable build | `TASK`, S3-08 `EVAL-RETRIEVAL`, `SEC-TENANT`, `INT-KNOWLEDGE`, `QUICK`, `DOC` | local Windows / deterministic typed catalog and pre-score admission / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S3-08 durable evidence](./evidence/s3/s3-08-standard-applicability-20260825.md); 27 dedicated cases plus 17 inherited retrieval cases passed; all 529 collected tests completed with one skip; stable hash identity, date/region/role canonicalization, exact-scope and same-lineage acyclic replacement, current/restricted/rights/applicability decisions, explicit denial reasons, snapshot binding, and pre-score exclusion passed; Ruff, format over 248 files, strict mypy over 122 source files, DOC 1.42, and diff checks passed | licensed standard content, accountable rights decisions, live persistence/vector infrastructure, and immutable CI remain TG-03 evidence | Codex |
| S3-09-TASK-20260825-01 | 2026-08-25 | S3-09 / configuration `81182fe0b1b73aae51e3b6f5a97455e9e91066b0b90fd5291077a6aefee33de3` / no immutable build | `TASK`, `INT-KNOWLEDGE`, `INT-REVIEW`, `INT-APPROVAL`, `EVAL-RETRIEVAL`, `SEC-TENANT`, `RES-CHECKPOINT`, migration upgrade/rollback, `QUICK`, `DOC` | local Windows / actual S1-09 workflow, S1-13 approval, in-memory atomic repository, offline PostgreSQL DDL / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S3-09 durable evidence](./evidence/s3/s3-09-knowledge-release-20260825.md); ten end-to-end release cases, 96 affected-boundary cases, 18 storage/release cases, and all 539 collected tests completed with one skip; incremental diff, validation state, exact review binding, distinct human approvals, atomic publication and fault retry, supersession, withdrawal, rollback, history, forced RLS, append-only journal, Ruff, format over 253 files, strict mypy over 124 source files, DOC 1.43, and diff checks passed | live multi-session PostgreSQL/vector transaction, real services and corpus, accountable approvals, and immutable CI remain TG-03 evidence | Codex |
| TG-03-LOCAL-20260825-01 | 2026-08-25 | S3 code commit `a5008908c24970033f196b534b5009d853aac556` / tree `8d291bcde6d7af76907a4d13ba0e0c7a267b10f0` / manifest SHA-256 `78d48e279a8bb9efd2e8d7e432b6b950beebfc34a57ec629d886455eecce980c` | `PHASE_GATE` local automated subset: `INT-MINERU`, `INT-OCR`, `INT-KNOWLEDGE`, `INT-BASH`, `EVAL-RETRIEVAL`, `SEC-BASH`, affected review/approval/storage, migration upgrade/rollback, `QUICK`, `DOC`, deterministic generation, dependency audit, Code Graph review | local Windows / deterministic adapters and offline DDL / CPython 3.12.13 / uv 0.11.20 | `BLOCKED` | [TG-03 local assessment](./evidence/s3/tg-03-local-assessment-20260825.md); dedicated phase run completed 201 passes with one Windows skip; follow-up exact 18 release/storage tests passed; exact code commit completed all 539 collected tests with one skip; retrieval metrics were 1.00; four generators had zero drift; Ruff format over 254 files, strict mypy over 124 source files, DOC 1.43, dependency audit, graph refresh to 1,997 nodes/17,332 edges/137 files, and clean status passed | real MinerU/OCR and approved corpora, licensed standards/accountable approvals, production embedding, live atomic storage/index/recovery, zero-skip Linux path corpus, and protected immutable CI are unavailable | Codex |
| S4-01-TASK-20260825-01 | 2026-08-25 | S4-01 / local provider-neutral candidate / no immutable build | `TASK`, `EVAL-QA`, `INT-REVIEW`, `EVAL-RETRIEVAL`, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic S3-07 retrieval and in-memory exact-scope index / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S4-01 durable evidence](./evidence/s4/s4-01-technical-qa-20260825.md); 12 dedicated QA cases and 62 task-profile cases passed; exact citation reconstruction, stable hashes, missing input, domain stop, unrelated/stale/non-published/cross-scope evidence, critical/formal escalation, Ruff, format, strict mypy, DOC 1.45, and diff checks passed | expert correctness and full 288-case adjudicated benchmark remain blocked by R-008 and R-009; no immutable PR CI | Codex |
| S4-02-TASK-20260825-01 | 2026-08-25 | S4-02 / local provider-neutral candidate / no immutable build | `TASK`, `EVAL-PLAN`, `EVAL-QA`, `INT-REVIEW`, `SEC-TENANT`, generated fixture integrity, `QUICK`, `DOC` | local Windows / deterministic S4-01 QA, S3-07 index, S3-08 catalog, and generated V1 template / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S4-02 durable evidence](./evidence/s4/s4-02-inspection-plan-20260825.md); 12 dedicated plan cases and 92 task-profile cases passed; generated template/hash integrity, complete/stable plan, explicit gaps, ontology/reference/unit/range checks, QA hash/scope, standard applicability, approval injection, Ruff, format, strict mypy, DOC 1.45, and diff checks passed | expert completeness and full 60-case adjudicated benchmark remain blocked by R-008 and R-009; no immutable PR CI | Codex |
| S4-03-TASK-20260825-01 | 2026-08-25 | S4-03 / local provider-neutral candidate / no immutable build | `TASK`, `EVAL-REPORT`, `EVAL-PLAN`, `INT-REVIEW`, `SEC-TENANT`, generated fixture integrity, `QUICK`, `DOC` | local Windows / deterministic S4-01 QA, S4-02 plan, and generated V1 report template / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S4-03 durable evidence](./evidence/s4/s4-03-inspection-report-20260825.md); 13 dedicated report cases and 93 task-profile cases passed; template/hash fidelity, source-processing-observation trace, Decimal recomputation, unit/calibration/method controls, finding/citation/conclusion/revision boundaries, approval injection, Ruff, format, strict mypy, DOC 1.45, and diff checks passed | expert report quality and full 40-case adjudicated benchmark remain blocked by R-008 and R-009; no immutable PR CI | Codex |
| S4-04-TASK-20260825-01 | 2026-08-25 | S4-04 / local provider-neutral candidate / no immutable build | `TASK`, source-data golden, `INT-REVIEW`, `BUDGET`, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic processing-control candidate and S4-03 report bridge / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S4-04 durable evidence](./evidence/s4/s4-04-data-processing-20260825.md); 13 dedicated processing cases and 88 task-profile cases passed; exact scope/source/parameter/output hashing, calibration/method/unit/quality/budget controls, one-attempt and zero-external-action enforcement, typed partial/failure preservation, report bridge, Ruff, format, strict mypy, DOC 1.45, and diff checks passed | authorized six-method real samples, expert processing gold answers, production adapters, accountable review, and immutable CI remain blocked by R-008 and R-009 | Codex |
| S4-05-TASK-20260825-01 | 2026-08-25 | S4-05 / local provider-neutral candidate / no immutable build | `TASK`, six-method and source-data golden, `INT-REVIEW`, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic S4-04 requests/candidates and read-only method registry / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S4-05 durable evidence](./evidence/s4/s4-05-method-skills-20260825.md); 11 dedicated method cases and 57 task-profile cases passed; six stable definitions, six golden boundaries, metadata/calibration/applicability/input/parameter/output/origin/scope denial, zero actions, Ruff, format, strict mypy, DOC 1.45, and diff checks passed | real calibrated-device validation, production adapters, licensed standards, expert gold answers, accountable review, and immutable CI remain blocked by R-008 and R-009 | Codex |
| S4-06-TASK-20260825-01 | 2026-08-25 | S4-06 / local provider-neutral candidate / no immutable build | `TASK`, `INT-REVIEW`, `EVAL-QA`, `EVAL-PLAN`, `EVAL-REPORT`, source-data golden, `SEC-TENANT`, `QUICK`, `DOC` | local Windows / deterministic S4-01 through S4-05 outputs and S1-09 review contracts / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S4-06 durable evidence](./evidence/s4/s4-06-professional-review-20260825.md); 9 dedicated professional-review cases and 103 task-profile cases passed; five stable checklists, clean per-result/cross-result pass, tamper/scope/human/conflict denial, exact S1-09 adapter, zero calls, Ruff, format, strict mypy, DOC 1.45, and diff checks passed | licensed standards, real calibrated evidence, adjudicated gold answers, qualified reviewer and measured correction evidence, and immutable CI remain blocked by R-008 and R-009 | Codex |
| S4-07-TASK-20260825-01 | 2026-08-25 | S4-07 / local provider-neutral candidate / no immutable build | `TASK`, `INT-REVIEW`, `INT-APPROVAL`, approval/permission, `SEC-TENANT`, `SEC-PLATFORM`, `RES-CHECKPOINT`, `QUICK`, `DOC` | local Windows / deterministic S4-02/S4-03/S4-06 results and actual S1-09/S1-13 workflows / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S4-07 durable evidence](./evidence/s4/s4-07-professional-approval-20260825.md); 9 dedicated professional-approval cases and 131 task-profile cases passed; separate roles, exact PASS and HUMAN_REQUIRED review bindings, critical/ordinary path separation, subject/checkpoint hashes, idempotency, scope/role/stale/reject/replay denial, zero external actions, Ruff, format, strict mypy, DOC 1.45, and diff checks passed | R-004 formal/accreditation boundary, accountable qualified owners, live identity/storage, expert review/gold, real calibrated data, and immutable CI remain unavailable | Codex |
| TG-04-LOCAL-20260825-01 | 2026-08-25 | S4 local candidate / branch `codex/s4-professional-capabilities` / no immutable build | `PHASE_GATE` local assigned groups, complete regression, generator reproducibility, static checks, `DOC`, code-graph coverage | local Windows / deterministic provider-neutral fixtures / CPython 3.12.13 / uv 0.11.20 | `BLOCKED` | [TG-04 local assessment](./evidence/s4/tg-04-local-assessment-20260825.md); 140 S4 phase-profile tests passed; 618 complete tests passed with one documented Windows skip; four generators had zero tracked-output drift; Ruff, format, strict mypy, DOC 1.45, diff checks, graph refresh, and direct generator coverage passed | R-004, R-008, and R-009; qualified accountable approvers, live identity and durable approval storage, and immutable CI revalidation are unavailable | Codex |
| S5-08-TASK-20260825-01 | 2026-08-25 | S5-08 / branch `codex/s5-unified-tools` / source `7ffc225aa67261124b0c21b2b52d334a5deda8790adf9cf96c54af9e96e19c0b` / no immutable build | `TASK`, `INT-INSTRUMENT`, six-method and source-data golden tests, `UNIT-TOOLREG`, `SEC-TOOLS`, `SEC-TENANT`, `BUDGET`, `OBS-AUDIT`, `QUICK`, `DOC` | local Windows / six in-process deterministic fixture providers, shared Tool Registry, canonical codec, in-memory budget and audit / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-08 durable evidence](./evidence/s5/s5-08-reference-adapters-20260825.md); 42 dedicated cases passed; 246 task-profile tests passed; all 922 repository tests passed with one documented Windows control-character filename skip; exact six-profile order and hashes, method-Skill binding, strict simulator registrations, one physical-tool call per method, byte-deterministic canonical UTF-8, exact simulated scope/method/device/calibration/parser provenance, processing eligibility and formal-use denial, zero LLM/network/secret/real-device/approval/publication/retry calls, typed preflight/provider/timeout/schema/canonical failures, two correlated hash-only TOOL audits on success, Ruff, format over 165 files, strict mypy, DOC 1.54, diff checks, and graph refresh passed | no immutable PR CI, real instrument or simulator process, vendor SDK/protocol, production parser, authorized calibration/source data, hardware-lab, expert gold, or production approval evidence; TG-05 remains pending; the exact S5 candidate has no Linux rerun | Codex |
| S5-07-TASK-20260825-01 | 2026-08-25 | S5-07 / branch `codex/s5-unified-tools` / inference source `473c8a7fe6568ec0cca5b93113d6cb7eb8bf17c923d5ec10dd2eae71ae9de044` / profile source `3c21d042832f41cdb41a64d69e2e618f6d5b79a6527d9032286a11084a4a9e7e` / no immutable build | `TASK`, `UNIT-MODELREG`, `INT-INSTRUMENT`, deterministic `PROVIDER-SMOKE`, `SEC-TOOLS`, `SEC-TENANT`, `BUDGET`, `OBS-AUDIT`, `QUICK`, `DOC` | local Windows / deterministic injected provider, reference-only route, in-memory budget and audit / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-07 durable evidence](./evidence/s5/s5-07-inference-gateway-20260825.md); 41 dedicated cases passed; 275 task-profile tests passed; all 880 repository tests passed with one documented Windows control-character filename skip; exact profile/API/catalog/canonical/instruction hashes, strict local output schema, one-call LLM and token metering, zero tool calls, typed terminal/provider/schema/quality/budget failures, zero-call preflight denials, formal human boundary, sanitized provider failure text, correlated hash-only MODEL audit, Ruff, format over 163 files, strict mypy, DOC 1.53, and diff checks passed | no live provider, managed secret, approved region/retention/training/commercial policy, production model/hardware benchmark, immutable PR CI, real data, or expert gold evidence; S5-08 and TG-05 remain pending; the exact S5 candidate has no Linux rerun | Codex |
| S5-06-TASK-20260825-01 | 2026-08-25 | S5-06 / branch `codex/s5-unified-tools` / source `27a8c911a04c47b21a38248acd82bbd1ec05ee55024825ca982fd38a87741a94` / no immutable build | `TASK`, `INT-INSTRUMENT`, source-data and six-method golden tests, `SEC-TENANT`, affected S4 processing/method and S5 adapter boundaries, `QUICK`, `DOC` | local Windows / deterministic strict models, immutable artifact references, and no external actions / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-06 durable evidence](./evidence/s5/s5-06-canonical-inspection-data-20260825.md); 64 dedicated cases passed; 155 task-profile tests passed; all 839 repository tests passed with one documented Windows control-character filename skip; all six methods round-tripped exactly with Chinese, space, leading-dash, and newline source names; immutable source/channel/calibration evidence, method acquisition fields, coordinates, homogeneous channel bounds, typed settings, device/calibration/operator/parser provenance, separate processing/formal-use decisions, invalid-calibration denial, exact S4 projection/parser comparison, Ruff, format over 160 files, strict mypy, DOC 1.51, diff checks, and graph refresh passed | no immutable PR CI, authorized calibrated real-device data, production parser qualification, or expert gold evidence; S5-07, S5-08, and TG-05 remain pending; the exact S5 candidate has no Linux rerun | Codex |
| S5-05-TASK-20260825-01 | 2026-08-25 | S5-05 / branch `codex/s5-unified-tools` / source `e476a15ac2b5ff6567e6ec8eab1737734dab2eae0a7687d352021f70bb012cf6` / no immutable build | `TASK`, `INT-INSTRUMENT`, `SEC-TOOLS`, `SEC-BASH`, `SEC-TENANT`, `SEC-PLATFORM`, affected `BUDGET`, `OBS-AUDIT`, adapter golden tests, `QUICK`, `DOC` | local Windows / deterministic injected adapter providers and shared registry / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-05 durable evidence](./evidence/s5/s5-05-adapter-sdk-20260825.md); 49 dedicated cases passed; 250 task-profile tests passed with one documented Windows control-character filename skip; all 775 repository tests passed with the same skip; seven exact transport bindings, static registration and registry hashes, AI-model physical-path denial, zero-call preflight denials, one-call provider execution, idempotent approved side effects, untrusted review-required envelopes, complete success/failure evidence, exact artifact/provenance/output/error validation, non-disclosing typed failures, timeout without hidden retry, Ruff, format over 158 files, strict mypy, DOC 1.50, diff checks, and graph refresh passed | no immutable PR CI or live command, network, SDK, DLL, file exchange, MCP, simulator process, instrument, model, device, or production artifact evidence; S5-06 through S5-08 and TG-05 remain pending; the exact S5 candidate has no Linux rerun | Codex |
| S5-04-TASK-20260825-01 | 2026-08-25 | S5-04 / branch `codex/s5-unified-tools` / source `4d24d31f4cbf535adb57e69714def8783426974905b10bf2f518e36270797426` / no immutable build | `TASK`, `INT-MCP`, `SEC-TOOLS`, `RES-ALL`, `SEC-TENANT`, `SEC-PLATFORM`, affected `BUDGET`, `OBS-AUDIT`, `QUICK`, `DOC` | local Windows / deterministic injected MCP transport and credential broker, in-memory discovery and async state / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-04 durable evidence](./evidence/s5/s5-04-mcp-gateway-20260825.md); 37 dedicated cases passed; 211 task-profile tests passed with one documented Windows control-character filename skip; all 726 repository tests passed with the same skip; exact local/remote endpoints and static registration hashes, post-authorization nonserializing credentials, separately metered discovery/invoke/poll/cancel, expiring discovery and retained async history, idempotent async launch/cancel, exact scope/task/run state binding, disconnect preservation, bounded untrusted streams, exact artifact binding, typed malformed/provider/timeout failures, Ruff, format over 156 files, strict mypy, DOC 1.49, diff checks, and graph refresh passed | no immutable PR CI or live MCP server, external credential, production network, subprocess, or durable async-store evidence; S5-05 through S5-08 and TG-05 remain pending; the exact S5 candidate has no Linux rerun | Codex |
| S5-03-TASK-20260825-01 | 2026-08-25 | S5-03 / branch `codex/s5-unified-tools` / source `000d061392d53dc89b27fba4a8990f988e266c47d4d78d868509f3e0987bb63e` / no immutable build | `TASK`, `INT-WEB`, `SEC-TOOLS`, `EVAL-QA`, `EVAL-TOKEN`, `SEC-CACHE`, affected `BUDGET`, `OBS-AUDIT`, `QUICK`, `DOC` | local Windows / deterministic injected Web provider, S2 in-memory cache, budget guard, and audit exporter / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-03 durable evidence](./evidence/s5/s5-03-web-search-20260825.md); 24 dedicated cases passed; 206 task-profile tests passed with one documented Windows control-character filename skip; all 689 repository tests passed with the same skip; exact source policy, URL and redirect denial, current-request freshness and cache bypass, scoped non-current cache isolation and invalidation, exact citations and evidence hashes, untrusted prompt-marker handling, typed offline and malformed degradation, permission/network/destination/timeout/budget enforcement, Ruff, format over 154 files, strict mypy, DOC 1.48, and diff checks passed | no immutable PR CI or live Web provider and production-network evidence; S5-04 through S5-08 and TG-05 remain pending; the exact S5 candidate has no Linux rerun | Codex |
| S5-02-TASK-20260825-01 | 2026-08-25 | S5-02 / branch `codex/s5-unified-tools` / source `73793b0498439fdad19f025087b07dd75e51e28aeeba4ddb8411de0e11315cfc` / no immutable build | `TASK`, `UNIT-TOOLREG`, `INT-FUNCTION`, `SEC-TOOLS`, affected `BUDGET`, `OBS-AUDIT`, `QUICK`, `DOC` | local Windows / deterministic injected adapters, budget guard, and audit exporter / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-02 durable evidence](./evidence/s5/s5-02-function-gateway-20260825.md); 27 dedicated cases passed; 163 task-profile tests passed with one documented Windows control-character filename skip; all 665 repository tests passed with the same skip; strict authorized catalogs, deterministic function names, HMAC attestation, local-reference-only schemas, bounded duplicate-safe JSON, exact version and context binding, permission and approval denial, orchestration-owned idempotency, timeout, malformed result denial, zero-call invalid inputs, hash-only audit, Ruff, format over 152 files, strict mypy, DOC 1.47, diff checks, and graph refresh passed | no immutable PR CI or live Function Calling provider, model, network, MCP, Bash, instrument, or device evidence; S5-03 through S5-08 and TG-05 remain pending; the exact S5 candidate has no Linux rerun | Codex |
| S5-01-TASK-20260825-01 | 2026-08-25 | S5-01 / branch `codex/s5-unified-tools` / registry source `fbcf18018d1033f32bca7402df4e5d0d36af62baa6d16703ee1d895db7ce50e4` / no immutable build | `TASK`, `UNIT-TOOLREG`, `INT-FUNCTION`, `SEC-TOOLS`, affected `BUDGET`, `OBS-AUDIT`, S3-02 `INT-BASH`, `QUICK`, `DOC` | local Windows / deterministic injected adapters and audit exporter / CPython 3.12.13 / uv 0.11.20 | `PASS` | [S5-01 durable evidence](./evidence/s5/s5-01-unified-tool-registry-20260825.md); 20 dedicated S5-01 cases passed; 136 task-profile tests passed with one documented Windows control-character filename skip; all 638 repository tests passed with the same skip; seven families, strict publication, minimal exposure, six/twelve tool and one/two MCP namespace limits across all MCP transports, permission/network/secret/destination/approval denial, declared errors, bounded retries, model-meter separation, S3-02 migration, Ruff, format over 150 files, strict mypy, DOC 1.46, diff checks, and graph refresh passed | no immutable PR CI or live provider, MCP, model, instrument, or device evidence; S5-02 through S5-08 and TG-05 remain pending; the exact S5 candidate has no Linux rerun | Codex |

`DOC-20260821-01` is preserved as a historical claim but is not valid gate evidence: it did not record a reproducible command, immutable build identifier, configuration hash, or durable evidence location.

### 11.3 `DOC-20260821-02` evidence

- Task and build: `S0-09`, `workspace-unversioned-20260821-v1.4`.
- Environment and command: local Windows workspace; PowerShell 7.6.4 read-only inline `DOC-v1.4` checker implementing Section 8.1; the originating Codex task transcript preserves the exact command and output.
- Start and end: 2026-08-21T21:49:35+08:00 to 2026-08-21T21:49:36+08:00.
- Configuration: `DOC-v1.4|AGENTS.md|development-spec.md|plan.md|test.md|ascii|bom|links|fences|versions|tasks|gates|policy`.
- Configuration SHA-256: `fa9e18dcbde68b83bdf617c541cb73bbfdbcd4a280b16bcddad5e1d6a492da05`.
- Automated result: four files present; zero non-ASCII bytes; zero BOM; zero broken local links; zero unbalanced fences; all document versions are 1.4; 66 unique task definitions; 37 unique catalog groups; seven gate mappings with zero mismatch.
- Policy result: general move is not exposed; shared Tool Registry precedes Bash; knowledge publication requires human approval; TG-06 validates S6-09 before S6-10; all six structure classes are represented; per-task tool, time, and concurrency budgets are explicit.
- Result: `PASS` for the S0-09 local task check.
- Limitation: the workspace is not yet version-controlled, so this result cannot satisfy TG-00 or any release gate; S0-08 must establish Git and CI, then rerun `DOC` with an immutable commit or build identifier.

### 11.4 `S0-BASELINE-20260821-01` evidence

The repository now has Git metadata, exact dependencies, deterministic generators, local quality
gates, and a pinned GitHub Actions workflow. The full reproducible command, timestamps, tool
versions, results, artifact hashes, and external blockers are preserved in
[local-baseline-20260821.md](./evidence/s0/local-baseline-20260821.md).

The result is a local engineering `PASS` and a TG-00 `BLOCKED` assessment. It cannot become phase
evidence until the external approvals/data are supplied, an immutable commit or build exists, and
the pinned remote CI workflow produces its evidence artifact.

## 12. Known defects and waivers

| ID | Severity | Scope | Description | Owner | Target date | State or waiver expiry |
|---|---|---|---|---|---|---|
| D-001 | P2 | `DOC` evidence | `DOC-20260821-01` lacked the required reproducible command, immutable build, configuration hash, and durable evidence | Architecture and Documentation Owner | 2026-08-21 | CLOSED by `DOC-20260821-02`; the original row remains non-gating |
| D-002 | P1 | S0 deterministic fixture generation | Office ZIP metadata and Pillow PNG compression were host-dependent, so remote Linux regeneration differed from the Windows baseline and stopped CI before the quality suite | Build and Supply-Chain Owner | 2026-08-24 | CLOSED by canonical Office ZIP metadata, project-owned PNG encoding, 220 local tests, and successful immutable CI run `32685686560` |

## 13. Maintenance rule

Update this file in the same change whenever a task, test trigger, threshold, data set, tool, model, architecture boundary, or phase gate changes. New code without a defined test and execution time is incomplete.
