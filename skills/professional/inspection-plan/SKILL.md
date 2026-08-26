---
name: inspection-plan
version: 1.0.0
agent: Plan Agent
task_class: P2
output_contract: InspectionPlanResult@1.0.0
template: TPL-INSPECTION-PLAN-V1
review_required: true
approval_required: true
---

# Inspection Plan Skill

Create a typed civil-infrastructure NDT inspection-plan candidate only for the exact supplied task
scope, ontology, applicable standards, and approved template version.

## Required workflow

1. Preserve the registered template order and complete all seventeen required sections.
2. Keep objective, scope, structure/component, requested methods, layout, equipment, calibration,
   procedure, sampling, acceptance, safety, data, quality, schedule, deliverables, limitations,
   review/approval, and missing-input handling explicit.
3. Use only registered V1 methods. Bind each sampling target or acceptance value to a typed quantity
   with a registered dimension and unit.
4. Bind each acceptance basis to an applicable, exact-scope Technical QA claim and published
   standard citation. Do not invent a standard, clause, threshold, value, unit, or source.
5. List every unresolved required input with its impact, responsible role, and blocking state.
6. Return an approval-pending candidate for independent review. Do not mark a plan approved, permit
   formal use, operate an instrument, or communicate directly with the user.

## Stop conditions

Stop with a typed result when sections are absent or reordered, a reference is missing, a quantity
is dimensionally invalid, an ontology value is unsupported, QA evidence is stale or cross-scope, or
a standard is not current and applicable for the requested date, region, type, rights, and roles.
