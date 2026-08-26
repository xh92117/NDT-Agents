# Inspection Report Skill V1

## Purpose

S4-03 creates and validates provider-neutral inspection-report candidates. It consumes an exact
S4-02 plan, immutable source artifacts, processing evidence, observations, calculations, figures,
findings, and conclusion data. It does not acquire or process device data, approve a report, permit
formal release, or replace independent review.

## Template and contracts

Generated `TPL-INSPECTION-REPORT-V1` contains fifteen ordered sections: identity; scope; plan
reference; source data; method, equipment, and calibration; observations; calculations and units;
figures; findings; limitations; citations; conclusion boundary; revision history; review; and
approval. The fixture generator and catalog bind its exact hash.

`InspectionReportRequest@1.0.0` binds task, request, report, revision, title, plan hash, and template.
The candidate carries:

- immutable scoped source artifacts with dataset hash, method, instrument, calibration, operator,
  and UTC acquisition time;
- scoped processing runs with exact dataset, adapter, parser, algorithm, parameter, and output
  hashes;
- scoped observations with processing, dataset, location, dimension, unit, value, and evidence hash;
- allowlisted calculations over sorted unique observation IDs;
- immutable figures bound to observations;
- findings bound to observations, calculations, applicable plan bases, limitations, and human
  boundary;
- a traced preliminary or human-confirmed formal conclusion;
- contiguous immutable revision records; and
- the exact inspection-plan result.

`InspectionReportResult@1.0.0` preserves validated content plus exact template, request, plan,
report, and result hashes. It always sets `review_required=true`, `approval_state=PENDING`, and
`formal_release_allowed=false`.

## Validation

- The plan scope, plan hash, result hash, usable status, approval-pending state, and non-formal state
  are revalidated.
- Sections must match the generated template exactly once and in order.
- Source, artifact, processing, observation, and figure scopes and references must match exactly.
- Source methods use the ontology and calibration must be valid at acquisition.
- `COUNT`, `MAXIMUM`, `MEAN`, `MINIMUM`, `RANGE`, and `SUM` are the only formulas. Inputs must exist;
  non-count inputs must share dimension and unit; outputs are recomputed with Decimal arithmetic.
- Findings must reference existing observations, calculations, and applicable plan standard bases.
- Conclusions may reference only existing findings. Formal conclusions and critical findings require
  qualified human confirmation and cannot enable release.
- Revision numbers are contiguous, end at the requested revision, and every later revision binds a
  previous report hash.

The finalizer is deterministic and makes no model, network, approval, publication, instrument, or
retry call.

## Local evidence boundary

Synthetic tests cover template order, stable hashes, plan identity, exact traceability, numeric and
unit consistency, calibration and method controls, finding/citation references, formal conclusion,
revision sequence, approval injection, and cross-scope data. Expert report scoring and TG-04 remain
blocked by R-008 and R-009.
