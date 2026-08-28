# NDT Agents

NDT Agents is the V1 foundation for a multi-tenant civil-infrastructure non-destructive-testing
agent platform. The repository contains the S0 engineering baseline, the isolated S1 agent runtime,
the S2 context, memory, restore, cache, and governed data-lifecycle boundaries, the S3 knowledge
pipeline, and locally implemented S4 professional boundaries. Production enablement remains
blocked by the approvals and external evidence recorded in `plan.md`. S5 now includes the shared
Tool Registry, provider-neutral gateways, adapter SDK, canonical inspection data, metered model
inference, a strict opt-in DeepSeek HTTPS adapter, and deterministic six-method reference
simulators; one bounded local synthetic DeepSeek smoke has passed, while no MCP server, production
model, or instrument is approved.

## Repository layout

| Path | Purpose |
|---|---|
| `src/ndt_agents` | provider-independent product code and V1 contracts |
| `schemas/v1` | generated JSON Schemas and examples |
| `migrations` | reversible Alembic PostgreSQL and pgvector migrations |
| `domain` | machine-readable ontology and data dictionary |
| `docs` | governance, domain, security, decision, contract, and test-data records |
| `fixtures/v1` | synthetic parser, template, and raw-inspection fixtures |
| `benchmarks/v1` | synthetic evaluation JSONL sets and frozen manifest |
| `config/model-providers` | non-secret provider and model catalogs |
| `config/runtime` | non-secret model binding and agent runtime examples; local copies are ignored |
| `security` | machine-readable security and license decision baselines |
| `sbom` | generated CycloneDX inventory |
| `tools` | deterministic generators and repository checks |
| `tests` | contract and baseline verification |

