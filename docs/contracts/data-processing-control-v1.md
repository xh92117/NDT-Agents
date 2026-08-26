# Data Processing Control Skill V1

## Purpose

S4-04 implements a provider-neutral control boundary around one registered processing adapter
result. It validates provenance, versions, parameters, budgets, quality, and traceability. It does
not execute an NDT algorithm or adapter, control a device, call a model, form a report conclusion,
approve evidence, or publish output.

## Source and request

`ProcessingSourceManifest@1.0.0` binds exact scope, immutable artifact and dataset hashes, explicit
simulated/laboratory/production origin, method, structure, component, location, coordinate
reference, channels, sample count/rate, signal dimension/unit, bounded acquisition settings,
instrument/version, calibration/version/validity interval, operator, and UTC acquisition time.

`ProcessingRequest@1.0.0` adds task/run/request identity, exact adapter/parser/algorithm versions,
output schema, canonical JSON parameters, one-attempt budget, and versioned quality policy.

## Candidate and result

The candidate binds the exact run/source/method/version/parameter identities, immutable output,
bounded observations and figures, quality metrics, duration/bytes/call counters, external-action
counters, status, and typed failure evidence. Observations bind scope, run, dataset, structure,
component, location, channel, sample range, dimension, unit, value, coordinates, and evidence hash.

`ProcessingControlResult@1.0.0` preserves both request/source identity and candidate identity so a
rejected cross-scope or mismatched result remains reproducible. It carries deterministic processing
and result hashes, issues, failure cause/impact/next action, mandatory review, and report eligibility.

## Validation

- Exact request/source/candidate scope, run, dataset, hash, method, versions, schema, and parameter
  hash are required.
- The source method must be in the six-method V1 ontology and calibration must cover acquisition.
- Duration, bytes, observations, figures, adapter calls, and attempts are bounded. Exactly one
  adapter call and one attempt are accepted; no hidden retry exists.
- Model, network, and physical-command counters must remain zero.
- Completeness and quality must meet their minimums and corruption must not exceed its maximum.
- Every observation stays within source channel/sample bounds and exact structure/component/location
  identity; each figure is exact-scope and references existing observations.
- Failed or blocked candidates must state cause, impact, and next action.

Only a clean `SUCCESS` from explicit `PRODUCTION` origin is report eligible. The deterministic
bridge rebuilds S4-03 source, processing, and observation evidence without changing identifiers,
hashes, units, or values. Simulation and laboratory results remain reviewable but not report
eligible through this bridge.

## Local evidence boundary

Synthetic tests cover stable clean processing, report conversion, explicit origins, calibration,
scope/source/version/parameter identity, budget and one-attempt enforcement, external-action denial,
quality degradation, observation/figure bounds, typed failure, and strict units. Real six-method
device evidence and TG-04 remain blocked by R-008 and R-009.
