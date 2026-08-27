# Civil Infrastructure NDT Agent Platform Development Specification

**Specification version:** 1.87
**Date:** 2026-08-27
**Plan:** [plan.md](./plan.md)  
**Test schedule:** [test.md](./test.md)  
**Codex rules:** [AGENTS.md](./AGENTS.md)

## 1. Product goal

Build a lightweight, multi-tenant, reviewable, recoverable agent platform for civil infrastructure inspection and structural health monitoring.

The platform must:

1. Answer technical questions about structural inspection and monitoring.
2. Help users prepare inspection plans, process source data, and draft reports.
3. Call instrument software, engineering applications, and trained AI models through Bash tools, Function Calling, MCP, APIs, SDKs, or DLL adapters.
4. Read and maintain standards, templates, and organization knowledge from PDF, Office, Markdown, images, and structured files.
5. Support Web, desktop, mobile, and third-party API clients.
6. Provide strict tenant, project, user, memory, cache, file, and tool isolation.
7. Provide bounded ReAct loops, independent review, context compression, memory distillation, memory restore, caching, retries, checkpoint recovery, and explicit failure reports.

## 2. Initial domain scope

- Structure classes: roads, bridges, tunnels, hydraulic structures, municipal buildings, and energy infrastructure buildings.
- Materials: plain concrete, reinforced concrete, structural steel, concrete-filled steel tubes, and future material packs.
- Priority methods: ultrasonic testing, ground-penetrating radar, impact echo, rebound testing, acoustic emission, and machine vision.
- Work stages: commission, plan, field acquisition, source-data processing, evaluation, report drafting, review, approval, and long-term monitoring.
- Standards: national, industry, local, association, and international standards.

The first release uses one generic framework. Structure-specific differences are supplied by project context, metadata filters, standards, and templates. A new Skill is justified only when the procedure, data model, or tool chain materially differs.

## 3. Mandatory agent topology

```text
User
  -> Web/Desktop/Mobile/API client
  -> Identity, tenant, project, role, and quota layer
  -> Main Agent
       -> General path: General Agent -> Main Agent
       -> Professional path:
            Task planning and dependency graph
            -> isolated professional subagents
            -> independent review for every complex sub-result
            -> optional targeted revision or human escalation
            -> result aggregation and consistency checks
            -> Main Agent
  -> Main Agent summarizes the reviewed result for the user
```

Rules:

- The Main Agent understands, routes, schedules, assembles minimal context, and writes the final response.
- The Main Agent does not directly run Bash, Web Search, MCP, instrument control, file edits, or knowledge publishing.
- Professional subagents run synchronously or asynchronously and serially or in parallel according to explicit dependencies.
- A subagent never sends a result directly to the user.
- Each subagent receives an isolated context, task directory, memory namespace, tool allowlist, and budget.
- The Review Agent is independently prompted and read-only by default.
- High-risk conclusions, instrument control, knowledge publishing, and formal report approval require a human checkpoint.

## 4. Runtime design

Use a deterministic state graph outside the agents and bounded ReAct loops inside execution agents.

Implementation must remain simple and efficient. Use the smallest clear module and execution path
that satisfies the typed contract, security controls, and measured requirements. Add an abstraction,
service, dependency, or external call only when it removes proven duplication or meets an evidenced
isolation, scale, deployment, or failure-domain need.

Recommended initial stack:

- Python 3.12, FastAPI, Pydantic, SQLAlchemy, and Alembic.
- LangGraph for state graphs, checkpoints, interrupts, and recovery.
- Selected LangChain model, retrieval, and tool abstractions only where needed.
- PostgreSQL with pgvector and full-text search.
- Redis for hot cache, locks, limits, and a lightweight queue.
- S3-compatible object storage for source files and artifacts.
- OpenTelemetry for traces, model calls, tool calls, cache events, tokens, and errors.
- Docker Compose for the first deployment; Kubernetes only after measured scaling demand.

Do not add Kafka, Elasticsearch, a separate vector database, or a large workflow platform to the first release.

Before a stack component, model, parser, OCR engine, or container enters the reference architecture, pin its version, add it to the code-and-model SBOM, record license obligations and additional conditions, complete a security and commercial-use review, and document a tested replacement or rollback path. Reference hardware, staffing, procurement lead times, and the critical path must be approved before the 26-week roadmap becomes a delivery commitment.

The executable S0 baseline freezes V1 contracts in [contracts-v1.md](./docs/contracts/contracts-v1.md),
the proposed security policy in [security-baseline.md](./docs/security/security-baseline.md), and the
provider-neutral reference decision in
[ADR-0001](./docs/decisions/ADR-0001-reference-runtime.md). LangGraph, OpenAI Responses, vLLM, and
MinerU are architecture candidates or adapters at this stage, not approved production
dependencies. S0 and default CI use deterministic synthetic data and no live model provider.
Production selection remains blocked until the recorded security, legal, data-rights, expert,
provider, hardware, and immutable-CI conditions are satisfied.

S0-08 captures one versioned license-evidence snapshot from the official PyPI version JSON API for
every exact locked Python distribution. The snapshot binds each response hash, package URL,
declared SPDX expression or legacy metadata, dependency scope, SBOM hash, and lock-file hash.
Author-declared SPDX expressions are preserved without legal reinterpretation. Missing or legacy
metadata remains explicitly queued for license-text review. Refresh is a deliberate networked
maintenance action; CI performs offline integrity and coverage validation and never grants legal
or production approval.

For the personal pre-commercial stage, the current repository owner may record a provisional
jurisdiction and accept baseline values as engineering targets. That record does not satisfy the
independent Security, Legal, Operations, or Quality approval roles. It cannot authorize production
deployment, production customer data, a formal compliance claim, or commercial release. The
jurisdiction, targets, authority, and applicable obligations require review before commercialization.

The personal S0-05 runtime candidate uses the observed owner workstation for Python 3.12 repository
development and the deterministic fake model for public or synthetic data only. Physical hosted
model calls are disabled because the provisional current jurisdiction is not on the candidate
provider's official supported-country list. Local LLM inference remains disabled until the exact
model, weights, license, quantization, context, concurrency, and hardware benchmark are frozen.
This offline route is not production hardware or provider approval.

The S1 API bootstrap uses an application factory that performs no external I/O. Its immutable
environment settings use an explicit `NDT_` allowlist. Unknown or unsafe values fail startup with a
stable non-disclosing code. Versioned liveness and readiness payloads, structured credential-
redacted logs, safe request correlation, and typed error responses are defined in
[Runtime API V1](./docs/contracts/runtime-api-v1.md). Liveness never depends on an external
service. Each later infrastructure task extends readiness only for dependencies it owns.

The S1 storage foundation is defined in
[Storage Ports V1](./docs/contracts/storage-ports-v1.md). PostgreSQL, Redis, and artifact clients
are lazy and use bounded typed operations. Redis and object keys include tenant and project scope;
artifact writes are immutable and reads revalidate hashes and metadata. The initial reversible
PostgreSQL migration enables pgvector and creates scoped runtime task, checkpoint, artifact, and
embedding tables. RLS is applied by S1-03 before any production use. Local simulated backends and
offline PostgreSQL compilation are task evidence only; TG-01 requires approved live-service
evidence.

The initial identity boundary is defined in
[Identity and Isolation V1](./docs/contracts/identity-isolation-v1.md). OIDC JWT validation uses
exact issuer/audience checks, an algorithm allowlist, and explicitly supplied JWKS; it performs no
implicit discovery network call. Signed claims select the maximum tenant/project scope, request
headers select only within that scope, and immutable versioned RBAC denies unregistered routes and
permissions by default. Cache authorization scope includes tenant, project, user, permission, RBAC,
and route-policy versions. PostgreSQL transactions require a scope and set local scope variables;
the identity migration enables and forces RLS on every current scoped table. Live identity-provider
and non-BYPASSRLS database-role validation remain TG-01 requirements.

The initial Main Graph is defined in [Main Graph V1](./docs/contracts/main-graph-v1.md). It accepts
strict explicit route signals, applies deterministic rules before any optional classifier, validates
professional dependencies as a DAG, and stops at a typed dispatch plan. Successful routing records
`Observe -> Plan -> Act -> Verify`; invalid input, task mismatch, cycles, and topology violations
return typed blocked or failed state with a next action. Main has no tools and performs no LLM call
for routing. Every professional dispatch requires review, and only the General child path may be
used when no professional assignment is declared.

Child execution is defined in [Child Subgraphs V1](./docs/contracts/child-subgraphs-v1.md). General
and professional agents are registered child definitions. Each run receives an immutable minimal
context with explicit scope, selected artifacts, intersected tool permissions, exact versions,
budget, dependency IDs, and one private scratch namespace. Parent-private dependency data, raw Main
history, other-child scratch, and user-delivery capability are absent. Child output is revalidated
as a strict `AgentResult` with matching task, run, and artifact scope. General output returns to Main
aggregation; every professional output remains review-pending. S1-05 executes one child per call;
scheduling and review are separate later state transitions.

S1-06 scheduling uses an explicit in-process queue boundary. Synchronous dispatches execute before
return; asynchronous dispatches return a tenant- and project-bound queued handle and execute only
when the scheduler is explicitly advanced. The scheduler validates assignment identity, dependency
references, cycles, task and scope consistency, and active versus hard professional-concurrency
limits before any child starts. Dependency-free professional assignments form deterministic
topological waves and may run concurrently only within the active limit. Dependent assignments and
any side-effecting assignment remain serial. A failed or cancelled prerequisite produces a typed
blocked dependent outcome without invoking its executor. Queue durability, checkpoints,
idempotency, restart recovery, and distributed workers are deferred to S1-07.

S1-07 recovery persists immutable, hash-verified scheduler snapshots through a versioned recovery
store and artifact boundary. A scoped idempotency key is bound to the exact request hash; reuse with
the same request returns the existing recovery run, while reuse with different input is denied.
Every accepted state transition appends a monotonically sequenced checkpoint before exposing the
new state. Recovery revalidates task, full identity scope, graph and state versions, artifact hash,
snapshot hash, and every child context manifest. Assignment outputs are committed before scheduler
completion so replay after process loss reuses the verified output without another physical child
call. Side effects require a stable side-effect ID and request hash; an already committed result is
reused, while an ambiguous started-but-uncommitted effect stops for reconciliation instead of being
repeated. Interrupts are cooperative and take effect at checkpoint-safe boundaries. The local
reference repository is deterministic and restart-testable; a live PostgreSQL/object-store recovery
probe remains required before TG-01.

S1-08 uses one `BudgetGuard` bound to one exact versioned `BudgetPolicy`. It reserves resources
before a physical call, records actual tokens after an LLM call, checks elapsed time at every guard
boundary, and leases professional concurrency with an async context manager. Graph steps, physical
LLM calls, physical tool calls, actual and reserved tokens, retries, cache lookups and hits, logical
actions, reviews, corrections, current concurrency, and peak concurrency remain separate metrics.
Identical tool name, version, and normalized arguments with the same observation are denied before
a second physical call. At 70, 85, and 95 percent of any active limit, low-value, expansion, and
non-finalization actions are deterministically restricted. Active and hard exhaustion produce a
typed stop with completed work, impact, next action, and immutable telemetry. Default task-class
policies are created only by the versioned central factory; task-specific active elevation cannot
exceed the hard ceiling. Recovery state schema 1.1.0 persists the exact policy, counters,
outstanding graph reservation, elapsed time, degradation stage, and decision events. A returned
scheduler result is checkpointed with current telemetry before terminalization. Restart restores
the same guard, conservatively charges an outstanding process-loss reservation, and denies a new
attempt with a typed zero-call result when no capacity remains; usage never resets at restart.

