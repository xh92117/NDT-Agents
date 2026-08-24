# S0 Security and License Approval Packet

## 1. Status and boundary

| Field | Value |
|---|---|
| Packet version | `1.0.0` |
| Task | `S0-08` with required `S0-10` baseline input |
| State | `PENDING_ACCOUNTABLE_REVIEW` |
| Prepared from | `main` commit `9dca6edc1b08ab8e5b83b3bf50fb026ae27b542b` plus the review branch |
| Decisions requested | R-005 license review and R-007 baseline review |

This packet is engineering evidence, not legal advice or an approval record. It does not authorize
production deployment, customer data, licensed standards, a model provider, a parser/OCR runtime,
or a commercial release. An approval applies only to the exact hashes below. Any changed hash
requires a new packet and review.

## 2. Exact review targets

| Target | Version | SHA-256 |
|---|---|---|
| [security baseline](./security-baseline.md) machine source | `1.0.0` | `90315dd61e1c378addf6d6e20186de75ef865a8b0782df0c97fde7c20b774bed` |
| [CycloneDX SBOM](../../sbom/cyclonedx.v1.json) | `1` / CycloneDX `1.6` | `c1d7f986437cc1c30efbe857a6a7d920ef9f9f0de2edacbb263a8d4d13d44ebd` |
| [official license evidence](../../security/license-evidence.v1.json) | `1.0.0` | `640e0aa63c0893d67d50ccf1e6b42172d1aae87348133aa01cedafe83386b00e` |
| [pending license decisions](../../security/license-decisions.v1.json) | `1.1.0` | `38c1cffa96f14174fdeea30b8221639f2040c231f057ee100571f1b58c5dcb18` |
| [locked dependency graph](../../uv.lock) | lock revision `1` | `fdba41c6834c6b3cb44ac844966ee65fd5c93f9008383eac8039b63cf304a908` |

The license snapshot was captured at `2026-08-24T04:03:33Z` from the official PyPI version JSON
API. Its method follows the Python packaging `License-Expression` and `License-File` metadata
specification. The source policy is recorded in the snapshot; every response is independently
hash-bound.

## 3. R-005 review summary

The exact Python inventory contains 87 components: 13 runtime-direct, 15 development-direct, and
59 transitive. Official release metadata provides:

- 56 author-declared SPDX expressions;
- 30 legacy metadata records that still require license-text and notice review; and
- one record with no license metadata: `mypy-extensions@1.1.0`.

The SPDX declarations group as follows: 30 `MIT`, ten `Apache-2.0`, nine `BSD-3-Clause`, one each
of `BSD-2-Clause`, `MIT-0`, `MIT-CMU`, `PSF-2.0`, `MIT AND PSF-2.0`,
`Apache-2.0 OR BSD-2-Clause`, and `Apache-2.0 OR BSD-3-Clause`.

The direct dependencies requiring text review are:

- runtime: `sqlalchemy@2.0.52`;
- development: `openpyxl@3.1.5`, `pip-audit@2.10.1`, `python-docx@1.2.0`,
  `python-pptx@1.0.2`, `pyyaml@6.0.3`, and `reportlab@5.0.1`.

The remaining 23 legacy transitive records and the one missing record are listed by exact purl,
source URL, raw metadata value, classifier, and response hash in the license-evidence JSON.

R-005 cannot close until the Legal and Security Owners:

1. review the 30 legacy records and the missing record against distribution license texts;
2. confirm commercial-use compatibility for the intended distribution and service model;
3. define required copyright, attribution, notice, source-offer, patent, and modification handling;
4. approve or reject each exact component and record conditions;
5. approve a tested replacement or rollback path for critical runtime components; and
6. require a new review when a container, model, parser, OCR engine, model weight, or dependency
   version enters the candidate.

## 4. R-007 decisions still required

The baseline is internally consistent and machine-testable, but the following are organizational
decisions rather than engineering facts:

| Decision | Proposed value | Required accountable role |
|---|---|---|
| legal and operating jurisdiction | not yet recorded | Legal Owner |
| security and approval audit retention | 2,557 days | Legal and Security Owners |
| project evidence and report retention | organization-defined; no automatic deletion | Legal, Quality, and Data Governance Owners |
| operational telemetry retention | 90 days hot plus 365 days archive | Security and Operations Owners |
| rolling backup retention | 35 days | Security and Operations Owners |
| availability SLO | 99.5 percent per calendar month | Operations and Quality Owners |
| accepted-task durability SLO | 99.9 percent per calendar month | Operations and Quality Owners |
| core task RPO/RTO | 15 minutes / 4 hours | Operations Owner |
| noncritical analytics RTO | 24 hours | Operations Owner |
| reference measurement environment | not selected under S0-05 | Architecture and Operations Owners |
| baseline acceptance and residual risk | no residual critical risk accepted | Security and Quality Owners |

R-007 also requires named human actors and evidence that each actor has authority for the role.
One repository-owner statement must not be treated as four independent role decisions unless the
organization explicitly documents that authority and accepts the separation-of-duty impact.

## 5. Required decision record

Each accountable actor must return one decision with all fields below:

```text
actor_name:
actor_identity:
organization:
role: SECURITY_OWNER | LEGAL_OWNER | OPERATIONS_OWNER | QUALITY_OWNER
authority_basis:
decision: APPROVED | CHANGES_REQUESTED | REJECTED
target_versions:
target_sha256_values:
conditions_or_required_changes:
decision_time_utc:
```

Approval must reference every applicable target hash from Section 2. `CHANGES_REQUESTED` must state
the exact policy value or component treatment to change. Missing identity, authority, hash, role,
reason, or time leaves the decision invalid and the corresponding risk open.

## 6. Recommended review order

1. Legal and Security Owners resolve the 31 non-SPDX metadata records and component obligations.
2. Legal and Operations Owners decide jurisdiction and retention values.
3. Operations and Quality Owners decide SLO, RPO/RTO, and measurement-environment changes.
4. All four required roles review the resulting exact baseline hash.
5. The repository records immutable decisions and reruns `SEC-BASELINE`, `TASK`, PR CI, and the
   affected gate assessment before either risk can close.

