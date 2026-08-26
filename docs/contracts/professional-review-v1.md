# Professional Review V1

## Purpose

S4-06 supplies domain-specific deterministic checklists to the existing S1-09 Review Graph. It
does not replace that graph's scheduling, independent reviewer context, correction budget,
cross-result ordering, recovery journal, or Main aggregation gate.

## Registered checklists

`ProfessionalChecklistDefinition@1.0.0` is versioned and canonically hash-bound. The read-only
registry contains one checklist for each of Technical QA, inspection plan, data processing, method
validation, and inspection report. Checks cover exact scope and schema, stable hashes, status,
unresolved issues, evidence and citation traceability, units and calculations, review/approval and
human boundaries, and prohibited side-effect counters as applicable.

## Result envelope and per-result review

`ProfessionalResultEnvelope@1.0.0` binds one typed result payload and its canonical hash to exact
tenant/project/user/permission scope, parent task, child run, and result kind. Review rehydrates the
declared strict type so every result's own hash validators run again. It rejects a changed payload,
wrong type, cross-scope/task/run identity, failed status, unresolved issue, missing QA citation,
review or approval bypass, formal release, unsafe human boundary, or prohibited external action.

Decisions map to the existing public `ReviewDecision`: clean output is `PASS`; a bounded defect is
`REVISE`; failed or hash-invalid output is `FAILED`; and a critical/formal or explicit
human-required boundary is `HUMAN_REQUIRED`. No non-pass assessment is aggregation-ready.

## Cross-result review

Cross review starts only after every supplied interacting result independently passes. It verifies:

- QA result and exact claim/citation chunk to plan standard basis;
- plan hash to report plan identity;
- processing source, run, adapter/parser/algorithm/parameter/output identity and every observation
  against report evidence;
- method code plus exact request/candidate hashes against processing evidence;
- reviewed method presence in report source evidence.

An exact mismatch returns `CONFLICT` with typed evidence and blocks aggregation. S1-09 remains
responsible for ensuring that every scheduled result is present, every per-result review passes,
cross review receives the complete interacting target set, and only the Main Agent can aggregate.

## Assessment and adapter

`ProfessionalReviewAssessment@1.0.0` binds review kind, exact scope/task, result kinds, sorted target
hashes, checklist hashes, decision, findings, aggregation state, literal zero model/tool/correction
calls, and a canonical assessment hash. `ProfessionalReviewExecutor` adapts the assessment to the
strict S1-09 `ReviewResult` contract using the exact target run/hash and reviewer version.

The adapter is read-only and deterministic. It performs zero model, tool, network, approval,
publication, correction, or user-delivery actions. Expert quality and external evidence required
for TG-04 remain outside this local validation boundary.
