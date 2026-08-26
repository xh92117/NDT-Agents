# S5-06 Canonical Inspection Data Evidence

## Result

`PASS` for the local S5-06 task profile. This is not TG-05 or immutable PR evidence.

Evidence ID: `S5-06-TASK-20260825-01`

## Candidate identity

- Branch: `codex/s5-unified-tools`
- Base commit: `16c0c6871b23be6fc03416bdec38adfc85d7d1b9`
- Immutable build: none; the workspace contains preserved uncommitted S4 and S5 work
- Canonical-data source SHA-256: `27a8c911a04c47b21a38248acd82bbd1ec05ee55024825ca982fd38a87741a94`
- Dedicated-test SHA-256: `9368a06c5be35e23f667342d181bbaf59792461a24d7245d8611ac4c0635eadd`
- Contract-document SHA-256: `3c2c6cd3f9d855a567677a2329cd880495511b4cdbfff314b7e992b09ca71bad`

## Implemented boundary

- Exact scope, dataset, simulated/laboratory/production origin, six-method identity, stable
  structure/component/area/point/location topology, and registered-dimensional coordinates are
  strict and immutable.
- Source, every channel, and calibration evidence use immutable exact-scope artifacts. Reused
  artifact identities cannot change metadata; channel ranges are bounded and non-overlapping.
- V1 channels are contiguous and homogeneous for sample count, Decimal rate, UTC time origin,
  dimension, and unit, while raw sample arrays remain outside the bounded manifest.
- Acquisition settings are sorted, typed, unique, and complete for the selected S4-05 method.
  Device, adapter, calibration, operator, encoding, parser, and source-name provenance are distinct.
- Canonical UTF-8 JSON rejects BOM, malformed bytes, duplicate keys, non-finite values, unknown
  fields, and changed hashes. Chinese, whitespace, leading-dash, and newline names round-trip.
- Processing and formal-use eligibility are separate. Lossy or uncertain source normalization
  blocks processing; non-production origin, missing qualification, or inactive/out-of-interval
  calibration blocks formal use while preserving reviewable evidence.
- The S4-04 projection and comparison bind the exact shared source and parser identity without
  making a parser, provider, model, network, instrument, device, approval, publication, or retry
  action.

## Reproducible checks

Dedicated S5-06 boundary:

```text
uv run pytest tests/contracts/test_canonical_inspection_data.py -q
```

Result: 64 tests passed.

Mapped task profile:

```text
uv run pytest tests/contracts/test_canonical_inspection_data.py tests/professional/test_data_processing.py tests/professional/test_method_skills.py tests/tools/test_adapter_sdk.py tests/identity/test_identity_isolation.py tests/security/test_platform_security.py -ra
```

Result: 155 tests passed.

Complete regression:

```text
uv run pytest -ra
```

Result: 839 tests passed and one test skipped. The inherited Windows skip is
`tests/tools/test_file_gateway.py:190`; the file system cannot create the control-character
filename. Historical S3-02 protected Ubuntu evidence covers that fixture, but not this exact S5
candidate.

Static, documentation, and diff checks:

```text
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
uv run python tools/check_controlled_docs.py
git diff --check
```

Result: Ruff passed; all 160 Python files were formatted; strict mypy passed over 160 source files;
`DOC` passed at version 1.51 for four ASCII controlled documents and seven gates; the diff check
passed.

## Code graph

`code-review-graph update` and `status` completed at the exact repository root. The persisted graph
reports 145 files, 2,228 nodes, and 19,583 edges at base commit `16c0c6871b23`. The S4 and S5 source
and tests are intentionally preserved uncommitted, so the graph tool did not ingest the new
untracked canonical module or its tests. Direct static analysis, six-method tests, S4 bridge tests,
and complete execution cover this local boundary; immutable PR review must refresh graph analysis
after the files are tracked.

## Remaining limitations

- S5-07, S5-08, and TG-05 remain pending.
- No authorized calibrated real-device sample, production parser, live provider/model/instrument,
  qualified expert gold review, or production approval was available.
- There is no immutable S5 build, protected PR CI result, or exact-candidate Linux rerun.
- Existing phase-gate, rights, real-data, external-service, and accountable-approval blockers remain
  unchanged.
