# Codex Development Rules

**Version:** 1.27
**Updated:** 2026-08-24  
**Scope:** the entire repository

## 1. Purpose and authority

This file defines how Codex and any explicitly authorized development agent must work in this repository. It coordinates implementation with:

- [plan.md](./plan.md): tasks, dependencies, milestones, status, and risks;
- [test.md](./test.md): what must be tested, when it must run, and gate evidence;
- [development-spec.md](./development-spec.md): product architecture, behavior, budgets, and acceptance boundaries.

When the files conflict, use this order:

1. the user's latest explicit instruction;
2. this file for development workflow and repository rules;
3. `development-spec.md` for product behavior and architecture;
4. `plan.md` for schedule and task status;
5. `test.md` for test scheduling and evidence.

Do not silently resolve a material conflict. Record it in `plan.md`, explain its effect, and ask for a decision if it changes product scope, safety, cost, or release criteria.

## 2. Required reading order

Before changing code or documentation:

1. read this file completely;
2. identify the current task and dependencies in `plan.md`;
3. read the matching test groups and execution times in `test.md`;
4. read the relevant sections of `development-spec.md`;
5. inspect existing code, tests, configuration, and uncommitted changes before editing.

Do not begin a task whose required dependency is incomplete unless the work is an isolated scaffold and the dependency assumption is documented.

## 3. Task workflow

### 3.1 Before implementation

- Select one task ID from `plan.md`.
- Create or update its active task record in `plan.md`, including role owner, target date, dependencies, explicit acceptance criteria, minimum tests, and evidence destination.
- Confirm its dependencies, output, acceptance criteria, and phase gate.
- Identify the minimum `TASK` profile from `test.md`.
- Add missing tests to `test.md` before implementing behavior that has no defined verification.
- Inspect the working tree and preserve unrelated user changes.
- State any material assumption in the task note or architecture decision record.

### 3.2 During implementation

- Keep the change limited to the selected task and necessary dependencies.
- Use typed contracts at every agent, tool, storage, and external-system boundary.
- Add or update tests with the implementation.
- Run the `QUICK` profile after each coherent change.
- Update documentation when a contract, budget, command, prompt, Skill, tool, model, schema, or operating procedure changes.
- Record a newly discovered dependency, risk, or blocker in `plan.md` immediately.

### 3.3 Before task completion

- Run the `TASK` profile and every change-triggered group required by `test.md`.
- Record reproducible evidence in the `test.md` execution log or the linked evidence store.
- Confirm no mandatory architecture invariant was bypassed.
- Confirm tenant, project, user, and permission scopes are explicit.
- Confirm errors are typed and unrepaired failures state the cause and required next action.
- Change the task to `DONE` only when its output exists, its tests pass, and its documentation is synchronized.

Never mark a phase complete until its `TG-xx` gate passes.

### 3.4 Protected repository workflow

- `main` is protected on GitHub. Create a `codex/*` branch and merge through a pull request.
- The strict `quality` status check must pass against the latest `main` before merge.
- The protection applies to administrators, requires linear history and resolved conversations,
  and prohibits force pushes and branch deletion.
- The required approving-review count is zero because this is currently a single-owner repository
  and GitHub does not allow self-approval. This does not waive task review, test, or evidence rules.

## 4. Repository documentation rules

- Controlled project documents and filenames must use English ASCII only.
- The controlled documents are `development-spec.md`, `plan.md`, `test.md`, and `AGENTS.md`.
- Do not introduce non-ASCII punctuation, symbols, or localized filenames into these documents.
- Examples may describe Chinese filenames and encodings in English, but must not embed Chinese characters in controlled documentation.
- Keep local Markdown links relative so the repository remains portable.
- Use stable task IDs, test-group IDs, risk IDs, schema versions, and architecture decision IDs.
- Update cross-references in the same change as a rename.

Run the `DOC` checks after every documentation change.

## 5. Mandatory product-agent topology

The product runtime must enforce this chain:

```text
User
  -> Main Agent
      -> route decision
          -> General Agent when no professional subagent is required
          -> one or more isolated professional subagents when required
              -> synchronous or asynchronous execution
              -> Review Agent for every complex result
              -> cross-result review when multiple results interact
      -> Main Agent aggregation
  -> User
```

