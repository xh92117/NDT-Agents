# S0-08 Approval Readiness Evidence

## Scope

- Task: S0-08
- Branch: `codex/s0-08-approval-readiness`
- Base commit: `9dca6edc1b08ab8e5b83b3bf50fb026ae27b542b`
- Risks: R-005 and R-007
- State: engineering evidence captured; accountable human decisions remain pending

## Official metadata capture

Command:

```text
uv run python tools/refresh_license_evidence.py --workers 16 --timeout-seconds 30
```

Result: `LICENSE_EVIDENCE=CAPTURED components=87 spdx=56 legacy=30 missing=1`.

The tool requested the official PyPI version JSON endpoint for every exact SBOM component. It used
at most 16 workers, a 30-second per-attempt timeout, and at most two explicit attempts. Publication
was atomic and occurred only after every endpoint returned validated name and version metadata.
The snapshot records the raw response SHA-256, source URL, dependency scope, author-declared SPDX
expression, legacy value and hash, license classifiers, SBOM hash, and lock hash. It records no
automated legal decision.

The one missing license-metadata record is `mypy-extensions@1.1.0`. Thirty records have only legacy
metadata and require license-text review. All 28 direct dependencies have either an SPDX expression
or legacy metadata.

## Exact hashes

| Artifact | SHA-256 |
|---|---|
| `security/security-baseline.v1.json` | `90315dd61e1c378addf6d6e20186de75ef865a8b0782df0c97fde7c20b774bed` |
| `sbom/cyclonedx.v1.json` | `c1d7f986437cc1c30efbe857a6a7d920ef9f9f0de2edacbb263a8d4d13d44ebd` |
| `security/license-evidence.v1.json` | `640e0aa63c0893d67d50ccf1e6b42172d1aae87348133aa01cedafe83386b00e` |
| `security/license-decisions.v1.json` | `38c1cffa96f14174fdeea30b8221639f2040c231f057ee100571f1b58c5dcb18` |
| `uv.lock` | `fdba41c6834c6b3cb44ac844966ee65fd5c93f9008383eac8039b63cf304a908` |

## Initial targeted verification

Command:

```text
uv run pytest -q tests/baseline/test_license_evidence.py tests/baseline/test_sbom.py tests/baseline/test_ci_workflow.py
```

Result before the packet-binding assertion was added: 13 tests passed. The final targeted profile
contains 20 passing tests. Coverage includes exact SBOM and lock binding, complete purl coverage,
official source URL and response hashes, evidence-state classification, legacy value hashes, direct
dependency metadata, pending-only approval state, generated decision binding, workflow upload, and
UTF-8/LF validation.

## Approval boundary

The review packet is [S0 Security and License Approval Packet](../../docs/security/s0-approval-packet.md).
R-005 remains open because 30 legacy records and one missing record require accountable legal and
security review, component decisions, notice obligations, and replacement paths. R-007 remains open
because jurisdiction, retention, project-evidence lifetime, SLO, RPO/RTO, reference environment,
actor identity, and role authority are not yet approved. No automated result in this evidence can
close either risk.

## Complete local TASK validation

Commands:

```text
uv run python tools/generate_schemas.py
uv run python tools/generate_fixture_catalog.py
uv run python tools/generate_benchmarks.py
uv run python tools/generate_sbom.py
uv run pytest -q
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
uv run python tools/check_controlled_docs.py
uv run pip-audit --local --progress-spinner off
```

Result: all four generators completed, all 226 tests passed, Ruff passed, all 76 files were already
formatted, strict mypy reported no issues in 76 source files, DOC 1.27 passed for four ASCII
controlled documents and seven gates, and the dependency audit found no known vulnerabilities.

PR CI and protected `main` CI are recorded after they run against immutable commits. Those runs
validate the evidence package but cannot replace the pending accountable decisions.
