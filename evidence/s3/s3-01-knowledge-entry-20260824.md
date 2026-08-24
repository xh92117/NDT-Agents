# S3-01 Knowledge Agent Entry Evidence

## Result

S3-01 passes its local TASK profile. The implementation deliberately continues the existing Main
Graph, S2 context manifest, child-isolation, approval, and mandatory-review boundaries. It does not
create a parallel orchestration path and does not start parsing, OCR, indexing, publication, or
physical child execution.

This is reproducible local engineering evidence, not immutable PR CI or TG-03 gate evidence.

## Candidate

- Branch: `codex/s3-01-knowledge-entry`.
- Parent baseline: local S2 commit `5629b1276783be5359a48b8f116f6f5bbc437963`.
- Configuration SHA-256: `7f8167408ff7c74366014b6ba6098aa016c17bb46ca23516a93b98144a8c45f2`.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.
- Test run: `S3-01-TASK-20260824-01`.

The configuration digest is the SHA-256 of sorted path and file-SHA-256 rows for the S3-01 source,
runtime, route, identity, contract, and test files listed in this evidence.

## Continuation decision

Code Graph and source review showed that S3-01 changes the existing route and runtime entry
boundaries. The correct continuation is therefore:

1. use the existing rules-first `MainGraph` for the route decision;
2. require the existing S2 manifest-verified `TaskContext`;
3. use the existing child registry and minimal `ChildContextFactory` handoff;
4. require the existing professional-review route contract;
5. use the existing approval grant model for administrator jobs; and
6. reuse the completed S3-02 controlled file gateway in later S3 intake work.

A separate Knowledge orchestration stack would duplicate authorization, budget, review, and audit
paths and would violate the repository topology.

## Delivered boundary

- Strict request, response, transition, and result models for user intent, UI action, and approved
  administrator job triggers.
- A normal read-only question returns `NOT_APPLICABLE` before task lookup and performs zero Main,
  child, tool, or LLM calls.
- Exact tenant, project, user, permission version, task ID, K1 budget, immutable source membership,
  uniqueness, and 50-file hard-limit validation.
- Exact current administrator approval validation bound to action, target, task, scope, policy,
  candidate hash, and expiry.
- Exactly one asynchronous Knowledge professional assignment with mandatory review, zero Main
  tools, and zero Main LLM calls.
- Manifest-verified minimal S2 child context, private scratch namespace, intersected tool grant, and
  direct user delivery disabled.
- Default-deny authenticated `POST /v1/knowledge/imports` route returning only safe accepted
  metadata.

## Verification

The affected TASK profile used:

```text
uv run pytest tests/knowledge tests/orchestration tests/identity tests/approval tests/runtime
```

Result: 135 passed.

The dedicated S3-01 and route subset used:

```text
uv run pytest tests/knowledge/test_entry.py tests/orchestration/test_main_graph.py
```

Result: 34 passed.

The complete QUICK regression and static checks used:

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python tools/check_controlled_docs.py
git diff --check
```

Results: all 423 tests completed; 422 passed and one known Windows control-character filename test
skipped. Ruff passed, all 225 files were formatted, strict mypy passed over 110 source files, DOC
1.36 passed, and the diff check passed.

Controlled generation and dependency audit used:

```text
uv run python tools/generate_schemas.py
uv run python tools/generate_fixture_catalog.py
uv run python tools/generate_benchmarks.py
uv run python tools/generate_sbom.py
uv run pip-audit --local --progress-spinner off
```

Result: repository status did not change across the four generators, and no known dependency
vulnerabilities were found. The audit ran with an explicit UTF-8 process environment because the
repository path contains non-ASCII characters.

## Code Graph evidence

The graph was rebuilt after exposing the new untracked source paths to Git intent-to-add, then the
index-only state was restored. Verification reported:

- 130 Python files;
- 1,799 nodes;
- 15,172 edges;
- zero parse errors;
- built and verified on branch `codex/s3-01-knowledge-entry` at parent baseline `5629b12`;
- the new `KnowledgeEntryGraph`, UI handler, route models, and tests were indexed.

Change analysis rated the boundary high impact at 0.85 because the route enum and rules-first
router participate in all Main Graph topologies. The graph associated 43 tests with the Knowledge
entry file and 26 tests with the runtime entry file. Direct source verification and the test runs
above cover the new single-professional asynchronous route, invalid inputs, exact approval,
scope, immutable artifacts, K1 limits, minimal child isolation, UI authorization, and zero-call
behavior.

## Configuration files

- `src/ndt_agents/knowledge/__init__.py`
- `src/ndt_agents/knowledge/entry.py`
- `src/ndt_agents/knowledge/models.py`
- `src/ndt_agents/runtime/app.py`
- `src/ndt_agents/identity/rbac.py`
- `src/ndt_agents/orchestration/models.py`
- `src/ndt_agents/orchestration/routing.py`
- `tests/knowledge/test_entry.py`
- `tests/orchestration/test_main_graph.py`
- `docs/contracts/knowledge-entry-v1.md`
- `docs/contracts/main-graph-v1.md`
- `docs/contracts/child-subgraphs-v1.md`
- `docs/contracts/runtime-api-v1.md`
- `docs/contracts/identity-isolation-v1.md`

## Remaining boundaries

- S3-03 owns MIME identification, hashing, path safety, Chinese encoding detection, and normalized
  intake, continuing through the S3-02 controlled file gateway.
- S3-04 through S3-09 own MinerU, OCR fallback, normalization, retrieval, metadata lifecycle,
  independent review, human approval, publication, withdrawal, and rollback.
- TG-03 remains `NOT_RUN` until S3-01 through S3-09 complete.
- TG-02 remains blocked on immutable CI, approved live services, full frozen evaluation, lifecycle
  integration, and accountable approvals.