S1-09 adds one independent, read-only Review Graph after professional scheduling. Its context
contains the task and complete identity scope, exact result payload and hash, review checklist, and
reviewer versions, but no child scratch, Main history, user-delivery channel, mutation tool, or
another child's private state. Every completed professional result receives a strict per-result
review before aggregation. `PASS` enables aggregation; `REVISE` sends only structured actionable
findings to the responsible child through a targeted correction context and then re-reviews only
the repaired result; `CONFLICT`, `HUMAN_REQUIRED`, and `FAILED` stop aggregation with an explicit
next action. Interacting results receive a cross-result review only after all individual reviews
pass. Review and correction rounds use the same S1-08 guard, stop at active or hard limits, and
produce a hash-bound final review manifest. Invalid, timed-out, or identity-mismatched reviewer and
corrector output becomes a typed failure and is never represented as a passed review. The Main
aggregation gate accepts exactly one verified direct General outcome or a professional workflow
with a validated passing manifest; it rejects raw professional and unresolved review output.

S1-10 uses one typed audit service and the standard OpenTelemetry API and SDK behind a narrow trace
port. Every event binds actor, tenant and project scope when available, action, target, policy
decision, input and output hashes, UTC time, outcome, request correlation, and trace and span IDs.
Project events are append-only, monotonically sequenced, hash-chained, idempotent for the exact
event payload, and isolated by forced PostgreSQL RLS. Trace propagation uses the W3C `traceparent`
format and exports only allowlisted low-cardinality attributes; raw prompts, credentials, business
payloads, and unrestricted tool output are excluded. The local task uses an in-memory audit port and
in-memory span exporter for deterministic tests. An approved OTLP endpoint, live PostgreSQL adapter,
retention policy, and collector availability evidence remain TG-01 integration requirements.

S1-11 adds one provider-neutral platform-security boundary. Contracts store only versioned secret
and key references; raw values exist only in bounded in-memory leases or inside an approved provider
adapter and never enter prompts, logs, traces, audit events, configuration serialization, or
artifacts. Environment and tenant/project scope are exact. Rotation activates a new version while
preserving authorized reads of data encrypted by a decrypt-only predecessor; revocation denies the
stale version with no plaintext fallback. Local at-rest protection uses AES-256-GCM with a unique
96-bit nonce and scope-bound authenticated data. Transport policy requires certificate-validated
TLS 1.2 or later, PostgreSQL `verify-full`, and encrypted Redis outside loopback-only local and CI
use. Every allow and denial emits a hash-only S1-10 security audit event. The local deterministic
providers are test doubles, not production secret or key stores; approved managed providers,
certificates, endpoints, HSM or KMS policy, and live rotation evidence remain TG-01 requirements.

S1-12 adds one immutable shared Tool Registry core. Only application-owned `ToolDefinition`
instances may be published; definitions supplied by a model or an untrusted adapter are rejected.
Each definition binds a stable name and semantic version to strict Draft 2020-12 input and output
schemas, side-effect and idempotency policy, exact permissions and scope requirements, timeout,
retry, concurrency, byte and token budgets, secret and network declarations, audit ownership, and
test groups. A published snapshot has a content-derived registry version so dependent context and
cache manifests become stale when any definition changes. Invocation resolves only a published
definition, checks exact task and scope, permissions, security declarations, idempotency, and the
central S1-08 physical-tool budget before calling an injected adapter. Arguments are validated
before execution and the returned V1 `ToolResult`, its identity, hashes, scope, status, and declared
output are validated before entering agent context. Every allow or denial produces a correlated,
hash-only S1-10 `TOOL` audit record. S3-02 supplies the controlled Bash adapter family. Function
Calling, Web, MCP, instrument, and model gateways remain assigned to S5.

S1-13 adds one generic human-approval state machine for knowledge changes, inspection plans, formal
reports, critical findings, high-impact instrument commands, destructive operations, and release
publication. A checkpoint binds the exact tenant and project, task, requester, action, target ID,
target version, candidate SHA-256, policy version, preview, and expiry. It remains paused until the
required independent role or role set produces an immutable decision. Approvers cannot approve
their own candidate; direct and delegated authority are explicit, bounded, versioned, and
scope-bound. Reject, request-change, expiry, and cancellation are terminal. Approval requires an
exact current candidate hash, and resume creates one idempotent grant bound to that hash; stale,
cross-scope, unauthorized, duplicate-actor, or replayed decisions are denied. Candidate,
delegation, decision, and resume events are monotonically sequenced and hash-chained for restart
recovery, with forced-RLS append-only PostgreSQL schema support. Every success and denial creates a
correlated hash-only S1-10 `APPROVAL` audit record. Later knowledge, professional, instrument,
lifecycle, and release tasks configure domain-specific policies around this shared core.

S1-14 makes the ADR-selected LangGraph runtime concrete behind the existing child-execution port.
The application compiles one bounded Observe-Plan-Act-Verify graph for each registered child
runtime, invokes one injected executor in the Act node, validates the existing minimal
`ChildTaskContext` before entry and the strict `AgentResult` before exit, and keeps raw LangGraph
state, provider SDK objects, checkpointer objects, and model credentials outside domain and API
contracts. The adapter has no hidden retry and accepts persistence only through an injected
checkpointer port; production checkpoint selection remains governed by S1-07. A versioned strict
YAML document borrows the DeerFlow organization of named `models` and `subagents`, including global
subagent defaults and per-agent overrides. Model entries reference existing S5-07 binding and model
identities, and agent entries reference application-owned prompt, Skill, graph, and Tool Registry
versions. Dynamic Python class paths, inline secrets, caller-selected tools, unbounded limits, YAML
aliases or anchors, duplicate keys, and unresolved references are forbidden. Startup loading is
offline and publishes only non-secret status metadata; configuration does not enable a provider.

S1-15 connects that configuration to the executable orchestration path without changing the
application-owned scheduler contract. One configured assembly layer runs the deterministic Main
Graph, builds minimal child contexts from the configuration-derived Agent Registry, and binds each
assignment to exactly one LangGraph child executor selected by registered agent type. Delegate
catalogs must match the configured profiles exactly; missing, extra, stale, or kind-incompatible
bindings fail before scheduling and before a delegate call. General work runs synchronously;
verified professional dispatch preserves the Main Graph asynchronous decision and remains review
required. Human-required dispatch is never scheduled. A separate recoverable binder recreates
assignment executors from persisted child contexts after restart and passes `RecoveryControl` only
to recoverable delegates. The exact configuration hash is included in the private child context
and therefore in its integrity manifest and recovery request hash; raw configuration, provider
objects, delegates, checkpointers, and LangGraph state remain outside persisted and API contracts.
This local assembly does not enable a provider, review bypass, user delivery, publication, or
physical action.

S1-16 connects terminal configured schedules to the existing S1-09 Review Workflow and Main
Aggregation Gate. A General schedule must complete successfully before its one verified result is
converted to Main-only aggregation input. Every professional schedule enters per-result review;
multiple professional results also enter cross-result review, including independent results that
may interact during Main synthesis. A review `REVISE` decision binds the responsible correction
executor by configured agent type and re-reviews only changed results. `CONFLICT`,
`HUMAN_REQUIRED`, `FAILED`, timeout, malformed output, missing correction, schedule failure, or
budget stop remains typed and non-aggregatable. Queued schedules retain their minimal contexts
until explicit advancement, after which review is automatic and terminal review results are
idempotently reusable in the local runtime. When an S1-09 recovery repository is injected, the
review and correction calls use its append-only replay boundary before Main aggregation. Reviewer
and correction executors remain injected application dependencies; this assembly enables no model
provider, credential, direct user delivery, publication, or physical action.

S1-17 publishes one local candidate catalog for common domestic and international hosted model
providers and expands the DeerFlow-shaped agent example to the planned General, Technical QA,
inspection planning, inspection reporting, data processing, method compatibility, and Knowledge
child profiles. Every hosted binding is disabled by default, uses only an environment-variable
secret selector, remains limited to PUBLIC and SYNTHETIC data, and is not production eligible.
The example keeps provider selection separate from child-role selection, supports exact
case-sensitive provider model IDs, and performs no provider call during configuration loading.
The independent Review Agent remains an application-injected review dependency rather than a
dispatchable child profile. MinerU remains on the pinned local CLI adapter; optional official
hosted MinerU variables are documented as reserved configuration until a separately tested API
adapter exists.

S1-18 publishes and loads application-owned prompts through a separate strict catalog. Agent
profiles reference a prompt name rather than carrying inline text. Each catalog entry binds an
exact identifier, version, relative Markdown path, UTF-8 content hash, and bounded content. The
loader rejects duplicate identities, unsafe or escaping paths, symbolic-link escapes, BOM or
invalid encoding, stale hashes, missing files, oversized text, and unresolved profile references.
Resolved child, review, and correction bindings receive one immutable prompt instruction while raw
prompt text remains outside ChildTaskContext, LangGraph checkpoint state, audit payloads, and public
contracts. The agent-configuration hash binds the prompt-catalog hash so prompt changes invalidate
stale execution and recovery bindings. This task does not create a live provider adapter or approve
external model use.

TG-01 corrective work closes the S1-09 mid-review recovery gap with a small idempotent review
journal. The journal binds the exact schedule, child contexts, reviewer definition, cross-review
choice, and scope to one recovery ID and hash chain. It checkpoints before review, caches each
strict reviewer or corrector output by exact context hash before the next graph action, and commits
the terminal `ReviewWorkflowResult` plus its manifest before Main aggregation. Restart replays the
deterministic graph from the initial budget state while verified cached outputs prevent repeated
completed physical calls; a committed terminal result returns directly. Corrupt, cross-scope,
incompatible, or conflicting recovery content is rejected. Failure injection before review, after
one completed review call, and after the final manifest but before Main aggregation demonstrates
the recovery boundaries. A forced-RLS append-only PostgreSQL event journal supports the same port.

All S1 implementation tasks have a passing local deterministic task profile. This does not pass
TG-01. The phase gate requires the same contracts to run from an immutable CI build against the
approved production identity, PostgreSQL, Redis, object, secret, key, TLS, and telemetry services,
plus accountable security and license decisions. Until those external prerequisites exist and the
exact candidate is revalidated, S1 remains gate-blocked and production enablement is prohibited.

## 5. Agent contracts

Every execution agent receives a typed `TaskContext` containing:

- tenant, project, user, role, and permission summary;
- task goal, success criteria, risk level, and dependency data;
- only the required project facts and artifact references;
- relevant Skill, prompt, model, knowledge, and tool versions;
- allowed tools and JSON schemas;
- graph-step, LLM-call, tool-call, token, and time budgets;
- output schema and review checklist.

Every agent returns a typed `AgentResult`:

```json
{
  "task_id": "string",
  "status": "SUCCESS",
  "summary": "string",
  "structured_data": {},
  "artifacts": [],
  "evidence": [],
  "confidence": 0.0,
  "issues": [],
  "retryable": false,
  "failure_code": null
}
```

Allowed statuses are `SUCCESS`, `PARTIAL_SUCCESS`, `NEEDS_USER`, `HUMAN_REQUIRED`, `FAILED`, and `BLOCKED`.

## 6. Quantitative runtime budgets

These are initial safety defaults. Production values must be recalculated from the benchmark suite in [test.md](./test.md).