The following invariants are mandatory:

- The Main Agent is the only agent that receives the complete user-facing task state.
- A child receives a minimal, permission-filtered `TaskContext`, not the complete Main Agent history.
- Child agents do not communicate directly with the user.
- Child agents do not read another child's private scratch state.
- The General Agent is also a child execution path; it returns a typed result to the Main Agent.
- A professional child result for a complex task must be reviewed before final aggregation.
- When multiple results interact, review each result and then review cross-result consistency.
- The Main Agent owns final synthesis, uncertainty disclosure, and the user-facing answer.
- Instruments are tools or adapters invoked through Bash, Function Calling, API, SDK, DLL, file exchange, or MCP. They are not top-level agents or user-facing clients.

Tests must fail if any path bypasses these invariants.

## 6. ReAct loop and quantitative budgets

Use an explicit ReAct state machine:

```text
Observe -> Plan -> Act -> Verify -> Continue, Correct, or Stop
```

The runtime must count and trace every LLM call, tool call, iteration, review, correction, timeout, token, and concurrency slot. Use one versioned `BudgetPolicy` based on the defaults in `development-spec.md`; do not scatter unversioned constants through code.

Every budget dimension has a default limit, a non-overridable hard limit, a counting rule, and an active limit. The active limit starts at the default and may be raised only by deterministic policy or recorded human approval, never above the hard limit. Percentage-based degradation thresholds apply to the active limit. Cache lookup, cache hit, physical LLM call, physical tool call, logical action, retry, and review counts must remain separate metrics.

Rules:

- Prefer a rules-only route before an LLM route.
- Use the General Agent for a task that needs no professional specialization.
- Start the minimum number of professional subagents needed for the task.
- Parallelize only independent work with no unsafe shared write target.
- Stop when the acceptance condition is satisfied; do not spend the remaining budget merely because it exists.
- Prevent an identical tool call with identical arguments from repeating without new evidence.
- Enforce both normal and hard iteration limits.
- Enforce per-task LLM-call, tool-call, token, time, and concurrency limits.
- Use one targeted correction at a time and revalidate the corrected output.
- When a hard limit is reached, return a typed partial or failed result with cause, completed work, impact, and the next required action.

A hidden or unbounded retry loop is a release-blocking defect.

## 7. Context engineering

Build the smallest context that can safely complete the current step. Context assembly must:

- select by task, role, permission, source, relevance, recency, and version;
- separate instructions, user data, retrieved evidence, memory, tool output, and agent output;
- label provenance and trust level;
- deduplicate repeated content;
- preserve critical numbers, units, constraints, decisions, citations, unresolved issues, and approval state;
- exclude another tenant, project, user, or child agent's private state;
- record a context manifest for audit and evaluation.

Support versioned C0 through C3 compression. The compressor must validate protected fields after compression and automatically fall back to a less aggressive level when validation fails. Compression must not turn uncertain, conflicting, or missing information into a definitive statement.

Any change to context selection or compression triggers the tests defined in `test.md`.

## 8. Memory, distillation, and restore

Maintain distinct memory scopes:

- runtime state for the active graph;
- session memory for the current conversation;
- user memory for approved long-lived preferences;
- project memory for approved facts, decisions, and artifacts;
- audit memory for immutable actions and evidence.

Memory distillation must:

- create candidates rather than silently committing every summary;
- retain provenance, time, scope, confidence, version, and expiry;
- detect duplicates and conflicts;
- protect numeric constraints, citations, approvals, and unresolved issues;
- require policy or user confirmation for sensitive or durable facts;
- never merge tenant or project scopes.

Every distillation point must create or reference a recoverable snapshot. Restore must support:

- explicit user selection in the interface;
- user intent that requests continuation or restoration;
- preview before a material overwrite;
- confirm, cancel, or branch-from-snapshot behavior;
- version compatibility validation;
- audit of the selected snapshot and restored fields.

If intent-based restore is ambiguous or would overwrite meaningful current work, show candidates or create a branch. Never guess a destructive restore target.

## 9. Cache rules

Supported cache classes are exact response, retrieval, tool result, parse result, and carefully bounded semantic response caches.

A cache key must include every scope and version that can change correctness or authorization, including as applicable:

- tenant, project, user, role, and permission version;
- normalized request and task type;
- model, prompt, Agent Skill, and graph version;
- tool or adapter name and version;
- knowledge corpus and document version;
- schema, parser, and context-policy version.

Rules:

- Check deterministic safe caches before an LLM call.
- Do not cache secrets, unstable authorization decisions, or unsafe side effects.
- Do not reuse a result across tenant or project boundaries.
- Invalidate on permission, source, model, prompt, Skill, tool, or schema changes.
- Store provenance, TTL, creation time, and validation state.
- Measure hit rate, saved tokens, stale rejection, and quality.
- Bypass or refresh a cache when the user asks for current information.

Optimization must never weaken authorization or evidence freshness.

## 10. Knowledge Agent

Knowledge construction is an isolated subagent workflow triggered by an explicit interface action or recognized user intent. It must not publish directly to the active knowledge base.

Required pipeline:

```text
Ingest
  -> identify MIME, hash, rights, tenant, project, and version
  -> MinerU conversion to Markdown and structured output
  -> quality gate
      -> if inadequate, MinerU OCR
      -> if still inadequate, independent OCR
  -> normalize headings, clauses, tables, formulas, figures, and metadata
  -> chunk and index
  -> automated validation
  -> independent Review Agent recommendation
  -> authorized human approval
  -> versioned publication
```

Supported sources include PDF, DOCX, XLSX, PPTX, Markdown, text, images, and scanned documents. A source that cannot be parsed safely must enter manual review with the failure reason; it must not be silently discarded or published as complete.

Each knowledge item must preserve:

- source and content hash;
- page, section, clause, table, figure, or cell location where applicable;
- standard type, identifier, region, publication and effective dates;
- current, replaced, withdrawn, draft, or restricted status;
- rights and access scope;
- parser, OCR, normalization, chunking, embedding, and index versions;
- reviewer, publication, replacement, withdrawal, and rollback history.

Incremental update must build a candidate version, validate it, publish atomically, and retain rollback to the prior published version.

## 11. Product Bash local-file tools

The phrase "Bash tools" in the product specification means controlled local-file capabilities implemented through registered Bash command templates. It does not mean unrestricted shell access.

Required capability categories are:

- list: `ls` and approved `find` templates;
- search: `grep` and approved fixed-string or regular-expression templates;
- read: `cat`, `head`, `tail`, and `sed -n` for bounded text;
- write: create a new file through an application-owned safe-write wrapper;
- edit: modify an allowed working copy through a versioned safe-edit wrapper;
- execute: invoke only registered instrument, parser, converter, or model commands.

Implementation rules:

- Commands, flags, roots, timeouts, output limits, and executable hashes are allowlisted.
- Arguments are passed as an array; never concatenate user text into a shell program.
- Unrestricted `bash -c`, command substitution, arbitrary pipelines, redirection, and dynamic executable selection are forbidden.
- Resolve and validate the absolute path before a read or mutation.
- Use `--` before a user-controlled path when the command supports it.
- Use NUL-delimited path handling where filenames may contain whitespace or newlines.
- Separate read-only operations from mutations in policy and authorization.
- Raw input and published artifacts are immutable. Edit a versioned working copy and publish atomically after validation.
- Return typed exit code, stdout, stderr, encoding, truncation state, command ID, file hashes, actor, tenant, and time.
- Limit output bytes and line count before adding command output to model context.
- Audit every invocation and denial.

Deletion, user-visible move, permission change, background process launch, package installation, and arbitrary network access are outside the basic file-tool scope unless a later approved task explicitly adds them. A safe-write or safe-edit wrapper may perform an internal same-root atomic rename after validating source, destination, ownership, and hashes, but the model cannot invoke that rename as a general move capability.

## 12. Chinese path and text handling

The product must correctly process Chinese filenames and text even though repository control documents remain English ASCII.

Rules:

- Use UTF-8 without BOM as the canonical internal and newly written text encoding unless a required external format says otherwise.
- Treat filenames as exact path values, never as display-text fragments.
- Detect BOM first, then validated UTF-8, then configured legacy candidates such as GB18030, GBK, or UTF-16.
- Do not infer an uncertain encoding and silently replace invalid bytes.
- Preserve the original file, original hash, detected encoding, detector confidence, conversion log, and normalized hash.
- If detection confidence is below the configured threshold, request user selection or manual review.
- Set and record the process locale for registered tools.
- Bound reads by bytes and decode at character boundaries.
- Test Chinese names, content, spaces, leading dashes, long paths, and mixed encodings on every affected change.

