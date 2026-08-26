# S1-18 Prompt Runtime Evidence

Status: PASS for the local mutable S1-18 task profile

## Scope and result

S1-18 publishes eight optimized application-owned prompts: General, Technical QA, inspection
planning, inspection reporting, data processing, method compatibility, Knowledge, and independent
Review. The strict catalog binds each prompt to an ID, semantic version, relative Markdown path,
and exact UTF-8 SHA-256. Its catalog hash is
`66b9aacef671d90eeeecca41222e996f4a1a0a7164ea06625bacaf780664f350`.

The seven configured child profiles reference prompt aliases. Startup resolves those aliases before
building child executors. The LangGraph adapter holds the resolved `ApplicationInstruction` outside
graph state and passes it to the configured delegate on Act. Configured reviewer and corrector
adapters receive the Review instruction and responsible child instruction respectively. Prompt
identity, version, and content hash bind the agent configuration and recovery identity.

The format follows DeerFlow's configurable model/subagent approach and its custom-agent system
prompt concept, while this repository keeps prompt text in separately hashed files and forbids
dynamic imports, inline credentials, and unchecked paths.

## Security and failure evidence

Tests reject duplicate YAML keys, aliases, anchors, unknown fields, duplicate identities, absolute
or escaping paths, missing files, symlink escapes where supported, BOM, invalid UTF-8, empty or
oversized content, stale hashes, unresolved profile aliases, and reviewer prompt-version mismatch.
All fail before a child, reviewer, or corrector delegate call.

Prompt text remains absent from `ChildTaskContext`, persisted LangGraph input, audit payloads,
environment secrets, and readiness responses. Static prompt evaluation covers role isolation,
minimal permission-filtered context, untrusted user/retrieved/tool content, evidence handling,
missing and conflicting inputs, uncertainty and limitations, typed output boundaries, human review,
no direct user delivery, and no unauthorized publication or physical action.

## Reproducible commands and results

Environment: local Windows, CPython 3.12.13, uv 0.11.20, branch
`codex/langgraph-child-runtime`, mutable base `966624f7b340`.

- `uv run pytest tests/professional/test_technical_qa.py tests/models/test_model_inference.py tests/orchestration/test_prompt_registry.py tests/orchestration/test_agent_runtime_config.py`: 79 passed.
- `uv run pytest tests/orchestration tests/models tests/professional tests/context tests/cache tests/runtime`: 393 passed.
- `uv run pytest`: 1086 passed and one existing Windows control-character filename case skipped.
- `uv run ruff check src tools tests`: passed.
- `uv run ruff format --check src tools tests`: passed over 199 files.
- `uv run mypy`: passed over 200 source files.
- `uv run python tools/check_controlled_docs.py`: `DOC=PASS version=1.76 files=4 gates=7 ascii=true`.
- Offline configuration load: two provider catalogs, eleven disabled model bindings, eight prompts,
  and seven child profiles resolved with prompt catalog version 1.1.0 and no provider call.
- `git diff --check`: passed; the only output was the existing Git LF-to-CRLF warning for
  `.env.example`.
- Code graph full refresh: 210 files, 3576 nodes, 32505 edges, Python/JavaScript/Rust, zero build
  errors.

## Limitations

This task connects verified prompts to injected child, reviewer, and corrector delegate boundaries.
It does not implement or authorize a live HTTP model-provider delegate, managed secret, hosted
MinerU adapter, production checkpointer, network call, publication, or physical action. Frozen
expert quality and live token/latency comparisons remain unavailable until approved providers,
real data, adjudicated gold answers, and immutable CI evidence exist. TG-01 therefore retains its
existing live-service and approval blockers.