### 6.1 Per-agent limits

| Agent | Default ReAct cycles | Hard cycles | Default tools | Hard tools |
|---|---:|---:|---:|---:|
| Main Agent | 0 | 0 | 0 | 0 |
| General Agent | 2 | 4 | 2 | 4 |
| Technical QA Agent | 3 | 4 | 4 | 6 |
| Plan or Report Agent | 4 | 6 | 6 | 8 |
| Data Processing Agent | 3 | 5 | 6 | 10 |
| Knowledge Agent | 4 | 6 | file budget | file budget |
| Review Agent | 1 | 2 | 2 | 3 |

One ReAct cycle may issue one tool group. A read-only group may contain at most three parallel calls. Write, edit, publish, and instrument-control calls are serial.

### 6.2 Per-task limits

The values before and after `/` are the default and hard limits unless the column explicitly says P95. The active limit starts at the default. For tokens, the initial active limit is `ceil(successful_task_P95 * 1.15)`, bounded by the listed hard limit. A deterministic risk policy or recorded human approval may raise an active limit, but never above the hard limit.

| Class | LLM calls default/hard | Token P95/hard | Tool calls default/hard | Graph steps default/hard | Wall time default/hard | Professional concurrency default/hard | Execution |
|---|---:|---:|---:|---:|---:|---:|---|
| G0 general | 3 / 4 | 4,000 / 8,000 | 2 / 4 | 8 / 12 | 30 s / 60 s | 0 / 0 | synchronous |
| P1 one professional agent | 6 / 10 | 10,000 / 20,000 | 6 / 10 | 16 / 24 | 120 s / 300 s | 1 / 1 | synchronous, then async |
| P2 plan or report section | 18 / 32 | 35,000 / 60,000 | 16 / 24 | 32 / 48 | 15 min / 30 min | 1 / 2 | asynchronous |
| P3 full report or cross-method | 24 / 40 | 60,000 / 120,000 | 30 / 48 | 48 / 64 | 60 min / 120 min | 3 / 4 | asynchronous |
| K1 knowledge import | 7 / 12 | 20,000 / 40,000 | `5 * file_count` / `min(8 * file_count, 400)` | 48 / 64 | 2 h / 4 h | 2 / 4 files | asynchronous |

One individual call inside a parallel tool group counts as one tool call. Failed physical calls and retries count against the corresponding LLM or tool budget. A cache lookup and hit count as graph actions and cache metrics, but do not count as physical LLM or tool calls when no provider or tool is executed. Internal checkpoint writes and telemetry do not count as agent tools but have separate timeout and rate limits.

At 70 percent of an active limit, stop low-value branches. At 85 percent, stop query expansion. At 95 percent, allow validation and finalization only. At 100 percent, stop that dimension and return a partial result or explicit failure. The hard limit remains a non-overridable safety ceiling even when an active limit is elevated.

Initial calibration formulas:

- `default_limit = ceil(successful_task_P95 * 1.15)`
- `hard_limit = min(ceil(successful_task_P99 * 1.25), product_global_limit)`

## 7. Review and correction

The Review Agent returns one of:

- `PASS`: result may be aggregated;
- `REVISE`: send structured findings to the original agent;
- `CONFLICT`: return to the Main Agent for one optional replan;
- `HUMAN_REQUIRED`: pause for a qualified reviewer;
- `FAILED`: preserve and explain the verification failure.

Default revision count is one; hard limit is two. Full-task replanning is disabled by default and has a hard limit of one.

Validation order:

1. JSON schema, types, fields, units, dimensions, ranges, hashes, and formulas.
2. Local format repair or one parser fallback.
3. Retry transient failures.
4. Restore from a checkpoint or use one approved alternative tool.
5. Apply Review Agent findings.
6. Escalate to a human or return an explicit failure.

Keep the last ten action signatures. If the same action and parameters occur twice with no new observation, stop the loop. Three consecutive failures trip a 60-second tool circuit breaker.

### 7.1 S4 professional validation

The S4-01 Technical QA Skill accepts a strict request and typed child-agent candidate, then performs
deterministic evidence validation through the S3-07 exact-scope retrieval boundary. Missing method,
structure, or material inputs stop before retrieval. Values outside the V1 ontology require a
qualified domain owner. Every used snapshot is revalidated for exact tenant, project, user, roles,
permission version, published state, corpus/index/embedding versions, metadata, and content
identity. The finalizer rebuilds citations from immutable index records and accepts a support only
when its exact quote occurs in the retrieved chunk and every canonical support term occurs in both
the claim and quote. Unsupported claims remain explicit; unsupported critical claims and all formal
conclusions require a qualified human. Identical inputs and repository state produce identical
claim and result hashes. The boundary makes no model, network, approval, publication, instrument,
or retry call and does not replace independent S1-09 review.

The S4-02 inspection-plan Skill consumes one exact-scope, hash-valid S4-01 result and the generated
`TPL-INSPECTION-PLAN-V1` template. The template has seventeen ordered required sections spanning
objective, scope, structure/component, basis, methods/layout, equipment/calibration, procedure,
sampling/coverage, acceptance, safety, data, quality, schedule, deliverables, limitations,
review/approval, and missing-input handling. Candidate methods use only ontology codes and bind
equipment, calibration, procedure, registered-dimensional sampling quantities, applicable standard
bases, and safety controls. Missing request inputs remain explicit gaps with reason, impact, owner,
and blocking state. Each standard basis must bind an applicable QA claim and exact published index
record, then pass the S3-08 scope, date, region, type, lifecycle, rights, role, and supersession
checks. Output is deterministically hash-bound, always review-required and approval-pending, and
never allowed for formal use before the later approval workflow. The finalizer makes no model,
network, approval, publication, instrument, or retry call.

The S4-03 inspection-report Skill consumes one exact-scope, hash-valid, approval-pending S4-02 plan
and generated `TPL-INSPECTION-REPORT-V1`. The template has fifteen ordered sections spanning
identity, scope, plan, source data, method/equipment/calibration, observations, calculations/units,
figures, findings, limitations, citations, conclusion boundary, revisions, review, and approval.
Every dataset binds an immutable artifact, method, instrument, calibration, operator, acquisition
time, and dataset hash. Processing binds adapter, parser, algorithm, parameter, and output versions
and hashes. Observations bind processing, dataset, location, dimension, unit, value, and evidence.
Only count, minimum, maximum, mean, range, and sum calculations are allowed; Decimal recomputation
must exactly match the reported value, dimension, and unit. Figures bind immutable artifacts and
observations. Findings bind observations, calculations, applicable plan bases, and limitations;
conclusions bind findings. Critical findings and formal conclusions require qualified human
confirmation. Revision history is contiguous and hash-linked. Output is deterministically
hash-bound, review-required, approval-pending, and forbidden for formal release. The finalizer makes
no model, network, approval, publication, instrument, or retry call.

The S4-04 Data Processing Control Skill validates one already-executed registered adapter result; it
does not execute an algorithm or physical command. The source manifest binds exact scope, immutable
artifact and dataset hashes, simulated/laboratory/production origin, method, structure, component,
location, coordinates, channel and sample bounds, sample rate, dimension/unit, acquisition settings,
instrument, calibration interval, operator, and UTC acquisition time. The request binds exact
adapter, parser, algorithm, output schema, canonical parameters, one-attempt budget, and quality
policy. Candidate output binds immutable artifacts, observations, figures, quality metrics,
duration/bytes/call counters, and typed failure evidence. Validation enforces exact identity and
versions, calibration at acquisition, ontology method, registered units, source bounds, quality
thresholds, and exactly one adapter call and one attempt; model, network, and physical-command
counters must be zero. Failed output preserves cause, impact, and next action. Only a clean
production result is report eligible, and the deterministic S4-03 bridge preserves every source,
processing, observation, hash, unit, and value field. All output remains review-required.

The S4-05 Method Skill Pack is a read-only registry containing exactly six versioned skeletons:
UT, GPR, IE, RT, AE, and MV. Each hash-bound definition declares supported V1 structures and
materials, required acquisition settings and calibration kinds, accepted input dimensions and
units, required processing parameter names, registered output observation families, allowed
simulated/laboratory/production origins, limitations, safety notes, and production-report policy.
Validation binds one exact S4-04 request and candidate to the selected definition and fails closed
on unknown or changed methods, cross-scope data, missing metadata or parameters, unsupported
applicability, incompatible calibration/input units, missing successful output, or unregistered
observation names, dimensions, and units. A compatible simulated or laboratory result remains
reviewable but cannot receive production-report permission. That permission does not bypass the
independent S4-04 processing, S4-06 review, or S4-07 approval gates. The skeletons execute no
algorithm, instrument command, model/network call, approval, publication, conclusion, or retry and
make no standards-compliance or expert-correctness claim.

The S4-06 professional review layer adds five versioned, hash-bound checklists to the existing
S1-09 Review Graph for Technical QA, inspection plan, data processing, method validation, and
inspection report results. Each result travels in an exact scope/task/run/type envelope and is
rehydrated through its strict contract so schema and internal hashes are independently rechecked.
Per-result review checks status, unresolved issues, citations and traceability, units and numeric
evidence, explicit human boundaries, review/approval/formal-use state, and zero-action counters as
applicable. It returns only the existing PASS, REVISE, HUMAN_REQUIRED, or FAILED decisions. Cross-
result review begins only after per-result PASS and compares QA claims/citation chunks to plan
bases, plan identity to report identity, processing source/run/versions/output/observations to
report evidence, and method request/candidate identity to processing. Duplicate singular results,
stale hashes, changed identities, cross-scope inputs, and any relationship mismatch remain an
explicit non-aggregatable conflict. The deterministic S1-09 adapter performs zero model, tool,
network, correction, approval, publication, mutation, retry, or user-delivery calls; S1-09 still
owns correction/re-review budgets and the Main-only aggregation gate.

The S4-07 professional approval layer configures S1-13 with separate qualified plan, report, and
critical-finding roles. A plan or preliminary non-formal report checkpoint requires a strict clean
S4-02 or S4-03 result, exact PASS S4-06 assessment, and completed aggregation-ready S1-09 manifest
whose reviewed child envelope binds that result. Plan approval cannot imply report approval or
formal use. Report approval cannot set formal-release state and rejects any unresolved critical,
formal, or human-confirmation boundary. A critical-finding checkpoint instead requires the exact
hash-valid S4-03 HUMAN_REQUIRED report, selected sorted critical finding IDs, S4-06 HUMAN_REQUIRED
assessment, and S1-09 human-required pause. It binds hashes for each statement, observation,
calculation, plan basis, limitation, and evidence reference; confirmation supplies evidence for a
bounded correction and re-review and does not mutate the report. The professional subject hash
covers exact scope/task, action, target, result/content, review envelope, assessment, manifest, and
finding bindings and becomes the generic approval candidate hash. S1-13 continues to enforce
separation of duty, action-specific roles, expiry, terminal decisions, event/audit integrity,
idempotency, and one exact resume grant. The wrapper performs zero model, tool, network,
publication, mutation, formal-conclusion, retry, or user-delivery actions. Formal responsibility
and accreditation remain blocked under R-004.

## 8. Context engineering and compression

Context compression controls the current task. Memory distillation controls cross-session retention. They are separate systems.

```text
Raw conversation, project facts, tool observations, and retrieval results
  -> permission filter
  -> relevance scoring
  -> deterministic deduplication
  -> large content moved to artifacts
  -> hierarchical summaries
  -> structured facts, numbers, evidence, and open issues
  -> compression validation
  -> minimal TaskContext
```

