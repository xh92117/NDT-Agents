# Civil Infrastructure NDT Agent Platform Development Plan

**Plan version:** 1.29
**Specification:** [development-spec.md](./development-spec.md)  
**Test schedule:** [test.md](./test.md)  
**Codex rules:** [AGENTS.md](./AGENTS.md)  
**Duration:** 26 weeks, provisional until S0 resourcing and critical-path approval  
**Current phase:** S1 - implementation tasks complete; TG-01 blocked  
**Overall status:** BLOCKED

## 1. Plan rules

This file is the single source of truth for development tasks, dependencies, deliverables, and status.

Allowed status values:

- `TODO`: not started;
- `IN_PROGRESS`: active work;
- `BLOCKED`: cannot continue; record cause and release condition;
- `DONE`: deliverable complete and required tests pass;
- `DEFERRED`: explicitly moved out of the current release.

Before implementation, select one task ID and verify dependencies. After implementation, run the tests mapped in [test.md](./test.md), record evidence, and mark the task `DONE` only after all required results are `PASS`.

Before a task becomes `IN_PROGRESS`, Section 14 must contain an active task record with a role owner, target date, explicit acceptance criteria, minimum test groups, and an evidence destination. A deliverable name by itself is not an acceptance criterion. Phase week ranges are planning targets, not delivery commitments, until staffing, reference hardware, procurement lead times, and the critical path are approved in S0.

## 2. Fixed architecture constraints

1. The user communicates only with the Main Agent.
2. The Main Agent selects either the General Agent or the professional subagent system.
3. Professional subagents run with explicit dependencies and isolated contexts.
4. Every complex sub-result is reviewed independently.
5. Results return to the Main Agent before the user receives a response.
6. The Main Agent does not directly run Bash, Web Search, MCP, file edits, instruments, or knowledge publishing.
7. The outer runtime is a deterministic state graph; execution agents use bounded ReAct.
8. Large files and source data move through artifact references, not prompts.
9. Knowledge parsing is MinerU-first, then MinerU OCR, then one independent OCR fallback.
10. Local file capabilities use controlled Bash commands for list, search, read, write, edit, and execute.
11. Chinese paths and text require an UTF-8 locale, encoding detection, raw-byte retention, and write-back verification.
12. Runtime self-repair may retry, restore, or replan, but cannot self-publish code, prompts, Skills, or policies.

## 3. Initial quantitative defaults

| Item | Default | Hard limit |
|---|---:|---:|
| General Agent ReAct cycles | 2 | 4 |
| Technical QA cycles | 3 | 4 |
| Plan or Report Agent cycles | 4 | 6 |
| Data Processing Agent cycles | 3 | 5 |
| Knowledge Agent cycles | 4 | 6 |
| Review Agent cycles | 1 | 2 |
| Sub-result revisions | 1 | 2 |
| Full-task replans | 0 | 1 |
| Parallel professional subagents | 3 | 4 |
| Functions exposed to one agent | 6 | 12 |
| Web queries per subtask | 2 | 4 |
| Opened Web pages per subtask | 4 | 8 |
| MCP namespaces per subagent | 1 | 2 |
| Bash commands per file | 5 | 8 |
| Files per knowledge batch | 20 | 50 |

Per-task LLM-call hard limits: G0 = 4, P1 = 10, P2 = 32, P3 = 40, K1 = 12.

## 4. Milestones

| Phase | Weeks | Goal | Status | Test gate |
|---|---|---|---|---|
| S0 | 1-2 | Requirements, models, fixtures, and CI baseline | BLOCKED | TG-00 |
| S1 | 3-6 | Lightweight agent runtime | BLOCKED | TG-01 |
| S2 | 7-9 | Context, memory, restore, and cache | TODO | TG-02 |
| S3 | 10-13 | Bash files, encoding, MinerU, and knowledge lifecycle | TODO | TG-03 |
| S4 | 14-18 | Professional Skills and review workflows | TODO | TG-04 |
| S5 | 19-22 | Tools, instruments, applications, and AI models | TODO | TG-05 |
| S6 | 23-26 | Clients, hardening, calibration, pilot, and release | TODO | TG-06 |

## 5. S0 - Requirements, models, and test baseline

| ID | Task | Dependencies | Deliverable | Status |
|---|---|---|---|---|
| S0-01 | Freeze users, roles, tenants, projects, approval, and liability boundaries | none | [role and responsibility matrix](./docs/governance/role-responsibility-matrix.md) | DONE |
| S0-02 | Define the generic civil-structure ontology | S0-01 | [ontology and machine-readable model](./docs/domain/ontology.md) | DONE |
| S0-03 | Define the inspection business data model | S0-01, S0-02 | [ER model, data dictionary, and version rules](./docs/domain/inspection-data-model.md) | DONE |
| S0-04 | Freeze TaskContext, AgentResult, ToolResult, and Artifact schemas | S0-03 | [V1 typed contracts, schemas, and examples](./docs/contracts/contracts-v1.md) | DONE |
| S0-05 | Select model providers, deployment mode, and reference hardware | S0-01, S0-10 | [proposed reference-runtime ADR](./docs/decisions/ADR-0001-reference-runtime.md) | BLOCKED |
| S0-06 | Collect standards, templates, files, and six-method source-data samples | S0-02 | [synthetic fixture catalog and rights gaps](./docs/testing/fixture-catalog.md) | BLOCKED |
| S0-07 | Build routing, QA, compression, restore, file, tool, and fault benchmarks | S0-06 | [synthetic benchmark baseline](./docs/testing/benchmark-baseline.md) | BLOCKED |
| S0-08 | Create repository layout, dependency lock, SBOM, CI, and quality gates | S0-04, S0-10 | [runnable repository and quality scaffold](./README.md) | BLOCKED |
| S0-09 | Resolve the V1.3 documentation audit and freeze an executable baseline | none | synchronized V1.4 controlled documents and DOC evidence | DONE |
| S0-10 | Define the threat model, data classification, retention, encryption, secret, dependency-license, and initial SLO baseline | S0-01 | [security, compliance, supply-chain, and SLO baseline](./docs/security/security-baseline.md) | BLOCKED |

Exit: schemas are frozen for V1, fixtures are versioned, source and dependency rights are recorded, the threat model and initial SLOs are approved, and TG-00 passes.

## 6. S1 - Lightweight agent runtime