The runtime API contract is documented in
[`docs/contracts/runtime-api-v1.md`](./docs/contracts/runtime-api-v1.md).
The provider-neutral multi-API catalog and binding contract is documented in
[`docs/contracts/model-api-registry-v1.md`](./docs/contracts/model-api-registry-v1.md).
The first strict hosted transport is documented in
[`docs/contracts/deepseek-provider-v1.md`](./docs/contracts/deepseek-provider-v1.md).
Storage ports and local adapter boundaries are documented in
[`docs/contracts/storage-ports-v1.md`](./docs/contracts/storage-ports-v1.md).
The isolated OIDC, RBAC, request-scope, and PostgreSQL RLS contract is documented in
[`docs/contracts/identity-isolation-v1.md`](./docs/contracts/identity-isolation-v1.md).
The deterministic rules-first routing boundary is documented in
[`docs/contracts/main-graph-v1.md`](./docs/contracts/main-graph-v1.md).
The isolated General and professional child execution boundary is documented in
[`docs/contracts/child-subgraphs-v1.md`](./docs/contracts/child-subgraphs-v1.md).
The pinned LangGraph child adapter and strict DeerFlow-inspired agent configuration are documented
in [`docs/contracts/langgraph-runtime-v1.md`](./docs/contracts/langgraph-runtime-v1.md).
The deterministic permission-filtered context-assembly boundary is documented in
[`docs/contracts/context-assembly-v1.md`](./docs/contracts/context-assembly-v1.md).
The provider-neutral C0 through C3 context-compression boundary is documented in
[`docs/contracts/context-compression-v1.md`](./docs/contracts/context-compression-v1.md).
The context-validation and raw-input fallback boundary is documented in
[`docs/contracts/context-validation-v1.md`](./docs/contracts/context-validation-v1.md).
Memory storage, distillation, and restore are documented in
[`docs/contracts/memory-store-v1.md`](./docs/contracts/memory-store-v1.md),
[`docs/contracts/memory-distillation-v1.md`](./docs/contracts/memory-distillation-v1.md), and
[`docs/contracts/memory-restore-v1.md`](./docs/contracts/memory-restore-v1.md).
Cache policy and canonical cache keys are documented in
[`docs/contracts/cache-service-v1.md`](./docs/contracts/cache-service-v1.md) and
[`docs/contracts/cache-keys-v1.md`](./docs/contracts/cache-keys-v1.md).
The governed retention, export, deletion, legal-hold, and cryptographic-erasure boundary is
documented in [`docs/contracts/data-lifecycle-v1.md`](./docs/contracts/data-lifecycle-v1.md).
The explicit-intent, authenticated UI, and approved administrator Knowledge start boundary is
documented in [`docs/contracts/knowledge-entry-v1.md`](./docs/contracts/knowledge-entry-v1.md).
The explicit synchronous and queued-asynchronous scheduling boundary is documented in
[`docs/contracts/task-scheduler-v1.md`](./docs/contracts/task-scheduler-v1.md).
The immutable checkpoint, idempotency, interrupt, and restart-recovery boundary is documented in
[`docs/contracts/recovery-runtime-v1.md`](./docs/contracts/recovery-runtime-v1.md).
The central quantitative policy, reservation, degradation, and typed-stop boundary is documented in
[`docs/contracts/budget-guard-v1.md`](./docs/contracts/budget-guard-v1.md).
The independent per-result, targeted-correction, and cross-result aggregation gate is documented in
[`docs/contracts/review-graph-v1.md`](./docs/contracts/review-graph-v1.md).
The exact-scope Technical QA candidate and citation-validation boundary is documented in
[`docs/contracts/technical-qa-v1.md`](./docs/contracts/technical-qa-v1.md).
The generated-template inspection-plan, quantity, applicable-basis, gap, review, and approval-
pending boundary is documented in
[`docs/contracts/inspection-plan-v1.md`](./docs/contracts/inspection-plan-v1.md).
The traceable report template, source/processing evidence, Decimal calculation, finding, revision,
review, and approval-pending boundary is documented in
[`docs/contracts/inspection-report-v1.md`](./docs/contracts/inspection-report-v1.md).
The source manifest, processing version/parameter, budget, quality, observation, figure, failure,
and report-evidence bridge is documented in
[`docs/contracts/data-processing-control-v1.md`](./docs/contracts/data-processing-control-v1.md).
The six-method metadata, calibration, input/output, provenance, limitation, safety, and zero-action
Skill registry is documented in
[`docs/contracts/method-skills-v1.md`](./docs/contracts/method-skills-v1.md).
The five professional per-result checklists, exact review envelopes, cross-result traceability, and
deterministic S1-09 adapter are documented in
[`docs/contracts/professional-review-v1.md`](./docs/contracts/professional-review-v1.md).
The action-specific plan, preliminary-report, and critical-finding checkpoints layered on S1-13 are
documented in
[`docs/contracts/professional-approval-v1.md`](./docs/contracts/professional-approval-v1.md).
The unified internal, Bash, Function Calling, Web Search, MCP, instrument, and AI-model registration
and authorized-exposure boundary is documented in
[`docs/contracts/tool-registry-v1.md`](./docs/contracts/tool-registry-v1.md).
The provider-neutral strict Function Calling catalog, catalog attestation, call-envelope validation,
and exact ToolResult mapping are documented in
[`docs/contracts/function-gateway-v1.md`](./docs/contracts/function-gateway-v1.md).
The policy-bound Web Search adapter, source classes, query/page budgets, exact citations, untrusted
candidate evidence, and retrieval-cache behavior are documented in
[`docs/contracts/web-search-v1.md`](./docs/contracts/web-search-v1.md).
The local/remote MCP registration, exact capability discovery, scoped credential lease, streaming,
artifact, asynchronous handle, polling, cancellation, and disconnect-recovery boundary is
documented in [`docs/contracts/mcp-gateway-v1.md`](./docs/contracts/mcp-gateway-v1.md).
The common Bash/CLI, HTTP API, SDK, DLL, file-exchange, MCP, and simulator adapter registrations,
provider wrapper, result envelope, and provenance evidence are documented in
[`docs/contracts/adapter-sdk-v1.md`](./docs/contracts/adapter-sdk-v1.md).
The strict six-method canonical source manifest, immutable channel locators, deterministic UTF-8
codec, processing/formal-use validation, and S4-04 projection are documented in
[`docs/contracts/canonical-inspection-data-v1.md`](./docs/contracts/canonical-inspection-data-v1.md).
The exact AE, GPR, IE, MV, RT, and UT local reference-simulator profiles and shared-registry
canonical-data execution boundary are documented in
[`docs/contracts/reference-adapters-v1.md`](./docs/contracts/reference-adapters-v1.md).