The S2-01 C0 assembly boundary is deterministic and provider-neutral. Every candidate carries an
exact tenant and project, user or project visibility, permission version, required roles and
permissions, classification, source type, source reference, source version, source hash, trust
level, observation time, canonical content hash, relevance score, and protected flag. Artifact and
tool candidates use the same default-deny scope and permission rules. The filter order is exact
scope, visibility, permission freshness, roles, permissions, classification, relevance, and then
lossless content-hash deduplication. Deduplication preserves every authorized source label.

Protected content bypasses relevance dropping and fails with a typed next action if it cannot fit
the active lossless policy. The selected bundle contains no rejected content or grant list. Its
authorization digest and the final complete-context manifest make the result deterministic and
invalidate it when scope, permissions, clearance, policy, content, artifacts, tools, or versions
change. The Main Agent retains the non-content decision report. A General child receives all
manifest-verified selected entries; a professional child receives only entries explicitly selected
by content hash. Raw parent dependency data and rejected candidates never enter a child.

| Level | Trigger against application context budget | Action |
|---|---:|---|
| C0 | below 40% | permission filter and lossless deduplication only |
| C1 | 40% to 60% | remove repeated confirmations, retrieval duplicates, and long logs |
| C2 | 60% to 80% | summarize older turns to at most 800 tokens; keep six recent turns |
| C3 | above 80% | checkpoint first, then build a task digest of at most 1,200 tokens |

The S2-02 pipeline expresses this table as one versioned strict policy. Its ordered raw-event input
binds the exact task and tenant scope, monotonic sequence, event kind, canonical content hash,
token estimate, protected status, creation time, and optional recoverable artifact. It rejects
reordered, duplicate, hash-invalid, cross-scope, and summary-derived input before compression. C0
and C1 make no semantic call. C1 may replace only a non-protected tool log with a reference that
binds both the raw-event hash and immutable artifact hash. C2 retains every protected event and six
recent conversation turns. C3 requires an exact-task, exact-scope durable checkpoint before the
semantic call.

Every semantic call is rebuilt from raw events, identifies the exact ordered source set, and uses a
provider-neutral bounded port. C2 and C3 candidates remain validation-required and are not
execution-ready. S2-03 must compare their protected fields with raw sources and either authorize
the result or automatically retry a less aggressive level.

The S2-03 validator binds the candidate to the exact task, tenant scope, raw-event manifest, and
one-time coverage of every source event. It compares canonical atomic leaves and treats protected
events, instructions, security and permission state, tenant identity, conflicts, unresolved
issues, standards, clauses, numeric values, units, citations, hashes, tool errors, approvals, and
decisions as critical. Critical retention must be 100 percent, confirmed non-critical retention
must be at least 98 percent, and supplied answer-quality degradation must not exceed three points.
Only a passing hash-bound report makes C2 or C3 execution-ready. Unsafe C3 retries C2 and then C1;
unsafe C2 retries C1. Every retry starts from raw events and remains inside the two-semantic-call
limit.

Never lossily compress the current user instruction, security policy, permissions, tenant data, unresolved conflicts, standard identifiers, clause numbers, critical values, units, source hashes, tool errors, or approval decisions.

At most two semantic compressions are allowed in one task. Later compression must rebuild from raw events and artifacts, not summarize an existing summary again.

Acceptance targets:

- 100 percent retention of critical fields.
- At least 98 percent retention of confirmed non-critical facts.
- At least 50 percent token reduction for C2 and C3 cases.
- Zero cross-project restore or citation errors caused by compression.

## 9. Memory distillation and restore

Memory layers:

1. runtime and checkpoint state;
2. short-term conversation memory;
3. user preferences;
4. project facts;
5. organization knowledge and templates;
6. professional knowledge;
7. audit and evidence records.

The S2-04 memory store maps these into five runtime contract scopes: runtime, session, user,
project, and audit. Every record is immutable and binds exact tenant scope, namespace, canonical
content hash, provenance, confidence, classification, approval state, protected state, source
version, creation time, and optional expiry. Runtime, session, and user reads require the exact
user; project and audit sharing still require the exact tenant, project, and permission version.
Distinct read/write grants, candidate-read grants, clearance, expiry, forced PostgreSQL RLS, and
immutable update denial are enforced before content is returned.

Distillation triggers when any condition is true:

- active context reaches 60 percent of its application budget;
- user and assistant messages total 20;
- a task completes;
- the user confirms, corrects, or asks the system to remember something;
- a task is archived or paused for a long period.

Keep the last six raw turns and distill older conversation into at most 800 tokens. Store at most 30 candidate project facts per distillation. Separate facts from inferences, preserve sources, detect conflicts, and do not silently overwrite old facts.

The S2-05 pipeline evaluates every trigger deterministically, retains protected events and the six
recent turns, and sends only eligible raw events through a bounded provider-neutral port. Exact
ordered source attestation is mandatory. Fact, inference, and preference proposals preserve
provenance, confidence, classification, expiry, sensitivity, durability, and adapter versions.
They enter immutable candidate state with stable scope-derived IDs. Content hashes remove exact
duplicates; same-key different-value proposals create explicit conflicts without overwriting
existing memory. A run cannot exceed 30 project fact candidates.

Restore paths:

- Intent restore: search at most five snapshots. Initial auto-restore requires confidence >= 0.90 and a top-two score margin >= 0.12. Otherwise show candidates.
- Direct restore: the user selects a snapshot in the UI.

Restore creates a new branch and never overwrites the current session. Recheck tenant, project, permission, artifact existence, and version compatibility. Inject at most 6,000 tokens, 20 project facts, ten artifact references, and six required turns.

The S2-06 snapshot binds the exact user scope, task, source branch, checkpoint, graph and state
versions, canonical state hash, memory IDs, project facts, artifacts, required turns, and injection
budget. Direct and intent restore always create a hash-bound preview. Intent search sees only
authorized snapshots, returns at most five ordered matches, and auto-previews only at confidence
at least 0.90 with a top-two margin at least 0.12. Confirmation creates a deterministic child
branch; cancel and confirm are append-only terminal decisions. Every preview and confirmation
revalidates scope, permission version, compatibility, hashes, artifact availability, and limits.

## 10. Cache design

| Cache | Default TTL | Restriction |
|---|---:|---|
| process prompt/config LRU | 15 minutes | 256 MB initial maximum |
| route and extraction | 24 hours | exact input and version match |
| knowledge retrieval | 6 hours | tenant, permission, and index in key |
| exact low-risk QA | 24 hours | no project-specific result |
| semantic cache | 1 hour | G0/P1 only; initial similarity 0.95 |
| pure function tool result | 30 days | content, parameters, and version addressed |
| parsed file artifact | 90 days | source hash addressed |
| negative cache | 60 seconds | prevent failure storms |

Cache keys include tenant, project, permission scope, model, prompt, Skill, knowledge index, tool, input hash, and parameter hash. A cache hit never bypasses current authorization or standards validation.

The S2-07 cache service implements exact response, retrieval, pure tool result, parse result, and
semantic classes with the table TTLs above. Every record binds exact user scope, canonical value
hash, complete version manifest, provenance, validation state, and saved-token estimate. Expired or
version-stale records are removed on lookup. Current-information intent bypasses cache. Secrets,
authorization decisions, unstable values, write side effects, and non-pure tool operations are
uncacheable. Semantic entries require G0/P1 and similarity at least 0.95. Metrics separate lookup,
hit, miss, stale rejection, bypass, and saved tokens.

The S2-08 key is canonical over exact tenant, project, user, sorted roles, permission and RBAC
versions, normalized request, task type, parameters, class, model, prompts, Skills, graph, route
policy, tool and adapter, knowledge corpus and documents, public schema, parser, context policy,
and bounded class-specific dimensions. Mapping order cannot change the digest; every correctness,
source, or authorization change must. The backend repeats exact user scope in its physical key and
lookup compares the complete current version manifest, preventing cross-scope reuse and stale
authorization after revocation.

## 11. Knowledge Agent

The Knowledge Agent starts only from an explicit user intent, a UI action, or an approved administrator job. Normal question answering uses read-only retrieval and does not start an ingestion agent.

The S3-01 entry boundary accepts only typed, scope-bound start signals. A normal question produces
a non-start result and remains on the read-only retrieval path. An accepted import creates exactly
one asynchronous `K1` professional dispatch through the Main Graph, requires independent review,
keeps Main at zero LLM and tool calls, and never grants the child a user-delivery channel. UI starts
derive tenant, project, and user scope from authenticated middleware. Administrator jobs additionally
require a current approval grant bound to the exact task and candidate hash.

The S3-03 intake boundary reads one exact relative source through an application-owned adapter to
the S3-02 root and path policy. It streams the immutable original into a SHA-256 digest, determines
MIME from bounded signature bytes before considering the suffix, checks container entry names and
compression ratios without extraction, and records declared and detected MIME separately. Text
encoding detection checks BOM first, then strict UTF-8, then configured GB18030, GBK, and UTF-16
candidates. An ambiguous or invalid encoding, MIME mismatch, unsafe container, unsupported type,
scope mismatch, mutable source, or size-limit violation returns a typed manual-review or rejection
state without changing the source. Accepted text is normalized to UTF-8 without BOM while retaining
the source hash, normalized hash, exact path, detected encoding, confidence, and conversion log.

Supported first-release inputs:

- Markdown and plain text;
- text and scanned PDF;
- DOCX, XLSX, and PPTX;
- optional legacy DOC, XLS, and PPT after controlled conversion;
- images and table attachments.

Primary parsing pipeline:

```text
source registration and license check
  -> MIME, size, hash, encoding, and security inspection
  -> Markdown/TXT read through controlled Bash
  -> legacy Office conversion when required
  -> MinerU converts PDF/image/modern Office to Markdown
  -> validate Markdown, content_list, middle JSON, pages, tables, and formulas
  -> fallback to MinerU OCR when quality fails
  -> fallback to one independent OCR CLI when MinerU OCR fails
  -> canonical Markdown and JSON
  -> clause, table, formula, image, and metadata normalization
  -> full-text and vector indexes
  -> automated evaluation
  -> independent review
  -> authorized human approval
  -> publish, deprecate, or rollback
```

The S3-04 MinerU adapter pins one application-owned executable identity, parser version, pipeline
backend, Chinese language option, formula and table options, timeout, source root, and working output
root. It invokes argument arrays only and never a shell. Current MinerU CLI fields are represented
by an internal versioned command contract instead of being inferred from model output. The adapter
accepts only an S3-03 `ACCEPTED` intake record bound to the same immutable artifact and source hash.
It validates one Markdown file, one legacy content list, and one middle JSON file with bounded size,
strict JSON, page, block type, coordinate, image-path, backend, and parser-version checks before
returning a typed parse artifact. Markdown and plain text use a deterministic zero-tool passthrough;
legacy Office compound files require a later registered conversion. Process failure, timeout,
missing output, malformed JSON, path escape, source mismatch, or unsupported output fails explicitly.

The S3-05 quality gate computes whole-document and per-page page coverage, meaningful-character,
corrupted-character, expected-table, and expected-formula metrics. Drawing pages are explicitly
classified and excluded from text-density failure. A primary quality failure starts exactly one
MinerU OCR attempt; a remaining failure starts exactly one independently registered OCR adapter.
No stage retries itself. When only selected pages fail, the pipeline replaces those pages from the
next validated result and retains the earlier good pages with hash-bound merge lineage. A result is
ready only after the merged or selected document passes the same deterministic gate. Exhausted,
malformed, low-confidence, or failed fallback output enters manual review with every attempt,
reason code, source hash, parser version, and call count preserved.