| ID | Task | Dependencies | Deliverable | Status |
|---|---|---|---|---|
| S1-01 | Build FastAPI app, configuration, logs, and health checks | S0-08 | API service scaffold | DONE |
| S1-02 | Build PostgreSQL, pgvector, Redis, and artifact storage interfaces | S1-01 | migrations and storage services | DONE |
| S1-03 | Implement OIDC, tenant/project scope, RBAC, and RLS | S1-02, S0-10 | identity and isolation middleware | DONE |
| S1-04 | Implement Main Agent graph and rules-first router | S0-04, S1-01, S1-03 | Main Graph | DONE |
| S1-05 | Implement General Agent and isolated professional subgraphs | S1-04, S1-03 | subgraph runtime | DONE |
| S1-06 | Implement sync, async, serial, and parallel scheduling | S1-05, S1-02 | [task scheduler](./docs/contracts/task-scheduler-v1.md) | DONE |
| S1-07 | Implement checkpoints, idempotency, interrupts, and recovery | S1-06 | [recoverable runtime](./docs/contracts/recovery-runtime-v1.md) | DONE |
| S1-08 | Implement graph, LLM, tool, token, time, and concurrency guards | S1-05 | [budget guard](./docs/contracts/budget-guard-v1.md) | DONE |
| S1-09 | Implement Review Agent and review-state transitions | S1-05 | [Review Graph](./docs/contracts/review-graph-v1.md) | DONE |
| S1-10 | Implement audit events and OpenTelemetry traces | S1-01 to S1-09 | [trace and audit services](./docs/contracts/audit-tracing-v1.md) | DONE |
| S1-11 | Implement secret management, TLS, encryption at rest, key rotation, and security policy hooks | S1-02, S1-03, S1-10, S0-10 | [platform security controls](./docs/contracts/platform-security-v1.md) | DONE |
| S1-12 | Implement the core Tool Registry and versioned ToolResult validation | S0-04, S1-03, S1-08, S1-11 | [shared tool registry core](./docs/contracts/tool-registry-v1.md) | DONE |
| S1-13 | Implement generic human-approval checkpoints and immutable decision records | S1-03, S1-07, S1-10, S1-11 | [approval checkpoint service](./docs/contracts/approval-service-v1.md) | DONE |

Exit: mandatory topology is enforced, restart recovery works, hard budgets stop calls, platform security controls and the shared tool registry are active, approval checkpoints are auditable, and TG-01 passes.

## 7. S2 - Context, memory, restore, and cache

| ID | Task | Dependencies | Deliverable | Status |
|---|---|---|---|---|
| S2-01 | Implement minimal TaskContext assembly and permission filtering | S1-04, S1-03 | context assembler | TODO |
| S2-02 | Implement C0-C3 context compression | S2-01 | compression pipeline | TODO |
| S2-03 | Implement protected fields and post-compression validation | S2-02 | compression validator | TODO |
| S2-04 | Implement runtime, session, user, project, and audit memory | S1-02 | memory store | TODO |
| S2-05 | Implement distillation, candidates, deduplication, and conflicts | S2-04, S2-02 | distillation pipeline | TODO |
| S2-06 | Implement snapshots, intent restore, direct restore, and branching | S2-05, S1-07 | restore service | TODO |
| S2-07 | Implement exact, retrieval, tool, parse, and semantic caches | S1-02, S2-01 | cache service | TODO |
| S2-08 | Implement versioned cache keys and tenant isolation | S2-07, S1-03 | cache policy | TODO |
| S2-09 | Implement retention, export, deletion, legal hold, and cryptographic erasure workflows | S2-04, S1-11 | governed data-lifecycle service | TODO |

Exit: critical compression retention is 100 percent, restore is isolated, cache leaks are zero, governed data-lifecycle operations pass, and TG-02 passes.

## 8. S3 - Knowledge Agent and local files

| ID | Task | Dependencies | Deliverable | Status |
|---|---|---|---|---|
| S3-01 | Implement explicit-intent and UI entry points for Knowledge Agent | S1-04 | Knowledge Graph | TODO |
| S3-02 | Build Bash allowlist and list/search/read/write/edit/execute tools | S1-08, S1-03, S1-12 | Bash file gateway registered in the shared Tool Registry | TODO |
| S3-03 | Build MIME, hash, path, Chinese encoding, and security intake | S3-02 | file intake and UTF-8 normalization | TODO |
| S3-04 | Integrate MinerU Markdown and structured outputs | S3-03 | MinerU adapter | TODO |
| S3-05 | Implement MinerU quality gate, MinerU OCR, and independent OCR | S3-04 | parser fallback pipeline | TODO |
| S3-06 | Normalize clauses, tables, formulas, images, and metadata | S3-05 | canonical document model | TODO |
| S3-07 | Implement full-text plus vector retrieval and reranking | S3-06, S1-02 | retrieval service | TODO |
| S3-08 | Implement standard version, replacement, region, date, and rights | S3-06 | knowledge metadata | TODO |
| S3-09 | Implement incremental update, review, human approval, publish, withdraw, and rollback | S3-07, S1-09, S1-13 | knowledge release workflow | TODO |

Exit: parsing, OCR, Chinese round-trip, retrieval, permission filtering, and Bash safety meet TG-03.

## 9. S4 - Professional capabilities

| ID | Task | Dependencies | Deliverable | Status |
|---|---|---|---|---|
| S4-01 | Implement Technical QA Skill and citation validation | S3-07, S1-09 | QA Agent | TODO |
| S4-02 | Implement inspection-plan Skill, template, and completeness checks | S4-01 | Plan Agent | TODO |
| S4-03 | Implement report Skill, fields, and numeric consistency checks | S4-02 | Report Agent | TODO |
| S4-04 | Implement source-data processing control Skill | S1-05, S3-06 | Data Processing Agent | TODO |
| S4-05 | Create method-Skill skeletons for the six priority methods | S4-04 | method Skill pack | TODO |
| S4-06 | Implement per-result review and cross-result consistency checks | S4-01 to S4-05, S1-09 | review checklists | TODO |
| S4-07 | Extend the generic approval service for plans, reports, and critical findings | S4-02, S4-03, S1-13 | professional approval workflow | TODO |

Exit: QA, plan, report, and review quality meet TG-04.

## 10. S5 - Unified tools, instruments, and models

