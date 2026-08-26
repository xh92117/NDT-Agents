"""S5-06 canonical inspection-data, provenance, codec, and S4 bridge tests."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import DataClassification, TenantScope
from ndt_agents.inspection_data import (
    CalibrationStatus,
    CanonicalInspectionDataError,
    build_canonical_inspection_dataset,
    canonical_inspection_dataset_sha256,
    canonical_validation_result_sha256,
    dump_canonical_inspection_data,
    load_canonical_inspection_data,
    to_processing_source_manifest,
    validate_canonical_inspection_dataset,
    validate_processing_source_manifest,
)
from ndt_agents.professional.processing import DataOrigin, ProcessingSourceManifest

TENANT = UUID("50000000-0000-4000-8000-000000000001")
PROJECT = UUID("50000000-0000-4000-8000-000000000002")
USER = UUID("50000000-0000-4000-8000-000000000003")
DATASET = UUID("50000000-0000-4000-8000-000000000004")
STRUCTURE = UUID("50000000-0000-4000-8000-000000000005")
COMPONENT = UUID("50000000-0000-4000-8000-000000000006")
LOCATION = UUID("50000000-0000-4000-8000-000000000007")
ACQUIRED_AT = datetime(2026, 8, 25, 6, 30, tzinfo=UTC)

METHOD_SIGNAL = {
    "AE": ("AMPLITUDE", "mV", "SENSOR_SENSITIVITY"),
    "GPR": ("AMPLITUDE", "mV", "TIME_ZERO"),
    "IE": ("AMPLITUDE", "mV", "SYSTEM_RESPONSE"),
    "MV": ("AMPLITUDE", "level", "GEOMETRIC_SCALE"),
    "RT": ("INDEX", "index", "REFERENCE_ANVIL"),
    "UT": ("AMPLITUDE", "mV", "REFERENCE_BLOCK"),
}
METHOD_SETTINGS: dict[str, dict[str, bool | int | str]] = {
    "AE": {
        "preamplifier_gain_db": 40,
        "sensor_layout_ref": "layout-ae-01",
        "threshold_db": 45,
    },
    "GPR": {
        "antenna_frequency_mhz": "400",
        "scan_spacing_mm": "25",
        "time_window_ns": "80",
    },
    "IE": {
        "impactor_id": "impactor-01",
        "sampling_frequency_hz": "100000",
        "sensor_spacing_mm": "100",
    },
    "MV": {
        "camera_distance_mm": "1500",
        "image_plane_ref": "image-plane-01",
        "lighting_ref": "lighting-01",
        "pixel_scale_mm_per_pixel": "0.10",
    },
    "RT": {
        "impact_direction": "HORIZONTAL",
        "surface_condition": "DRY_SMOOTH",
        "test_grid_ref": "grid-rt-01",
    },
    "UT": {
        "couplant_ref": "couplant-batch-01",
        "gain_db": 20,
        "probe_frequency_mhz": "2.5",
        "scan_layout_ref": "layout-ut-01",
    },
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def scope_payload(*, tenant_id: UUID = TENANT) -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "project_id": PROJECT,
        "user_id": USER,
        "role_codes": ("inspector",),
        "permission_version": "permissions-v1",
    }


def artifact_payload(
    artifact_id: str,
    *,
    owner: dict[str, object] | None = None,
    media_type: str = "application/octet-stream",
    size_bytes: int = 4_096,
    immutable: bool = True,
) -> dict[str, object]:
    return {
        "artifact_id": UUID(artifact_id),
        "scope": owner or scope_payload(),
        "artifact_version": "1",
        "uri": f"artifact://inspection/{artifact_id}",
        "media_type": media_type,
        "size_bytes": size_bytes,
        "sha256": digest(artifact_id),
        "classification": DataClassification.INTERNAL,
        "immutable": immutable,
    }


def manifest_payload(
    method_code: str = "UT",
    *,
    origin: DataOrigin = DataOrigin.PRODUCTION,
) -> dict[str, object]:
    dimension, unit, calibration_kind = METHOD_SIGNAL[method_code]
    source_artifact = artifact_payload(
        "50000000-0000-4000-8000-000000000011",
        media_type="application/x-ndt-fixture",
        size_bytes=8_192,
    )
    channel_artifact = artifact_payload(
        "50000000-0000-4000-8000-000000000012",
        size_bytes=4_096,
    )
    calibration_artifact = artifact_payload(
        "50000000-0000-4000-8000-000000000013",
        media_type="application/pdf",
        size_bytes=1_024,
    )
    setting_values: dict[str, bool | int | str] = {
        "calibration_kind": calibration_kind,
        "material_class": "REINFORCED_CONCRETE",
        "structure_class": "BRIDGE",
        **METHOD_SETTINGS[method_code],
    }
    settings = tuple(
        {
            "name": name,
            "value": value,
            **(
                {"dimension": "AMPLITUDE", "unit": "dB"}
                if name in {"gain_db", "preamplifier_gain_db", "threshold_db"}
                else {}
            ),
        }
        for name, value in sorted(setting_values.items())
    )
    return {
        "dataset_id": DATASET,
        "scope": scope_payload(),
        "origin": origin,
        "method_code": method_code,
        "topology": {
            "structure_id": STRUCTURE,
            "structure_class": "BRIDGE",
            "component_id": COMPONENT,
            "component_class": "GIRDER",
            "area_id": "area-west-01",
            "point_id": "point-01",
            "location_id": LOCATION,
            "material_class": "REINFORCED_CONCRETE",
            "coordinates": {
                "reference": "bridge-local-grid-v1",
                "values": (
                    {"axis": "x", "value": "12.50", "dimension": "LENGTH", "unit": "m"},
                    {"axis": "y", "value": "3.25", "dimension": "LENGTH", "unit": "m"},
                    {"axis": "z", "value": "0.00", "dimension": "LENGTH", "unit": "m"},
                ),
            },
        },
        "source": {
            "source_name": f"-桥梁 西侧\n{method_code} 原始数据.ndt",
            "artifact": source_artifact,
            "media_type": source_artifact["media_type"],
            "source_sha256": source_artifact["sha256"],
            "parser_id": f"{method_code.lower()}-fixture-parser",
            "parser_version": "parser-1.0.0",
            "parser_configuration_sha256": digest("parser-config-v1"),
            "detected_encoding": "GB18030",
            "normalized_encoding": "UTF-8",
            "encoding_confidence": "0.99",
            "lossless": True,
        },
        "channels": (
            {
                "channel_index": 0,
                "channel_id": "channel-00",
                "point_id": "point-01",
                "name": "主通道",
                "sample_count": 1_000,
                "sample_rate_hz": "1000000.00",
                "first_sample_at": ACQUIRED_AT,
                "dimension": dimension,
                "unit": unit,
                "sample_encoding": "little-endian-int16",
                "data_artifact": channel_artifact,
                "byte_offset": 0,
                "byte_length": 2_000,
                "data_sha256": digest(f"{method_code}-channel-0"),
            },
            {
                "channel_index": 1,
                "channel_id": "channel-01",
                "point_id": "point-01",
                "name": "参考通道",
                "sample_count": 1_000,
                "sample_rate_hz": "1000000.00",
                "first_sample_at": ACQUIRED_AT,
                "dimension": dimension,
                "unit": unit,
                "sample_encoding": "little-endian-int16",
                "data_artifact": channel_artifact,
                "byte_offset": 2_000,
                "byte_length": 2_000,
                "data_sha256": digest(f"{method_code}-channel-1"),
            },
        ),
        "acquired_at": ACQUIRED_AT,
        "acquisition_settings": settings,
        "instrument": {
            "instrument_id": f"{method_code.lower()}-device-01",
            "manufacturer": "NDT Fixture Works",
            "model": f"{method_code}-SIM-1",
            "serial_number": f"SIM-{method_code}-0001",
            "instrument_version": "instrument-1.0.0",
            "firmware_version": "firmware-1.0.0",
            "adapter_id": f"{method_code.lower()}-reference-adapter",
            "adapter_version": "adapter-1.0.0",
            "adapter_registration_sha256": digest(f"{method_code}-adapter"),
        },
        "calibrations": (
            {
                "calibration_id": f"{method_code.lower()}-calibration-01",
                "calibration_version": "calibration-1.0.0",
                "calibration_kind": calibration_kind,
                "status": CalibrationStatus.ACTIVE,
                "instrument_id": f"{method_code.lower()}-device-01",
                "performed_at": ACQUIRED_AT - timedelta(days=2),
                "valid_from": ACQUIRED_AT - timedelta(days=1),
                "valid_until": ACQUIRED_AT + timedelta(days=30),
                "evidence_artifact": calibration_artifact,
                "evidence_sha256": calibration_artifact["sha256"],
            },
        ),
        "primary_calibration_id": f"{method_code.lower()}-calibration-01",
        "operator": {
            "operator_id": USER,
            "identity_version": "identity-1.0.0",
            "display_name": "张三",
            "organization": "示例检测机构",
            "qualifications": (f"NDT-{method_code}-LEVEL-2",),
        },
    }


@pytest.mark.parametrize("method_code", tuple(sorted(METHOD_SIGNAL)))
def test_six_method_round_trip_and_s4_projection(method_code: str) -> None:
    dataset = build_canonical_inspection_dataset(manifest_payload(method_code))

    encoded = dump_canonical_inspection_data(dataset)
    restored = load_canonical_inspection_data(encoded)
    validation = validate_canonical_inspection_dataset(restored)
    source = to_processing_source_manifest(restored)

    assert restored == dataset
    assert dump_canonical_inspection_data(restored) == encoded
    assert not encoded.startswith(b"\xef\xbb\xbf")
    assert "桥梁" in encoded.decode("utf-8")
    assert b'"samples"' not in encoded
    assert restored.source.source_name == f"-桥梁 西侧\n{method_code} 原始数据.ndt"
    assert restored.manifest_sha256 == canonical_inspection_dataset_sha256(restored)
    assert validation.processing_eligible
    assert validation.formal_use_eligible
    assert validation.validation_sha256 == canonical_validation_result_sha256(validation)
    assert source.dataset_sha256 == restored.manifest_sha256
    assert source.channel_count == 2
    validate_processing_source_manifest(
        restored,
        source,
        parser_version=restored.source.parser_version,
    )


def test_manifest_hash_is_stable_for_equivalent_input_mapping_order() -> None:
    payload = manifest_payload()
    reversed_payload = dict(reversed(tuple(payload.items())))

    first = build_canonical_inspection_dataset(payload)
    second = build_canonical_inspection_dataset(reversed_payload)

    assert first == second
    assert first.manifest_sha256 == second.manifest_sha256


@pytest.mark.parametrize("method_code", tuple(sorted(METHOD_SETTINGS)))
def test_missing_method_specific_acquisition_setting_is_rejected(method_code: str) -> None:
    payload = manifest_payload(method_code)
    missing_name = sorted(METHOD_SETTINGS[method_code])[0]
    payload["acquisition_settings"] = tuple(
        item
        for item in cast(tuple[dict[str, object], ...], payload["acquisition_settings"])
        if item["name"] != missing_name
    )

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


@pytest.mark.parametrize(
    ("payload", "code"),
    (
        (b"\xef\xbb\xbf{}", "CANONICAL_ENCODING_INVALID"),
        (b"\xff", "CANONICAL_PAYLOAD_INVALID"),
        (b'{"value":NaN}', "CANONICAL_NON_FINITE_NUMBER"),
        (b'{"schema_version":"1.0.0","schema_version":"1.0.0"}', "CANONICAL_DUPLICATE_KEY"),
    ),
)
def test_codec_rejects_bom_malformed_duplicate_and_non_finite_json(
    payload: bytes,
    code: str,
) -> None:
    with pytest.raises(CanonicalInspectionDataError) as caught:
        load_canonical_inspection_data(payload)

    assert caught.value.code == code
    assert caught.value.next_action


def test_codec_rejects_unknown_fields_and_tampered_hash() -> None:
    dataset = build_canonical_inspection_dataset(manifest_payload())
    decoded = json.loads(dump_canonical_inspection_data(dataset))
    decoded["unknown"] = "forbidden"

    with pytest.raises(CanonicalInspectionDataError) as unknown:
        load_canonical_inspection_data(json.dumps(decoded).encode())
    assert unknown.value.code == "CANONICAL_PAYLOAD_INVALID"

    decoded.pop("unknown")
    decoded["manifest_sha256"] = "f" * 64
    with pytest.raises(CanonicalInspectionDataError) as changed:
        load_canonical_inspection_data(json.dumps(decoded).encode())
    assert changed.value.code == "CANONICAL_PAYLOAD_INVALID"


@pytest.mark.parametrize("target", ("source", "channel", "calibration"))
def test_mutable_artifact_is_rejected(target: str) -> None:
    payload = manifest_payload()
    if target == "source":
        payload["source"]["artifact"]["immutable"] = False  # type: ignore[index]
    elif target == "channel":
        payload["channels"][0]["data_artifact"]["immutable"] = False  # type: ignore[index]
    else:
        payload["calibrations"][0]["evidence_artifact"]["immutable"] = False  # type: ignore[index]

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


@pytest.mark.parametrize("target", ("source", "channel", "calibration"))
def test_cross_scope_artifact_is_rejected(target: str) -> None:
    payload = manifest_payload()
    other_scope = scope_payload(tenant_id=UUID("50000000-0000-4000-8000-000000000099"))
    if target == "source":
        payload["source"]["artifact"]["scope"] = other_scope  # type: ignore[index]
    elif target == "channel":
        payload["channels"][0]["data_artifact"]["scope"] = other_scope  # type: ignore[index]
    else:
        payload["calibrations"][0]["evidence_artifact"]["scope"] = other_scope  # type: ignore[index]

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("channels", 1, "channel_index"), 2),
        (("channels", 1, "channel_id"), "channel-00"),
        (("channels", 1, "point_id"), "point-02"),
        (("channels", 1, "sample_count"), 999),
        (("channels", 1, "sample_rate_hz"), "500000"),
        (("channels", 1, "unit"), "dB"),
        (("channels", 1, "first_sample_at"), ACQUIRED_AT + timedelta(seconds=1)),
    ),
)
def test_channel_identity_and_homogeneous_sampling_fail_closed(
    path: tuple[str, int, str],
    value: object,
) -> None:
    payload = manifest_payload()
    collection, index, field = path
    payload[collection][index][field] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


@pytest.mark.parametrize(
    ("offset", "length"),
    ((1_999, 2_000), (3_000, 2_000)),
)
def test_channel_overlap_and_artifact_overflow_are_rejected(offset: int, length: int) -> None:
    payload = manifest_payload()
    payload["channels"][1]["byte_offset"] = offset  # type: ignore[index]
    payload["channels"][1]["byte_length"] = length  # type: ignore[index]

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


def test_reused_immutable_artifact_identity_cannot_change_metadata() -> None:
    payload = manifest_payload()
    changed = copy.deepcopy(payload["channels"][1]["data_artifact"])  # type: ignore[index]
    changed["sha256"] = "f" * 64
    payload["channels"][1]["data_artifact"] = changed  # type: ignore[index]

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


@pytest.mark.parametrize(
    ("mutation", "value"),
    (
        ("method_code", "PAUT"),
        ("coordinate_unit", "inch"),
        ("channel_unit", "inch"),
        ("acquired_at", datetime(2026, 8, 25, 14, 30, tzinfo=timezone(timedelta(hours=8)))),
    ),
)
def test_method_unit_and_utc_contracts_are_strict(mutation: str, value: object) -> None:
    payload = manifest_payload()
    if mutation == "method_code":
        payload["method_code"] = value
    elif mutation == "coordinate_unit":
        payload["topology"]["coordinates"]["values"][0]["unit"] = value  # type: ignore[index]
    elif mutation == "channel_unit":
        payload["channels"][0]["unit"] = value  # type: ignore[index]
        payload["channels"][1]["unit"] = value  # type: ignore[index]
    else:
        payload["acquired_at"] = value
        payload["channels"][0]["first_sample_at"] = value  # type: ignore[index]
        payload["channels"][1]["first_sample_at"] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


@pytest.mark.parametrize(
    "mutation",
    ("unsorted", "duplicate", "missing", "structure_mismatch", "calibration_mismatch"),
)
def test_acquisition_settings_are_canonical_and_bound(mutation: str) -> None:
    payload = manifest_payload()
    settings = list(cast(tuple[dict[str, object], ...], payload["acquisition_settings"]))
    if mutation == "unsorted":
        settings.reverse()
    elif mutation == "duplicate":
        settings.insert(1, copy.deepcopy(settings[0]))
    elif mutation == "missing":
        settings = [item for item in settings if item["name"] != "material_class"]
    elif mutation == "structure_mismatch":
        next(item for item in settings if item["name"] == "structure_class")["value"] = "ROAD"
    else:
        next(item for item in settings if item["name"] == "calibration_kind")["value"] = (
            "SYSTEM_CALIBRATION"
        )
    payload["acquisition_settings"] = tuple(settings)

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


@pytest.mark.parametrize("status", tuple(CalibrationStatus))
def test_inactive_calibration_blocks_formal_use_but_preserves_review(
    status: CalibrationStatus,
) -> None:
    payload = manifest_payload()
    payload["calibrations"][0]["status"] = status  # type: ignore[index]
    dataset = build_canonical_inspection_dataset(payload)

    result = validate_canonical_inspection_dataset(dataset)

    assert result.processing_eligible
    assert result.formal_use_eligible is (status is CalibrationStatus.ACTIVE)
    if status is not CalibrationStatus.ACTIVE:
        assert {item.code for item in result.issues} == {"CANONICAL_CALIBRATION_INVALID"}


def test_out_of_interval_calibration_blocks_formal_use() -> None:
    payload = manifest_payload()
    payload["calibrations"][0]["valid_until"] = ACQUIRED_AT - timedelta(seconds=1)  # type: ignore[index]
    result = validate_canonical_inspection_dataset(build_canonical_inspection_dataset(payload))

    assert result.processing_eligible
    assert not result.formal_use_eligible
    assert "CANONICAL_CALIBRATION_INVALID" in {item.code for item in result.issues}


@pytest.mark.parametrize("origin", (DataOrigin.SIMULATED, DataOrigin.LABORATORY))
def test_non_production_origin_blocks_formal_use(origin: DataOrigin) -> None:
    result = validate_canonical_inspection_dataset(
        build_canonical_inspection_dataset(manifest_payload(origin=origin))
    )

    assert result.processing_eligible
    assert not result.formal_use_eligible
    assert {item.code for item in result.issues} == {"CANONICAL_ORIGIN_NOT_PRODUCTION"}


def test_missing_operator_qualification_blocks_formal_use() -> None:
    payload = manifest_payload()
    payload["operator"]["qualifications"] = ()  # type: ignore[index]
    result = validate_canonical_inspection_dataset(build_canonical_inspection_dataset(payload))

    assert result.processing_eligible
    assert not result.formal_use_eligible
    assert {item.code for item in result.issues} == {"CANONICAL_OPERATOR_UNQUALIFIED"}


@pytest.mark.parametrize(
    ("lossless", "confidence", "expected_codes"),
    (
        (False, "0.99", {"CANONICAL_SOURCE_LOSSY"}),
        (True, "0.50", {"CANONICAL_ENCODING_UNCERTAIN"}),
        (
            False,
            "0.50",
            {"CANONICAL_SOURCE_LOSSY", "CANONICAL_ENCODING_UNCERTAIN"},
        ),
    ),
)
def test_lossy_or_uncertain_source_blocks_processing(
    lossless: bool,
    confidence: str,
    expected_codes: set[str],
) -> None:
    payload = manifest_payload()
    payload["source"]["lossless"] = lossless  # type: ignore[index]
    payload["source"]["encoding_confidence"] = confidence  # type: ignore[index]
    dataset = build_canonical_inspection_dataset(payload)

    result = validate_canonical_inspection_dataset(dataset)

    assert not result.processing_eligible
    assert not result.formal_use_eligible
    assert {item.code for item in result.issues} == expected_codes
    with pytest.raises(CanonicalInspectionDataError) as caught:
        to_processing_source_manifest(dataset)
    assert caught.value.code == "CANONICAL_PROCESSING_INELIGIBLE"


def test_s4_source_or_parser_mismatch_is_typed() -> None:
    dataset = build_canonical_inspection_dataset(manifest_payload())
    source = to_processing_source_manifest(dataset)
    changed = ProcessingSourceManifest.model_validate(
        {**source.model_dump(mode="json"), "instrument_version": "changed"}
    )

    with pytest.raises(CanonicalInspectionDataError) as source_error:
        validate_processing_source_manifest(
            dataset,
            changed,
            parser_version=dataset.source.parser_version,
        )
    assert source_error.value.code == "CANONICAL_S4_SOURCE_MISMATCH"

    with pytest.raises(CanonicalInspectionDataError) as parser_error:
        validate_processing_source_manifest(dataset, source, parser_version="changed")
    assert parser_error.value.code == "CANONICAL_S4_SOURCE_MISMATCH"


@pytest.mark.parametrize(
    "mutation",
    ("calibration_order", "wrong_instrument", "missing_primary", "qualification_order"),
)
def test_sorted_calibration_and_operator_provenance_fail_closed(mutation: str) -> None:
    payload = manifest_payload()
    if mutation == "calibration_order":
        second = copy.deepcopy(payload["calibrations"][0])  # type: ignore[index]
        second["calibration_id"] = "aa-calibration"
        payload["calibrations"] = (payload["calibrations"][0], second)  # type: ignore[index]
    elif mutation == "wrong_instrument":
        payload["calibrations"][0]["instrument_id"] = "other-device"  # type: ignore[index]
    elif mutation == "missing_primary":
        payload["primary_calibration_id"] = "missing-calibration"
    else:
        payload["operator"]["qualifications"] = ("Z", "A")  # type: ignore[index]

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


@pytest.mark.parametrize("mutation", ("source_hash", "media_type", "calibration_hash", "nul_name"))
def test_source_and_calibration_evidence_identity_is_exact(mutation: str) -> None:
    payload = manifest_payload()
    if mutation == "source_hash":
        payload["source"]["source_sha256"] = "f" * 64  # type: ignore[index]
    elif mutation == "media_type":
        payload["source"]["media_type"] = "text/plain"  # type: ignore[index]
    elif mutation == "calibration_hash":
        payload["calibrations"][0]["evidence_sha256"] = "f" * 64  # type: ignore[index]
    else:
        payload["source"]["source_name"] = "bad\x00name"  # type: ignore[index]

    with pytest.raises(ValidationError):
        build_canonical_inspection_dataset(payload)


def test_scope_object_and_typed_setting_values_survive_round_trip() -> None:
    payload = manifest_payload()
    settings = list(cast(tuple[dict[str, object], ...], payload["acquisition_settings"]))
    settings.append({"name": "high_pass_enabled", "value": True})
    payload["acquisition_settings"] = tuple(
        sorted(settings, key=lambda item: cast(str, item["name"]))
    )
    restored = load_canonical_inspection_data(
        dump_canonical_inspection_data(build_canonical_inspection_dataset(payload))
    )

    assert isinstance(restored.scope, TenantScope)
    values = {item.name: item.value for item in restored.acquisition_settings}
    assert values["gain_db"] == 20
    assert values["high_pass_enabled"] is True
    assert restored.operator.display_name == "张三"