The S3-06 normalizer accepts only a quality-passed S3-05 document and maps every parsed block
exactly once into a canonical heading, clause, paragraph, table, formula, figure, list, code, or
auxiliary element. It preserves page, coordinates, parser block order, source hash, section path,
clause identifier, table cells or raw body, formula text, figure path, and exact content hashes.
Heading state and clause recognition are deterministic and language-neutral for numeric clause
identifiers. Markdown and simple HTML tables are parsed without executing markup. Metadata keys and
values are bounded, sorted, and treated as data. Stable element, chunk, and document IDs derive from
the exact scope, source, version, locator, and content. Every element enters one or more bounded
traceable chunks without losing a table, formula, figure, number, unit, or citation locator. No LLM,
parser, OCR, retrieval, index, approval, or publication call occurs during normalization.

The S3-07 indexer builds immutable candidate snapshots from canonical chunks using a versioned
embedding port, exact scope, corpus and document versions, metadata, role requirements, status, and
source locators. The local deterministic embedding implementation is a test and offline baseline;
an external embedding binding remains a registered model call. Retrieval intersects exact tenant,
project, user, roles, permission version, published status, and metadata before scoring. It computes
bounded BM25-style full-text rank over Latin terms, numbers, Chinese characters, and Chinese
bigrams, vector cosine rank, reciprocal-rank fusion, and a deterministic phrase/token/numeric
rerank. Only published records may become hits. Each hit reconstructs the exact canonical chunk and
returns source, document, parser, normalizer, corpus, index, element, page, locator, and content-hash
evidence. Draft, superseded, withdrawn, stale-permission, unauthorized, or filter-mismatched records
are never returned. Query and candidate counts are bounded and ranking is stable for identical
inputs.

The S3-08 standard catalog binds each indexed standard version to exact scope, type, identifier,
edition, title, publication and effective dates, optional expiry, region set, lifecycle state,
rights basis, rights evidence reference, role requirements, and explicit replacement links. Stable
version IDs cover every correctness and authorization field. Date intervals must be ordered,
regions and roles are canonical, duplicate versions are immutable, and replacement links must stay
inside one scope and standard lineage and remain acyclic. Applicability is evaluated before
retrieval scoring against exact scope, requested date, region, standard type, usable rights,
lifecycle, roles, and supersession. Draft, replaced, withdrawn, expired, future-effective,
unlicensed, prohibited, role-denied, wrong-region, wrong-type, cross-scope, unregistered, or
superseded versions never enter the scoring repository. A restricted version may be used only with
an accepted rights basis and all required roles. Every exclusion returns stable reason codes for
audit; no policy path silently assumes rights or applicability.

The S3-09 release workflow creates a hash-bound candidate from one exact-scope set of draft index
snapshots and the current base publication, computes document and chunk additions, updates, and
removals, and preserves every immutable input. It transitions through `DRAFT`, `VALIDATING`, and
`REVIEW_REQUIRED`; deterministic validation fails closed on scope, status, corpus/index versions,
duplicate documents or chunks, missing citations, unregistered or unusable standard bindings, or
stale base state. Publication requires an aggregation-ready S1-09 independent professional review
whose reviewed result binds the exact candidate and validation hashes, followed by an S1-13
`KNOWLEDGE` human approval and one exact resume grant. The repository atomically marks the prior
publication and snapshots superseded and the candidate snapshots published. Withdraw and rollback
are separate hash-bound operations requiring their own human approval; rollback creates a new
publication record from preserved prior snapshots rather than erasing history. Candidate,
publication, approval, review, diff, state-transition, and operation hashes remain recoverable.
Idempotent replay returns the same result, while stale base, stale hash, wrong action, cross-scope,
unreviewed, rejected, expired, or reused approval evidence fails before mutation.

The complete S3 local reference implementation passes its automated synthetic and offline test
profile. This does not satisfy TG-03: real pinned MinerU and independent OCR, licensed standards,
accountable rights and publication approvals, an approved production embedding and frozen corpus,
live PostgreSQL/full-text/vector/object-store atomicity and recovery, a zero-skip Linux path corpus,
and protected immutable CI evidence remain mandatory external evidence.

MinerU references:

- [MinerU repository](https://github.com/opendatalab/mineru)
- [MinerU CLI](https://github.com/opendatalab/MinerU/blob/master/docs/en/usage/cli_tools.md)
- [MinerU output files](https://github.com/opendatalab/MinerU/blob/master/docs/en/reference/output_files.md)

Initial file limits:

| Parameter | Default | Hard limit |
|---|---:|---:|
| files per batch | 20 | 50 |
| batch size | 1 GB | 2 GB |
| one file | 200 MB | 500 MB |
| one PDF | 1,000 pages | 2,000 pages |
| Bash commands per file | 5 | 8 |
| Bash commands per batch | `8 * file_count` | 400 |
| parallel files per worker | 2 | 4 after memory tests |
| alternate parser | 1 | 1 |
| OCR time per file | 600 seconds | 900 seconds |

Initial OCR fallback signals include page coverage below 95 percent, fewer than 50 meaningful characters per sampled text page, more than 1 percent obvious replacement or corrupted characters, and missing table or formula blocks above 5 percent. Low-text drawings must be classified before applying text-density rules.

Knowledge states are `DRAFT`, `VALIDATING`, `REVIEW_REQUIRED`, `PUBLISHED`, `SUPERSEDED`, `WITHDRAWN`, and `FAILED`.

Automated validation and the Review Agent provide recommendations; neither can publish, replace, withdraw, or roll back knowledge without an authorized human decision record that references the candidate version and content hashes.

## 12. Bash local file tools

The product agent uses a controlled Bash runtime to inspect, search, read, create, and edit local files in an authorized task directory.

| Capability | Allowed commands | Purpose |
|---|---|---|
| list | `ls`, restricted `find` | enumerate authorized paths |
| search | `grep`, optional `rg` | search authorized text files |
| read | `cat`, `head`, `tail`, `sed -n`, `wc`, `file`, `stat`, `sha256sum` | read and inspect files |
| write | application-owned safe-write wrapper using approved `mkdir`, `touch`, `tee`, or copy primitives | create new directories and artifacts |
| edit | wrapped `patch` or range-limited `sed` | versioned edits to drafts or copies |
| execute | `mineru`, `libreoffice`, OCR, and registered algorithms | run approved local programs |

The model never submits an unrestricted `bash -c` string. Commands use an allowlist, fixed templates, and argument arrays. `rm`, `sudo`, `chmod`, `chown`, `eval`, `source`, and child shells are not exposed by default. Deletion is a separate high-risk management operation.

Writes use a temporary file and atomic rename. Edits create a new version and diff. Original uploads, source inspection data, published knowledge, and formal reports are immutable.

The atomic rename is an internal same-root commit step of the safe wrapper. It validates source and destination paths, ownership, expected hashes, and overwrite policy, and is not exposed to the model as a general `mv` or move action.

The S3-02 implementation registers `file.list`, `file.search`, `file.read`, `file.write`,
`file.edit`, `file.rollback`, and `file.execute` through the shared Tool Registry. Read operations
use exact hashed executables, fixed flags, argument arrays, a UTF-8 locale, literal relative paths,
and bounded captured output. Safe write denies overwrite. Safe edit and rollback require exact
content hashes, preserve a prior working-copy version, and commit through an internal same-root
atomic replace. An execute request selects only an application-published command template and
bounded authorized paths; it cannot select an executable, flags, shell, or network destination.

Path policy is host-independent. POSIX absolute paths, Windows drive-qualified and drive-relative
paths, rooted Windows paths, UNC paths, traversal segments under either separator convention, and
ambiguous control or metacharacter forms are rejected before existence checks on every worker OS.
The same lexical policy is reused by knowledge intake and registered application adapters.

### 12.1 Chinese paths and text encoding

The internal text encoding is UTF-8.

- Verify an UTF-8 locale at worker startup. Prefer `LANG=C.UTF-8` and `LC_ALL=C.UTF-8`. Do not process Chinese text with `LC_ALL=C`.
- Set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` for Python CLIs.
- Pass paths as separate arguments. Use `find -print0` and NUL-delimited consumers for batch filenames.
- Detect BOM and encoding before text conversion. Support UTF-8, GBK/GB18030, UTF-16LE, and UTF-16BE.
- If detection is uncertain, return `NEEDS_USER` or require review. Never silently guess.
- Preserve original bytes as an artifact and normalize a processing copy to UTF-8.
- Record source encoding, normalized encoding, detector, and confidence.
- Decode stdout and stderr strictly. On failure, preserve raw bytes and run one encoding-detection attempt. Do not hide errors with replacement characters.
- Write new text as UTF-8 without BOM unless an explicit project rule requires another encoding.
- Re-read every write or edit and verify filename, Chinese content, line count, hash, and round-trip integrity.

Reference deployment uses Linux Bash. A Windows desktop bridge must use WSL, a controlled Linux container, or a tested UTF-8 Bash runtime instead of translating commands into CMD strings.

## 13. Web Search, Function Calling, and MCP

S5-01 upgrades the shared Tool Registry contract to schema `1.1.0`. One application-owned
definition now declares internal, Bash, Function Calling, Web Search, MCP, instrument, or AI-model
kind; registered transport and namespace for MCP transport; tenant/project/task data scope; local,
tenant-managed, or approved-external data destination; side effect; permissions; secret purposes;
network and approval policy; timeout, attempts, concurrency, bytes, and tokens; declared errors;
recovery policy; and audit and test ownership. Family-specific invalid combinations and plaintext
credential fields fail before publication. The immutable registry hash changes with any definition.

The S5-01 exposure boundary resolves only an allowlisted exact version or unambiguous registered
name and rechecks registry version, permissions, secret purposes, network, and data destination. It
returns a deterministic hash-bound minimal input-schema manifest with no secret declaration,
transport, output schema, adapter, or adapter state. The active defaults expose at most six tools
and one MCP namespace; the hard limits are twelve tools and two namespaces. Side-effecting and
approval-gated definitions require explicit exposure policy. Exposure makes zero external calls and
is hash-only audited. Invocation also binds approval to the exact scope, task, run, registry, policy,
tool, and canonical input hash; validates attempt and retry state; accepts only declared result
errors and compatible retryability; and preserves the S1-08 physical-tool meter. AI-model
definitions stop before that meter and require the separate S5-07 LLM-call and token-metered gateway.
S5-01 enables no live provider, network request, MCP server, model inference, or instrument action.

### Web Search

- Use only when the user requests current information or a standards/status check requires it.
- Prefer government, standards bodies, vendors, and primary research sources.
- Default two queries and four opened pages per subtask; hard limits are four and eight.
- Save URL, title, publication date, and access time.
- Search results enter a candidate knowledge area and never auto-publish.

S5-03 implements Web Search as one read-only `WEB_SEARCH` definition executed only through the
shared Tool Registry. An application-owned policy maps exact HTTPS domains or approved subdomains
to government, standards-body, vendor, or primary-research source classes; literal IP addresses,
credentials in URLs, non-HTTPS schemes, non-default ports, fragments, redirects outside policy,
and request-supplied domain expansion fail closed. Active query and opened-page limits start at two
and four and cannot exceed hard limits of four and eight. Provider calls, opened pages, cache state,
source policy, provider version, access time, publication time, canonical URL, excerpt hash, and
result hash remain explicit evidence.

The adapter uses the S2 retrieval cache only for non-current requests. Cache keys bind exact scope,
normalized queries, domain filters, source policy, provider version, schema, and permission version.
A current-information request always bypasses and does not populate the cache. Stale or undated
evidence cannot satisfy a current request. Provider content is bounded, marked `UNTRUSTED`, scanned
for instruction-like text without executing it, and returned only as candidate evidence with exact
citations. It never changes tool authority, becomes a system instruction, or auto-publishes into
knowledge. Offline, malformed, freshness, budget, and source-policy failures return typed results
with zero fabricated citations.

### Function Calling

- Every function maps to a registered Bash, Web Search, MCP, API, or internal tool.
- Validate strict JSON Schema, permission, risk, budget, idempotency, cache, and timeout.
- Expose at most six functions by default and twelve at hard limit.
- At most three read-only calls may run in parallel. Side-effect calls are serial.

S5-02 adds one provider-neutral Function Calling gateway over the S5-01 registry. Catalog loading
starts from an authorized `ToolExposureManifest`, converts every exposed tool into one deterministic
strict function schema, and binds the catalog to the exact registry snapshot, exposure manifest,
and authorization-context hash. Only the function name, purpose, strict input schema, and strict
flag enter model context; the internal tool mapping remains outside the model-visible schema.

Function calls enter as bounded UTF-8 JSON. Duplicate keys, non-finite numbers, unknown envelope
fields, wrong types, unknown functions, stale or fabricated catalogs, cross-context reuse, and
schema-invalid arguments fail before registry execution and before a physical tool-call count.
Retry state, attempt number, idempotency key, approval evidence, and budget remain orchestration
inputs rather than model-controlled fields. A valid call resolves one exact registered tool version,
reuses the shared authorization, approval, concurrency, timeout, idempotency, result-validation, and
audit path, and returns the registry's validated `ToolResult` unchanged. The gateway performs no
provider, model, network, MCP, Bash, or instrument discovery outside the registry.

### MCP

- Register capability, transport, authorization scope, timeout, side effects, and data destination.
- Expose one MCP namespace per subagent by default and two at hard limit.
- Use short-lived, least-privilege, audience-bound credentials. Do not pass through tokens.
- Bind async tasks to tenant, user, project, and original task identifiers.
- Store large results as artifacts and return only references and summaries.

S5-04 implements an application-owned MCP gateway over the S5-01 Tool Registry. A server
registration fixes local or remote deployment, safe endpoint, namespace, audience, credential
policy, capability allowlist, schemas, side effects, destination, timeouts, streaming bounds, and
asynchronous support. Remote registrations require restricted HTTPS egress and a short-lived
credential broker; local registrations use an explicit application-owned local endpoint and cannot
silently become remote. Caller-supplied access tokens, server-discovered permissions, unregistered
capabilities, unsafe endpoints, and cross-namespace routing are rejected before transport use.

Capability discovery is a separately registered and metered read-only MCP action. The returned
manifest is untrusted, bounded, canonicalized, and intersected with the static application allowlist.
Capability name, version, input/output schema hashes, side-effect class, and async/streaming flags
must match exactly. A changed or malformed manifest fails closed and cannot rewrite the Tool
Registry. Capability invocation, polling, and cancellation are separately registered operations;
each reuses registry permission, scope, destination, approval, idempotency, timeout, physical-call,
result-validation, and hash-only audit controls.
Discovery has a five-minute local default and one-hour hard lifetime. New work requires the current
unexpired manifest; prior exact manifests may only finish or cancel asynchronous work already bound
to their hash, preventing refresh from orphaning a valid handle.

Remote credentials are issued only after registry authorization. Each lease binds exact tenant,
project, user, permission version, server audience, requested capability permission, policy version,
and a bounded expiry. Only the injected transport receives the secret value; model input, MCP
arguments, results, artifacts, errors, audit, and serialized state contain no credential material.

An accepted asynchronous result creates an application-owned local handle bound to the exact scope,
original task and run, server and capability versions, input hash, and opaque remote task identity.
Poll and cancel reject wrong scope, user, task, run, capability, or terminal-state replay before
transport use. State transitions are monotonic. Timeout, cancellation, disconnect, malformed
payload, and provider failure are typed; a disconnect preserves the last valid task state. Streaming
chunks require contiguous indexes and bounded aggregate bytes. Oversized completed results require
immutable scoped artifact references and return only a bounded summary and references.

The S5-04 local tests use an injected deterministic transport and credential broker. They perform no
live MCP, network, subprocess, or external credential operation.

## 14. Source data, instruments, and AI models

```text
source file or instrument task
  -> tool gateway
  -> format parser
  -> canonical inspection data
  -> completeness, unit, and calibration checks
  -> signal algorithm or vision model
  -> quality control
  -> structured result and visualization artifact
  -> Data Processing Agent explanation
  -> Review Agent
  -> qualified human confirmation
```

Canonical data includes structure, component, area, point, channel, sample rate, unit, coordinates,
time, acquisition settings, instrument, calibration, operator, source hash, and parser version. The
S5-06 canonical contract binds one exact tenant and project scope, immutable source and channel
artifacts, explicit simulated/laboratory/production origin, one of the six registered methods, and
a deterministic manifest hash. Large samples remain in immutable artifacts; the manifest stores
only bounded channel locators, counts, rates, time origins, dimensions, units, and content hashes.

Topology contains stable structure, component, area, point, and legacy location identities plus an
explicit coordinate reference and registered-dimensional coordinate values. Acquisition settings
are sorted typed scalar entries. Device identity, adapter version, calibration kind/status/validity
and evidence, operator identity and qualifications, exact source name, media type, encoding
decision, parser identity/version/configuration, and lossless-conversion state remain distinct.
Canonical UTF-8 serialization rejects a BOM, malformed or duplicate JSON keys, non-finite values,
unknown fields, and a changed manifest hash. It preserves non-ASCII filenames and text exactly.

Deterministic validation separates structural processing eligibility from formal-use eligibility.
Missing provenance, cross-scope or mutable artifacts, invalid registered units, non-contiguous
channels, source-range overflow, lossy normalization, or a changed hash blocks processing. A
simulated or laboratory origin, invalid/revoked/expired calibration, acquisition outside every
calibration interval, or an operator without a declared qualification blocks formal use. The S4-04
bridge projects the exact canonical subset into `ProcessingSourceManifest@1.0.0` and revalidates
scope, dataset, source, method, topology, channel/sample bounds, unit, time, instrument,
calibration, operator, and parser identity without executing a parser, tool, model, network call,
instrument, or device.

S5-05 defines one application-owned adapter SDK for registered Bash/CLI, HTTP API, SDK, DLL,
file-exchange, MCP, and simulator transports. A transport binding contains only stable command,
endpoint, package, library, exchange-root, MCP-registration, or simulator identities and hashes; it
never contains raw command text, dynamic executable or library paths, credentials, arbitrary file
paths, or caller-selected destinations. Transport-specific combinations fail before registration.
Remote HTTP endpoints require safe HTTPS and restricted egress. Bash/CLI uses an S3-02 registered
command identity, file exchange uses an application-owned root identifier, and simulators are local,
network-free, credential-free, and explicitly simulated.

An adapter registration fixes capability family, origin, strict input/output schemas, transport
binding, permissions, secrets, network, destination, side effects, approval, idempotency, timeout,
attempt, concurrency, byte/token budgets, required device/calibration/model provenance, declared
errors, and a canonical registration hash. Its generated Tool Registry definition binds that hash.
AI-model definitions remain non-executable through the physical-tool path and are consumed only by
the separate S5-07 inference gateway.

The registration hash canonicalizes every set-valued permission, secret-purpose, and declared-error
field as a sorted JSON array before hashing. Draft construction, validated reconstruction, process
hash randomization, worker OS, and caller insertion order cannot change an equivalent registration
hash. Any semantic member change must still change the hash.

The provider-neutral runtime wrapper receives one registry-authorized request, invokes one injected
provider once, validates its strict reply and declared failure, and constructs the final untrusted
result and evidence itself. Evidence binds exact tenant/project/user scope, task, run, call,
registration, transport, origin, input/output hashes, artifact identities, device, calibration,
model, provider operation, bytes, duration, and call count. Required provenance is enforced before
success. Artifact references must be immutable and exact-scope. Provider exceptions, malformed
identity or output, undeclared errors, timeout, and retryability mismatch are typed; no hidden retry
or dynamic transport discovery is allowed.

The S5-05 local tests use injected deterministic providers only. They execute no Bash command,
network request, SDK, DLL, file exchange, MCP call, simulator process, instrument, model, or device.

The model registry stores model version, valid structures and materials, input/output schema,
training and validation scope, thresholds, runtime, resources, and report eligibility.

S5-07 extends the reference-only API-management registry with a separate inspection-model profile
registry and inference gateway. A hash-bound profile fixes provider/model snapshot, supported
methods/structures/materials, canonical-input schema hash, strict local-only output schema,
training and validation evidence scopes, quality thresholds, runtime identity, bounded resources,
declared provider errors, and report-eligibility class. Profiles cannot expand the provider catalog
or claim formal eligibility without explicit validation metadata and mandatory human review.

An inference request binds exact scope/task/run/call/request, both registry hashes, selected profile,
the S5-06 manifest hash, application-owned instruction identity/version/hash, bounded canonical
parameters, data class, capabilities, input/output token reservations, network authorization, and
formal-use intent. Registry, scope, method, structure, material, canonical processing eligibility,
formal-use prerequisites, schema, token, and budget checks run before provider execution. The model
call uses `BudgetGuard.begin_llm_call` and `complete_llm_call`; it never consumes the physical-tool
meter. One injected provider is called at most once with a reference-only credential selector and
no plaintext secret. Timeout, cancellation, refusal, incomplete, rate limit, provider error,
malformed identity, usage overflow, invalid output schema, quality-threshold failure, and budget
telemetry failure are typed and have no hidden retry or fallback call.

Every physical attempt produces hash-only audit and immutable evidence containing exact registry,
route, provider, endpoint, model snapshot, profile, canonical input, instruction, parameter, output,
artifact, token, latency, confidence, quality, status, and call-count identities. Provider output is
untrusted and review-required. Even an otherwise formal-use candidate remains human-confirmation
required; the inference gateway cannot publish a report conclusion or approval. S5-07 local tests
use an injected deterministic provider and perform no live network, secret resolution, model, tool,
instrument, device, approval, or publication action.

S5-08 publishes one application-owned reference-simulator profile for each of AE, GPR, IE, MV, RT,
and UT. Every profile binds the exact S4-05 method-definition hash, one S5-05 simulator transport and
adapter-registration hash, and one deterministic fixture hash. Simulators are local, network-free,
credential-free, read-only, explicitly simulated, and available only through the shared Tool
Registry permission, scope, schema, budget, timeout, result, and audit boundary. The caller selects
only a registered fixture identity; it cannot select a command, executable, endpoint, path, device,
parser, calibration, method, or output identity.

One accepted simulator call returns a bounded canonical UTF-8 payload and declared manifest hash.
The reference-adapter consumer re-parses the payload through S5-06 and verifies exact scope, method,
simulated origin, fixture/profile/registration hashes, device and calibration provenance, manifest
hash, processing eligibility, and formal-use denial before returning an untrusted review-required
result. Every method uses one deterministic physical-tool call and zero LLM, network, secret,
instrument-command, device, approval, publication, or retry calls. Cross-scope output, a changed
fixture or method, malformed or non-canonical payload, missing provenance, stale registration,
provider error, timeout, or tampered hash remains a typed failure with no fallback. These reference
fixtures demonstrate integration contracts only; they are not real instrument, calibration,
algorithm-quality, or formal inspection evidence.

The local TG-05 assessment exercises the assigned `UNIT-MODELREG`, `INT-FUNCTION`, `INT-WEB`,
`INT-MCP`, `INT-INSTRUMENT`, and `SEC-TOOLS` boundaries together with their tenant, budget, audit,
cache, canonical-data, and method-Skill dependencies. Local deterministic evidence may complete the
S5 implementation tasks, but it cannot pass TG-05 without an immutable candidate and protected CI,
approved live provider and credential evidence, production parser and model qualification,
authorized calibrated real-device data, hardware-lab and expert-gold results, and accountable
security, rights, license, provider-policy, and formal-use approvals. S6 does not inherit permission
to enable any missing production integration while TG-05 is blocked.

The isolated S5-07 API-management control plane separates immutable provider and model catalog
metadata from tenant/project provider bindings. A binding contains only a scoped S1-11
`SecretSelector`; plaintext API keys are never accepted by catalog, binding, resolution, audit, or
serialized evidence contracts. Resolution validates the expected registry hash, environment,
tenant, project, permission version, model capabilities, data classification, network policy,
bounded timeout, attempt, concurrency, input-token, and output-token limits before returning a
reference-only route. Provider compliance metadata records the verification state of processing
region, retention, training use, and commercial terms. Unverified hosted providers cannot be
enabled for production or confidential/restricted data. The initial DeepSeek V4 catalog is a
non-secret personal-development candidate; it does not perform inference, resolve a secret, or
satisfy the unfinished S5-06 canonical-data and S5-07 metered-inference dependencies.

The S5-07 configuration bootstrap reads an explicitly selected strict YAML document at application
startup. The YAML contains only catalog paths, scoped provider bindings, limits, and secret-source
references. An optional ignored local environment file and the process environment contain secret
values; process environment values take precedence. Secret values never enter Pydantic models,
registry hashes, readiness responses, logs, exceptions, or checked-in examples. Startup without a
model configuration remains provider-neutral. An enabled binding with a missing, empty, duplicate,
or invalid secret source fails with a typed non-disclosing configuration error; a disabled binding
may remain unprovisioned. Successful loading validates every catalog and binding and attaches the
reference-only model runtime configuration to application state without making a provider call.

S5-07-LIVE adds the first real hosted-model transport behind the existing S5-07 provider port. The
DeepSeek adapter accepts only an exact authorized DeepSeek OpenAI Chat Completions route, resolves
the scoped secret only after preflight, uses certificate-validated HTTPS, disables redirects,
performs one bounded non-streaming POST without hidden retry, bounds response bytes, and maps HTTP,
timeout, transport, JSON, identity, finish-reason, usage, and output-schema failures into the
existing typed provider contract. Authorization, LLM-call and token metering, output validation,
review requirements, and hash-only audit remain owned by the S5-07 gateway. The adapter never logs,
serializes, returns, or hashes plaintext credentials or provider response bodies.

The ignored local DeepSeek binding may be enabled only for PUBLIC or SYNTHETIC personal-development
inputs after its secret is present. Adapter construction and offline transport tests do not grant a
physical network call. A live synthetic smoke requires a separate explicit operator policy
acknowledgement because processing region, retention, training use, and commercial terms remain
unverified. Without that acknowledgement, smoke preflight returns a typed blocked result and makes
zero network calls.

S6-02-LIVE adds a bounded local integration harness before native desktop binding. It runs the
existing Main Graph, configured General LangGraph child, S5-07 ModelInferenceGateway, and Main
aggregation gate with one fixed SYNTHETIC request. The harness uses the exact ignored local model,
agent, and prompt configurations; performs no tool call, retry, fallback, review bypass, direct
child delivery, formal conclusion, or publication; and returns only a strict AgentResult plus
sanitized provider, model, usage, budget, audit, and hash evidence. Offline injected-provider tests
must prove acknowledgement denial, exact one-call accounting, output validation, typed provider and
budget failure, scope isolation, and zero secret output before a separately acknowledged physical
call. This harness is personal-development evidence only and does not enable a production delegate,
desktop invocation permission, confidential or restricted data, or commercial release.

The first S6-02-LIVE physical attempt used a 512-token output cap and stopped with the typed
`MODEL_INCOMPLETE` result after exactly one LLM and network call and zero tool calls. It did not
retry or fall back. The bounded correction raises only the local smoke total-token active limit from
the G0 default 4000 to 6000, below the unchanged hard limit of 8000, and raises the output cap to
1024. A second physical attempt still requires a fresh explicit acknowledgement.

The separately acknowledged second attempt also stopped as `MODEL_INCOMPLETE`, with 3344 input
tokens, exactly 1024 output tokens, finish reason `length`, one LLM/network call, zero tool calls,
and no retry, fallback, or secret output. The next bounded correction raises only the output cap to
2048; the 5448-token maximum reservation remains below the unchanged 6000 active and 8000 hard
limits. A third attempt requires another fresh acknowledgement.

The separately acknowledged third attempt completed successfully with 3350 input tokens, 1853
output tokens, finish reason `stop`, one LLM/network call, zero tool calls, no retry or fallback,
strict AgentResult validation, and `GENERAL_SYNC` Main aggregation. The output remains untrusted,
review-required model evidence, is not a formal-use candidate, and does not enable a production or
desktop execution binding.

Offline S6-02-LIVE verification injects explicit model and agent runtime objects. It must not read
ignored local bindings, local environment files, or credentials, so the complete test suite remains
reproducible on a clean Linux CI checkout while the physical command retains explicit local loading.

S6-02-APP productizes the bounded General model delegate as an application-owned runtime component.
It accepts only an exact General child context, builds a same-scope deterministic SIMULATED reference
dataset, calls the existing S5-07 gateway once, validates a strict task- and run-bound AgentResult,
and preserves review-required, non-formal, no-tool, no-retry, and no-fallback evidence. The delegate
and its schemas must not import tests or live-smoke tools. Application startup keeps the binding off
by default and permits it only in the local environment with the exact unverified-provider-policy
acknowledgement, configured model, prompt, and agent catalogs, and an application-owned audit service.
When enabled, only a G0 Web workbench task may synchronously traverse authenticated task creation,
Main routing, the configured General child, model inference, Main aggregation, and ordered terminal
events. Every other client task class fails closed without a provider call. This local Web path uses
SYNTHETIC input only and enables no customer data, professional conclusion, formal use, publication,
desktop permission, production deployment, retry, fallback, or tool access.

## 15. Multi-tenancy, security, and audit

- Every business row carries `tenant_id`; project data also carries `project_id`.
- PostgreSQL Row Level Security is mandatory. The application account must not bypass RLS.
- Object storage, retrieval, memory, cache, tasks, and artifacts enforce tenant and project scope server-side.
- Tool credentials are short-lived and least privilege.
- Source files, model runs, prompts, tool calls, tokens, evidence, reviews, and approvals are auditable.
- External documents and web pages are untrusted data and cannot change system instructions or permissions.
- Instrument control, knowledge publishing, formal report approval, and bulk destructive operations require explicit human approval.

The security baseline is approved in S0 and implemented with the protected capabilities. It includes:

- a versioned threat model, trust-boundary diagram, data classification, and abuse cases;
- TLS in transit and encryption at rest for databases, object storage, queues, backups, and portable artifacts;
- managed secrets, key separation by environment and scope, rotation, revocation, and auditable key use;
- retention, export, deletion, legal hold, backup expiry, and cryptographic erasure rules;
- a code-and-model SBOM, dependency and container scanning, license obligations, and replacement plans;
- incident response ownership, evidence preservation, notification criteria, and tested recovery procedures;
- approved service-level indicators, objectives, error budgets, RPO, RTO, and degraded-mode behavior.

The S2 lifecycle boundary registers immutable scoped data records with classification, canonical
content hashes, retention deadlines, and optional object-unique key references. Export is exact
scope and permission filtered and carries a canonical manifest hash. Deletion requires a hash-bound
preview and current approval, retains a non-content tombstone, and distinguishes approved forced
deletion from expiry-based deletion. Active legal holds block deletion and cryptographic erasure.
Cryptographic erasure requires retention expiry, exact approval, and confirmed revocation of an
object-unique key before content removal. Every successful lifecycle action appends hash-bound audit
evidence. Backup expiry, cache and index invalidation, and live-service probes remain integration
requirements; local contract tests cannot promote them to production gate evidence.

### 15.1 S6 client boundary

S6-01 adds one provider-neutral Web workbench over application-owned client contracts. The server,
not browser input, derives tenant, project, user, roles, and permission version from the authenticated
request. Task creation accepts only a bounded goal, success criteria, task class, and an idempotency
key. It creates server-owned task and event identities and begins with a non-terminal accepted event;
it cannot fabricate an AgentResult, review, approval, formal conclusion, or publication state.

Task reads and event streams use fixed protected routes with task identity in validated query data so
the existing exact-route authorization policy remains default deny. Events are immutable, strictly
ordered, scope-bound, and replayable after the last acknowledged sequence. A reconnect receives only
later events and never repeats a committed side effect. Terminal tasks replay the bounded terminal
history and close the stream. Unknown, cross-scope, stale-permission, invalid-sequence, and conflicting
idempotency requests fail with stable non-disclosing errors before state is exposed or changed.
Task-state reads, sequence validation, event append, and task-state replacement occur in one atomic
repository transaction. Concurrent appenders cannot commit the same sequence, overwrite a later
state, or return an event batch whose cursor and terminal metadata describe a different snapshot.

The initial Web shell is responsive and keyboard operable, uses semantic landmarks and labeled
controls, announces stream state through a polite live region, provides visible focus, honors reduced
motion, renders event text as text rather than trusted markup, stores no bearer token, and prevents
client/API caching. Local S6-01 uses an in-memory repository and deterministic event injection only;
durable queues, multi-process fan-out, production identity, browser and assistive-technology matrices,
and load qualification remain later S6 evidence.

S6-02 packages a pinned Rust and Tauri desktop shell around one application-owned local origin. One
exact local window receives only the generated readiness-status permission. The native invocation
command is registered so its permission identity is deterministic, but the window capability does
not grant it until an authenticated application session and registry-bound executor are qualified.
The frontend has no shell, process, filesystem, network, credential storage, permission, approval,
review, or formal-state authority and may query bridge readiness only.

The native bridge and application service share strict camelCase invoke, cancel, and error envelopes.
The checked-in golden JSON and canonical UTF-8 SHA-256 rules bind both implementations to identical
wire values. Invoke carries an opaque session handle, non-nil task and run identities, an exact
lowercase SHA-256 registry version, one compiled reference-adapter identity and version, a bounded
JSON object, and a bounded idempotency key. Cancel is a distinct operation bound to the same session,
task, run, and registry plus the exact target request hash and a 512-byte UTF-8 reason. Unknown fields,
malformed identities or hashes, changed versions, unknown tools, non-object arguments, and oversized
input fail before execution. The
application-owned desktop service hashes rather than persists raw handles, resolves exact task,
run, tenant, project, user, permission, policy, registry, allowlist, budget, observation, and expiry
state from the session, and invokes only the shared Tool Registry. Therefore approval, permission,
destination, budget, idempotency, strict schema, typed ToolResult, and hash-only audit controls remain
server-owned and cannot be supplied by IPC. Missing, expired, mismatched, stale, or unauthorized
requests stop before the provider; same-scope replay reuses the committed registry result. A valid
cancellation intent is scope-checked and hash-only audited, but returns the typed
`DESKTOP_CANCEL_UNAVAILABLE` denial until a qualified application-owned cancellation adapter exists;
receipt of intent is never reported as physical cancellation.

The Tauri window still receives status permission only. Invoke returns
`DESKTOP_SESSION_REQUIRED`, and cancel returns `DESKTOP_CANCEL_UNAVAILABLE`, with zero external action
until the native commands bind to the application service. A local no-bundle binary proves
compilation only; native service process binding, invocation and cancellation permission, signing,
installers, upgrade, rollback, live desktop E2E, and immutable release
qualification remain required.

S6-03 extends the same shell into a PWA without creating a second business path. Its service worker
is a public-shell cache only: it accepts safe same-origin GET requests for the workbench document and
versioned assets, rejects every protected API, event, task, mutation, authorization-bearing, and
cross-origin request, and stores no user data or credential. Offline mode reports disconnection and
may show only the static shell and limitations; it cannot queue work or synthesize server state.

### 15.2 S6 operations and recovery boundary

S6-04 uses one hash-bound operations profile whose governance state is explicit. Provisional targets
may drive deterministic local tests but cannot produce an approved SLO or release-gating restore
PASS. Independent approval must bind the exact profile, security baseline, metric definitions,
reference environment, backup stores, key policy, RPO, RTO, zero-loss categories, and owners.

Quota claims are server-owned, exact-scope, atomic, and separately count tenant concurrency, user
concurrency, accepted tasks, storage bytes, and request rate. Active and hard limits remain distinct;
denial changes no counter, release is idempotent, and no claim or capacity crosses tenant, project,
user, permission-version, or policy-version boundaries.

Backup manifests contain hashes and key references, never content or key material. Restore evidence
must revalidate manifest-chain integrity, exact stores and artifacts, source-to-restored hashes,
checkpoint and event counts, approval/publication zero-loss, elapsed recovery point and recovery time,
degraded mode, rollback readiness, and evidence location. Any missing, stale, cross-scope, synthetic,
or provisional requirement returns a typed blocked result with the required next action.

### 15.3 S6 assurance evidence

S6-05 uses a versioned required-case catalog rather than treating an undifferentiated test command as
commercial assurance. Each result binds case, build, environment, configuration, data, start/end,
evidence hash and URI, severity counts, tenant leaks, duplicate committed side effects, retry-limit
violations, and failure-explanation completeness. Aggregation is fail closed and distinguishes local
deterministic, CI, staging, production-like, hardware-lab, and independent penetration evidence.
Simulation cannot satisfy a case marked live or independent, and a green local report cannot clear
the corresponding release blocker.

### 15.4 S6 performance and token evidence

S6-06 records latency, throughput, concurrency, token, and cache measurements as versioned sample
series bound to one exact build, benchmark profile, workload, environment, and configuration. Every
latency series reports a deterministic nearest-rank P50, P95, and P99 plus sample count and failures.
Token economics separates input, output, hidden orchestration, review, retry, cache-hit, and
cache-miss usage and compares cold and warm repetitions without converting estimated or synthetic
counts into provider billing evidence.

A local microbenchmark can validate aggregation, threshold, and concurrency contracts. Release
qualification additionally requires the approved reference hardware and live database, vector,
parser, artifact-transfer, client-streaming, queue, model-provider, and cache paths. Missing live
dimensions, an incorrect result, an isolation failure, insufficient samples, or stale build/profile
binding yields a typed blocked or failed assessment rather than an inferred production result.

### 15.5 S6 budget calibration

S6-07 calibrates each task-class budget dimension only from successful exact-build observations that
report P95 and P99, sample count, environment, provider-measurement state, quality result, and zero
correctness or isolation failures. The candidate default is `ceil(P95 * 1.15)` and the candidate hard
limit is `min(ceil(P99 * 1.25), product_global_limit)`. A candidate whose default exceeds its hard
limit or whose hard limit exceeds the existing global ceiling is invalid.

The calibration record preserves every source observation and emits a new immutable policy rather
than mutating the V1 defaults. Missing, local-only, estimated, failed-quality, stale, or insufficient
evidence yields a provisional or blocked result. Only complete approved-reference and
provider-measured evidence for every required task class and dimension can produce an approvable
production budget profile.

### 15.6 S6 shadow deployment and expert pilot

S6-08 uses an immutable hash-chained ledger for seven consecutive UTC service dates. Every daily
record binds the same release build, benchmark profile, calibrated budget profile, deployment
configuration, production-like environment, start/end times, workload counts, workflow pass rates,
security, resilience, performance, and token assessments, and zero P0/P1, tenant leak, duplicate
committed side effect, correctness, and isolation failure counts.

Completion requires seven daily records, at least six elapsed 24-hour periods between the first
start and final evaluation, no future or duplicate date, 100 percent critical workflow pass rate,
at least 98 percent noncritical workflow pass rate, and the profile-defined number of distinct
qualified expert acceptances bound to the same evidence. A local test, backdated fabricated record,
broken hash chain, changed build/profile, missing live prerequisite, or insufficient elapsed time
returns blocked or failed and cannot satisfy S6-08.

### 15.7 S6 immutable release candidate

S6-09 constructs one content-addressed candidate manifest only after S6-01 through S6-08 and every
required phase prerequisite pass for the exact immutable source commit. The manifest binds source,
dependency lock, SBOM, client and server artifacts, migrations, configuration, schema, prompts,
Skills, tools, models, test evidence, rollback evidence, and release-smoke evidence by SHA-256.

Migration evidence proves upgrade and downgrade against a production-like copy with unchanged
protected-data hashes. Signing uses an approved asymmetric key reference and signs the canonical
candidate hash; private key material never enters the manifest, logs, or artifacts. Verification
resolves that reference through a trusted application-owned key registry, requires an exact approved
and non-revoked release-signing key identity, and never treats a candidate-supplied public key,
environment label, or approval flag as trust evidence. Verification checks the signature against the
resolved trusted public key, artifact sizes and hashes, exact build/profile bindings,
mandatory smoke checks, and zero P0/P1, leak, duplicate-side-effect, correctness, or isolation
failure. A local generated-key contract test, offline SQL compilation, mutable source tree, missing
prerequisite, or synthetic smoke result cannot create a release-qualified V1.0 candidate.

### 15.8 S6 publication and post-publication verification

S6-10 accepts only the exact S6-09 sealed candidate whose RELEASE assessment and TG-06 evidence
PASS. An immutable release decision binds candidate hash, artifact-set hash, TG-06 evidence hash,
authorized approver, role, permission version, decision time, expiry, target, and residual-risk
acknowledgement. TG-06 evidence and the release decision must resolve by immutable hash from an
application-owned authority store; request-supplied copies are untrusted and must exactly match the
stored records. The authority adapter revalidates approval, permission, freshness, target, and
revocation state before publication. Publication is idempotent for that exact decision and target;
a changed input or replayed key fails before the publisher adapter runs.

The publisher adapter returns an immutable deployment identity and deployed candidate hash. The
runtime creates a PUBLISHED_PENDING_SMOKE record, then requires live post-publication checks for
health, identity, tenant isolation, task streaming, review/approval controls, cache/tool isolation,
and artifact/version identity within the approved window. A mismatch or unsafe count produces a
typed rollback-required state. Missing candidate, TG-06, approval, permission, publisher, or live
smoke evidence remains blocked; local injected adapters cannot publish commercial V1.0.

## 16. Core data objects

At minimum implement:

- tenants, users, roles, memberships;
- projects, structures, components, inspection points;
- threads, tasks, subtask runs, checkpoints, review runs;
- tool registry, tool calls, model registry, model runs;
- artifacts, raw datasets, processing runs, observations, defects;
- memory events, distilled memories, snapshots, restore events;
- knowledge sources, document versions, chunks, rules, index versions;
- Skills, prompts, templates, release versions;
- plans, reports, approvals, audit logs, and cache metadata.
- security policies, data classifications, key references, retention jobs, SBOM versions, license decisions, SLO versions, incidents, and release approvals.

A report conclusion must trace to processing output, algorithm or model version, parameters, source file, instrument, calibration, point, operator, and standard clause.

## 17. Delivery roadmap

| Phase | Weeks | Delivery |
|---|---|---|
| S0 | 1-2 | requirements, domain/data model, schemas, fixtures, CI |
| S1 | 3-6 | agent core, tenancy, checkpoints, budgets, review, audit |
| S2 | 7-9 | context compression, memory, restore, and cache |
| S3 | 10-13 | Bash file tools, encoding, MinerU/OCR, knowledge lifecycle |
| S4 | 14-18 | QA, plan, report, data-processing Skills, review workflows |
| S5 | 19-22 | Function Calling, Web Search, MCP, instruments, AI models |
| S6 | 23-26 | clients, hardening, benchmarks, seven-day shadow run, immutable release candidate, final gate, and publication |

Detailed tasks and dependencies are maintained only in [plan.md](./plan.md).

## 18. Release validation

Minimum release gates are maintained in [test.md](./test.md). Critical targets include:

- routing Macro-F1 >= 0.97;
- restore false-trigger rate <= 0.5 percent;
- direct snapshot restore >= 99.9 percent;
- retrieval Recall@6 >= 0.92;
- citation correctness >= 0.95;
- clean-file parsing >= 98 percent;
- scanned-PDF usable text >= 95 percent;
- critical compression-field retention = 100 percent;
- Chinese path and text round-trip = 100 percent;
- cross-tenant leaks = 0;
- stale or cross-tenant cache errors = 0;
- infinite loops and post-budget calls = 0;
- recoverable-error automatic recovery >= 90 percent;
- unrecoverable-error explanation coverage = 100 percent;
- repeated-workload median token reduction >= 25 percent;
- checkpoint recovery = 100 percent;
- duplicate side effects = 0.

Every metric used by a task or gate must reference a versioned metric definition containing its formula, population, exclusions, denominator, sampling and stratification rules, random seed where applicable, confidence interval or tolerance, human-adjudication rubric, baseline version, and evidence format. Terms such as `usable text`, `expert pass`, `critical workflow`, and `citation correctness` are not gateable until defined in that registry. Resilience acceptance must reference an approved SLO version.

TG-06 validates the exact immutable hashes of the signed release candidate after packaging, migration, rollback, artifact-signing, and release-smoke tests. Publication is a separate authorized step and may publish only those gated hashes.

## 19. Definition of done for commercial V1.0

V1.0 is ready for a controlled commercial pilot only when:

1. The mandatory agent topology is enforced end to end.
2. Subagents cannot bypass the Main Agent.
3. Context compression preserves all critical fields and supports local restore.
4. Memory can be distilled, viewed, restored by intent or click, branched, and deleted.
5. The Knowledge Agent supports approved files, MinerU-first parsing, OCR fallback, review, publishing, and rollback.
6. Bash tools can list, search, read, write, and edit authorized local files with correct Chinese encoding.
7. Web Search, Function Calling, and MCP use least privilege and shared budgets.
8. Hard limits for loops, calls, tokens, time, and concurrency are enforced.
9. Every complex sub-result is reviewed and failures are explained.
10. Tenant, project, cache, file, memory, and retrieval isolation tests show zero leaks.
11. Report conclusions trace to source data, processing, tools, models, and standards.
12. All blocking test gates in [test.md](./test.md) pass.
13. The exact signed release-candidate hashes validated by TG-06 are approved and published, and post-publication smoke evidence is recorded.