| ID | Task | Dependencies | Deliverable | Status |
|---|---|---|---|---|
| S5-01 | Extend the shared Tool Registry for Function Calling, Web Search, MCP, instruments, and AI models | S1-12, S3-02 | unified tool registry extensions | TODO |
| S5-02 | Implement Function Calling schema loading and validation | S5-01 | function gateway | TODO |
| S5-03 | Implement Web Search sources, citations, budgets, and cache | S5-01, S2-07 | Web Search tool | TODO |
| S5-04 | Implement local/remote MCP authorization and async binding | S5-01, S1-03 | MCP gateway | TODO |
| S5-05 | Define instrument, API, SDK, DLL, and Bash adapter contracts | S5-01 | adapter SDK | TODO |
| S5-06 | Define canonical inspection-data format | S0-03, S4-04 | canonical inspection data | TODO |
| S5-07 | Implement AI model registry, inference, and evidence tracking | S5-01, S5-06 | model registry | TODO |
| S5-08 | Integrate first reference adapter or simulator for each method | S5-05 to S5-07 | reference adapters | TODO |

Exit: every tool uses shared permission, budget, version, and audit controls; TG-05 passes.

## 11. S6 - Clients, hardening, calibration, and release

| ID | Task | Dependencies | Deliverable | Status |
|---|---|---|---|---|
| S6-01 | Build Web workbench and streamed task UI | S1 to S5 | Web client | TODO |
| S6-02 | Build Tauri desktop client and local tool bridge | S6-01, S5-05 | desktop client | TODO |
| S6-03 | Build responsive mobile/PWA review interface | S6-01 | mobile/PWA | TODO |
| S6-04 | Implement quotas, approved SLOs, backups, RPO/RTO, and recovery runbook | S1-02, S1-03, S0-10 | operations runbook | TODO |
| S6-05 | Run security, isolation, fault-injection, and recovery suites | S1 to S5 | security and resilience report | TODO |
| S6-06 | Run performance, concurrency, token, and cache benchmarks | S1 to S5 | performance report | TODO |
| S6-07 | Calibrate all budgets from P95/P99 measurements | S6-06 | production budget profile | TODO |
| S6-08 | Run a seven-day shadow deployment and expert pilot | S6-05 to S6-07 | pilot report | TODO |
| S6-09 | Build and sign the V1.0 release candidate and run migration, rollback, signing, and release-smoke tests | S6-08 | immutable release candidate and RELEASE evidence | TODO |
| S6-10 | Publish commercial V1.0 after TG-06 and authorized release approval | S6-09, TG-06 | published release and post-publication smoke evidence | TODO |

Exit: the immutable release candidate passes TG-06, authorized release approval is recorded, commercial V1.0 is published, post-publication smoke checks pass, and leaks and duplicate side effects remain zero.

## 12. Test-gate mapping

| Gate | Required test groups |
|---|---|
| TG-00 | DOC, SCHEMA, DATASET, SEC-BASELINE, PROVIDER-SMOKE |
| TG-01 | UNIT-CORE, INT-ORCH, SEC-TENANT, RES-CHECKPOINT, BUDGET, OBS-AUDIT, SEC-PLATFORM, UNIT-TOOLREG, INT-APPROVAL |
| TG-02 | UNIT-CONTEXT, EVAL-COMPRESSION, INT-MEMORY, SEC-CACHE, INT-DATA-LIFECYCLE |
| TG-03 | INT-MINERU, INT-OCR, INT-KNOWLEDGE, INT-BASH, EVAL-RETRIEVAL, SEC-BASH |
| TG-04 | EVAL-QA, EVAL-PLAN, EVAL-REPORT, INT-REVIEW |
| TG-05 | INT-FUNCTION, INT-WEB, INT-MCP, INT-INSTRUMENT, SEC-TOOLS |
| TG-06 | E2E, SEC-ALL, PERF, RES-ALL, EVAL-TOKEN |

## 13. Current risks and blockers

| ID | Risk | Affected tasks | Owner role | Likelihood | Impact | Mitigation and release condition | Status |
|---|---|---|---|---|---|---|---|
| R-001 | Commercial rights for standards text are not confirmed | S0-06, S3-08 | Legal and Knowledge Owner | high | high | approve the rights and procurement register | OPEN |
| R-002 | Instrument SDKs and proprietary formats are unknown | S5-05, S5-08 | Integration Owner | high | high | confirm vendor interfaces or the simulator-only scope | OPEN |
| R-003 | Production model and deployment mode are not selected | S0-05 | Architecture Owner | medium | high | use the provisional personal runtime only for offline deterministic development; evaluate the owner-offered China-region API only after non-secret provider/model, protocol, regional-processing, retention, training, and commercial metadata is reviewed and `PROVIDER-SMOKE` passes; direct OpenAI API use is blocked for the provisional current jurisdiction, and local inference is blocked until the model and benchmark size the hardware; approve a production decision before production | OPEN |
| R-004 | Formal report and accreditation boundary is not confirmed | S0-01, S4-07 | Product and Quality Owner | high | high | domain and quality owners approve the responsibility and accreditation boundary | OPEN |
| R-005 | Third-party code, model, and parser licenses may restrict commercial deployment | S0-05, S0-08, S1-11, S3-04, S5-07, TG-01 | Legal and Security Owner | medium | high | bind official release metadata to the exact SBOM and lock hash; complete license-text and notice review for legacy or missing metadata; approve or reject every component obligation and replacement path | OPEN |
| R-006 | The 26-week target has no approved staffing, procurement, or critical-path basis | all phases | Program Owner | high | high | approve staffing, hardware lead times, critical path, contingency, and revised dates | OPEN |
| R-007 | The S0 security, retention, license, and SLO baseline has not received accountable human approval | S0-05, S0-08, S1-11, TG-00, TG-01 | Security, Legal, Operations, and Quality Owners | high | high | retain the owner-recorded personal pre-commercial mode, provisional Mainland China jurisdiction, and accepted engineering targets as non-approval evidence; before commercialization, appoint accountable actors and independently review jurisdiction, retention, project-evidence lifetime, SLO, RPO/RTO, reference environment, and residual risk against the exact hash-bound packet | OPEN |
| R-008 | Licensed standards and de-identified calibrated real-device samples are not available for the frozen fixture catalog | S0-06, S0-07, TG-00, TG-03, TG-04 | Legal, Knowledge, Domain, and Data Owners | high | high | approve a standards rights register and provide authorized six-method real samples with provenance, calibration, and de-identification evidence | OPEN |
| R-009 | Technical QA, inspection-plan, and report benchmarks lack authorized expert gold answers and adjudication rubrics | S0-07, TG-00, TG-04 | Domain and Evaluation Owners | high | high | qualified experts create and independently adjudicate gold outputs against approved sources; freeze rubric and agreement evidence | OPEN |
| R-010 | S1 local scaffolds may require revision after S0 runtime, security, license, and CI approvals | S1-01 to S1-13, TG-01 | Architecture, Security, Legal, and Build Owners | medium | high | keep S1 work provider-neutral and isolated; do not enable production deployment; revalidate exact dependency, policy, and build hashes after R-003, R-005, and R-007 close | OPEN |
| R-011 | The frozen routing benchmark assigned five different routes to request text that contained no route-distinguishing task signal | S0-07, S1-04, TG-01 | Evaluation and Runtime Owners | high | high | closed by the versioned generator repair: explicit route signals and discriminative intent were added, dataset checks passed, and the router test excludes case ID, request number, split, and expected labels | CLOSED |
| R-012 | The S1-09 review manifest is checkpoint-ready, but the current recovery runtime cannot resume from inside a review/correction round | S1-09, S1-10, TG-01 | Runtime Resilience and Audit Owners | medium | high | closed by the exact-input append-only review journal, completed-call replay, terminal-manifest checkpoint, restart tests, and fault injection before review, after one call, and before Main aggregation | CLOSED |
| R-013 | The current GitHub account plan cannot enforce branch protection on the private repository | S0-08, PR governance, release evidence | Build, Security, and Program Owners | high | medium | closed after the owner explicitly made the repository public; `main` now requires a pull request, strict `quality`, administrator enforcement, linear history, and resolved conversations, and denies force pushes and deletion | CLOSED |

