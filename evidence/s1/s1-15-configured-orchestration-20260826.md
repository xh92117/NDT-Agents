# S1-15 Configured Orchestration Evidence

Status: PASS for the local mutable S1-15 task profile

## Candidate and environment

- Branch: `codex/langgraph-child-runtime`
- Base commit: `966624f7b340`
- Operating system: local Windows
- Python: CPython 3.12.13
- uv: 0.11.20
- LangGraph: 1.2.11 from the S1-14 lock
- Model state: disabled reference binding; no provider or network call
- Execution state: injected test delegates, in-memory LangGraph and recovery stores

## Implemented boundary

- `ConfiguredExecutorFactory` requires an exact application-owned delegate catalog and binds each
  assignment by configured `agent_type` to one `LangGraphChildExecutor`.
- `ConfiguredOrchestrationRuntime` runs the existing Main Graph, creates minimal contexts from the
  configuration-derived Agent Registry, enforces configured total and active concurrency limits,
  and selects the existing synchronous or queued-asynchronous scheduler path.
- Each configured child context carries the exact agent configuration SHA-256 inside its integrity
  manifest. A graph-only configuration change therefore cannot resume an old context.
- `ConfiguredRecoverableExecutorBinder` recreates LangGraph executor bindings from persisted child
  contexts, propagates the existing `RecoveryControl`, and stores no Python delegate object in a
  checkpoint.
- `TaskRecoveryRuntime` accepts the optional binder while preserving explicit legacy bindings,
  output replay, side-effect reconciliation, interrupts, budgets, and typed failures.
- FastAPI startup may inject `agent_delegates`; when supplied with the strict YAML configuration it
  publishes the assembled runtime at `app.state.orchestration_runtime` without external access.
- Human-required work is not scheduled. Professional outcomes remain review required, not
  aggregation ready, and not user deliverable.

## Reproducible verification

Focused implementation and recovery tests:

```text
uv run pytest tests/orchestration/test_configured_runtime.py -q
```

Result: 10 cases passed. Coverage includes startup assembly, General synchronous execution,
professional queued execution, exact delegate catalogs, active concurrency denial, human pause,
stale context rejection, recovery control propagation, output replay, and changed-configuration
denial.

Orchestration regression:

```text
uv run pytest tests/orchestration -q
```

Result: 117 cases passed.

Complete TASK and local regression:

```text
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
uv run python tools/check_controlled_docs.py
uv run pytest -q
git diff --check
code-review-graph status --repo "D:\program flies\智能体开发\NDT Agents"
```

Results:

- Ruff passed.
- Format check passed for 194 files.
- Strict mypy passed for 194 source files.
- DOC passed at controlled-document version 1.73.
- Complete regression collected 1054 cases and completed with one existing Windows filename skip.
- Diff checks passed; the only output was the existing Git LF-to-CRLF warning for `.env.example`.
- The refreshed code graph contains 3578 nodes, 32499 edges, and 210 tracked files; post-change
  detection reported medium risk 0.65. New untracked source and test files caused graph-only test-gap
  false positives, while their direct tests passed.

## Limits

This is local mutable engineering evidence, not TG-01 or release evidence. It does not provide a
production delegate catalog, live model provider, credential, durable LangGraph checkpointer,
live PostgreSQL or object-store recovery probe, immutable protected CI result, or accountable
license and security approval. The configured scheduler deliberately returns professional results
at the existing S1-09 review boundary; automatic Review Workflow invocation and final Main
aggregation are not part of S1-15 and no child can deliver directly to a user.
