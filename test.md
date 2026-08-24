# Civil Infrastructure NDT Agent Platform Test Plan

**Version:** 1.22  
**Updated:** 2026-08-24  
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
| Client API or event contract | `SCHEMA`, `E2E` | run against Web, desktop, and PWA contract clients |
| Dependency or operating-system image | `QUICK`, full unit suite, dependency scan | run `NIGHTLY` before promotion |
| Threat model, data classification, encryption, secret, retention, SLO, SBOM, or license policy | `SEC-BASELINE`, affected security and lifecycle groups | run before approving the policy or dependent architecture decision |
| Release packaging, migration, signing, or publication workflow | complete `RELEASE`, artifact-hash verification, `DOC` | validate the immutable candidate before TG-06 and publication |

## 5. Phase gate schedule

Each group is defined in Section 8. A phase is complete only when every assigned group passes and the evidence is entered in Section 11.

| Gate | Development phase | What must pass | When to run |
|---|---|---|---|
| `TG-00` | S0 requirements and baseline | `DOC`, `SCHEMA`, `DATASET`, `SEC-BASELINE` | after S0-01 through S0-10 and before S1 starts |
| `TG-01` | S1 lightweight runtime | `UNIT-CORE`, `INT-ORCH`, `SEC-TENANT`, `RES-CHECKPOINT`, `BUDGET`, `OBS-AUDIT`, `SEC-PLATFORM`, `UNIT-TOOLREG`, `INT-APPROVAL` | after S1-01 through S1-13 and before S2 starts |
| `TG-02` | S2 context, memory, and cache | `UNIT-CONTEXT`, `EVAL-COMPRESSION`, `INT-MEMORY`, `SEC-CACHE`, `INT-DATA-LIFECYCLE` | after S2-01 through S2-09 and before S3 starts |
| `TG-03` | S3 files and knowledge | `INT-MINERU`, `INT-OCR`, `INT-KNOWLEDGE`, `INT-BASH`, `EVAL-RETRIEVAL`, `SEC-BASH` | after S3-01 through S3-09 and before S4 starts |
| `TG-04` | S4 professional capabilities | `EVAL-QA`, `EVAL-PLAN`, `EVAL-REPORT`, `INT-REVIEW` | after S4-01 through S4-07 and before S5 starts |
| `TG-05` | S5 tools and instruments | `INT-FUNCTION`, `INT-WEB`, `INT-MCP`, `INT-INSTRUMENT`, `SEC-TOOLS` | after S5-01 through S5-08 and before S6 starts |
| `TG-06` | S6 clients and release | complete `RELEASE`, including `E2E`, `SEC-ALL`, `PERF`, `RES-ALL`, `EVAL-TOKEN`, migration, rollback, signing, release-smoke, and candidate-hash checks | after S6-01 through S6-09 and before S6-10 publication |

## 6. Development task to test mapping

This table determines the minimum `TASK` profile. Add more groups when a change crosses boundaries.

| Tasks | Minimum test groups before `DONE` |
|---|---|
| S0-01 to S0-03 | `DOC`, deterministic role, ontology, data-model, and cross-reference consistency checks |
| S0-04 | `SCHEMA`, `UNIT-CORE` contract tests |
| S0-05 | `DOC`, provider smoke test |
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
| S5-05 to S5-08 | `INT-INSTRUMENT`, `SEC-TOOLS`, method golden tests |
| S6-01 to S6-03 | `E2E`, client contract and accessibility tests |
| S6-04 to S6-05 | `SEC-ALL`, `RES-ALL` |
| S6-06 to S6-07 | `PERF`, `EVAL-TOKEN` |
| S6-08 | `E2E`, `SEC-ALL`, `RES-ALL`, `PERF`, `EVAL-TOKEN`, and pilot acceptance |
| S6-09 | complete `RELEASE` profile, including migration, rollback, artifact-signing, release-smoke, and immutable candidate-hash tests |
| S6-10 | authorized release-decision verification, gated-hash equality, publication audit, and post-publication smoke tests |

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

