# NDT Agents

NDT Agents is the V1 foundation for a multi-tenant civil-infrastructure non-destructive-testing
agent platform. The repository contains the S0 engineering baseline and the first isolated S1
runtime task: a provider-neutral FastAPI application with validated settings, JSON logs, request
correlation, typed failures, and liveness/readiness endpoints. Production enablement remains
blocked by the approvals and external evidence recorded in `plan.md`.

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
| `config/runtime` | non-secret model binding examples; local copies are ignored |
| `security` | machine-readable security and license decision baselines |
| `sbom` | generated CycloneDX inventory |
| `tools` | deterministic generators and repository checks |
| `tests` | contract and baseline verification |

The runtime API contract is documented in
[`docs/contracts/runtime-api-v1.md`](./docs/contracts/runtime-api-v1.md).
The provider-neutral multi-API catalog and binding contract is documented in
[`docs/contracts/model-api-registry-v1.md`](./docs/contracts/model-api-registry-v1.md).
Storage ports and local adapter boundaries are documented in
[`docs/contracts/storage-ports-v1.md`](./docs/contracts/storage-ports-v1.md).
The isolated OIDC, RBAC, request-scope, and PostgreSQL RLS contract is documented in
[`docs/contracts/identity-isolation-v1.md`](./docs/contracts/identity-isolation-v1.md).
The deterministic rules-first routing boundary is documented in
[`docs/contracts/main-graph-v1.md`](./docs/contracts/main-graph-v1.md).
The isolated General and professional child execution boundary is documented in
[`docs/contracts/child-subgraphs-v1.md`](./docs/contracts/child-subgraphs-v1.md).
The explicit synchronous and queued-asynchronous scheduling boundary is documented in
[`docs/contracts/task-scheduler-v1.md`](./docs/contracts/task-scheduler-v1.md).
The immutable checkpoint, idempotency, interrupt, and restart-recovery boundary is documented in
[`docs/contracts/recovery-runtime-v1.md`](./docs/contracts/recovery-runtime-v1.md).
The central quantitative policy, reservation, degradation, and typed-stop boundary is documented in
[`docs/contracts/budget-guard-v1.md`](./docs/contracts/budget-guard-v1.md).
The independent per-result, targeted-correction, and cross-result aggregation gate is documented in
[`docs/contracts/review-graph-v1.md`](./docs/contracts/review-graph-v1.md).

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

Start the API without storage, cache, model, or network dependencies:

```text
uv run python -m ndt_agents.runtime
```

To assemble the disabled DeepSeek reference binding without making a provider call, copy
`config/runtime/model-bindings.example.yaml` to the ignored
`config/runtime/model-bindings.local.yaml`, then set these process or IDE environment values:

```text
NDT_MODEL_CONFIG=config/runtime/model-bindings.local.yaml
NDT_MODEL_ENV_FILE=.env.local
```

Copy `.env.example` to the ignored `.env.local` and place the real value after
`DEEPSEEK_API_KEY=`. Do not commit or send that file. The application does not automatically load
`.env.example` or `.env.local`; `NDT_MODEL_ENV_FILE` explicitly selects the latter. Process
environment variables take precedence over the selected file. Change a binding to `ENABLED` only
when its referenced secret is present; startup otherwise fails closed. This bootstrap validates and
assembles configuration but still performs zero model-network calls.

Supported settings are `NDT_SERVICE_NAME`, `NDT_ENVIRONMENT`, `NDT_LOG_LEVEL`, `NDT_HOST`,
`NDT_PORT`, `NDT_EXPOSE_API_DOCS`, `NDT_MODEL_CONFIG`, and `NDT_MODEL_ENV_FILE`. Unknown `NDT_`
settings fail startup. API documentation is disabled by default and cannot be enabled when
`NDT_ENVIRONMENT=production`. Local environment files are forbidden in production.

Runtime probes:

- `GET /health/live` confirms that the service process is serving requests;
- `GET /health/ready` confirms that the S1-01 application scaffold initialized and, when selected,
  that non-secret model configuration assembled successfully;
- both responses use schema version `1.0.0` and return `Cache-Control: no-store`.

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
