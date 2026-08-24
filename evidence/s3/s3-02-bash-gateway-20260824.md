# S3-02 Controlled Bash File Gateway Evidence

**Run ID:** `S3-02-BASH-GATEWAY-20260824-01`

**Status:** `PASS`

**Branch:** `codex/s3-02-bash-file-gateway`

## Scope

This run covers the scoped local-file gateway registered through the shared Tool Registry. It
includes fixed read-only command templates and application-owned safe mutation wrappers. It does
not expose a shell program, general process execution, deletion, move, permission mutation,
background launch, package installation, or network access.

## Implemented boundary

- seven strict shared-registry definitions cover list, search, read, safe write, versioned edit,
  rollback, and registered read-only execution;
- exact tenant/project root, permission, immutable-zone, byte, line, timeout, and output-schema
  enforcement;
- exact executable path and SHA-256 verification before every fixed argument-array command;
- NUL-delimited listing, literal fixed-string search, and bounded raw-byte reads;
- strict UTF-8, UTF-8 BOM, GBK, GB18030, UTF-16LE, and UTF-16BE handling without replacement;
- safe write denies overwrite; edit and rollback require current hashes, preserve LF/CRLF, retain
  the prior exact bytes, and use an internal same-root atomic replace;
- traversal, absolute or drive-relative paths, wildcard and shell syntax, cross-scope access,
  immutable mutation, stale hashes, internal versions, unknown commands, and changed executables
  return typed audited denials.

## Local results

- `uv run pytest tests/tools/test_file_gateway.py`: 25 passed and one skipped in 22.21 seconds;
- the skip is the control-character filename case because this Windows file system did not create
  that name; the same test must pass on GitHub Ubuntu before S3-02 becomes DONE;
- `uv run pytest`: 297 passed and one platform skip in 27.19 seconds;
- `uv run ruff format --check src tools tests`: 87 files formatted;
- `uv run ruff check src tools tests`: passed;
- `uv run mypy`: 87 source files passed strict checks;
- `uv run python tools/check_controlled_docs.py`: `DOC=PASS version=1.32`;
- all four controlled generators reran with zero working-diff drift;
- `PYTHONUTF8=1 uv run pip-audit --local --progress-spinner off`: no known vulnerabilities.

## Remote Linux result

- PR head commit: `e0998ad475a345e77d3e9058f43b817f6c4052d5`;
- GitHub Actions run: [32699999214](https://github.com/xh92117/NDT-Agents/actions/runs/32699999214);
- environment: Ubuntu 24.04, CPython 3.12.14, uv 0.11.20;
- result: all 298 tests passed in 18.41 seconds with zero skip, including the NUL-delimited
  control-character filename denial;
- controlled generation produced zero drift; DOC 1.32, Ruff, strict mypy, dependency audit, and
  evidence upload passed;
- S3-02 acceptance is complete. TG-03 remains a separate phase gate and S5-01 remains the next
  dependent task.
