# Civil Infrastructure NDT Agent Platform Development Specification

**Specification version:** 1.22  
**Date:** 2026-08-24  
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
hash-only S1-10 `TOOL` audit record. Concrete Bash, Function Calling, Web, MCP, instrument, and model
adapters remain assigned to S3 and S5.

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

| Level | Trigger against application context budget | Action |
|---|---:|---|
| C0 | below 40% | permission filter and lossless deduplication only |
| C1 | 40% to 60% | remove repeated confirmations, retrieval duplicates, and long logs |
| C2 | 60% to 80% | summarize older turns to at most 800 tokens; keep six recent turns |
| C3 | above 80% | checkpoint first, then build a task digest of at most 1,200 tokens |

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

Distillation triggers when any condition is true:

- active context reaches 60 percent of its application budget;
- user and assistant messages total 20;
- a task completes;
- the user confirms, corrects, or asks the system to remember something;
- a task is archived or paused for a long period.

Keep the last six raw turns and distill older conversation into at most 800 tokens. Store at most 30 candidate project facts per distillation. Separate facts from inferences, preserve sources, detect conflicts, and do not silently overwrite old facts.

Restore paths:

- Intent restore: search at most five snapshots. Initial auto-restore requires confidence >= 0.90 and a top-two score margin >= 0.12. Otherwise show candidates.
- Direct restore: the user selects a snapshot in the UI.

Restore creates a new branch and never overwrites the current session. Recheck tenant, project, permission, artifact existence, and version compatibility. Inject at most 6,000 tokens, 20 project facts, ten artifact references, and six required turns.

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

## 11. Knowledge Agent

The Knowledge Agent starts only from an explicit user intent, a UI action, or an approved administrator job. Normal question answering uses read-only retrieval and does not start an ingestion agent.

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

### Web Search

- Use only when the user requests current information or a standards/status check requires it.
- Prefer government, standards bodies, vendors, and primary research sources.
- Default two queries and four opened pages per subtask; hard limits are four and eight.
- Save URL, title, publication date, and access time.
- Search results enter a candidate knowledge area and never auto-publish.

### Function Calling

- Every function maps to a registered Bash, Web Search, MCP, API, or internal tool.
- Validate strict JSON Schema, permission, risk, budget, idempotency, cache, and timeout.
- Expose at most six functions by default and twelve at hard limit.
- At most three read-only calls may run in parallel. Side-effect calls are serial.

### MCP

- Register capability, transport, authorization scope, timeout, side effects, and data destination.
- Expose one MCP namespace per subagent by default and two at hard limit.
- Use short-lived, least-privilege, audience-bound credentials. Do not pass through tokens.
- Bind async tasks to tenant, user, project, and original task identifiers.
- Store large results as artifacts and return only references and summaries.

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

Canonical data includes structure, component, area, point, channel, sample rate, unit, coordinates, time, acquisition settings, instrument, calibration, operator, source hash, and parser version.

The model registry stores model version, valid structures and materials, input/output schema, training and validation scope, thresholds, runtime, resources, and report eligibility.

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