## 14. Active task records

Only selected or recently completed tasks appear here. Preserve completed records and evidence references.

| Task ID | Owner role | Start | Target | Acceptance criteria | Minimum tests | Evidence | Status |
|---|---|---|---|---|---|---|---|
| `S0-09` | Architecture and Documentation Owner | 2026-08-21 | 2026-08-21 | all four controlled documents are version 1.4 and ASCII-only; audited policy conflicts, dependency inversions, gate timing, budget semantics, test coverage, risk ownership, and evidence rules are resolved; local links, fences, task IDs, gate mappings, and quantitative defaults are consistent | DOC | `DOC-20260821-02` in test.md Section 11.3 | DONE |
| `S0-01` | Product and Quality Owner | 2026-08-21 | 2026-08-21 | role, scope, approval, segregation-of-duty, formal-conclusion, and liability boundaries are versioned; every privileged action has an accountable role; unresolved accreditation decisions remain explicit | DOC and role consistency | `S0-01-TASK-20260821-01` and `docs/governance/role-responsibility-matrix.md` | DONE |
| `S0-02` | Domain Architecture Owner | 2026-08-21 | 2026-08-21 | the ontology defines stable identifiers, hierarchy, core entities, six priority methods, materials, damage, observations, relationships, extensibility, and validation rules without structure-specific prompt proliferation | DOC and ontology consistency | `S0-02-TASK-20260821-01`, `docs/domain/ontology.md`, and `domain/ontology.v1.json` | DONE |
| `S0-03` | Data Architecture Owner | 2026-08-21 | 2026-08-21 | the ER model and data dictionary cover identity, task, evidence, inspection, knowledge, memory, approval, audit, and cache objects; scope keys, immutable/versioned fields, lifecycle rules, and critical traceability relationships are explicit | DOC and data-model consistency | `S0-03-TASK-20260821-01`, `docs/domain/inspection-data-model.md`, and `domain/data-dictionary.v1.json` | DONE |
| `S0-04` | Contract Owner | 2026-08-21 | 2026-08-21 | versioned strict typed contracts and JSON Schemas exist for task, agent, tool, artifact, citation, checkpoint, memory, cache, tenant scope, review, approval, and budget boundaries; valid examples pass and malicious, extra, or incompatible payloads fail | SCHEMA and contract unit tests | `S0-04-TASK-20260821-01`, `schemas/v1/manifest.json`, and `tests/contracts/test_contracts_v1.py` | DONE |
| `S0-10` | Security and Operations Owner | 2026-08-21 | 2026-08-21 | a versioned threat model covers all critical assets and trust boundaries; classification, encryption, secret, retention, incident, supply-chain, SLI/SLO, RPO/RTO, degraded-mode, ownership, implementation-task, and test mappings are explicit; unresolved legal or security decisions are not represented as approved | DOC and SEC-BASELINE | `S0-10-TASK-20260821-01`; six baseline tests passed; the personal-project record accepts provisional targets but leaves the four independent roles unassigned and R-007 open | BLOCKED |
| `S0-05` | Architecture Owner | 2026-08-24 | 2026-08-24 | the isolated ADR and machine-readable candidate bind the personal pre-commercial scope, provisional Mainland China jurisdiction, observed owner hardware, exact offline runtime route, data limits, provider feasibility, and explicit non-production restrictions; the deterministic fake provider passes strict schema, function, budget, failure, metadata, retention, and zero-network smoke checks; hosted and local providers remain unselected and no credential is requested | DOC and PROVIDER-SMOKE; QUICK and TASK | `S0-05-PERSONAL-RUNTIME-20260824-01` in test.md and [durable evidence](./evidence/s0/s0-05-personal-runtime-20260824.md); live provider, local model, production hardware, contract, region, benchmark, and S0-10 approvals remain blocked | BLOCKED |
| `S0-06` | Test Data and Knowledge Owner | 2026-08-21 | 2026-08-21 | a reproducible project-owned synthetic corpus contains 192 parser files across declared formats, 60 raw inspection samples balanced across six methods, and versioned plan/report templates; every item has a hash, rights basis, classification, de-identification state, and training exclusion; missing licensed standards and real de-identified device samples are explicit and are not substituted by synthetic data | DATASET, rights, hash, and de-identification checks | `S0-06-TASK-20260821-01`; deterministic catalog SHA-256 `DF25DB0FD930775945DF971327F0055DA657463E04B6F9EC596CC43EAAFEC43A`; R-008 blocks completeness | BLOCKED |
| `S0-07` | Evaluation Owner | 2026-08-21 | 2026-08-21 | an isolated synthetic benchmark manifest covers the planned routing, technical QA, inspection-plan, report, compression/restore, Bash/encoding, fault, and tenant-isolation counts with unique IDs, deterministic generation, rights, de-identification, frozen splits, training exclusion, expected machine-checkable outcomes, and explicit pending expert adjudication where a professional gold answer is required | DATASET count, coverage, hash, split, and leakage checks | `S0-07-TASK-20260821-01`; the original manifest hash is preserved in historical evidence; routing repair produced 3,008 unique cases, current manifest SHA-256 `BB5768976AB8D2214C2E2AA2DE9579AF3E6F46ADB023CB407E971F1DAE909908`, and routing SHA-256 `129EA5FBD73408670CD3257DB376230D16D584130A1B63E6C6CF756EEF66F453`; R-008 and R-009 still block expert quality use | BLOCKED |
| `S0-08` | Build and Supply-Chain Owner | 2026-08-24 | 2026-08-24 | the exact source candidate contains no detected credential or private-key material and no uncataloged fixture; Git attributes preserve LF text and exact binary fixtures; generated artifacts are byte-deterministic across Windows and Linux; the public GitHub repository has an immutable passing baseline and protected `main`; every locked Python component has official version-metadata evidence bound to the SBOM and lock hashes; SPDX declarations remain distinct from legacy or missing metadata; a hash-bound approval packet states all unresolved legal, security, retention, SLO, and authority decisions; a machine-readable personal-project record binds provisional jurisdiction and engineering targets without representing independent approval | DOC, SEC-BASELINE, SBOM/license evidence and scan, CI smoke, QUICK and TASK | [remote CI evidence](./evidence/s0/s0-08-remote-ci-20260824.md) and [approval-readiness evidence](./evidence/s0/s0-08-approval-readiness-20260824.md); deterministic build and branch governance pass; personal pre-commercial restrictions remain enforced; R-013 and D-002 are closed; R-005 and R-007 remain pending | BLOCKED |

