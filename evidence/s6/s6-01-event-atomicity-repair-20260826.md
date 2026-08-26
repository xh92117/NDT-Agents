# S6-01 event atomicity repair evidence

- Run ID: `S6-01-REPAIR-20260826-01`
- Date: 2026-08-26
- Branch: `codex/s6-clients`
- Build state: mutable local workspace
- Defect: `DEF-CLIENT-001`

## Change

The in-memory workbench repository now loads the exact-scope task, validates the cursor or next
sequence, selects or appends events, and reads or replaces task metadata under one repository lock.
Concurrent appenders cannot both commit the same next sequence, and event batches use task metadata
from the same atomic snapshot as their selected events.

## Verification

- The new deterministic race test reproduced two successful sequence-2 commits before the repair.
- After the repair, one concurrent append commits and the other returns
  `CLIENT_EVENT_SEQUENCE_INVALID`.
- Client-focused tests: 9 passed.
- `uv run pytest`: 1003 passed, 1 skipped in 36.50 seconds.
- `uv run python -m ruff check .`: PASS.
- `uv run python -m ruff format --check .`: PASS; 378 files already formatted.
- `uv run mypy`: PASS over 186 source files.
- `uv run python tools/check_controlled_docs.py`: `DOC=PASS version=1.65 files=4 gates=7 ascii=true`.
- `git diff --check`: PASS.

## Source hashes

- `service.py`: `96af18d35571fc5b7ce3195a6a0eecaeccaab25c993122777a82f83a49fc126b`
- `test_web_workbench.py`: `74ceb063b301fd822244bd39fc54baaf4039d3ce5f405f2f59c56ac331c325f4`

## Remaining limitations

This closes the local in-memory race. Durable multi-process storage, database transaction and
isolation tests, queue fan-out, proxy streaming, load qualification, and immutable CI remain S6
release evidence requirements.
