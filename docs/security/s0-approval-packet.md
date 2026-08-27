# S0 Security and License Approval Packet

## 1. Status and boundary

| Field | Value |
|---|---|
| Packet version | `1.5.0` |
| Task | `S0-08` with required `S0-10` baseline input |
| State | `PENDING_ACCOUNTABLE_REVIEW` |
| Prepared from | `main` commit `0b3e9a88694135cbccd15324496a6c65da8bf818` plus the review branch |
| Decisions requested | R-005 license review and R-007 baseline review |

This packet is engineering evidence, not legal advice or an approval record. It does not authorize
production deployment, customer data, licensed standards, a model provider, a parser/OCR runtime,
or a commercial release. An approval applies only to the exact hashes below. Any changed hash
requires a new packet and review.

## 2. Exact review targets

| Target | Version | SHA-256 |
|---|---|---|
| [security baseline](./security-baseline.md) machine source | `1.0.0` | `90315dd61e1c378addf6d6e20186de75ef865a8b0782df0c97fde7c20b774bed` |
| [personal-project governance](../../security/personal-project-governance.v1.json) | `1.0.0` | `c649dfa59ec6cc94c2bd80ea8f9f24699a10d9af36e033a3bc87a80f9a63b083` |
| [personal-development runtime candidate](../../architecture/personal-development-runtime.v1.json) | `1.2.0` | `3259b8d6297fbea93e409ad8f20a2d401331ff8ea2dd83c8ddcafd033101da7f` |
| [DeepSeek V4 non-secret catalog](../../config/model-providers/deepseek-v4.v1.json) | `1.0.0` | `7eb570adb12b029a4995b77e39813a534a89109fe92e2f13ef09f1a344f01fef` |
| [CycloneDX SBOM](../../sbom/cyclonedx.v1.json) | `1` / CycloneDX `1.6` | `e79b28b343b348cf679446d87397f677a58fec16caf0332bbbb836c42c8532b2` |
| [official license evidence](../../security/license-evidence.v1.json) | `1.0.0` | `6cf9770ae982edda3a532b65221bfd992fa18479a85e9db1fc2c595e93605972` |
| [pending license decisions](../../security/license-decisions.v1.json) | `1.1.0` | `6c8489d752343eba10902b2680206bb0c288ccbcc406320110b0e84dd26482a7` |
| [locked dependency graph](../../uv.lock) | lock revision `1` | `7cdff2ed2771d928f218eef98fc6d75bdf3bf5460ba9c6f8c98283dbd77ebb4d` |

The license snapshot was captured at `2026-08-27T06:12:00Z` from the official PyPI version JSON
API. Its method follows the Python packaging `License-Expression` and `License-File` metadata
specification. The source policy is recorded in the snapshot; every response is independently
hash-bound.

## 3. Personal-project provisional record

The current repository owner confirmed `PERSONAL_PRE_COMMERCIAL` project stage and
`SOLE_PROJECT_OWNER` governance. `CN_MAINLAND` is recorded as a provisional jurisdiction that
must be reviewed before commercialization. The existing retention, SLO, RPO, and RTO values are
accepted only as provisional engineering targets. Project evidence and reports have no automatic
deletion before that review.

This confirmation is not independent approval. The `SECURITY_OWNER`, `LEGAL_OWNER`,
`OPERATIONS_OWNER`, and `QUALITY_OWNER` roles remain `UNASSIGNED`, so the independent approval
state is `NOT_SATISFIED`. R-005 and R-007 remain open. Production deployment, production customer
data, formal compliance claims, and commercial release remain blocked.

## 4. R-005 review summary

The exact Python inventory contains 109 components: 15 runtime-direct, 15 development-direct, and
79 transitive. Official release metadata provides:

- 67 author-declared SPDX expressions;
- 41 legacy metadata records that still require license-text and notice review; and
- one record with no license metadata: `mypy-extensions@1.1.0`.

The SPDX declarations group as follows: 34 `MIT`, 13 `BSD-3-Clause`, ten `Apache-2.0`, and one each
of `BSD-2-Clause`, `MIT-0`, `MIT-CMU`, `PSF-2.0`, `MIT AND PSF-2.0`,
`Apache-2.0 OR MIT`, `MIT OR Apache-2.0`, `Apache-2.0 OR BSD-2-Clause`,
`Apache-2.0 OR BSD-3-Clause`, and
`MPL-2.0 AND (Apache-2.0 OR MIT)`.

The direct dependencies requiring text review are:

- runtime: `pyyaml@6.0.3` and `sqlalchemy@2.0.52`;
- development: `openpyxl@3.1.5`, `pip-audit@2.10.1`, `python-docx@1.2.0`,
  `python-pptx@1.0.2`, and `reportlab@5.0.1`.

The remaining 34 legacy transitive records and the one missing record are listed by exact purl,
source URL, raw metadata value, classifier, and response hash in the license-evidence JSON.

R-005 cannot close until the Legal and Security Owners:

1. review the 41 legacy records and the missing record against distribution license texts;
2. confirm commercial-use compatibility for the intended distribution and service model;
3. define required copyright, attribution, notice, source-offer, patent, and modification handling;
4. approve or reject each exact component and record conditions;
5. approve a tested replacement or rollback path for critical runtime components; and
6. require a new review when a container, model, parser, OCR engine, model weight, or dependency
   version enters the candidate.

## 5. R-007 decisions still required

The baseline is internally consistent and machine-testable, but the following are organizational
decisions rather than engineering facts:

| Decision | Proposed value | Required accountable role |
|---|---|---|
| legal and operating jurisdiction | Mainland China, provisional until commercialization review | Legal Owner |
| security and approval audit retention | 2,557 days, accepted only as an engineering target | Legal and Security Owners |
| project evidence and report retention | no automatic deletion before commercialization review | Legal, Quality, and Data Governance Owners |
| operational telemetry retention | 90 days hot plus 365 days archive, accepted only as an engineering target | Security and Operations Owners |
| rolling backup retention | 35 days, accepted only as an engineering target | Security and Operations Owners |
| availability SLO | 99.5 percent per calendar month, accepted only as an engineering target | Operations and Quality Owners |
| accepted-task durability SLO | 99.9 percent per calendar month, accepted only as an engineering target | Operations and Quality Owners |
| core task RPO/RTO | 15 minutes / 4 hours, accepted only as an engineering target | Operations Owner |
| noncritical analytics RTO | 24 hours, accepted only as an engineering target | Operations Owner |
| reference measurement environment | `PERSONAL-DEV-1` for offline deterministic development only; production environment remains unselected | Architecture and Operations Owners |
| baseline acceptance and residual risk | no residual critical risk accepted | Security and Quality Owners |

R-007 also requires named human actors and evidence that each actor has authority for the role.
One repository-owner statement must not be treated as four independent role decisions unless the
organization explicitly documents that authority and accepts the separation-of-duty impact.

## 6. Required decision record

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

## 7. Recommended review order

1. Legal and Security Owners resolve the 31 non-SPDX metadata records and component obligations.
2. Legal and Operations Owners decide jurisdiction and retention values.
3. Operations and Quality Owners decide SLO, RPO/RTO, and measurement-environment changes.
4. All four required roles review the resulting exact baseline hash.
5. The repository records immutable decisions and reruns `SEC-BASELINE`, `TASK`, PR CI, and the
   affected gate assessment before either risk can close.