The resumed S0-08 work is an isolated build-evidence continuation. It does not approve S0-10,
licenses, production dependencies, providers, data rights, or production deployment. Any remote
CI pass remains non-gating until the accountable R-005 and R-007 decisions are recorded.

The current owner confirmed a personal pre-commercial project, provisionally selected Mainland
China, and accepted the baseline retention, SLO, RPO, and RTO values only as engineering targets.
The versioned governance record leaves all four independent review roles unassigned and blocks
production, customer-data, formal-compliance, and commercial use until the required review.

| `S1-01` | Runtime Platform Owner | 2026-08-21 | 2026-08-21 | a provider-neutral FastAPI application factory loads immutable validated environment settings; emits structured redacted logs with correlation IDs; exposes versioned liveness and readiness responses; maps unhandled failures to a typed non-disclosing response; imports and starts without database, cache, object-store, model, or external-network access; exact runtime dependencies are locked and inventoried | `UNIT-CORE`, API scaffold tests, `QUICK`, `DOC`, SBOM/license checks; storage integration is scheduled with S1-02 because S1-01 defines no storage adapter | `S1-01-TASK-20260821-01` and [durable evidence](./evidence/s1/s1-01-api-scaffold-20260821.md); 39 task tests and 62 complete tests passed; Ruff, strict mypy, DOC, SBOM/license checks, and dependency audit passed | DONE |

The S1-01 dependency assumption is intentionally narrow: S0-08 local deterministic checks are
usable for isolated development, while its remote CI, immutable-build, security, and license
approvals remain blocked. S1-01 cannot enable production deployment or satisfy TG-00/TG-01 until
the upstream blockers close and the exact candidate is revalidated.

| `S1-02` | Storage Platform Owner | 2026-08-21 | 2026-08-21 | versioned PostgreSQL and pgvector schema metadata and a reversible Alembic migration exist; PostgreSQL and Redis connection adapters use bounded timeouts and typed failures; Redis keys and artifact object keys include explicit tenant and project scope; artifact writes verify SHA-256 and reject overwrite; dependency readiness is injectable without changing liveness; no service connects until explicitly started or called | `UNIT-CORE`, storage integration tests, migration compile and rollback checks, `QUICK`, `DOC`, SBOM/license checks | `S1-02-TASK-20260821-01` and [durable evidence](./evidence/s1/s1-02-storage-20260821.md); 47 task tests and 70 complete tests passed; Ruff, strict mypy, DOC, SBOM/license checks, and dependency audit passed | DONE |

The S1-02 local profile uses deterministic in-memory Redis and object-storage backends plus
PostgreSQL dialect compilation. Live PostgreSQL, pgvector, Redis, and S3-compatible integration is
required in CI or staging after approved service endpoints and credentials exist; local fakes are
not represented as live-service evidence.

| `S1-03` | Identity and Security Owner | 2026-08-21 | 2026-08-21 | OIDC JWT validation uses a pinned issuer, audience, algorithm allowlist, and preloaded JWKS without implicit discovery network access; authenticated tenant/project/user/role/permission claims are bound to an immutable request scope; RBAC denies by default and requires a versioned policy; protected API paths reject missing, invalid, expired, forged-scope, and insufficient-role requests with typed errors; cache authorization scope includes tenant, project, user, permission, and policy versions; a reversible migration creates scoped membership tables and enables and forces PostgreSQL RLS on every S1 business table; database transactions require and set local scope | `SEC-TENANT`, `SEC-CACHE` scope cases, OIDC/RBAC unit tests, RLS migration compile and rollback, `QUICK`, `DOC`, SBOM/license checks | `S1-03-TASK-20260821-01` and [durable evidence](./evidence/s1/s1-03-identity-isolation-20260821.md); 57 task tests and 80 complete tests passed; Ruff, strict mypy, DOC, SBOM/license checks, and dependency audit passed | DONE |

S1-03 proceeds as an isolated security scaffold under the unapproved S0-10 proposal. Production
OIDC discovery, identity-provider metadata, credentials, administrator mapping, and live RLS probes
remain blocked by R-007 and R-010 and must be revalidated against the approved policy.

| `S1-04` | Agent Runtime Owner | 2026-08-21 | 2026-08-21 | a deterministic Main Graph validates the typed task and explicit route signals, records `Observe -> Plan -> Act -> Verify` transitions, invokes a rules-only router before any optional classifier, emits a typed minimal dispatch plan, sends general work only to the General child path, sends the minimum declared professional set to isolated professional paths, requires review for professional results, never exposes tools to Main, and returns typed blocked/failure state when routing evidence is missing or invalid | `UNIT-CORE`, `INT-ORCH` route topology, `BUDGET` no-Main-call assertions, routing Macro-F1 on repaired frozen set, `DATASET`, `QUICK`, `DOC` | `S1-04-TASK-20260821-01` and [durable evidence](./evidence/s1/s1-04-main-graph-20260821.md); routing Macro-F1 1.00; 37 task tests and 85 complete tests passed; Ruff, strict mypy, DOC, DATASET, and dependency audit passed | DONE |

The repaired routing evaluation must continue to exclude benchmark case ID, request number, split,
and expected labels. R-008 and R-009 remain unrelated blockers for expert-quality benchmark sets.