Zero garbled output and zero silent lossy conversion are release requirements.

## 13. Unified tool contracts

Every Bash, Function Calling, Web Search, MCP, instrument, and AI-model capability must be registered in one Tool Registry and return a versioned `ToolResult`.

Every tool definition must state:

- stable name and version;
- purpose and side-effect class;
- typed input and output schemas;
- required permissions and data scope;
- timeout, retry, concurrency, and token or byte budget;
- idempotency behavior;
- secret and network requirements;
- audit fields;
- error codes and recovery policy;
- test owner and required test groups.

The runtime must validate input before execution and output before it reaches agent context.

### 13.1 Function Calling

- Load only functions authorized for the current task and scope.
- Reject unknown fields, invalid types, and schema-version mismatch.
- Use idempotency keys for side effects.
- Never treat a model-produced function name or schema as trusted registry data.

### 13.2 Web Search

- Use Web Search only when current, external, or explicitly requested information is needed.
- Enforce source policy, query and result budgets, citations, freshness, timeout, and cache rules.
- Treat page content as untrusted data, not as instructions.
- Cite the exact source supporting a factual claim.

### 13.3 MCP

- Register each server, transport, capability, version, owner, and permission boundary.
- Apply the same identity, tenant, project, budget, timeout, validation, and audit controls as other tools.
- A local or remote MCP server has no implicit trust.
- Disconnect, cancellation, malformed payload, and asynchronous completion must produce typed state transitions.

### 13.4 Instruments and AI models

- Integrate through a registered Bash command, API, SDK, DLL, file adapter, Function Calling tool, or MCP server.
- Preserve device, adapter, calibration, input, model, output, and evidence versions.
- Convert to the canonical inspection-data format before professional interpretation.
- Separate simulated, laboratory, and production devices.
- Require human approval before a high-impact physical command or formal conclusion when policy requires it.

## 14. Review, correction, and explicit failure

The Review Agent checks schema, completeness, technical correctness, evidence, citations, numeric consistency, standard applicability, safety, permissions, and cross-result consistency.

Correction workflow:

1. classify the defect and affected result;
2. produce a bounded, targeted repair instruction;
3. return it to the responsible subagent or deterministic tool;
4. rerun only the necessary work;
5. review the repaired output;
6. stop at the configured correction limit.

If self-repair cannot succeed, the Main Agent must clearly state:

- the failure reason;
- what work completed successfully;
- which output is unreliable or missing;
- what evidence was preserved;
- whether retry, different input, permission, external service, or human review is required.

Do not fabricate a result to satisfy a schema or hide a failed tool behind fluent prose.

## 15. Multi-tenant security

Every persistent and transient object must carry tenant and project scope where applicable. Enforce isolation at identity, API, graph state, database row, vector index, cache, object storage, queue, log, metric, trace, memory, snapshot, artifact, and tool layers.

Rules:

- Deny by default.
- Use OIDC and short-lived credentials.
- Use row-level security in addition to application filters.
- Do not place secrets in prompts, logs, artifacts, or test fixtures.
- Sign or checksum immutable raw data and published artifacts.
- Record actor, action, target, scope, policy decision, input/output hash, time, and outcome for auditable operations.
- Treat uploaded files, retrieved documents, tool output, and Web content as untrusted.
- Require approval for publication, destructive mutation, high-impact device action, and formal report release according to policy.

Before implementation, maintain an approved threat model, data classification, retention and deletion policy, encryption and key-management baseline, dependency and model SBOM, third-party license register, incident response owner, and initial service-level objectives. Security controls are implemented in the phase where the protected capability is built; they are not deferred to final penetration testing.

A cross-tenant data leak, unauthorized mutation, or unrepeatable audit gap is a `P0` defect.

## 16. Coding and architecture rules

