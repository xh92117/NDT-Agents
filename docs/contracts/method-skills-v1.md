# Method Skill Pack V1

## Purpose

S4-05 defines provider-neutral method skeletons for ultrasonic testing (`UT`), ground penetrating
radar (`GPR`), impact echo (`IE`), rebound testing (`RT`), acoustic emission (`AE`), and machine
vision (`MV`). The pack constrains metadata and typed evidence around S4-04. It does not implement
or execute a signal-processing algorithm, operate an instrument, or establish expert correctness.

## Definition contract

`MethodSkillDefinition@1.0.0` binds a method code and version to supported V1 structures and
materials, required acquisition settings, accepted calibration kinds, input dimensions and units,
required processing parameters, output observation families, allowed source origins, limitations,
safety notes, and production-report policy. The canonical definition hash changes if any field
changes. The read-only registry contains exactly the ordered set `AE`, `GPR`, `IE`, `MV`, `RT`,
and `UT`; duplicates, omissions, unknown methods, invalid ontology values, and unregistered units
fail construction.

## Validation contract

The registry validates the exact S4-04 request and candidate scope and method. It checks required
metadata, structure/material applicability, calibration kind, source signal dimension/unit,
processing parameter names, source origin, successful-output presence, and every observation's
exact registered name, dimension, and unit.

`MethodValidationResult@1.0.0` preserves method-definition, request, candidate, and result hashes,
typed issues, compatibility, production-report policy, and mandatory review. Production-report
permission means only that the method skeleton accepts the explicit production provenance; the
S4-04 control result, S4-06 review, and S4-07 approval boundaries must still pass independently.

## Method boundaries

- `UT`: amplitude or velocity input; reference-block/system calibration; indication-depth and
  amplitude observation families.
- `GPR`: amplitude input; time-zero/velocity-model calibration; two-way-time and interpreted-depth
  families.
- `IE`: amplitude or velocity input; system-response calibration; peak-frequency and interpreted-
  depth families.
- `RT`: rebound-index input; reference-anvil calibration; rebound-index family.
- `AE`: amplitude input; sensor-sensitivity/system-timing calibration; event-count and amplitude
  families.
- `MV`: level input; geometric-scale/lens calibration; crack-width and defect-area families.

These are contract skeletons, not standards, procedures, acceptance criteria, performance claims,
or formal interpretations. The six Skill files state method-specific metadata, limitations, and
safety boundaries. Real calibrated-device validation and qualified-expert review remain required.

## Side-effect boundary

Validation performs zero algorithm, instrument, model, network, approval, publication, and retry
actions. Simulation, laboratory, and production origins remain explicit. A laboratory or simulated
result can be compatible and reviewable but cannot receive production-report permission.
