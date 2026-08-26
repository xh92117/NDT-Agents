# S5-05 Registration Hash Repair Evidence

## Scope

- Task: `S5-05-CI-REPAIR`
- Branch: `codex/s6-clients`
- Pull request: `https://github.com/xh92117/NDT-Agents/pull/8`
- Passing code run before reproduction: `https://github.com/xh92117/NDT-Agents/actions/runs/32919640865`
- Reproducing run: `https://github.com/xh92117/NDT-Agents/actions/runs/32919785241`
- Local environment: Windows, CPython 3.12.13, uv 0.11.20

## Defect and cause

Two Ubuntu PR runs used identical Adapter SDK and reference-adapter source. The first passed all
1020 tests. The second failed 42 S5-08 tests because an `AdapterRegistration` draft hash did not
match the hash recomputed after Pydantic validation.

The registration contains three `frozenset` fields: permissions, secret purposes, and declared
errors. `model_dump(mode="json")` represents those sets as arrays in process-dependent iteration
order. JSON object-key sorting does not sort array elements, so an equivalent registration could
receive a different hash after reconstruction or in another process.

## Repair

`adapter_registration_sha256` now passes its payload through one canonical set normalizer. The
three set-valued fields become sorted JSON arrays before hashing. All other array order remains
semantic and unchanged. A dedicated test permutes each set array, verifies identical hashes, and
verifies that adding one declared error changes the hash.

## Local validation

- `uv run pytest tests/tools/test_adapter_sdk.py tests/tools/test_reference_adapters.py`: 92 passed.
- `uv run pytest`: 1020 passed, 1 skipped in 70.07 seconds.
- `uv run ruff check src tools tests`: passed.
- `uv run ruff format --check src tools tests`: 187 files already formatted.
- `uv run mypy`: passed for 187 source files.
- `uv run python tools/check_controlled_docs.py`: `DOC=PASS version=1.68 files=4 gates=7 ascii=true`.
- `git diff --check`: passed.

## Remaining qualification

The local result is not sufficient to close a Linux process-randomization defect. The task remains
in progress until protected Ubuntu quality passes the immutable repaired commit with the full S5-08
suite and zero skipped tests.