| `S1-05` | Agent Runtime Owner | 2026-08-21 | 2026-08-21 | the General Agent and every professional assignment execute only through a registered child subgraph; each child receives an immutable minimal `ChildTaskContext` with explicit scope, permissions, versions, budget, artifact references, dependency IDs, and a unique private scratch namespace; parent-only dependency data and another child's scratch are excluded; the child state machine records `Observe -> Plan -> Act -> Verify`; executor output is strictly validated against parent task, child run, and terminal-result invariants; children expose no user-response channel; General results return to Main aggregation and every professional result is marked review-pending | `UNIT-CORE`, `INT-ORCH` General/professional isolation paths, `BUDGET` one bounded execution call, `SEC-TENANT` scope propagation, `QUICK`, `DOC` | `S1-05-TASK-20260821-01` and [durable evidence](./evidence/s1/s1-05-subgraphs-20260821.md); 49 task tests and 92 complete tests passed; Ruff, strict mypy, DOC, and dependency audit passed after one bounded TLS retry | DONE |

S1-05 executes one prepared child at a time. Multi-child ordering, concurrency, cancellation, and
asynchronous completion are intentionally deferred to S1-06 rather than hidden inside this task.

| `S1-06` | Agent Runtime Owner | 2026-08-21 | 2026-08-21 | a typed scheduler validates task, scope, assignment, dependency, cycle, and concurrency invariants before execution; synchronous work completes before return; asynchronous work returns a scoped queued handle and starts only through an explicit advance; independent read-only professional work runs in deterministic bounded waves; dependent or side-effecting work remains serial; a failed or cancelled prerequisite blocks dependents without calling them; every terminal outcome is typed and children retain private contexts | `UNIT-CORE`, `INT-ORCH` scheduler paths, `BUDGET` active/hard concurrency and no-hidden-retry assertions, `QUICK`, `DOC` | `S1-06-TASK-20260821-01` and [durable evidence](./evidence/s1/s1-06-task-scheduler-20260821.md); 61 task tests and 104 complete tests passed; Ruff, strict mypy, DOC, and dependency audit passed | DONE |

S1-06 uses a deliberately explicit in-process asynchronous queue. Durable claims, checkpoints,
idempotency, mid-execution interrupts, restart recovery, and distributed worker coordination remain
S1-07 work and are not implied by the local enqueue/advance contract.

| `S1-07` | Runtime Resilience Owner | 2026-08-21 | 2026-08-22 | a scoped idempotency claim binds one exact request to one recovery run; every state change appends a monotonic immutable hash-verified checkpoint; restore validates scope, task, graph/state versions, artifact integrity, snapshot integrity, and child context manifests; accepted assignment output is reused after process loss without another physical child call; committed side effects are reused and ambiguous effects stop for reconciliation; cooperative interrupt and explicit resume preserve the last committed state; terminal errors state the completed work and next action | `RES-CHECKPOINT`, `INT-ORCH`, `SEC-TENANT` recovery scope cases, checkpoint contract tests, failure injection before/while/after execution, `QUICK`, `DOC` | `S1-07-TASK-20260822-01` and [durable evidence](./evidence/s1/s1-07-recovery-20260822.md); 79 task tests and 114 complete tests passed; Ruff, strict mypy, DOC, migration rollback, and dependency audit passed | DONE |

S1-07 local recovery uses deterministic implementations of the versioned recovery and immutable
artifact ports. The PostgreSQL schema and forced-RLS migration exist, but the live repository
adapter, object-store recovery probe, distributed lease, and approved RPO/RTO evidence remain
required before TG-01 and are not claimed by local restart tests.

| `S1-08` | Runtime Safety Owner | 2026-08-22 | 2026-08-22 | one exact versioned policy and guard centrally enforce graph, physical LLM, physical tool, reserved/actual token, wall-time, professional-concurrency, review, and correction limits; cache and logical-action metrics remain separate; active and hard ceilings are checked before calls; actual usage and every decision are traced; 70/85/95 percent degradation rules are deterministic; identical tools and arguments cannot repeat without new evidence; scheduler and child graph integration produce typed zero-call or partial stops without exceeding a limit; restart persists and restores the same counters, reservations, events, and repetition history; repeated process loss consumes capacity and cannot reset the guard; default class policies match the specification | `BUDGET`, `RES-ALL` budget-stop cases, `INT-ORCH` guarded child path, policy consistency, `QUICK`, `DOC` | `S1-08-TASK-20260822-01` and [durable evidence](./evidence/s1/s1-08-budget-guard-20260822.md); 101 task tests and 144 complete tests passed; Ruff, changed-file format, strict mypy, DOC, and dependency audit passed | DONE |

| `S1-09` | Review Runtime Owner | 2026-08-22 | 2026-08-22 | an independent read-only reviewer receives only scope-bound result evidence, hashes, checklist, and reviewer versions; every completed professional result is reviewed before aggregation; strict decision, identity, hash, finding, and correction-count invariants are enforced; `REVISE` sends one bounded targeted repair at a time to the responsible child and re-reviews only changed output; interacting results receive cross-result review after individual passes; conflict, human escalation, timeout, malformed output, missing repair, and exhausted budgets return typed non-aggregatable results; the final manifest binds all current results and reviews; Main aggregation accepts only a verified direct General result or a passing professional review manifest | `INT-REVIEW`, `INT-ORCH`, `BUDGET` review/correction limits, `QUICK`, `DOC` | `S1-09-TASK-20260822-01` and [durable evidence](./evidence/s1/s1-09-review-graph-20260822.md); 120 task tests and 163 complete tests passed; 19 Review Graph tests, Ruff, changed-file format, strict mypy, DOC, and dependency audit passed | DONE |

| `S1-10` | Runtime Observability and Audit Owner | 2026-08-24 | 2026-08-24 | a narrow provider-neutral port uses the pinned OpenTelemetry API and SDK to create W3C-correlated spans; immutable typed audit events bind actor, scope, action, target, policy, hashes, UTC time, outcome, request ID, trace ID, and span ID; append is exact-event idempotent and per-scope sequence and hash-chain integrity are verified; cross-scope access, mutation, malformed trace context, sensitive attributes, and hash tampering are rejected; PostgreSQL metadata and a reversible migration add a forced-RLS append-only audit table; the required S1 event set can be evaluated at 100 percent completeness without storing raw prompts, credentials, or business payloads | `OBS-AUDIT`, `SEC-TENANT` audit scope, migration upgrade/rollback, `QUICK`, `DOC`, dependency/SBOM/license checks | `S1-10-TASK-20260824-01` and [durable evidence](./evidence/s1/s1-10-audit-tracing-20260824.md); 29 affected-boundary tests and 171 complete tests passed; 8 OBS-AUDIT tests, Ruff, changed-file format, strict mypy, DOC, deterministic SBOM, and dependency audit passed | DONE |

