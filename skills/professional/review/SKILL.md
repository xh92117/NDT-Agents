---
name: professional-review
version: 1.0.0
agent: Review Agent
task_class: P3
output_contract: ProfessionalReviewAssessment@1.0.0
review_required: false
---

# Professional Review Skill

Apply the registered checklist independently to each Technical QA, inspection-plan,
data-processing, method-validation, or inspection-report result. Revalidate strict type, exact
scope/task/run, status, immutable hashes, issues, evidence, citations, traceability, units,
calculations, human boundaries, and side-effect counters. Do not trust candidate-provided review
or approval state.

Run cross-result review only after all interacting results pass independently. Compare QA to plan,
plan to report, processing to report, and method validation to processing and report. Return typed
PASS, REVISE, CONFLICT, HUMAN_REQUIRED, or FAILED evidence. Never aggregate an unresolved result.

Remain read-only. Perform no model, tool, network, correction, approval, publication, mutation, or
user-delivery action. The S1-09 graph owns targeted correction, bounded re-review, and the Main-only
aggregation gate.
