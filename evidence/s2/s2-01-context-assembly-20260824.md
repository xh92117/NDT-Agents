# S2-01 Context Assembly Evidence

## Status

`PASS` for the isolated local S2-01 task profile. This is not TG-01 or TG-02 evidence and is not an
immutable PR build.

## Scope

- deterministic minimal `TaskContext` assembly;
- tenant, project, user-visibility, permission-version, role, and permission filtering;
- relevance selection and lossless deduplication with preserved provenance;
- source, trust, classification, version, protected-field, and size labeling;
- default-deny artifact and tool selection;
- stable context manifests and typed failures.

## Gate boundary

This is isolated, provider-neutral development authorized while TG-01 remains blocked. It does
not approve production identity, storage, secret, key, TLS, telemetry, security, or license
decisions and cannot satisfy TG-01 or TG-02 by itself.

## Candidate identity

- Branch: `codex/s2-01-task-context`.
- Build state: local working tree; no immutable commit or CI build claimed.
- Configuration SHA-256: `aef038c1d1c7e4465874a6cc9b3dc4b306027032b66e49b7ba5bd222e54918d2`.
- Configuration input: sorted path and SHA-256 rows for the three context package files, two
  modified child-context files, the dedicated test file, and the two affected contract documents.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.

## Reproducible commands

```text
uv run python tools/generate_schemas.py
uv run python tools/generate_fixture_catalog.py
uv run python tools/generate_benchmarks.py
uv run python tools/generate_sbom.py
uv run python tools/check_controlled_docs.py
uv run pytest -o addopts='' -q tests/context/test_context_assembly.py
uv run pytest -o addopts='' -q
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
git diff --check
```

## Results

- All four controlled generators completed with zero resulting generated-file drift.
- `DOC=PASS version=1.33 files=4 gates=7 ascii=true`.
- 14 dedicated S2-01 tests passed.
- 311 complete repository tests passed; one file-gateway test skipped because control-character
  filenames are unavailable on the local Windows file system. The existing Ubuntu S3-02 evidence
  already covers that platform-specific case; it is not rerun or reattributed here.
- Ruff lint passed.
- Ruff format check passed over 91 files.
- Strict mypy passed over 91 files.
- Git diff whitespace checks passed.
- The code graph was fully rebuilt after temporarily marking the four new Python files as
  intent-to-add and then restoring the clean index. Verification found 100 Python files, 1,383
  nodes, 11,565 edges, 242 tests, and the indexed `TaskContextAssembler` class with zero build
  errors.

## Acceptance evidence

- Unauthorized tenant, project, user-visible, stale-permission, role, permission,
  classification, artifact, and tool candidates do not enter the context.
- Relevance and byte limits are deterministic; candidate bytes are bounded before selection.
- Deduplication preserves every authorized source label, trust level, source version, and hash.
- Protected content cannot be silently dropped and returns a typed actionable overflow.
- Identical authorized input produces an identical `TaskContext` manifest.
- Authorization state changes invalidate the manifest even when selected content stays equal.
- General children receive the complete verified selected bundle. Professional children receive
  only explicitly named selected content hashes.
- Parent-manifest tampering, selected-content tampering, and unknown child hashes fail before
  execution.

## Remaining work

- S2-02 implements C1 through C3 compression and quantitative compression evaluation.
- S2-03 implements field-level protected-field validation and automatic fallback.
- TG-01 remains blocked by the recorded live-service, security, and license prerequisites.
- TG-02 remains `NOT_RUN` until S2-01 through S2-09 complete.
- The protected-branch PR and immutable CI profile remain pending.