| `S1-11` | Platform Security Owner | 2026-08-24 | 2026-08-24 | strict versioned secret and key references carry environment and exact tenant/project scope without raw material; bounded identity-bound secret leases deny expiry, revocation, scope mismatch, unavailable providers, and stale versions without fallback; transport policy permits plaintext only for loopback local/CI and otherwise requires certificate-validated TLS 1.2+, PostgreSQL `verify-full`, and encrypted Redis; AES-256-GCM envelopes use unique nonces and scope-bound authenticated data; key rotation preserves authorized decrypt of predecessor data while new writes use the new key, and revocation denies stale ciphertext; every allow and denial creates a hash-only S1-10 security audit event; managed PostgreSQL and Redis settings resolve secret references transiently and direct secret settings remain local/CI-only; no production provider or policy approval is claimed while S0-10 is blocked | `SEC-PLATFORM`, `SEC-TENANT`, `OBS-AUDIT` security events, rotation/recovery tests, storage integration, `QUICK`, `DOC`, SBOM/license and dependency checks | `S1-11-TASK-20260824-01` and [durable evidence](./evidence/s1/s1-11-platform-security-20260824.md); 52 affected-boundary tests and 179 complete tests passed; 8 SEC-PLATFORM tests, Ruff, changed-file format, strict mypy, DOC, deterministic SBOM, and dependency audit passed | DONE |

| `S1-12` | Tool Runtime Owner | 2026-08-24 | 2026-08-24 | immutable application-owned definitions bind stable names and versions to strict input/output schemas, side-effect, permission, scope, budget, idempotency, timeout, retry, secret, network, audit, and test metadata; publication creates a deterministic content version and replaces a tool version only through a new snapshot; model-produced and unregistered definitions never execute; invocation validates exact task/scope and permissions before consuming one S1-08 physical-tool call, denies identical calls without new evidence, requires stable idempotency for side effects, validates V1 ToolResult identity, scope, hashes, status, and declared output before context entry, and preserves a correlated hash-only S1-10 TOOL audit event for every decision | `UNIT-TOOLREG`, `SEC-TOOLS`, `BUDGET`, `OBS-AUDIT` tool events, `QUICK`, `DOC` | `S1-12-TASK-20260824-01` and [durable evidence](./evidence/s1/s1-12-tool-registry-20260824.md); 13 dedicated registry tests and 195 complete tests passed; Ruff, changed-file format, strict mypy, DOC, deterministic SBOM, and dependency audit passed | DONE |

| `S1-13` | Approval Runtime Owner | 2026-08-24 | 2026-08-24 | one generic checkpoint contract covers knowledge, plans, reports, critical findings, high-impact instruments, destructive operations, and release publication; each paused candidate binds exact scope, task, requester, action, target identity/version/hash, policy, preview, and expiry; separation of duty, direct role sets, bounded delegation, multi-role release approval, stale-hash denial, expiry, cancellation, reject and request-change are deterministic; immutable hash-chained candidate, delegation, decision, and resume events recover across runtime instances; decision and resume IDs are exact-content idempotent while replay and conflicting content are denied; resume grants are issued only for a fully approved current candidate; every success and denial creates a correlated hash-only S1-10 APPROVAL audit event; forced-RLS append-only migration compiles and rolls back | `INT-APPROVAL`, `SEC-PLATFORM`, `RES-CHECKPOINT`, `SEC-TENANT`, migration upgrade/rollback, `OBS-AUDIT` approval events, `QUICK`, `DOC` | `S1-13-TASK-20260824-01` and [durable evidence](./evidence/s1/s1-13-approval-service-20260824.md); 19 dedicated approval tests, 63 affected-boundary tests, and 211 complete tests passed; Ruff, changed-file format, strict mypy, DOC, migration round trip, deterministic SBOM, and dependency audit passed | DONE |

| `S1-09-R012` | Runtime Resilience and Audit Owners | 2026-08-24 | 2026-08-24 | an exact-input idempotent review recovery claim binds scope, schedule, contexts, reviewer versions, and cross-review policy; append-only hash-chained checkpoints persist the prepared boundary, each verified reviewer/corrector output by exact context hash, the terminal result, and its review manifest; restart from a new runtime replays cached completed calls without another physical reviewer or corrector call and returns a committed terminal result directly; failure injection before review, after the first completed review call, and after the committed manifest but before Main aggregation preserves correct recovery; corrupt, stale-version, cross-scope, and conflicting content is denied; forced-RLS append-only migration compiles and rolls back | `RES-CHECKPOINT`, `INT-REVIEW`, `INT-ORCH`, `BUDGET`, migration upgrade/rollback, `QUICK`, `DOC` | `S1-09-R012-20260824-01` and updated [S1-09 durable evidence](./evidence/s1/s1-09-review-graph-20260822.md); 23 Review Graph tests, 103 affected tests, and 215 complete tests passed; Ruff, changed-file format, strict mypy, DOC, migration round trip, SBOM, and dependency audit passed | DONE |

## 15. Change log

