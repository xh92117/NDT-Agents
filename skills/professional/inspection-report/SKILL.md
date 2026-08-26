---
name: inspection-report
version: 1.0.0
agent: Report Agent
task_class: P3
output_contract: InspectionReportResult@1.0.0
template: TPL-INSPECTION-REPORT-V1
review_required: true
approval_required: true
---

# Inspection Report Skill

Create a typed, approval-pending civil-infrastructure NDT report candidate from an exact-scope plan,
immutable source data, registered processing evidence, traced observations, and applicable citations.

## Required workflow

1. Complete all fifteen report template sections in order and bind the exact plan hash.
2. Preserve dataset artifact, method, instrument, calibration, operator, acquisition, processing,
   algorithm, parameter, output, observation, location, unit, and evidence identities.
3. Use only allowlisted deterministic calculations. Keep every input observation explicit and copy
   the recomputed value, dimension, and unit exactly.
4. Bind each figure to immutable artifacts and observations. Bind each finding to observations,
   calculations where used, applicable plan standard bases, and explicit limitations.
5. Build conclusions only from traced findings. Mark every critical finding and formal conclusion
   for qualified human confirmation.
6. Preserve contiguous immutable revision history. Return review-required, approval-pending output;
   never claim formal release or deliver directly to the user.

## Forbidden behavior

- Do not fabricate missing source data, observations, calculations, figures, findings, citations,
  calibration, revision history, approval, or formal-release state.
- Do not mix incompatible dimensions or units or silently convert values.
- Do not use cross-scope, mutable, uncalibrated, untraced, or failed processing evidence.
