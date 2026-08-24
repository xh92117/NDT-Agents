# ADR-0001: Reference Runtime, Model Boundary, Deployment, and Hardware

## Status

`PROPOSED_BLOCKED_BY_S0-10_APPROVAL`

This ADR is an isolated architecture proposal. It does not select a production model provider,
region, commercial contract, or GPU purchase. Those decisions require the human approvals and
evidence listed in Section 10.

## Context

The V1 product requires deterministic routing, bounded ReAct execution, isolated professional
subagents, durable checkpoints, human interrupts, strict typed contracts, multiple model providers,
local document parsing, and a small operational footprint. The domain layer must remain independent
of the graph, model, database, queue, parser, and client implementations.

Current official documentation supports the following observations:

- [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) is a low-level runtime that
  combines deterministic and model-driven graph steps with persistence and human-in-the-loop
  control. Its subgraph documentation recommends per-invocation state for independent multi-agent
  calls and describes isolated state schemas and checkpoint behavior.
- The [OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
  exposes structured output, custom function calls, built-in tools, MCP tools, parallel calls,
  response state, and explicit output/tool-call limits. These capabilities are optional adapter
  features; the product's own contracts, budgets, authorization, and audit remain authoritative.
- Official [OpenAI data-control documentation](https://developers.openai.com/api/docs/guides/your-data)
  states that default Responses application state is retained for at least 30 days when stored,
  `store` is forced false under Zero Data Retention, and background mode temporarily persists data.
  Therefore hosted-provider retention and regional terms must be approved before confidential data
  is enabled.
- [vLLM structured outputs](https://docs.vllm.ai/en/stable/features/structured_outputs/) provide an
  OpenAI-compatible local-serving option with JSON Schema constraints, but compatibility is an
  adapter concern and requires per-model conformance tests.
- The official [MinerU quick start](https://github.com/opendatalab/MinerU/blob/master/docs/en/quick_start/index.md)
  reports CPU support for its pipeline backend, at least 16 GB RAM, 32 GB recommended, 20 GB disk,
  and higher GPU requirements for VLM backends. Its
  [current license](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md) adds commercial
  thresholds and attribution duties to Apache 2.0, so it cannot enter production without a legal
  decision and a complete transitive/model-weight inventory.

## Decision

### 1. Architecture style

Adopt a modular monolith for V1 with ports and adapters. Use one deployable application plus
separately managed stateful dependencies. Extract a service only after isolation, scaling,
deployment, or failure-domain measurements justify it.

The domain and application layers may depend on V1 contracts and abstract ports only:

- `ModelPort` and `EmbeddingPort`;
- `OrchestrationPort` and `CheckpointPort`;
- `ToolRegistryPort`;
- `RelationalStorePort`, `VectorSearchPort`, `CachePort`, `QueuePort`, and `ArtifactStorePort`;
- `ParserPort`, `OcrPort`, and `InstrumentPort`;
- `IdentityPort`, `PolicyPort`, `ApprovalPort`, `AuditPort`, and `TelemetryPort`.

Provider SDK objects and LangGraph state must not leak into domain models or public API contracts.

### 2. Graph runtime

Select LangGraph as the initial orchestration adapter, subject to exact dependency pinning and
license/security review in S1-04. Use raw, typed `StateGraph` nodes rather than a high-level
autonomous-agent abstraction for the outer workflow.

- Main Graph state contains the complete scoped task state.
- Each professional child uses a different, minimal state schema and a per-invocation checkpoint
  namespace.
- Durable PostgreSQL checkpoints are required outside local tests.
- Human approval uses explicit interrupts plus the product's immutable `ApprovalRecord`; a graph
  resume token alone is not approval evidence.
- The graph adapter may be replaced without changing the V1 domain contracts.

### 3. Model providers

Keep production selection open behind `ModelPort`.

| Candidate | Intended use | Required safeguards | Current decision |
|---|---|---|---|
| OpenAI Responses API | hosted reasoning and multimodal candidate | `store=false` by default; tenant-specific provider policy; ZDR/residency review; product-side budgets and audit; exact model snapshots | approved for adapter prototype with synthetic data only |
| vLLM OpenAI-compatible server | local or private-cloud candidate | pinned server and model weights; structured-output conformance; GPU sizing benchmark; license and provenance review | approved for interface smoke-test design only |
| deterministic fake model | CI, fault, schema, and budget tests | seeded outputs; no network | selected for S0 and default CI |

No automatic fallback may move confidential or restricted data from a local provider to a hosted
provider. Provider selection is a policy decision made before context assembly. The adapter must
record provider, endpoint class, region, model snapshot, request/response hashes, token counts,
retention mode, and failure state.

### 4. Application and data deployment

Select Linux containers and Docker Compose for the first reference deployment. Build application
images from an official Python base with pinned dependencies; use one application process per
container and scale only after measurements. Kubernetes is deferred until measured load or an
approved operational requirement justifies it.

Reference components remain:

- Python 3.12, FastAPI, Pydantic, SQLAlchemy, and Alembic;
- PostgreSQL plus pgvector and full-text search;
- Redis for bounded cache, locks, limits, and the initial queue;
- S3-compatible object storage;
- OpenTelemetry-compatible telemetry;
- LangGraph behind the orchestration port.

No separate vector database, Elasticsearch, Kafka, or general workflow platform enters V1 without
a new ADR.

### 5. Reference hardware profiles

| Profile | Minimum proposal | Purpose and limits |
|---|---|---|
| DEV-CPU-1 | x86-64, 8 logical cores, 32 GB RAM, 100 GB free SSD, Windows 11 or Linux | API/contracts, deterministic agents, unit tests, MinerU CPU-pipeline samples; not a latency benchmark |
| CI-CPU-1 | Linux x86-64, 4 vCPU, 16 GB RAM, 40 GB ephemeral SSD | deterministic tests only; no local LLM or full parser corpus |
| PARSER-GPU-1 | Linux, 16 CPU cores, 64 GB RAM, 1 TB NVMe, NVIDIA GPU with at least 16 GB VRAM | proposed MinerU/VLM evaluation margin above documented minima; must be benchmarked before purchase |
| PROD-APP-1 | Linux, 8 vCPU, 32 GB RAM, encrypted 200 GB SSD per application node | initial application/storage client sizing; external state services sized separately |
| LOCAL-LLM-1 | not selected | model, quantization, context, concurrency, latency, and license must be frozen before GPU sizing |

Local model hardware is calculated from a frozen benchmark: model weights plus KV-cache at target
context and concurrency, runtime overhead, 20 percent safety margin, target P95 time-to-first-token,
and sustained tokens per second. A generic GPU purchase before that benchmark is rejected.

### 6. Development and production separation

- S0 and CI use the deterministic fake model and synthetic or authorized fixtures.
- Hosted prototypes use synthetic data until Security and Legal approve the provider contract,
  data location, retention, sub-processors, and incident terms.
- Local-model evaluation uses a separately pinned image and model-weight manifest.
- Production secrets, keys, endpoints, and data cannot be reused in development or CI.

## Consequences

Benefits are a small V1 footprint, deterministic control around LLM calls, provider portability,
recovery and approval support, and a clear path from CPU development to separately benchmarked
parser/model hardware.

Costs are an adapter layer, explicit state translation, more contract tests, and deferred certainty
for production model cost and GPU capacity. LangGraph persistence does not replace product memory,
approval, audit, or retention controls. OpenAI-compatible APIs do not guarantee behavioral or
schema equivalence across providers.

## Provider smoke-test specification

Every provider candidate must pass the same synthetic suite before selection:

1. return a response that validates against a supplied V1 JSON Schema;
2. execute an allowlisted synthetic function with strict arguments and reject an unknown field;
3. enforce or expose output-token and timeout limits so the product guard can stop safely;
4. return typed timeout, cancellation, refusal, incomplete, and rate-limit states;
5. record exact model/version, region/endpoint class, usage, latency, and retention mode;
6. demonstrate no request storage for the configured non-storage mode;
7. produce no provider credential, chain-of-thought, or cross-tenant data in logs;
8. meet quality, latency, and cost thresholds on the frozen S0-07 benchmark.

## Rejected alternatives

- A provider SDK used directly throughout domain code: rejected because it blocks portability and
  makes authorization, retention, and testing inconsistent.
- A fully autonomous outer agent: rejected because routing, budgets, approval, and recovery must be
  deterministic and auditable.
- Kubernetes in S0: rejected because the modular monolith has no measured scale requirement.
- A local LLM GPU selected by parameter count alone: rejected because context and concurrency drive
  KV-cache and throughput requirements.
- MinerU production adoption based only on the top-level license: rejected because additional
  terms, transitive code, and model weights require review.

## Approval conditions and blockers

This ADR becomes `ACCEPTED` only when:

- Security, Legal, Operations, Quality, and Architecture Owners approve S0-10 and this exact ADR;
- provider contract, retention, data residency, sub-processor, commercial use, pricing, quota, and
  exit terms are recorded;
- the reference benchmark runs on named hardware and pins model/provider versions;
- code, model, parser, OCR, container, and model-weight SBOM obligations are approved;
- a replacement or rollback test passes for every selected adapter;
- staffing, procurement lead time, and the critical path are approved.

Until then, S0-05 remains blocked and production model/provider selection remains unresolved under
R-003, R-005, and R-007.