| Date | Version | Change | Impact |
|---|---|---|---|
| 2026-08-21 | 1.0 | Initial 26-week execution plan | all tasks |
| 2026-08-21 | 1.1 | Replaced abstract shell actions with Bash local-file commands | S3-02, S5-05, TG-03 |
| 2026-08-21 | 1.2 | Added Chinese paths, encoding detection, and round-trip checks | S3-03, TG-03 |
| 2026-08-21 | 1.3 | Converted project documents to English-only and revised test scheduling | documentation and all gates |
| 2026-08-21 | 1.4 | Resolved the documentation audit, added executable task records, moved shared security/tool/approval foundations earlier, and separated release-candidate validation from publication | S0, S1, S2, S3, S5, S6, and all gates |
| 2026-08-21 | 1.5 | Implemented the S0 engineering baseline, contracts, domain models, synthetic fixtures, benchmark manifests, security and runtime proposals, Git/CI scaffold, exact lock, SBOM, license inventory, and reproducible local evidence; recorded accountable external blockers without self-approval | S0 and TG-00 |
| 2026-08-21 | 1.6 | Started isolated S1 implementation and defined the versioned API scaffold, configuration, logging, health, correlation, and typed-failure contract without representing blocked production dependencies as approved | S1-01 and R-010 |
| 2026-08-21 | 1.7 | Added the scoped S1 storage contract, reversible PostgreSQL/pgvector migration, lazy PostgreSQL and Redis adapters, immutable artifact service, and dependency readiness while preserving the live-service gate limitation | S1-02 and TG-01 |
| 2026-08-21 | 1.8 | Added the isolated OIDC verifier, immutable request scope, default-deny RBAC and route policy, authorization-aware cache scope, scoped database transactions, and forced-RLS migration with explicit production-validation limits | S1-03, SEC-TENANT, and SEC-CACHE |
| 2026-08-21 | 1.9 | Added the deterministic Main Graph and rules-first router; repaired the synthetic routing generator with explicit non-leaking signals and discriminative intent; closed R-011 without using case identifiers as features | S0-07, S1-04, UNIT-CORE, INT-ORCH, and BUDGET |
| 2026-08-21 | 1.10 | Added registered General and professional child definitions, minimal immutable child contexts, private scratch namespaces, strict result verification, General-to-Main aggregation eligibility, and mandatory professional review-pending state | S1-05, UNIT-CORE, INT-ORCH, BUDGET, and SEC-TENANT |
| 2026-08-21 | 1.11 | Started the explicit synchronous and queued-asynchronous scheduler contract with dependency-aware serial and budget-bounded parallel execution; restart durability remains assigned to S1-07 | S1-06, UNIT-CORE, INT-ORCH, and BUDGET |
| 2026-08-21 | 1.12 | Started immutable scoped checkpoints, exact-request idempotency, output replay protection, side-effect reconciliation, cooperative interrupts, and restart recovery | S1-07, RES-CHECKPOINT, INT-ORCH, and SEC-TENANT |
| 2026-08-22 | 1.13 | Completed the central versioned budget factory and guard for calls, tokens, time, graph steps, degradation, repetition, reviews, corrections, concurrency, and restart-safe budget telemetry | S1-08, BUDGET, RES-ALL, and INT-ORCH |
| 2026-08-22 | 1.14 | Completed the independent per-result and cross-result Review Graph, targeted correction, strict hash binding, budgeted rounds, explicit non-pass states, and Main aggregation gate | S1-09, INT-REVIEW, INT-ORCH, and BUDGET |
| 2026-08-24 | 1.15 | Added a mandatory simple-and-efficient implementation rule before starting S1-10; new abstractions, dependencies, and calls require a clear contract, security, or measured operational need | all implementation tasks |
| 2026-08-24 | 1.16 | Completed the minimal typed audit and OpenTelemetry tracing boundary with immutable scoped events, W3C correlation, hash-chain integrity, append-only forced-RLS schema, and explicit local-versus-TG-01 evidence limits | S1-10, OBS-AUDIT, SEC-TENANT, and TG-01 |
| 2026-08-24 | 1.17 | Completed isolated platform security controls for scoped secret references and leases, certificate-validated TLS policy, AES-256-GCM envelopes, restart-safe rotation and revocation behavior, managed storage credential resolution, and mandatory security audit hooks; repaired the TG-01 OBS-AUDIT mapping drift | S1-11, SEC-PLATFORM, SEC-TENANT, OBS-AUDIT, and TG-01 |
| 2026-08-24 | 1.18 | Completed the minimal shared Tool Registry core with immutable application-owned definitions, deterministic publication versions, centralized authorization and budget enforcement, strict ToolResult validation, mandatory tool audit boundaries, and typed timeout and side-effect reconciliation | S1-12, UNIT-TOOLREG, SEC-TOOLS, BUDGET, and OBS-AUDIT |
| 2026-08-24 | 1.19 | Completed one generic, scope-bound, separation-of-duty approval checkpoint with immutable hash-chained decisions, bounded delegation, exact-candidate resume grants, restart recovery, and append-only forced-RLS persistence support | S1-13, INT-APPROVAL, SEC-PLATFORM, RES-CHECKPOINT, SEC-TENANT, and OBS-AUDIT |
| 2026-08-24 | 1.20 | Closed R-012 with durable hash-chained review-call replay, final-manifest recovery, forced-RLS append-only persistence support, and fault injection before review, after one completed call, and before Main aggregation | S1-09, R-012, RES-CHECKPOINT, INT-REVIEW, INT-ORCH, and TG-01 |
| 2026-08-24 | 1.21 | Completed all S1-01 through S1-13 implementation tasks and the local TG-01 automated profile; kept the phase blocked because live approved services, immutable CI build evidence, exact-candidate revalidation, and accountable security and license decisions do not exist | S1, TG-01, R-005, R-007, and R-010 |
| 2026-08-24 | 1.22 | Resumed S0-08 to establish the first immutable GitHub commit and remote CI evidence while preserving the security, license, provider, data-rights, and production-use blockers | S0-08, TG-00, TG-01, R-005, R-007, and R-010 |
| 2026-08-24 | 1.23 | Recorded the first immutable private GitHub baseline and its failed remote CI run; added a targeted cross-platform Office ZIP metadata correction and regression coverage under D-002 | S0-08, DOC, DATASET, CI smoke, and D-002 |
| 2026-08-24 | 1.24 | Closed D-002 with canonical Office ZIP and project-owned PNG generation; remote CI passed on the exact immutable commit and uploaded hashed evidence, leaving only accountable security and license approvals blocking S0-08 | S0-08, DOC, DATASET, CI smoke, D-002, R-005, and R-007 |
| 2026-08-24 | 1.25 | Recorded that the current GitHub plan cannot enforce branch protection for the private repository; preserved private visibility and deferred the paid-plan or public-visibility decision to authorized owners | S0-08, PR governance, release evidence, and R-013 |
| 2026-08-24 | 1.26 | Recorded the owner-authorized public visibility and enforced protected `main` workflow; closed R-013 after API readback confirmed pull requests, strict `quality`, administrator enforcement, linear history, resolved conversations, and force-push and deletion denial | S0-08, PR governance, release evidence, and R-013 |
| 2026-08-24 | 1.27 | Started S0-08 approval readiness with official per-version PyPI license evidence, exact SBOM and lock binding, offline CI validation, and a human-only decision packet for R-005 and R-007 | S0-08, S0-10, SEC-BASELINE, R-005, and R-007 |
| 2026-08-24 | 1.28 | Recorded the owner-confirmed personal pre-commercial mode, provisional Mainland China jurisdiction, and accepted engineering targets without assigning independent approvers or closing the commercial, production, legal, or security blockers | S0-08, S0-10, SEC-BASELINE, R-005, and R-007 |
| 2026-08-24 | 1.29 | Froze the personal offline runtime candidate on observed owner hardware, passed a zero-network deterministic provider smoke, blocked direct OpenAI use for the provisional current jurisdiction, and queued the owner-offered China-region API for non-secret metadata review | S0-05, PROVIDER-SMOKE, R-003, R-005, R-007, and R-010 |