Run after context, permission, retrieval, or prompt changes; in `PR`; and at `TG-02`.

Acceptance: 100 percent permission filtering and protected-field retention; deterministic input produces a stable context manifest.

### 8.10 `EVAL-COMPRESSION` - C0 to C3 compression

Compare each compression level with uncompressed baselines. Measure retained constraints, numbers, units, citations, decisions, unresolved issues, quality, and token reduction. Include automatic rollback to a less aggressive level.

Run after compression model, prompt, threshold, or context format changes; nightly sample; and at `TG-02`.

Acceptance: 100 percent critical-field retention; confirmed non-critical fact retention >= 98 percent; answer-quality degradation <= 3 percentage points; median token reduction >= 50 percent for C2 and C3 cases; unsafe compression always rejected or rolled back.

### 8.11 `INT-MEMORY` - Distillation and restore

Test runtime, session, user, project, and audit memory; candidate creation; conflict handling; deduplication; confidence; TTL; snapshot creation; direct-click restore; intent-based restore; preview; confirmation; cancel; branch restore; and version compatibility.

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

### 8.13 `INT-MINERU` - Primary document parsing

Test MinerU conversion to Markdown and structured output for born-digital and scanned documents. Verify headings, pages, clauses, tables, formulas, figures, captions, coordinates, source hashes, and parser version.

Run after MinerU, file intake, normalization, or container changes; complete corpus at `TG-03`.

Acceptance: clean-file parse success >= 98 percent, scanned-PDF usable text >= 95 percent, table and formula scores meet the frozen baseline, and every extracted element is traceable to source and page.

### 8.14 `INT-OCR` - Parser fallback chain

Force each stage: MinerU primary, MinerU OCR, and independent OCR. Test quality-gate thresholds, reason codes, retry limits, page-level fallback, merge behavior, and manual-review routing.

Run after OCR engine, quality gate, preprocessing, or parser orchestration changes; complete corpus at `TG-03`.

Acceptance: 100 percent correct fallback selection in labeled cases, no infinite retry, and low-confidence output is never silently published.

### 8.15 `INT-KNOWLEDGE` - Knowledge lifecycle

Test explicit button and intent entry, upload, parsing, normalization, chunking, metadata, embedding, indexing, human review, publish, replacement, withdrawal, rollback, incremental update, and audit. Include standards by region, type, date, status, and rights.

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

Run after any Bash tool, command allowlist, path, locale, encoding, read, write, or edit change; in `PR`; full corpus at `TG-03` and `RELEASE`.

Acceptance: 100 percent round-trip equality for valid samples; zero garbled Chinese output; zero silent lossy conversion; zero unintended file modification during read/search tests.

### 8.17 `SEC-BASH` - Bash sandbox and file safety

Test rejection of:

- unrestricted `bash -c`, command substitution, arbitrary pipelines, and unregistered executables;
- path traversal, symlink escape, absolute paths outside the allowed root, and tenant-root substitution;
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

### 8.19 `EVAL-QA` - Technical answers

Expert-score correctness, applicability, limits, uncertainty, evidence, citation validity, and safe escalation across the declared domain and six priority methods.

Run after model, prompt, Skill, retrieval, standard, review, or context changes; nightly sample; and at `TG-04`.

Acceptance: expert pass rate >= 90 percent, citation validity >= 98 percent, unsupported critical claims = 0, and unsafe definitive conclusions = 0.

### 8.20 `EVAL-PLAN` - Inspection plans

Test objective, scope, basis, methods, layout, equipment, calibration, procedure, sampling, acceptance, safety, data, quality, schedule, deliverables, limitations, and missing-input handling.

Run after plan template, Skill, standard, model, prompt, or review change; at `TG-04`; and before publishing a production template.

Acceptance: required-section completeness >= 98 percent, numeric and standard conflicts = 0, and every unresolved required input is explicit.

### 8.21 `EVAL-REPORT` - Inspection reports

Test template fidelity, identity fields, traceable raw data, calculations, units, figures, findings, limitations, conclusion boundaries, approvals, and revision history.

