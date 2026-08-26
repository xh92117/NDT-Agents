---
name: data-processing-control
version: 1.0.0
agent: Data Processing Agent
task_class: P1
output_contract: ProcessingControlResult@1.0.0
review_required: true
---

# Data Processing Control Skill

Validate one registered source-data processing result against its exact immutable source, scope,
method, instrument, calibration, versions, parameters, schema, quality policy, and budget.

## Required workflow

1. Preserve whether the source is simulated, laboratory, or production data.
2. Bind the immutable artifact and dataset hash to structure, component, location, coordinate
   reference, channels, sample count/rate, dimension/unit, acquisition settings, instrument,
   calibration, operator, and UTC acquisition time.
3. Verify exact adapter, parser, algorithm, output-schema, and canonical parameter hashes.
4. Accept exactly one adapter call and one attempt. Record duration, output bytes, observation and
   figure counts, completeness, quality, and corruption metrics against the versioned policy.
5. Keep every observation inside the exact channel and sample bounds and bind structure, component,
   location, unit, coordinates, and evidence hash. Bind immutable figures to observations.
6. Preserve typed cause, impact, evidence, and next action for partial, failed, or blocked output.
7. Return review-required evidence. Only a clean production result may be report eligible.

## Forbidden behavior

- Perform no provider/model call, network call, physical command, retry, report conclusion,
  approval, publication, or user delivery.
- Do not relabel simulated or laboratory data as production evidence.
- Do not hide calibration, quality, traceability, budget, or version failures.