- Keep all code and orchestration simple and efficient. Prefer the smallest clear design that satisfies typed contracts, security controls, and measured requirements; avoid speculative abstractions, duplicate paths, and unnecessary model, tool, storage, or network calls.
- Prefer a small modular monolith for V1. Extract a service only when isolation, scaling, deployment, or failure-domain evidence requires it.
- Keep domain logic independent of model provider, orchestration library, database driver, and client UI.
- Use ports and adapters for models, storage, queues, tools, parsers, instruments, and clients.
- Version all public contracts and persisted state.
- Use structured errors and stable error codes.
- Make side effects idempotent and retry-safe.
- Use database transactions and atomic artifact publication where needed.
- Add observability at boundaries, not ad hoc text logging.
- Keep prompts and Agent Skills in versioned files with tests and change history.
- Prefer deterministic validation, calculation, parsing, routing, and formatting before adding an LLM call.
- Do not create separate prompts or Skills for every structure type in V1. Use a generic ontology and shared workflow, then add a specialized Skill only when tools, validation, standards, or evaluation evidence materially differ.
- Pin dependencies and record an architecture decision for a major framework or provider choice.
- Generate an SBOM, review code and model licenses for commercial use, record additional license conditions, and maintain a tested replacement or rollback path for every critical third-party runtime.

## 17. Codex workspace operations

These rules apply to Codex while developing the repository. They are distinct from the product's Bash tool gateway.

- Use `rg` or `rg --files` first for repository search.
- Inspect a file before editing it.
- Use `apply_patch` for manual file changes.
- Use repository-native formatting and generation commands for mechanical output.
- Do not overwrite or remove unrelated user changes.
- Do not run destructive commands unless the user explicitly requested the exact scope and the target was verified.
- Do not use unrestricted shell write tricks when `apply_patch` is sufficient.
- Prefer non-interactive commands and bounded output.
- Quote paths safely, especially paths containing spaces or non-ASCII characters.
- Keep temporary output outside controlled source paths and remove it only after verifying the exact target.

Do not implement the product's Bash gateway by granting Codex, a container, or an agent unrestricted operating-system access.

## 18. Testing rules

- `test.md` is the authority for what to test and when.
- Run `QUICK` after each coherent local change.
- Run `TASK` before a task becomes `DONE`.
- Run every applicable `CHANGE_TRIGGERED` group.
- Run `PR`, `NIGHTLY`, `PHASE_GATE`, and `RELEASE` profiles at their defined events.
- Do not claim a test passed without command, build, environment, version, result, and evidence.
- Keep frozen evaluation data separate from training and prompt-tuning examples.
- Compare quality, token, latency, cache, and safety metrics before and after model, prompt, Skill, compression, or retrieval changes.
- A flaky test is a defect. Quarantine requires an owner, reason, expiry, and replacement coverage.
- Never waive tenant isolation, destructive-action safety, or critical evidence integrity for release.

If a required test cannot run, set it to `BLOCKED`, record the exact dependency, and do not close the affected task or gate.

A release gate must validate the exact immutable release-candidate hashes that will be published. Packaging, migration, rollback, signing, and release-smoke checks run before the final gate; publication requires the passing gate and an authorized release decision. Post-publication smoke checks do not replace the pre-publication gate.

## 19. Documentation synchronization

Update all affected documents in the same change:

- architecture, behavior, contract, budget, or acceptance change -> `development-spec.md`;
- task, dependency, milestone, status, risk, or decision change -> `plan.md`;
- test option, trigger, schedule, case, threshold, status, evidence, defect, or waiver change -> `test.md`;
- development workflow or repository rule change -> `AGENTS.md`.

After synchronization, run the `DOC` group and record its result. Documentation drift is an incomplete task, not a later cleanup item.

## 20. Definition of done

A development task is done only when:

- the planned output exists and satisfies the specification;
- required contracts and migrations are versioned;
- code, configuration, prompts, Skills, and tools are reviewed as applicable;
- the mapped tests ran at the required time and passed;
- security, tenant, audit, budget, failure, and recovery paths are covered;
- user-facing and operator-facing errors are actionable;
- `plan.md`, `test.md`, and `development-spec.md` are synchronized;
- no open `P0` or `P1` defect affects the task;
- reproducible evidence is linked from the test log.

A commercial release is done only when the gated immutable release candidate is the artifact actually published, the authorized approval record references its hashes, and post-publication smoke evidence is recorded.
