# S0 Local Engineering Baseline Evidence

## Identity and status

| Field | Value |
|---|---|
| Run ID | `S0-BASELINE-20260821-01` |
| Gate assessment | `TG-00-20260821-01` |
| Environment | local Windows workspace with a Chinese path |
| Start | `2026-08-21T22:36:26.2224923+08:00` |
| End | `2026-08-21T22:36:42.9633077+08:00` |
| Python | CPython 3.12.13 |
| uv | 0.11.20 |
| Git | 2.55.0.windows.2; repository initialized; no `HEAD` commit |
| Controlled-document version | 1.5 |
| Local result | `PASS` |
| TG-00 result | `BLOCKED` |

The local result validates the implemented engineering baseline only. It is not phase-gate evidence
because no immutable commit/build or remote CI run exists and accountable external approvals and
data are pending.

## Reproducible command sequence

```text
uv sync --locked
uv run python tools/generate_schemas.py
uv run python tools/generate_fixture_catalog.py
uv run python tools/generate_benchmarks.py
uv run python tools/generate_sbom.py
uv run python tools/check_controlled_docs.py
uv run pytest
uv run ruff check src tools tests
uv run mypy
$env:PYTHONUTF8='1'
uv run pip-audit --local --progress-spinner off
```

Every generator was run twice in the same verification process and its checked-in manifest hash
remained unchanged.

## Results

- Locked sync: 62 packages resolved and 61 installed packages checked.
- Controlled documents: `PASS`, four ASCII-only files, version 1.5, seven gates.
- Tests: 53 passed in 0.67 seconds.
- Ruff: passed.
- Strict mypy: passed for 16 source files.
- Dependency audit: no known vulnerabilities found at scan time.
- Schema contracts: 12 strict V1 boundary schemas covered by the test suite.
- Fixture catalog: 192 parser files, 60 balanced six-method raw samples, two templates.
- Benchmark catalog: 3,008 unique cases across eight data sets.
- SBOM: 61 components; every component has a pending license decision.

## Artifact hashes

| Artifact | SHA-256 |
|---|---|
| `pyproject.toml` | `35E3B94390E98601A2FC4043A0C079D6C32E2A672039F306CC54AE1052604C83` |
| `uv.lock` | `19AE8AFAC90804F3CCF35FD6E8ADD7F51998F5C24732F1BEBE892D69D5135E8A` |
| ontology | `CD14EFFB943334A07E856A16CBDCD2B98E7BBB0F3C8DBCF47A3191D9F6E9FC30` |
| data dictionary | `EE563904471060CAC2C0ABAAFA0FCCDDFF250A124A59628650ED9F90B3E480AA` |
| security baseline | `90315DD61E1C378ADDF6D6E20186DE75EF865A8B0782DF0C97FDE7C20B774BED` |
| schema manifest | `9538283608586489456E054AEE22EC008BEDA90A02B91653B9DD14E8E817A0DD` |
| fixture catalog | `DF25DB0FD930775945DF971327F0055DA657463E04B6F9EC596CC43EAAFEC43A` |
| benchmark manifest | `1C8FAD35263B3B418EA1B57FA3583216FA6EFEB03F9C5DD69DFA57FA8276C3B3` |
| CycloneDX SBOM | `1218DCD4BA4372D937380F2CD9BE2AFD731D52202E5237731770B695B629CF14` |
| license decisions | `EC78E7A7355025BF42BC8375E3DBA15BFC9472CFAF17FCCC4AACB8D1D3F45B9B` |
| CI workflow | `7ED9E76627A24DFF32FA07F87BB0DFBDD390394DBE7B198A1912BB8BAC07A35E` |

## Gate blockers

- R-001 and R-008: licensed standards and authorized, de-identified calibrated real-device data
  are missing.
- R-003: production provider, region, model snapshot, price/quota, and hardware are not selected.
- R-005: all 61 component licenses and replacement paths are pending Legal and Security review.
- R-007: Security, Legal, Operations, and Quality Owners have not approved the security/SLO
  baseline.
- R-009: technical QA, plan, and report sets lack expert gold answers and adjudication evidence.
- Git has no immutable commit, GitHub CI has not run, and the CI artifact has not been created.

No local test result is represented as satisfying these external conditions.