Run after report template, Skill, parser, calculation, model, prompt, or review change; at `TG-04`; and before publishing a production template.

Acceptance: required-field completeness >= 99 percent, numeric consistency = 100 percent, fabricated data or citation = 0, and approval boundary bypass = 0.

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

Run after a professional Skill, reviewer, rubric, graph, or result schema changes; nightly; and at `TG-04`.

Acceptance: 100 percent complex child results reviewed; correction success >= 90 percent for labeled repairable faults; hard correction limit enforced; unrepairable output states the cause and missing action.

### 8.23 `INT-FUNCTION` - Function Calling

Test schema discovery, argument validation, permission, idempotency, version, timeout, typed result, malformed output, and audit.

Run after function schema, registry, or gateway changes and at `TG-05`.

Acceptance: invalid calls rejected before execution, duplicate side effects = 0, and all results satisfy `ToolResult`.

### 8.24 `INT-WEB` - Web Search

Test source policy, time-sensitive queries, citations, result freshness, domain filters, cache, budget, timeout, prompt injection in pages, and offline degradation.

Run after provider, source policy, citation, cache, or prompt changes and at `TG-05`.

Acceptance: 100 percent cited factual web claims resolve to allowed sources, stale-result policy is enforced, and untrusted page instructions never gain tool authority.

### 8.25 `INT-MCP` - MCP integration

Test local and remote server registration, capability discovery, authorization, schema changes, timeout, cancellation, streaming, asynchronous completion, malformed payload, disconnect, and audit.

Run for every MCP server or gateway change, before enabling a server for a tenant, and at `TG-05`.

Acceptance: unauthorized capability calls = 0, contract errors are typed, and disconnects do not corrupt task state.

### 8.26 `INT-INSTRUMENT` - Instruments and AI models

Test CLI, API, SDK, DLL, file, MCP, and simulator adapters; canonical inspection data; model registry; input hash; model version; device identity; calibration; evidence; confidence; and failure mapping.

Run for every adapter or model version, against a simulator in `PR`, against authorized hardware before deployment, and at `TG-05`.

Acceptance: canonical-data round trip = 100 percent, provenance completeness = 100 percent, duplicate device action = 0, and invalid calibration blocks formal use.

### 8.27 `SEC-TOOLS` - Unified tool security

Test registry allowlist, least privilege, secret isolation, tenant authorization, input validation, output sanitization, prompt injection, SSRF, command injection, data exfiltration, rate limit, timeout, and audit for Bash, Function Calling, Web Search, MCP, instrument, and model tools.

Run after any tool or policy change, nightly sample, at `TG-05`, and in `RELEASE`.

Acceptance: zero unauthorized action or secret exposure; 100 percent high-risk calls have policy and audit evidence.

### 8.28 `E2E` - Complete user workflows

Test Web, desktop, and PWA flows for technical QA, plan generation, report generation, raw-data processing, memory restore, knowledge update, asynchronous tasks, review, human approval, export, and failure recovery.

Run nightly as a smoke subset, after client/API changes, and as a full suite at `TG-06`.

Acceptance: critical workflow pass rate = 100 percent, noncritical workflow pass rate >= 98 percent, and no client can bypass Main Agent or review policy.

### 8.29 `SEC-ALL` - Commercial security suite

Run threat-model cases, SAST, dependency and image scanning, secret scanning, API fuzzing, tenant isolation, authorization, storage encryption checks, audit integrity, upload attacks, prompt injection, model/tool boundary abuse, and penetration tests.

Run nightly automated subsets, monthly in active development, for every release candidate, and after a critical dependency or policy change.

Acceptance: zero open `P0` or `P1`, zero tenant leak, zero known critical exploitable dependency without an approved compensating control.

### 8.30 `RES-ALL` - Fault injection and self-repair

Inject LLM timeout, rate limit, malformed response, parser crash, Redis loss, database failover, object-store delay, process death, queue redelivery, MCP loss, instrument disconnect, disk-full condition, and partial network partition. Test diagnose -> bounded correction -> revalidation -> explicit failure.

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

