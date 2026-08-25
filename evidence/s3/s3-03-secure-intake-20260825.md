# S3-03 Secure Knowledge Intake Evidence

## Result

S3-03 passes its local TASK profile. The implementation extends the S3-02 root and path policy with
an application-owned binary source adapter and adds signature-first MIME inspection, immutable
source attestation, Office container safety checks, strict Chinese text decoding, and UTF-8
normalization evidence. It does not parse, OCR, index, or publish content.

## Candidate

- Branch: `codex/s3-knowledge-pipeline`.
- Parent: `c1a79337e69a25b93a831ac96ddd9123eed2fd53`.
- Configuration SHA-256: `a9d20ab1f77d21bb51fde28642ab1d3d69e64f0cc2498443f8666a4250e3e360`.
- Environment: Windows, CPython 3.12.13, uv 0.11.20.
- Run: `S3-03-TASK-20260825-01`.

## Verified behavior

- Exact tenant, project, user, roles, permission version, immutable artifact, relative path, size,
  and source SHA-256 are enforced.
- Source reads use the S3-02 traversal, metacharacter, root, symlink, and scope policy, read in
  one-megabyte chunks, and detect changes during inspection.
- PDF, PNG, JPEG, TIFF, BMP, DOCX, XLSX, PPTX, DOC, XLS, PPT, Markdown, and text are detected by
  signature class before bounded suffix disambiguation.
- Office Open XML entry paths, entry count, executable suffixes, expanded size, and compression
  ratio are checked without extracting files.
- UTF-8 with and without BOM, explicit GB18030, GBK, UTF-16LE, and UTF-16BE round-trip without
  replacement decoding. Automatic ambiguous legacy text requires manual confirmation.
- UTF-8 normalization records original and normalized hashes, source encoding, detector method,
  confidence, BOM removal, and `lossy=false`; original bytes remain unchanged.
- Executables, unsupported media, unsafe archives, MIME mismatch, invalid text, cross-scope access,
  mutable sources, over-limit input, duplicate paths, duplicate artifact IDs, and duplicate content
  have typed outcomes.

## Commands and results

```text
uv run pytest tests/knowledge/test_intake.py tests/tools/test_file_gateway.py
```

Result: 55 passed and one platform symlink case skipped.

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python tools/check_controlled_docs.py
git diff --check
```

Result: 452 passed and one known platform skip; Ruff passed; 228 files were formatted; strict mypy
passed over 112 source files; DOC 1.37 and diff checks passed. The test count is 453 collected.

## Remaining boundary

S3-04 owns registered MinerU execution and validation of Markdown plus structured output. Full-size
production probes, immutable PR CI, and the complete TG-03 frozen corpus remain pending.
