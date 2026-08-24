# Generic Civil-Infrastructure NDT Ontology

**Control ID:** DOMAIN-ONTOLOGY-1.0  
**Task:** S0-02  
**Machine-readable source:** [ontology.v1.json](../../domain/ontology.v1.json)

## 1. Design principles

- Use one generic ontology for V1; specialize through codes, metadata, standards, and Skills only when validation or tools materially differ.
- Use immutable IDs for identity and versioned codes for classification.
- Preserve observed facts separately from interpretations, evaluations, and formal conclusions.
- Attach tenant and project scope to every project object.
- Preserve source, location, unit, time, method, instrument, calibration, and processing provenance.
- Allow unknown, not-applicable, and conflicting values without inventing certainty.

## 2. Identity and scope

Entity IDs use lowercase UUID strings. Human-readable codes are unique only inside their declared scope.

| Object class | Required scope | Stable identity rule |
|---|---|---|
| tenant | platform | immutable `tenant_id` |
| project | tenant | immutable `project_id`; project code unique per tenant |
| structure | tenant and project | immutable `structure_id`; structure code unique per project |
| component | tenant, project, structure | immutable `component_id`; parent-child tree is acyclic |
| inspection location | tenant, project, component | immutable `location_id`; geometry versioned |
| observation and artifact | tenant and project | immutable ID; content addressed where possible |
| knowledge item | tenant and optional project | immutable source and version IDs; publication status versioned |

## 3. Structure classes

V1 declares six top-level classes:

1. `ROAD`
2. `BRIDGE`
3. `TUNNEL`
4. `HYDRAULIC_STRUCTURE`
5. `MUNICIPAL_BUILDING`
6. `ENERGY_INFRASTRUCTURE_BUILDING`

Each structure has a structure class, lifecycle state, location, owner metadata, design and construction dates when known, coordinate reference, and one or more component trees. New structure classes require an ontology version change only when current extension fields cannot represent them safely.

## 4. Component model

A component is a generic node with a typed role rather than a structure-specific table. Initial roles are:

- `FOUNDATION`
- `SUBSTRUCTURE`
- `SUPERSTRUCTURE`
- `DECK_OR_SLAB`
- `WALL_OR_LINING`
- `BEAM_OR_GIRDER`
- `COLUMN_OR_PIER`
- `JOINT_OR_BEARING`
- `CABLE_OR_TENDON`
- `PAVEMENT_OR_SURFACE`
- `PIPE_OR_CONDUIT`
- `EQUIPMENT_SUPPORT`
- `OTHER`

Each component may have a parent, material regions, geometry artifacts, design attributes, exposure zones, inspection locations, and applicable standards. Structure-specific names are stored as labels and aliases, not as new core entity types.

## 5. Material model

Initial material classes are:

- `PLAIN_CONCRETE`
- `REINFORCED_CONCRETE`
- `STRUCTURAL_STEEL`
- `CONCRETE_FILLED_STEEL_TUBE`
- `OTHER_VERSIONED_MATERIAL`

A material region records material class, grade when known, thickness or dimensions, reinforcement or section metadata, environmental exposure, source, confidence, and geometry reference. Unknown composition remains `UNKNOWN`; it is not mapped to a likely material without evidence.

## 6. Inspection methods

The six priority methods are:

| Code | Method | Canonical source-data family |
|---|---|---|
| `UT` | ultrasonic testing | waveform, A-scan, B-scan, or derived feature set |
| `GPR` | ground-penetrating radar | trace, profile, time slice, or derived feature set |
| `IE` | impact echo | time waveform, spectrum, or derived feature set |
| `RT` | rebound testing | individual readings, location aggregate, and correction inputs |
| `AE` | acoustic emission | hit, waveform, event, channel, and derived feature set |
| `MV` | machine vision | image, video frame, geometry, annotation, and derived feature set |

Every method run declares method version, procedure, acquisition settings, instrument, calibration state, operator, location, units, source hashes, parser version, algorithm or model version, and applicability limitations.

## 7. Damage and condition concepts

The ontology separates four layers:

1. `indication`: a measurable signal or visual feature.
2. `observation`: a normalized fact tied to source evidence.
3. `defect_hypothesis`: an interpretation with confidence and alternatives.
4. `condition_assessment`: a reviewed evaluation against declared criteria.

Initial damage families are `CRACKING`, `VOID_OR_DELAMINATION`, `CORROSION_RELATED`, `SECTION_LOSS`, `DEFORMATION_OR_DISPLACEMENT`, `MOISTURE_OR_LEAKAGE`, `MATERIAL_DEGRADATION`, `BOND_OR_INTERFACE`, `FATIGUE_OR_FRACTURE`, `CONSTRUCTION_ANOMALY`, and `UNKNOWN`.

Severity, extent, confidence, urgency, and report eligibility are independent fields. A high model confidence does not imply high damage severity, and neither field grants formal-report eligibility.

## 8. Observation and evidence model

An observation contains:

- observation type and version;
- component and inspection location;
- method and procedure reference;
- measured value, unit, uncertainty, and detection limit where applicable;
- time or time range;
- source artifact and source-location references;
- instrument, calibration, operator, parser, algorithm, and model provenance;
- quality flags and missing-data reasons;
- creator, review state, and immutable creation time.

An observation is immutable. Corrections create a replacement version linked by `supersedes_id`. Interpretations may reference multiple observations and must preserve conflicting evidence.

## 9. Relationships

| Relationship | Cardinality | Invariant |
|---|---|---|
| tenant contains project | one-to-many | no cross-tenant project parent |
| project contains structure | one-to-many | structure scope equals project scope |
| structure contains component | one-to-many | component tree is acyclic |
| component contains material region | one-to-many | geometry lies within or references component geometry |
| component contains inspection location | one-to-many | location version identifies coordinate reference |
| method run uses instrument | many-to-one | calibration validity checked at run time |
| method run produces source artifact | one-to-many | artifact hash and version are immutable |
| processing run consumes artifact | many-to-many | every input hash and adapter version recorded |
| observation derives from processing run | many-to-one | no observation without evidence provenance |
| defect hypothesis supported by observation | many-to-many | contrary evidence may also be linked |
| assessment evaluates hypothesis | many-to-many | standard and clause applicability recorded |
| report conclusion references assessment | many-to-many | only reviewed, eligible assessments allowed |

## 10. Versioning and extension

- Ontology versions use semantic versioning.
- Adding an optional code or metadata field is minor; changing meaning, identity, required scope, or an invariant is major.
- Persisted objects store `ontology_version` and the version of every referenced code set.
- Unknown extension fields are rejected at typed boundaries unless stored in a versioned `extensions` object with a registered namespace.
- Migration never rewrites immutable evidence; it creates a compatible projection or a new version.

## 11. Mandatory validation rules

1. Tenant and project scopes match across every relationship.
2. Component graphs are acyclic and have exactly one structure root.
3. Units use a registered unit code and dimensions match the observation type.
4. A formal conclusion cannot reference an unreviewed or ineligible assessment.
5. A method run with invalid calibration cannot support formal use.
6. An observation cannot exist without source and processing provenance.
7. Conflicting evidence remains explicit and cannot be compressed into a definitive statement.
8. A deleted or withdrawn knowledge version cannot become applicable through cache or restore.