### 8.33 `SEC-BASELINE` - Security, compliance, license, and SLO design

Review the threat model, trust boundaries, data classification, approval boundaries, retention and deletion rules, encryption and key-management policy, incident ownership, code-and-model SBOM, third-party license obligations, replacement plans, SLI/SLO definitions, error budgets, RPO, RTO, and degraded modes. Trace every mandatory control to an implementation task and test owner.

Run after any baseline policy or major architecture dependency changes, before the related architecture decision is approved, at `TG-00`, and in `RELEASE`.

Acceptance: 100 percent critical assets and trust boundaries are covered; every high-risk threat and license obligation has an owner and treatment; every required control maps to a task and test; no unresolved critical legal or security assumption is treated as approved; SLO metrics are versioned and measurable.

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

For S1-12, also verify deterministic content-derived registry versions, stale expected-version
rejection, strict Draft 2020-12 schema checking before and after execution, exact task and full
identity-scope binding, stable idempotency keys for side effects, identity and SHA-256 binding of
every `ToolResult`, S1-08 physical-call accounting and identical-call denial, mandatory hash-only
S1-10 `TOOL` audit records, timeout conversion, and zero adapter calls for every preflight denial.

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

Run after approval policy, identity, checkpoint, publication, formal-artifact, or release workflow changes; nightly; at `TG-01`; in the affected later phase gate; and in `RELEASE`.

Acceptance: 100 percent mandatory checkpoints block until a valid decision; unauthorized, stale, replayed, or mismatched-hash approvals are rejected; decision and resume are idempotent; no protected operation bypasses approval.

### 8.37 `INT-DATA-LIFECYCLE` - Retention, export, deletion, and legal hold

Test scope-aware retention, user and project export, deletion request, legal hold, backup expiry, cache and index invalidation, artifact tombstones, cryptographic erasure, restore restrictions, immutable audit retention, cancellation, partial failure, and cross-tenant denial.

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

The S0 engineering baseline exists and its local deterministic checks pass. TG-00 remains blocked:
the required human approvals, licensed standards, authorized real-device samples, expert gold
answers, production provider decision, immutable commit/build, and remote CI evidence do not yet
exist. Local synthetic evidence is not promoted to phase-gate evidence.

| Gate | Current state | Blocking groups | Next scheduled time |
|---|---|---|---|
| `TG-00` | `BLOCKED` | `DATASET` rights/real-data/expert-gold approval; `SEC-BASELINE` human approval; provider smoke; legal license decisions; immutable commit/build and remote CI `DOC`/`SCHEMA` evidence | after R-001, R-003, R-005, and R-007 to R-009 close |
| `TG-01` | `BLOCKED` | local assigned-group tests pass, but `SEC-TENANT`, `RES-CHECKPOINT`, `OBS-AUDIT`, `SEC-PLATFORM`, and `INT-APPROVAL` still require approved live-service probes; immutable CI build, exact-candidate revalidation, and accountable security and license approval are missing | after R-005, R-007, and R-010 close and the approved candidate is available |
| `TG-02` | `NOT_RUN` | all assigned groups | after S2-01 through S2-09 |
| `TG-03` | `NOT_RUN` | all assigned groups | after S3-01 through S3-09 |
| `TG-04` | `NOT_RUN` | all assigned groups | after S4-01 through S4-07 |
| `TG-05` | `NOT_RUN` | all assigned groups | after S5-01 through S5-08 |
| `TG-06` | `NOT_RUN` | complete `RELEASE` profile and all assigned groups | after S6-01 through S6-09 and before S6-10 |

### 11.2 Execution log

Append one row per meaningful test run. Do not overwrite prior evidence.

| Run ID | Date | Task/build | Profile or group | Environment | Result | Evidence | Defects | Reviewer |
|---|---|---|---|---|---|---|---|---|
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

## 13. Maintenance rule

Update this file in the same change whenever a task, test trigger, threshold, data set, tool, model, architecture boundary, or phase gate changes. New code without a defined test and execution time is incomplete.
