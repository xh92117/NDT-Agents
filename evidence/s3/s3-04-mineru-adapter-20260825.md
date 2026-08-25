# S3-04 MinerU Adapter Evidence

## Result

S3-04 passes its local TASK profile. It implements a pinned, zero-shell MinerU process contract and
strictly validates the three required downstream files. The tests use a deterministic process fake;
they do not claim that a real MinerU runtime or frozen corpus ran locally.

## Candidate

- Branch: `codex/s3-knowledge-pipeline`.
- Parent: `ac66753`.
- Configuration SHA-256: `93401f4e14a69387273627784655775a7dfee1d9d2b6a85d118460b7ee28a736`.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.
- Run: `S3-04-TASK-20260825-01`.

## Verified behavior

- Only exact-scope S3-03 accepted artifacts with matching path, size, MIME, and SHA-256 can parse.
- The source is re-read and re-attested before physical parser execution.
- MinerU execution binds executable hash, parser version, config file, input root, output root,
  tenant, project, timeout, and a run-specific directory.
- Arguments pin input, output, `txt|ocr`, pipeline backend, Chinese language, formulas, and tables;
  there is no shell, API URL, arbitrary backend, or model-provided flag.
- Exactly one Markdown, `*_content_list.json`, and `*_middle.json` file is required and hashed.
- Strict UTF-8, duplicate-key denial, pinned backend/version, contiguous pages, known block types,
  page binding, coordinates, and relative asset paths are enforced.
- Markdown and plain text use a deterministic zero-call passthrough. Legacy Office requires one
  registered conversion.
- Timeout, process failure, missing output, malformed JSON, invalid page or bbox, escaped asset,
  source change, scope mismatch, and request mismatch return typed failures.

## Commands and results

```text
uv run pytest tests/knowledge/test_mineru.py
```

Result: 14 passed.

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python tools/check_controlled_docs.py
git diff --check
```

Result: 466 passed and one known platform skip; Ruff passed; 232 files were formatted; strict mypy
passed over 114 source files; DOC 1.38 and diff checks passed.

## External contract review

The adapter command and output names were checked on 2026-08-25 against the official MinerU CLI
and output-file documentation referenced by `development-spec.md`. The current CLI accepts input,
output, method, backend, language, formula, and table options. The output reference documents
Markdown, content-list JSON, and middle JSON while warning that structured formats vary by backend
and version. The repository therefore pins both rather than accepting runtime drift.

## Remaining boundary

S3-05 owns parse quality classification and the bounded MinerU OCR plus independent OCR fallback.
Real MinerU runtime, scanned files, performance, and frozen corpus thresholds remain TG-03 work.