## Local setup

Requirements are CPython 3.12 and uv 0.11.20.

```text
uv sync --locked
uv run python tools/generate_schemas.py
uv run python tools/generate_fixture_catalog.py
uv run python tools/generate_benchmarks.py
uv run python tools/generate_sbom.py
uv run python tools/check_controlled_docs.py
uv run pytest
uv run ruff check src tools tests
uv run mypy
```

## Local runtime

`uv sync --locked` installs the `src` package and the `ndt-agents` console entry point. Validate the
default health-only composition without starting a listener:

```text
uv run ndt-agents --check
```

Start the API without storage, cache, model, or network dependencies:

```text
uv run ndt-agents
```

To assemble the disabled common hosted-model bindings and the planned bounded child profiles
without making a provider call, copy
`config/runtime/model-bindings.example.yaml` to the ignored
`config/runtime/model-bindings.local.yaml` and `config/runtime/agent-runtime.example.yaml` to the
ignored `config/runtime/agent-runtime.local.yaml`, then set these process or IDE environment values:

```text
NDT_MODEL_CONFIG=config/runtime/model-bindings.local.yaml
NDT_PROMPT_CONFIG=prompts/professional/catalog.v1.yaml
NDT_AGENT_CONFIG=config/runtime/agent-runtime.local.yaml
NDT_MODEL_ENV_FILE=.env
```

Copy `.env.example` to the ignored `.env` and place real values only after the provider variables
you intend to use. Do not commit or send that file. The application does not automatically load
`.env.example` or `.env`; `NDT_MODEL_ENV_FILE` explicitly selects the latter. Process
environment variables take precedence over the selected file. `NDT_PROMPT_CONFIG` selects the
versioned application-owned prompt catalog; its Markdown files are loaded and hash-verified before
agent assembly. Change a binding to `ENABLED` only
when its referenced secret is present; startup otherwise fails closed. This bootstrap validates and
assembles configuration but still performs zero model-network calls. The agent file may reference
only exact model bindings, prompt aliases, and application-owned tool versions; it cannot contain
inline prompts, API keys, provider class paths, dynamic imports, or caller-selected tools.

For the ignored local configuration, `personal-deepseek` can be enabled after
`DEEPSEEK_API_KEY` is present. This provisions the opt-in adapter but makes no call during startup.
The first synthetic network smoke was an explicit operator action because the catalog still marks
DeepSeek processing region, retention, training use, and commercial terms as unverified. Its single
successful call does not change production eligibility or authorize real inspection data.

For the authenticated loopback-only local Web workbench, also set the following values after the
selected local DeepSeek binding is enabled and its secret is present:

```text
NDT_GENERAL_MODEL_DELEGATE_ENABLED=true
NDT_PROFESSIONAL_MODEL_DELEGATE_ENABLED=true
NDT_LOCAL_WORKBENCH_ENABLED=true
NDT_LOCAL_WORKBENCH_STATE_PATH=C:/absolute/local/path/ndt-workbench.sqlite3
NDT_DEEPSEEK_POLICY_ACKNOWLEDGEMENT=I_ACKNOWLEDGE_UNVERIFIED_DEEPSEEK_PROVIDER_POLICY
```

Run `uv run ndt-agents --check` first. It must list `/workbench`,
`/v1/workbench/capabilities`, `/v1/workbench/tasks`, `/v1/workbench/task`, and
`/v1/workbench/events` without making a provider call. Then start `uv run ndt-agents` and open
`http://127.0.0.1:8000/local/workbench/session`. The application creates an ephemeral HttpOnly
same-origin session in memory and redirects to the workbench. Leave
`NDT_PROFESSIONAL_MODEL_DELEGATE_ENABLED` unset for the G0-only slice. When it is set, the server
also exposes P1 and routes one no-tool Technical QA model result through one independent read-only
Review Agent model call before Main aggregation. The two requests reserve at most 6,000 plus 4,000
tokens, use no retry or fallback, and keep every model-driven correction path disabled. The gateway
validates the complete synthetic canonical dataset for both calls; the Review provider prompt carries
only its hash-bound identity projection plus the exact typed review target, and the Review request
explicitly disables provider thinking so its bounded completion budget is available to the final JSON.
Both modes accept SYNTHETIC input only. A successful task submission returns the persisted
`ACCEPTED` task before local execution finishes. One bounded in-process coordinator owns execution,
and the Web event stream waits on committed event notifications instead of polling the repository.
The stream closes at its configured wait, duration, or batch bound; a nonterminal close leaves the
explicit resume control available from the last acknowledged sequence. State remains non-persistent
unless the explicit local SQLite path below is configured. Neither mode is eligible
for customer data, professional conclusions, formal use, publication, production, or commercial release. A
physical P1 smoke requires a separate explicit operator acknowledgement; startup and `--check`
make no provider call.

