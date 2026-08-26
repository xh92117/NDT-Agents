"""S4-05 six-method Skill registry and compatibility tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ndt_agents.contracts.v1 import AgentStatus
from ndt_agents.professional.methods import (
    METHOD_CODES,
    MethodSkillRegistry,
    default_method_definitions,
    method_definition_sha256,
)
from ndt_agents.professional.processing import (
    DataOrigin,
    ProcessingCandidate,
    ProcessingObservation,
    ProcessingRequest,
    ProcessingSourceManifest,
)
from tests.professional.test_data_processing import candidate, request, source
from tests.professional.test_inspection_plan import scope

ROOT = Path(__file__).resolve().parents[2]

METHOD_CASES: dict[str, dict[str, Any]] = {
    "AE": {
        "structure_class": "BRIDGE",
        "material_class": "STRUCTURAL_STEEL",
        "calibration_kind": "SENSOR_SENSITIVITY",
        "settings": {
            "preamplifier_gain_db": 40,
            "sensor_layout_ref": "ae-grid-v1",
            "threshold_db": 45,
        },
        "signal": ("AMPLITUDE", "dB"),
        "parameters": {"event_definition_time_us": 200, "hit_lockout_time_us": 400},
        "observation": ("Acoustic emission event count", "COUNT", "count"),
    },
    "GPR": {
        "structure_class": "ROAD",
        "material_class": "REINFORCED_CONCRETE",
        "calibration_kind": "TIME_ZERO",
        "settings": {
            "antenna_frequency_mhz": 1000,
            "scan_spacing_mm": 20,
            "time_window_ns": 80,
        },
        "signal": ("AMPLITUDE", "mV"),
        "parameters": {"background_removal_window": 32, "migration_velocity_m_s": 120000000},
        "observation": ("GPR two-way travel time", "TIME", "ns"),
    },
    "IE": {
        "structure_class": "BRIDGE",
        "material_class": "PLAIN_CONCRETE",
        "calibration_kind": "SYSTEM_RESPONSE",
        "settings": {
            "impactor_id": "impact-1",
            "sampling_frequency_hz": 50000,
            "sensor_spacing_mm": 50,
        },
        "signal": ("VELOCITY", "m/s"),
        "parameters": {"peak_threshold": "0.8", "spectrum_window": 1024},
        "observation": ("Impact echo peak frequency", "FREQUENCY", "Hz"),
    },
    "MV": {
        "structure_class": "TUNNEL",
        "material_class": "REINFORCED_CONCRETE",
        "calibration_kind": "GEOMETRIC_SCALE",
        "settings": {
            "camera_distance_mm": 500,
            "image_plane_ref": "wall-plane-v1",
            "lighting_ref": "lighting-v1",
            "pixel_scale_mm_per_pixel": "0.1",
        },
        "signal": ("AMPLITUDE", "level"),
        "parameters": {"minimum_feature_pixels": 4, "segmentation_threshold": "0.7"},
        "observation": ("Machine vision crack width", "LENGTH", "mm"),
    },
    "RT": {
        "structure_class": "MUNICIPAL_BUILDING",
        "material_class": "PLAIN_CONCRETE",
        "calibration_kind": "REFERENCE_ANVIL",
        "settings": {
            "impact_direction": "HORIZONTAL",
            "surface_condition": "DRY_SMOOTH",
            "test_grid_ref": "grid-v1",
        },
        "signal": ("INDEX", "index"),
        "parameters": {"correction_curve_version": "curve-v1", "outlier_policy": "iqr-v1"},
        "observation": ("Rebound index", "INDEX", "index"),
    },
    "UT": {
        "structure_class": "BRIDGE",
        "material_class": "REINFORCED_CONCRETE",
        "calibration_kind": "REFERENCE_BLOCK",
        "settings": {
            "couplant_ref": "couplant-lot-1",
            "gain_db": 20,
            "probe_frequency_mhz": 2.5,
            "scan_layout_ref": "ut-grid-v1",
        },
        "signal": ("VELOCITY", "m/s"),
        "parameters": {"threshold": "0.80", "window": 32},
        "observation": ("Ultrasonic indication depth", "LENGTH", "mm"),
    },
}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def method_boundary(
    method_code: str,
    *,
    origin: DataOrigin = DataOrigin.PRODUCTION,
) -> tuple[ProcessingRequest, ProcessingCandidate]:
    case = METHOD_CASES[method_code]
    base_source = source(origin=origin)
    settings = {
        "structure_class": case["structure_class"],
        "material_class": case["material_class"],
        "calibration_kind": case["calibration_kind"],
        **case["settings"],
    }
    signal_dimension, signal_unit = case["signal"]
    typed_source = ProcessingSourceManifest.model_validate(
        {
            **base_source.model_dump(mode="json"),
            "origin": origin,
            "method_code": method_code,
            "signal_dimension": signal_dimension,
            "signal_unit": signal_unit,
            "acquisition_settings": settings,
        }
    )
    parameters = case["parameters"]
    typed_request = request(typed_source, parameters=parameters)
    base_candidate = candidate(typed_source)
    name, dimension, unit = case["observation"]
    observation = ProcessingObservation.model_validate(
        {
            **base_candidate.observations[0].model_dump(mode="json"),
            "name": name,
            "dimension": dimension,
            "unit": unit,
        }
    )
    typed_candidate = ProcessingCandidate.model_validate(
        {
            **base_candidate.model_dump(mode="json"),
            "method_code": method_code,
            "parameters_sha256": canonical_hash(parameters),
            "observations": (observation,),
        }
    )
    return typed_request, typed_candidate


def test_registry_contains_exactly_six_stable_versioned_definitions() -> None:
    first = default_method_definitions()
    second = default_method_definitions()

    assert first == second
    assert tuple(item.method_code for item in first) == METHOD_CODES
    assert len({item.definition_sha256 for item in first}) == 6
    assert all(item.definition_sha256 == method_definition_sha256(item) for item in first)
    assert all(item.skill_version.endswith("-skill-1.0.0") for item in first)


@pytest.mark.parametrize("method_code", METHOD_CODES)
def test_each_method_accepts_its_exact_golden_boundary(method_code: str) -> None:
    typed_request, typed_candidate = method_boundary(method_code)

    first = MethodSkillRegistry().validate(scope(), typed_request, typed_candidate)
    second = MethodSkillRegistry().validate(scope(), typed_request, typed_candidate)

    assert first == second
    assert first.status is AgentStatus.SUCCESS
    assert first.issues == ()
    assert first.method_compatible is True
    assert first.production_report_allowed is True
    assert first.definition_sha256 != "0" * 64
    assert (
        first.algorithm_calls
        + first.instrument_commands
        + first.model_calls
        + first.network_calls
        + first.approval_calls
        + first.publication_calls
        + first.retries
        == 0
    )


def test_missing_metadata_calibration_and_parameters_fail_closed() -> None:
    typed_request, typed_candidate = method_boundary("UT")
    bad_source = typed_request.source.model_copy(
        update={"acquisition_settings": {"structure_class": "BRIDGE"}}
    )
    bad_request = typed_request.model_copy(update={"source": bad_source, "parameters": {}})

    result = MethodSkillRegistry().validate(scope(), bad_request, typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert result.method_compatible is False
    assert {item.code for item in result.issues} >= {
        "METHOD_ACQUISITION_METADATA_MISSING",
        "METHOD_APPLICABILITY_INVALID",
        "METHOD_CALIBRATION_KIND_INVALID",
        "METHOD_PROCESSING_PARAMETERS_MISSING",
    }


def test_scope_method_input_and_output_mismatch_are_rejected() -> None:
    typed_request, typed_candidate = method_boundary("GPR")
    foreign_scope = scope(project=typed_request.source.scope.project_id)
    bad_source = typed_request.source.model_copy(
        update={"signal_dimension": "VELOCITY", "signal_unit": "m/s"}
    )
    bad_request = typed_request.model_copy(update={"source": bad_source})
    bad_observation = typed_candidate.observations[0].model_copy(
        update={"name": "Unregistered result"}
    )
    bad_candidate = typed_candidate.model_copy(
        update={
            "scope": foreign_scope.model_copy(update={"permission_version": "permissions-v2"}),
            "method_code": "UT",
            "observations": (bad_observation,),
        }
    )

    result = MethodSkillRegistry().validate(scope(), bad_request, bad_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert {item.code for item in result.issues} >= {
        "METHOD_SCOPE_DENIED",
        "METHOD_IDENTITY_MISMATCH",
        "METHOD_INPUT_SIGNAL_INVALID",
        "METHOD_OUTPUT_OBSERVATION_INVALID",
    }


def test_unknown_method_and_nonproduction_origin_remain_explicit() -> None:
    typed_request, typed_candidate = method_boundary("AE", origin=DataOrigin.LABORATORY)
    laboratory = MethodSkillRegistry().validate(scope(), typed_request, typed_candidate)
    unknown_source = typed_request.source.model_copy(update={"method_code": "OTHER"})
    unknown_request = typed_request.model_copy(update={"source": unknown_source})
    unknown_candidate = typed_candidate.model_copy(update={"method_code": "OTHER"})

    unknown = MethodSkillRegistry().validate(scope(), unknown_request, unknown_candidate)

    assert laboratory.status is AgentStatus.SUCCESS
    assert laboratory.method_compatible is True
    assert laboratory.production_report_allowed is False
    assert unknown.status is AgentStatus.HUMAN_REQUIRED
    assert unknown.definition_sha256 == "0" * 64
    assert "METHOD_SKILL_NOT_REGISTERED" in {item.code for item in unknown.issues}


def test_six_method_skill_assets_share_the_control_contract() -> None:
    contract = (ROOT / "docs/contracts/method-skills-v1.md").read_text("utf-8")
    prompt = (ROOT / "prompts/professional/method-skills.v1.md").read_text("utf-8")

    assert "MethodValidationResult@1.0.0" in contract
    assert "execute no algorithm" in prompt
    for method_code in METHOD_CODES:
        skill_path = ROOT / "skills/professional/methods" / method_code.lower() / "SKILL.md"
        skill_text = skill_path.read_text("utf-8")
        assert "version: 1.0.0" in skill_text
        assert f"method_code: {method_code}" in skill_text
        assert "review_required: true" in skill_text
