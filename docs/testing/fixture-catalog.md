# S0 Fixture Catalog

## Status

Task `S0-06` provides a reproducible synthetic baseline at `fixtures/v1/catalog.json`.
It contains:

- 192 parser fixtures: 24 each for text PDF, scanned PDF, DOCX, XLSX, PPTX, Markdown,
  text, and PNG scan;
- 60 simulated raw inspection records: 10 each for ultrasonic, ground-penetrating radar,
  impact echo, rebound hammer, acoustic emission, and machine vision;
- one inspection-plan template and one inspection-report template.

All included items are project-generated synthetic data, classified `INTERNAL`, marked
`SYNTHETIC_NO_PERSONAL_DATA`, and excluded from model training. The catalog stores the exact path,
media type, byte count, SHA-256 hash, rights basis, and coverage features for every item.

## Reproduction

Run:

```text
uv run python tools/generate_fixture_catalog.py
uv run pytest tests/baseline/test_fixture_catalog.py
```

Generated Office ZIP containers and PDFs use fixed metadata so repeated generation is stable.
Tests verify counts, method balance, declared format/features, file hashes, rights, de-identification,
training exclusion, and blocking gaps.

## Blocking gaps

The synthetic corpus is not a substitute for licensed standards or real device evidence.

| Gap | Required action | Effect |
|---|---|---|
| standards rights register | Legal and Knowledge Owners approve identifiers, versions, regions, allowed uses, storage, excerpts, and procurement evidence | knowledge and technical QA gates cannot use standards content |
| real device samples | Domain and Data Owners provide authorized, de-identified, calibrated samples for all six methods | domain-quality and production calibration claims cannot be made |

Until both gaps close, S0-06 and the `DATASET` phase gate remain blocked even though the synthetic
integrity checks pass.