`NDT_LOCAL_WORKBENCH_STATE_PATH` is optional but, when present, must be an absolute path whose parent
already exists. It enables the versioned local SQLite task, event, and execution-ownership repository
so terminal tasks, events, idempotency, and accepted local work survive a process restart. An expired
claim that never advanced beyond `ACCEPTED` may be reclaimed once by the local coordinator. An
expired claim that already started is stopped as `CLIENT_EXECUTION_RECOVERY_REQUIRED`; it is never
silently rerun because the prior external outcome may be unknown. The adapter is for SYNTHETIC local
development only: it has one local coordinator and is not a distributed queue, PostgreSQL, RLS,
encryption, backup, multi-host, production, or customer-data qualification. Startup fails closed on
an unavailable, locked, corrupt, or unsupported database and does not fall back to in-memory state.

The example includes OpenAI, Anthropic, Gemini, DeepSeek, Qwen, Kimi, GLM, MiniMax, ERNIE,
Hunyuan, and Doubao bindings. All planned child profiles use the `primary` model alias by default;
change a profile's `model` value and enable the matching binding to select another provider. See
`docs/contracts/model-agent-configuration-v1.md` for the exact mapping. MinerU remains on the
pinned local CLI adapter. Its hosted API variables are reserved placeholders and do not activate a
network parser.

Supported settings are `NDT_SERVICE_NAME`, `NDT_ENVIRONMENT`, `NDT_LOG_LEVEL`, `NDT_HOST`,
`NDT_PORT`, `NDT_EXPOSE_API_DOCS`, `NDT_MODEL_CONFIG`, `NDT_PROMPT_CONFIG`,
`NDT_AGENT_CONFIG`, `NDT_MODEL_ENV_FILE`, `NDT_GENERAL_MODEL_DELEGATE_ENABLED`,
`NDT_PROFESSIONAL_MODEL_DELEGATE_ENABLED`, `NDT_LOCAL_WORKBENCH_ENABLED`,
`NDT_LOCAL_WORKBENCH_STATE_PATH`, and
`NDT_DEEPSEEK_POLICY_ACKNOWLEDGEMENT`. Unknown `NDT_` settings
fail startup. An agent
configuration requires both model and prompt configuration. API documentation is disabled by default and cannot be enabled when
`NDT_ENVIRONMENT=production`. Local environment files are forbidden in production.

Runtime probes:

- `GET /health/live` confirms that the service process is serving requests;
- `GET /health/ready` confirms that the S1-01 application scaffold initialized and, when selected,
  that non-secret model, prompt, and agent configurations assembled successfully;
- both responses use schema version `1.0.0` and return `Cache-Control: no-store`.

When an authenticated identity runtime and `KnowledgeEntryGraph` are explicitly injected,
`POST /v1/knowledge/imports` accepts a scoped import start and returns safe asynchronous dispatch
metadata. The route remains unavailable in the default standalone runtime.

On Windows paths containing non-ASCII characters, run the dependency audit in explicit UTF-8 mode:

```text
$env:PYTHONUTF8='1'
uv run pip-audit --local --progress-spinner off
```

## Generated-file policy

Generated schemas, fixtures, benchmarks, the SBOM, and license-decision inventory are checked in.
CI regenerates them and fails on drift. Do not manually edit their outputs; change the generator,
rerun it, and review the resulting hashes.

Synthetic fixtures are project-generated and excluded from model training. They are not substitutes
for licensed standards, real calibrated device data, expert gold answers, or accountable human
approval. See `plan.md` for current blockers and `test.md` for evidence.
