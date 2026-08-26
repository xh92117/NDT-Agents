"""S4-05 versioned method-Skill skeleton registry and compatibility checks."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import AgentStatus, Issue, StrictModel, TenantScope
from ndt_agents.professional.planning import is_registered_unit
from ndt_agents.professional.processing import (
    CandidateProcessingStatus,
    DataOrigin,
    ProcessingCandidate,
    ProcessingRequest,
)
from ndt_agents.professional.qa import SUPPORTED_MATERIALS, SUPPORTED_STRUCTURES

METHOD_SKILL_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
METHOD_CODES = ("AE", "GPR", "IE", "MV", "RT", "UT")
_ZERO_SHA256 = "0" * 64


class MethodSignalSpec(StrictModel):
    dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    units: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_units(self) -> Self:
        if self.units != tuple(sorted(set(self.units))):
            raise ValueError("method signal units must be sorted and unique")
        if any(not is_registered_unit(self.dimension, item) for item in self.units):
            raise ValueError("method signal unit is not registered")
        return self


class MethodObservationSpec(StrictModel):
    family: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=256)
    dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    units: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_units(self) -> Self:
        if self.units != tuple(sorted(set(self.units))):
            raise ValueError("method observation units must be sorted and unique")
        if any(not is_registered_unit(self.dimension, item) for item in self.units):
            raise ValueError("method observation unit is not registered")
        return self


class MethodSkillDefinition(StrictModel):
    schema_version: Literal["1.0.0"] = METHOD_SKILL_CONTRACT_VERSION
    method_code: str = Field(pattern=r"^(AE|GPR|IE|MV|RT|UT)$")
    method_name: str = Field(min_length=1, max_length=128)
    skill_version: str = Field(pattern=r"^[a-z0-9-]+-skill-[0-9]+\.[0-9]+\.[0-9]+$")
    supported_structures: tuple[str, ...] = Field(min_length=1)
    supported_materials: tuple[str, ...] = Field(min_length=1)
    required_acquisition_settings: tuple[str, ...] = Field(min_length=1)
    required_calibration_kinds: tuple[str, ...] = Field(min_length=1)
    input_signals: tuple[MethodSignalSpec, ...] = Field(min_length=1)
    required_processing_parameters: tuple[str, ...] = Field(min_length=1)
    output_observations: tuple[MethodObservationSpec, ...] = Field(min_length=1)
    allowed_origins: tuple[DataOrigin, ...] = Field(min_length=1)
    production_report_allowed: bool
    limitations: tuple[str, ...] = Field(min_length=1)
    safety_notes: tuple[str, ...] = Field(min_length=1)
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        sorted_fields = (
            self.supported_structures,
            self.supported_materials,
            self.required_acquisition_settings,
            self.required_calibration_kinds,
            self.required_processing_parameters,
        )
        if any(value != tuple(sorted(set(value))) for value in sorted_fields):
            raise ValueError("method definition sets must be sorted and unique")
        if not set(self.supported_structures) <= SUPPORTED_STRUCTURES:
            raise ValueError("method definition contains an unsupported structure")
        if not set(self.supported_materials) <= SUPPORTED_MATERIALS:
            raise ValueError("method definition contains an unsupported material")
        if self.allowed_origins != tuple(sorted(set(self.allowed_origins), key=str)):
            raise ValueError("method origins must be sorted and unique")
        if self.definition_sha256 != method_definition_sha256(self):
            raise ValueError("method definition hash is invalid")
        return self


class MethodValidationResult(StrictModel):
    schema_version: Literal["1.0.0"] = METHOD_SKILL_CONTRACT_VERSION
    scope: TenantScope
    method_code: str = Field(min_length=1, max_length=32)
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AgentStatus
    issues: tuple[Issue, ...] = Field(max_length=128)
    method_compatible: bool
    production_report_allowed: bool
    review_required: Literal[True] = True
    algorithm_calls: Literal[0] = 0
    instrument_commands: Literal[0] = 0
    model_calls: Literal[0] = 0
    network_calls: Literal[0] = 0
    approval_calls: Literal[0] = 0
    publication_calls: Literal[0] = 0
    retries: Literal[0] = 0
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.method_compatible != (not self.issues):
            raise ValueError("method compatibility must match validation issues")
        if self.production_report_allowed and (
            not self.method_compatible or self.status is not AgentStatus.SUCCESS
        ):
            raise ValueError("incompatible method output cannot allow production reporting")
        if self.result_sha256 != method_validation_result_sha256(self):
            raise ValueError("method validation result hash is invalid")
        return self


class MethodSkillRegistry:
    """Read-only six-method registry with deterministic request/candidate validation."""

    def __init__(self, definitions: tuple[MethodSkillDefinition, ...] | None = None) -> None:
        resolved = definitions or default_method_definitions()
        if tuple(item.method_code for item in resolved) != METHOD_CODES:
            raise ValueError("method registry must contain the six ordered V1 methods")
        self._definitions = {item.method_code: item for item in resolved}

    def definitions(self) -> tuple[MethodSkillDefinition, ...]:
        return tuple(self._definitions[item] for item in METHOD_CODES)

    def get(self, method_code: str) -> MethodSkillDefinition | None:
        return self._definitions.get(method_code)

    def validate(
        self,
        scope: TenantScope,
        request: ProcessingRequest,
        candidate: ProcessingCandidate,
    ) -> MethodValidationResult:
        issues: list[Issue] = []
        method_code = request.source.method_code
        definition = self.get(method_code)
        if definition is None:
            issues.append(
                _issue(
                    "METHOD_SKILL_NOT_REGISTERED",
                    "CRITICAL",
                    "The source method has no registered V1 method Skill.",
                    "source.method_code",
                    "Select one of AE, GPR, IE, MV, RT, or UT.",
                )
            )
        if request.source.scope != scope or candidate.scope != scope:
            issues.append(
                _issue(
                    "METHOD_SCOPE_DENIED",
                    "CRITICAL",
                    "The method request or candidate belongs to another exact scope.",
                    "scope",
                    "Use the current tenant, project, user, roles, and permission version.",
                )
            )
        if candidate.method_code != method_code:
            issues.append(
                _issue(
                    "METHOD_IDENTITY_MISMATCH",
                    "CRITICAL",
                    "The candidate method does not match the source method.",
                    "candidate.method_code",
                    "Regenerate the candidate with the selected method Skill.",
                )
            )
        if definition is not None:
            self._validate_definition(definition, request, candidate, issues)

        compatible = not issues
        status = AgentStatus.SUCCESS if compatible else AgentStatus.HUMAN_REQUIRED
        production_allowed = bool(
            compatible
            and definition is not None
            and definition.production_report_allowed
            and request.source.origin is DataOrigin.PRODUCTION
            and candidate.status is CandidateProcessingStatus.SUCCESS
        )
        payload: dict[str, object] = {
            "schema_version": METHOD_SKILL_CONTRACT_VERSION,
            "scope": scope,
            "method_code": method_code,
            "definition_sha256": definition.definition_sha256 if definition else _ZERO_SHA256,
            "request_sha256": _canonical_hash(request.model_dump(mode="json")),
            "candidate_sha256": _canonical_hash(candidate.model_dump(mode="json")),
            "status": status,
            "issues": tuple(issues),
            "method_compatible": compatible,
            "production_report_allowed": production_allowed,
            "review_required": True,
            "algorithm_calls": 0,
            "instrument_commands": 0,
            "model_calls": 0,
            "network_calls": 0,
            "approval_calls": 0,
            "publication_calls": 0,
            "retries": 0,
        }
        return MethodValidationResult.model_validate(
            {**payload, "result_sha256": _canonical_hash(_jsonable(payload))}
        )

    @staticmethod
    def _validate_definition(
        definition: MethodSkillDefinition,
        request: ProcessingRequest,
        candidate: ProcessingCandidate,
        issues: list[Issue],
    ) -> None:
        source = request.source
        settings = source.acquisition_settings
        missing_settings = sorted(set(definition.required_acquisition_settings) - settings.keys())
        if missing_settings:
            issues.append(
                _issue(
                    "METHOD_ACQUISITION_METADATA_MISSING",
                    "CRITICAL",
                    f"Required acquisition settings are missing: {', '.join(missing_settings)}.",
                    "source.acquisition_settings",
                    "Supply the method Skill's complete acquisition metadata.",
                )
            )
        structure = settings.get("structure_class")
        material = settings.get("material_class")
        calibration = settings.get("calibration_kind")
        if (
            structure not in definition.supported_structures
            or material not in definition.supported_materials
        ):
            issues.append(
                _issue(
                    "METHOD_APPLICABILITY_INVALID",
                    "CRITICAL",
                    "The declared structure or material is outside the method skeleton boundary.",
                    "source.acquisition_settings",
                    "Select an applicable method or obtain qualified human disposition.",
                )
            )
        if calibration not in definition.required_calibration_kinds:
            issues.append(
                _issue(
                    "METHOD_CALIBRATION_KIND_INVALID",
                    "CRITICAL",
                    "The declared calibration kind is not accepted by the method skeleton.",
                    "source.acquisition_settings.calibration_kind",
                    "Use one registered calibration kind with traceable evidence.",
                )
            )
        if not any(
            item.dimension == source.signal_dimension and source.signal_unit in item.units
            for item in definition.input_signals
        ):
            issues.append(
                _issue(
                    "METHOD_INPUT_SIGNAL_INVALID",
                    "CRITICAL",
                    "The source signal dimension or unit is incompatible with the method skeleton.",
                    "source.signal_dimension",
                    "Rebuild the source manifest with a registered method input signal.",
                )
            )
        missing_parameters = sorted(
            set(definition.required_processing_parameters) - request.parameters.keys()
        )
        if missing_parameters:
            issues.append(
                _issue(
                    "METHOD_PROCESSING_PARAMETERS_MISSING",
                    "CRITICAL",
                    f"Required processing parameters are missing: {', '.join(missing_parameters)}.",
                    "parameters",
                    "Supply the exact versioned method processing parameters.",
                )
            )
        if source.origin not in definition.allowed_origins:
            issues.append(
                _issue(
                    "METHOD_ORIGIN_INVALID",
                    "CRITICAL",
                    "The source origin is not allowed by the method skeleton.",
                    "source.origin",
                    "Preserve the real source origin and use an allowed method workflow.",
                )
            )
        allowed_outputs = {
            (item.name, item.dimension, unit)
            for item in definition.output_observations
            for unit in item.units
        }
        if candidate.status is CandidateProcessingStatus.SUCCESS and not candidate.observations:
            issues.append(
                _issue(
                    "METHOD_OUTPUT_MISSING",
                    "CRITICAL",
                    "A successful method candidate has no typed observations.",
                    "candidate.observations",
                    "Return at least one registered observation or a typed partial/failed result.",
                )
            )
        invalid_outputs = [
            str(index)
            for index, item in enumerate(candidate.observations)
            if (item.name, item.dimension, item.unit) not in allowed_outputs
        ]
        if invalid_outputs:
            issues.append(
                _issue(
                    "METHOD_OUTPUT_OBSERVATION_INVALID",
                    "CRITICAL",
                    "Observations do not match registered output families: "
                    f"{', '.join(invalid_outputs)}.",
                    "candidate.observations",
                    "Use an exact registered observation name, dimension, and unit.",
                )
            )


def method_definition_sha256(definition: MethodSkillDefinition) -> str:
    return _canonical_hash(definition.model_dump(mode="json", exclude={"definition_sha256"}))


def method_validation_result_sha256(result: MethodValidationResult) -> str:
    return _canonical_hash(result.model_dump(mode="json", exclude={"result_sha256"}))


def default_method_definitions() -> tuple[MethodSkillDefinition, ...]:
    all_origins = (DataOrigin.LABORATORY, DataOrigin.PRODUCTION, DataOrigin.SIMULATED)
    common_settings = ("calibration_kind", "material_class", "structure_class")
    definitions = (
        _definition(
            method_code="AE",
            method_name="Acoustic emission",
            structures=(
                "BRIDGE",
                "ENERGY_INFRASTRUCTURE_BUILDING",
                "HYDRAULIC_STRUCTURE",
                "MUNICIPAL_BUILDING",
                "TUNNEL",
            ),
            materials=("CONCRETE_FILLED_STEEL_TUBE", "REINFORCED_CONCRETE", "STRUCTURAL_STEEL"),
            settings=common_settings
            + ("preamplifier_gain_db", "sensor_layout_ref", "threshold_db"),
            calibrations=("SENSOR_SENSITIVITY", "SYSTEM_TIMING"),
            inputs=(MethodSignalSpec(dimension="AMPLITUDE", units=("dB", "mV")),),
            parameters=("event_definition_time_us", "hit_lockout_time_us"),
            outputs=(
                MethodObservationSpec(
                    family="EVENT_COUNT",
                    name="Acoustic emission event count",
                    dimension="COUNT",
                    units=("count",),
                ),
                MethodObservationSpec(
                    family="SIGNAL_AMPLITUDE",
                    name="Acoustic emission amplitude",
                    dimension="AMPLITUDE",
                    units=("dB",),
                ),
            ),
            limitations=(
                "Event location and source classification require validated sensor geometry "
                "and expert review.",
            ),
            safety=("Confirm sensor attachment and cable routing before monitored loading.",),
            origins=all_origins,
        ),
        _definition(
            method_code="GPR",
            method_name="Ground penetrating radar",
            structures=("BRIDGE", "MUNICIPAL_BUILDING", "ROAD", "TUNNEL"),
            materials=("PLAIN_CONCRETE", "REINFORCED_CONCRETE"),
            settings=common_settings
            + ("antenna_frequency_mhz", "scan_spacing_mm", "time_window_ns"),
            calibrations=("TIME_ZERO", "VELOCITY_MODEL"),
            inputs=(MethodSignalSpec(dimension="AMPLITUDE", units=("mV",)),),
            parameters=("background_removal_window", "migration_velocity_m_s"),
            outputs=(
                MethodObservationSpec(
                    family="TWO_WAY_TRAVEL_TIME",
                    name="GPR two-way travel time",
                    dimension="TIME",
                    units=("ns",),
                ),
                MethodObservationSpec(
                    family="INTERPRETED_DEPTH",
                    name="GPR interpreted depth",
                    dimension="LENGTH",
                    units=("mm",),
                ),
            ),
            limitations=("Depth interpretation depends on a reviewed propagation-velocity model.",),
            safety=("Control traffic and scanning-area access before acquisition.",),
            origins=all_origins,
        ),
        _definition(
            method_code="IE",
            method_name="Impact echo",
            structures=(
                "BRIDGE",
                "HYDRAULIC_STRUCTURE",
                "MUNICIPAL_BUILDING",
                "ROAD",
                "TUNNEL",
            ),
            materials=("PLAIN_CONCRETE", "REINFORCED_CONCRETE"),
            settings=common_settings
            + ("impactor_id", "sampling_frequency_hz", "sensor_spacing_mm"),
            calibrations=("SYSTEM_RESPONSE",),
            inputs=(
                MethodSignalSpec(dimension="AMPLITUDE", units=("mV",)),
                MethodSignalSpec(dimension="VELOCITY", units=("m/s",)),
            ),
            parameters=("peak_threshold", "spectrum_window"),
            outputs=(
                MethodObservationSpec(
                    family="PEAK_FREQUENCY",
                    name="Impact echo peak frequency",
                    dimension="FREQUENCY",
                    units=("Hz",),
                ),
                MethodObservationSpec(
                    family="INTERPRETED_DEPTH",
                    name="Impact echo interpreted depth",
                    dimension="LENGTH",
                    units=("mm",),
                ),
            ),
            limitations=(
                "Thickness or reflector interpretation requires reviewed wave-speed evidence.",
            ),
            safety=("Control the impact zone and verify that impact energy is acceptable.",),
            origins=all_origins,
        ),
        _definition(
            method_code="MV",
            method_name="Machine vision",
            structures=tuple(sorted(SUPPORTED_STRUCTURES)),
            materials=tuple(sorted(SUPPORTED_MATERIALS)),
            settings=common_settings
            + ("camera_distance_mm", "image_plane_ref", "lighting_ref", "pixel_scale_mm_per_pixel"),
            calibrations=("GEOMETRIC_SCALE", "LENS_CALIBRATION"),
            inputs=(MethodSignalSpec(dimension="AMPLITUDE", units=("level",)),),
            parameters=("minimum_feature_pixels", "segmentation_threshold"),
            outputs=(
                MethodObservationSpec(
                    family="CRACK_WIDTH",
                    name="Machine vision crack width",
                    dimension="LENGTH",
                    units=("mm",),
                ),
                MethodObservationSpec(
                    family="DEFECT_AREA",
                    name="Machine vision defect area",
                    dimension="AREA",
                    units=("mm2",),
                ),
            ),
            limitations=(
                "Occlusion, scale, perspective, and lighting remain explicit limitations.",
            ),
            safety=(
                "Use an approved access method for image acquisition at height or near traffic.",
            ),
            origins=all_origins,
        ),
        _definition(
            method_code="RT",
            method_name="Rebound testing",
            structures=tuple(sorted(SUPPORTED_STRUCTURES)),
            materials=("PLAIN_CONCRETE", "REINFORCED_CONCRETE"),
            settings=common_settings + ("impact_direction", "surface_condition", "test_grid_ref"),
            calibrations=("REFERENCE_ANVIL",),
            inputs=(MethodSignalSpec(dimension="INDEX", units=("index",)),),
            parameters=("correction_curve_version", "outlier_policy"),
            outputs=(
                MethodObservationSpec(
                    family="REBOUND_INDEX",
                    name="Rebound index",
                    dimension="INDEX",
                    units=("index",),
                ),
            ),
            limitations=("Rebound index is not a standalone formal strength conclusion.",),
            safety=("Verify stable footing and exclude loose surface material before impact.",),
            origins=all_origins,
        ),
        _definition(
            method_code="UT",
            method_name="Ultrasonic testing",
            structures=tuple(sorted(SUPPORTED_STRUCTURES)),
            materials=tuple(sorted(SUPPORTED_MATERIALS)),
            settings=common_settings
            + ("couplant_ref", "gain_db", "probe_frequency_mhz", "scan_layout_ref"),
            calibrations=("REFERENCE_BLOCK", "SYSTEM_CALIBRATION"),
            inputs=(
                MethodSignalSpec(dimension="AMPLITUDE", units=("mV",)),
                MethodSignalSpec(dimension="VELOCITY", units=("m/s",)),
            ),
            parameters=("threshold", "window"),
            outputs=(
                MethodObservationSpec(
                    family="INDICATION_DEPTH",
                    name="Ultrasonic indication depth",
                    dimension="LENGTH",
                    units=("mm",),
                ),
                MethodObservationSpec(
                    family="SIGNAL_AMPLITUDE",
                    name="Ultrasonic amplitude",
                    dimension="AMPLITUDE",
                    units=("dB",),
                ),
            ),
            limitations=(
                "Indication interpretation depends on geometry, coupling, and calibration "
                "evidence.",
            ),
            safety=("Apply the approved access and couplant controls before acquisition.",),
            origins=all_origins,
        ),
    )
    return definitions


def _definition(
    *,
    method_code: str,
    method_name: str,
    structures: tuple[str, ...],
    materials: tuple[str, ...],
    settings: tuple[str, ...],
    calibrations: tuple[str, ...],
    inputs: tuple[MethodSignalSpec, ...],
    parameters: tuple[str, ...],
    outputs: tuple[MethodObservationSpec, ...],
    limitations: tuple[str, ...],
    safety: tuple[str, ...],
    origins: tuple[DataOrigin, ...],
) -> MethodSkillDefinition:
    payload: dict[str, object] = {
        "schema_version": METHOD_SKILL_CONTRACT_VERSION,
        "method_code": method_code,
        "method_name": method_name,
        "skill_version": f"{method_code.lower()}-method-skill-1.0.0",
        "supported_structures": tuple(sorted(structures)),
        "supported_materials": tuple(sorted(materials)),
        "required_acquisition_settings": tuple(sorted(settings)),
        "required_calibration_kinds": tuple(sorted(calibrations)),
        "input_signals": inputs,
        "required_processing_parameters": tuple(sorted(parameters)),
        "output_observations": outputs,
        "allowed_origins": origins,
        "production_report_allowed": True,
        "limitations": limitations,
        "safety_notes": safety,
    }
    return MethodSkillDefinition.model_validate(
        {**payload, "definition_sha256": _canonical_hash(_jsonable(payload))}
    )


def _issue(
    code: str,
    severity: Literal["INFO", "WARNING", "ERROR", "CRITICAL"],
    message: str,
    affected_path: str | None,
    next_action: str,
) -> Issue:
    return Issue(
        code=code,
        severity=severity,
        message=message,
        affected_path=affected_path,
        next_action=next_action,
    )


def _jsonable(value: object) -> object:
    if isinstance(value, StrictModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
