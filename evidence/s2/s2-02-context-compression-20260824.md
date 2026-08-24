# S2-02 Context Compression Evidence

## Status

`PASS` for the isolated local S2-02 task profile. This is not TG-01 or TG-02 evidence and is not an
immutable PR build.

## Scope

- strict ordered raw-event and provider-neutral semantic-compression contracts;
- deterministic C0 through C3 pressure policy;
- zero-call C0/C1 lossless reduction and recoverable log references;
- bounded C2 older-event summaries with six recent turns retained;
- checkpoint-first bounded C3 task digests;
- exact scope, source attestation, semantic-call count, and token enforcement;
- validation-required semantic candidates pending S2-03.

## Gate boundary

This is isolated, provider-neutral development authorized while TG-01 remains blocked. S2-03 must
still validate protected fields and automatically reject or fall back from unsafe candidates. The
full retention and answer-quality benchmark, C3 median token target, TG-02, production approval,
and immutable CI evidence are not claimed.

## Candidate identity

- Branch: `codex/s2-01-task-context`.
- Build state: local working tree; no immutable commit or CI build claimed.
- Configuration SHA-256: `ccca013612e6eef612e82ca92e5d84c4508429e5f8638da3942aef0123804ca7`.
- Configuration input: ordered UTF-8 content of the five context package files and two context test
  files, with each relative path included in the digest input.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.

## Reproducible commands

```text
uv run python tools/generate_schemas.py
uv run python tools/generate_fixture_catalog.py
uv run python tools/generate_benchmarks.py
uv run python tools/generate_sbom.py
git diff --exit-code -- schemas fixtures benchmarks sbom
uv run python tools/check_controlled_docs.py
uv run pytest -o addopts='' -q tests/context/test_context_compression.py
uv run pytest -q
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
git diff --check
```

## Results

- All four controlled generators completed with zero generated-file drift.
- `DOC=PASS version=1.34 files=4 gates=7 ascii=true`.
- 22 dedicated S2-02 compression tests passed.
- 334 repository tests were collected; 333 passed and one file-gateway test skipped because a
  control-character filename is unavailable on the local Windows file system. Existing Ubuntu
  S3-02 evidence covers that platform-specific case and is not reattributed here.
- Ruff lint passed.
- Ruff format check passed over 94 files.
- Strict mypy passed over 94 source files.
- Git diff whitespace checks passed.
- The code graph incremental refresh parsed three new Python files with zero errors. Verification
  found 103 Python files, 1,447 nodes, 12,102 edges, and 259 indexed tests.

## Acceptance evidence

- Pressure boundaries select C0 below 40 percent, C1 from 40 to below 60 percent, C2 from 60
  through 80 percent, and C3 above 80 percent.
- C0 and C1 make zero semantic calls. C1 replaces only non-protected recoverable tool logs and
  binds both raw-event and immutable-artifact hashes.
- C2 keeps every protected event and the six most recent conversation turns as raw items.
- A representative C2 fixture reduces tokens by at least 50 percent without dropping those turns.
- C3 cannot run without an exact-task, exact-tenant-scope durable checkpoint.
- Semantic calls are rebuilt from raw events, limited to two per task, and must attest to the exact
  ordered source-event set.
- Cross-scope events or artifacts, reordered input, duplicate identifiers, changed content hashes,
  summary-derived input, oversized output, non-reducing output, and adapter failures are rejected.
- Every C2/C3 result is validation-required and cannot be represented as execution-ready.

## Remaining work

- S2-03 validates protected fields against raw sources and implements automatic fallback.
- Full `EVAL-COMPRESSION` retention, answer-quality, C3 median, and unsafe-candidate cases remain
  pending until S2-03.
- TG-01 remains blocked by the recorded live-service, security, and license prerequisites.
- TG-02 remains `NOT_RUN` until S2-01 through S2-09 complete.
- The protected-branch PR and immutable CI profile remain pending.
