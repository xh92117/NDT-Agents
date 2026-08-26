"""S5-06 canonical inspection-data contract, codec, and S4 source bridge."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from ndt_agents.contracts.v1 import ArtifactRef, Issue, StrictModel, TenantScope
from ndt_agents.professional.methods import default_method_definitions
from ndt_agents.professional.planning import is_registered_unit
from ndt_agents.professional.processing import (
    DataOrigin,
    ProcessingSourceManifest,
)
from ndt_agents.professional.qa import (
    SUPPORTED_MATERIALS,
    SUPPORTED_METHODS,
    SUPPORTED_STRUCTURES,
)

CANONICAL_INSPECTION_DATA_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_CANONICAL_MANIFEST_BYTES = 2_000_000
MIN_ENCODING_CONFIDENCE = Decimal("0.80")
_METHOD_ACQUISITION_SETTINGS = {
    item.method_code: frozenset(item.required_acquisition_settings)
    for item in default_method_definitions()
}


class CalibrationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    UNKNOWN = "UNKNOWN"


class CanonicalInspectionDataError(ValueError):
    """Stable canonical-data failure with a recovery action."""

    def __init__(self, code: str, message: str, *, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class CoordinateValue(StrictModel):
    axis: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    value: Decimal
    dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    unit: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_unit(self) -> Self:
        if not is_registered_unit(self.dimension, self.unit):
            raise ValueError("coordinate unit is not registered for its dimension")
        return self


class CoordinateSet(StrictModel):
    reference: str = Field(min_length=1, max_length=256)
    values: tuple[CoordinateValue, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_axes(self) -> Self:
        axes = tuple(item.axis for item in self.values)
        if axes != tuple(sorted(set(axes))):
            raise ValueError("coordinate axes must be sorted and unique")
        return self


class InspectionTopology(StrictModel):
    structure_id: UUID
    structure_class: str = Field(min_length=1, max_length=128)
    component_id: UUID
    component_class: str = Field(min_length=1, max_length=128)
    area_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
    point_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
    location_id: UUID
    material_class: str = Field(min_length=1, max_length=128)
    coordinates: CoordinateSet

    @model_validator(mode="after")
    def validate_ontology(self) -> Self:
        if self.structure_class not in SUPPORTED_STRUCTURES:
            raise ValueError("topology structure class is not registered")
        if self.material_class not in SUPPORTED_MATERIALS:
            raise ValueError("topology material class is not registered")
        return self


class AcquisitionSetting(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    value: bool | int | str
    dimension: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    unit: str | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_setting(self) -> Self:
        if (self.dimension is None) != (self.unit is None):
            raise ValueError("setting dimension and unit must be declared together")
        if self.dimension is not None and self.unit is not None:
            if not is_registered_unit(self.dimension, self.unit):
                raise ValueError("acquisition setting unit is not registered")
        return self


class InstrumentProvenance(StrictModel):
    instrument_id: str = Field(min_length=1, max_length=256)
    manufacturer: str = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=256)
    serial_number: str = Field(min_length=1, max_length=256)
    instrument_version: str = Field(min_length=1, max_length=128)
    firmware_version: str = Field(min_length=1, max_length=128)
    adapter_id: str = Field(min_length=1, max_length=256)
    adapter_version: str = Field(min_length=1, max_length=128)
    adapter_registration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CalibrationProvenance(StrictModel):
    calibration_id: str = Field(min_length=1, max_length=256)
    calibration_version: str = Field(min_length=1, max_length=128)
    calibration_kind: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    status: CalibrationStatus
    instrument_id: str = Field(min_length=1, max_length=256)
    performed_at: datetime
    valid_from: datetime
    valid_until: datetime
    evidence_artifact: ArtifactRef
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_calibration(self) -> Self:
        for value in (self.performed_at, self.valid_from, self.valid_until):
            _require_utc(value, "calibration times")
        if self.valid_from >= self.valid_until:
            raise ValueError("calibration validity interval is invalid")
        if self.performed_at > self.valid_until:
            raise ValueError("calibration was performed after its validity interval")
        if not self.evidence_artifact.immutable:
            raise ValueError("calibration evidence must be immutable")
        if self.evidence_sha256 != self.evidence_artifact.sha256:
            raise ValueError("calibration evidence hash must match its artifact")
        return self


class OperatorProvenance(StrictModel):
    operator_id: UUID
    identity_version: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    organization: str = Field(min_length=1, max_length=256)
    qualifications: tuple[str, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def validate_qualifications(self) -> Self:
        if self.qualifications != tuple(sorted(set(self.qualifications))):
            raise ValueError("operator qualifications must be sorted and unique")
        return self


class SourceProvenance(StrictModel):
    source_name: str = Field(min_length=1, max_length=4_096)
    artifact: ArtifactRef
    media_type: str = Field(min_length=1, max_length=255)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_id: str = Field(min_length=1, max_length=256)
    parser_version: str = Field(min_length=1, max_length=128)
    parser_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    detected_encoding: str = Field(min_length=1, max_length=64)
    normalized_encoding: Literal["UTF-8", "BINARY"]
    encoding_confidence: Decimal = Field(ge=0, le=1)
    lossless: bool

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if "\x00" in self.source_name:
            raise ValueError("source name cannot contain NUL")
        if not self.artifact.immutable:
            raise ValueError("canonical source artifact must be immutable")
        if self.media_type != self.artifact.media_type:
            raise ValueError("source media type must match its artifact")
        if self.source_sha256 != self.artifact.sha256:
            raise ValueError("source hash must match its immutable artifact")
        return self


class InspectionChannel(StrictModel):
    channel_index: int = Field(ge=0, le=65_535)
    channel_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
    point_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
    name: str = Field(min_length=1, max_length=256)
    sample_count: int = Field(ge=1, le=1_000_000_000)
    sample_rate_hz: Decimal = Field(gt=0, le=Decimal("1000000000000"))
    first_sample_at: datetime
    dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    unit: str = Field(min_length=1, max_length=32)
    sample_encoding: str = Field(min_length=1, max_length=128)
    data_artifact: ArtifactRef
    byte_offset: int = Field(ge=0)
    byte_length: int = Field(ge=1)
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_channel(self) -> Self:
        _require_utc(self.first_sample_at, "channel time origin")
        if not is_registered_unit(self.dimension, self.unit):
            raise ValueError("channel unit is not registered for its dimension")
        if not self.data_artifact.immutable:
            raise ValueError("channel data artifact must be immutable")
        if self.byte_offset + self.byte_length > self.data_artifact.size_bytes:
            raise ValueError("channel byte range exceeds its immutable artifact")
        return self


class CanonicalInspectionContent(StrictModel):
    schema_version: Literal["1.0.0"] = CANONICAL_INSPECTION_DATA_VERSION
    dataset_id: UUID
    scope: TenantScope
    origin: DataOrigin
    method_code: str = Field(min_length=1, max_length=32)
    topology: InspectionTopology
    source: SourceProvenance
    channels: tuple[InspectionChannel, ...] = Field(min_length=1, max_length=65_536)
    acquired_at: datetime
    acquisition_settings: tuple[AcquisitionSetting, ...] = Field(min_length=1, max_length=128)
    instrument: InstrumentProvenance
    calibrations: tuple[CalibrationProvenance, ...] = Field(min_length=1, max_length=64)
    primary_calibration_id: str = Field(min_length=1, max_length=256)
    operator: OperatorProvenance

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        _require_utc(self.acquired_at, "acquisition time")
        if self.method_code not in SUPPORTED_METHODS:
            raise ValueError("canonical method is not registered")
        if self.source.artifact.scope != self.scope:
            raise ValueError("canonical source artifact must use the exact scope")
        artifact_identities = {self.source.artifact.artifact_id: self.source.artifact}

        indexes = tuple(item.channel_index for item in self.channels)
        if indexes != tuple(range(len(self.channels))):
            raise ValueError("channel indexes must be contiguous, sorted, and zero-based")
        channel_ids = tuple(item.channel_id for item in self.channels)
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("channel identities must be unique")

        first = self.channels[0]
        for channel in self.channels:
            if channel.data_artifact.scope != self.scope:
                raise ValueError("channel artifact must use the exact scope")
            _bind_artifact_identity(artifact_identities, channel.data_artifact)
            if channel.point_id != self.topology.point_id:
                raise ValueError("channel point must match canonical topology")
            if channel.first_sample_at != self.acquired_at:
                raise ValueError("channel time origin must match acquisition time")
            if (
                channel.sample_count != first.sample_count
                or channel.sample_rate_hz != first.sample_rate_hz
                or channel.dimension != first.dimension
                or channel.unit != first.unit
            ):
                raise ValueError("V1 channels must use homogeneous sampling and signal units")
        _validate_non_overlapping_channel_ranges(self.channels)

        setting_names = tuple(item.name for item in self.acquisition_settings)
        if setting_names != tuple(sorted(set(setting_names))):
            raise ValueError("acquisition settings must be sorted and unique")
        settings = {item.name: item.value for item in self.acquisition_settings}
        required_settings = _METHOD_ACQUISITION_SETTINGS[self.method_code]
        if not required_settings.issubset(settings):
            raise ValueError("canonical acquisition settings are incomplete")
        if settings["structure_class"] != self.topology.structure_class:
            raise ValueError("acquisition structure class must match topology")
        if settings["material_class"] != self.topology.material_class:
            raise ValueError("acquisition material class must match topology")

        calibration_ids = tuple(item.calibration_id for item in self.calibrations)
        if calibration_ids != tuple(sorted(set(calibration_ids))):
            raise ValueError("calibration identities must be sorted and unique")
        by_id = {item.calibration_id: item for item in self.calibrations}
        if self.primary_calibration_id not in by_id:
            raise ValueError("primary calibration must exist in the manifest")
        for calibration in self.calibrations:
            if calibration.instrument_id != self.instrument.instrument_id:
                raise ValueError("calibration instrument must match dataset instrument")
            if calibration.evidence_artifact.scope != self.scope:
                raise ValueError("calibration evidence must use the exact scope")
            _bind_artifact_identity(artifact_identities, calibration.evidence_artifact)
        if settings["calibration_kind"] != by_id[self.primary_calibration_id].calibration_kind:
            raise ValueError("acquisition calibration kind must match the primary calibration")
        return self


class CanonicalInspectionDataset(CanonicalInspectionContent):
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest_hash(self) -> Self:
        if self.manifest_sha256 != canonical_inspection_dataset_sha256(self):
            raise ValueError("canonical inspection-data manifest hash is invalid")
        return self


class CanonicalDataValidationResult(StrictModel):
    schema_version: Literal["1.0.0"] = CANONICAL_INSPECTION_DATA_VERSION
    dataset_id: UUID
    scope: TenantScope
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    processing_eligible: bool
    formal_use_eligible: bool
    issues: tuple[Issue, ...] = Field(max_length=256)
    review_required: Literal[True] = True
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result_hash(self) -> Self:
        if self.formal_use_eligible and not self.processing_eligible:
            raise ValueError("formal use requires processing eligibility")
        if self.validation_sha256 != canonical_validation_result_sha256(self):
            raise ValueError("canonical validation-result hash is invalid")
        return self


def build_canonical_inspection_dataset(
    payload: Mapping[str, object],
) -> CanonicalInspectionDataset:
    """Validate content first, then attach its deterministic manifest hash."""

    content = CanonicalInspectionContent.model_validate(dict(payload))
    encoded = content.model_dump(mode="json")
    return CanonicalInspectionDataset.model_validate(
        {**encoded, "manifest_sha256": _canonical_sha256(encoded)}
    )


def canonical_inspection_dataset_sha256(dataset: CanonicalInspectionDataset) -> str:
    return _canonical_sha256(dataset.model_dump(mode="json", exclude={"manifest_sha256"}))


def canonical_validation_result_sha256(result: CanonicalDataValidationResult) -> str:
    return _canonical_sha256(result.model_dump(mode="json", exclude={"validation_sha256"}))


def dump_canonical_inspection_data(dataset: CanonicalInspectionDataset) -> bytes:
    """Return canonical UTF-8 JSON without a BOM."""

    if dataset.manifest_sha256 != canonical_inspection_dataset_sha256(dataset):
        raise CanonicalInspectionDataError(
            "CANONICAL_MANIFEST_INVALID",
            "The canonical inspection-data manifest hash changed.",
            next_action="Rebuild the manifest from validated immutable source evidence.",
        )
    encoded = _canonical_json(dataset.model_dump(mode="json")).encode("utf-8")
    if len(encoded) > MAX_CANONICAL_MANIFEST_BYTES:
        raise CanonicalInspectionDataError(
            "CANONICAL_MANIFEST_TOO_LARGE",
            "The canonical inspection-data manifest exceeds its byte limit.",
            next_action="Move sample data to immutable artifacts and keep only bounded locators.",
        )
    return encoded


def load_canonical_inspection_data(payload: bytes) -> CanonicalInspectionDataset:
    """Parse bounded duplicate-safe UTF-8 JSON and revalidate its manifest hash."""

    if len(payload) > MAX_CANONICAL_MANIFEST_BYTES:
        raise CanonicalInspectionDataError(
            "CANONICAL_MANIFEST_TOO_LARGE",
            "The canonical inspection-data payload exceeds its byte limit.",
            next_action="Provide a bounded manifest without inline samples.",
        )
    if payload.startswith(b"\xef\xbb\xbf"):
        raise CanonicalInspectionDataError(
            "CANONICAL_ENCODING_INVALID",
            "Canonical inspection data must use UTF-8 without BOM.",
            next_action="Remove the BOM without changing decoded text and retry validation.",
        )
    try:
        text = payload.decode("utf-8", errors="strict")
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=Decimal,
            parse_constant=_reject_non_finite,
        )
        if not isinstance(decoded, dict):
            raise ValueError("canonical inspection data must be a JSON object")
        return CanonicalInspectionDataset.model_validate(decoded)
    except CanonicalInspectionDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
        raise CanonicalInspectionDataError(
            "CANONICAL_PAYLOAD_INVALID",
            "Canonical inspection data is malformed or violates its strict contract.",
            next_action="Provide duplicate-free UTF-8 JSON generated from the V1 contract.",
        ) from error


def validate_canonical_inspection_dataset(
    dataset: CanonicalInspectionDataset,
) -> CanonicalDataValidationResult:
    """Return deterministic processing and formal-use eligibility evidence."""

    issues: list[Issue] = []
    processing_eligible = True
    if not dataset.source.lossless:
        processing_eligible = False
        issues.append(
            _issue(
                "CANONICAL_SOURCE_LOSSY",
                "CRITICAL",
                "Source normalization was not lossless.",
                "source.lossless",
                "Return to the original immutable source and select a lossless parser path.",
            )
        )
    if dataset.source.encoding_confidence < MIN_ENCODING_CONFIDENCE:
        processing_eligible = False
        issues.append(
            _issue(
                "CANONICAL_ENCODING_UNCERTAIN",
                "CRITICAL",
                "Source encoding confidence is below the processing threshold.",
                "source.encoding_confidence",
                "Record a user-selected encoding or complete manual encoding review.",
            )
        )

    formal_use_eligible = processing_eligible
    if dataset.origin is not DataOrigin.PRODUCTION:
        formal_use_eligible = False
        issues.append(
            _issue(
                "CANONICAL_ORIGIN_NOT_PRODUCTION",
                "WARNING",
                "Simulated or laboratory data cannot support formal use.",
                "origin",
                "Acquire production evidence through an authorized calibrated device.",
            )
        )
    if not dataset.operator.qualifications:
        formal_use_eligible = False
        issues.append(
            _issue(
                "CANONICAL_OPERATOR_UNQUALIFIED",
                "CRITICAL",
                "No operator qualification is declared for the acquisition.",
                "operator.qualifications",
                "Bind an approved, current operator qualification for human review.",
            )
        )
    for index, calibration in enumerate(dataset.calibrations):
        if (
            calibration.status is not CalibrationStatus.ACTIVE
            or not calibration.valid_from <= dataset.acquired_at <= calibration.valid_until
        ):
            formal_use_eligible = False
            issues.append(
                _issue(
                    "CANONICAL_CALIBRATION_INVALID",
                    "CRITICAL",
                    "Calibration is inactive or does not cover acquisition time.",
                    f"calibrations.{index}",
                    "Reacquire with valid calibration or obtain qualified human disposition.",
                )
            )

    ordered = tuple(
        sorted(issues, key=lambda item: (item.code, item.affected_path or "", item.message))
    )
    result_payload: dict[str, object] = {
        "schema_version": CANONICAL_INSPECTION_DATA_VERSION,
        "dataset_id": dataset.dataset_id,
        "scope": dataset.scope,
        "manifest_sha256": dataset.manifest_sha256,
        "processing_eligible": processing_eligible,
        "formal_use_eligible": formal_use_eligible,
        "issues": ordered,
        "review_required": True,
    }
    return CanonicalDataValidationResult.model_validate(
        {
            **result_payload,
            "validation_sha256": _canonical_sha256(_jsonable(result_payload)),
        }
    )


def to_processing_source_manifest(
    dataset: CanonicalInspectionDataset,
) -> ProcessingSourceManifest:
    """Project the exact shared canonical subset into the S4-04 source contract."""

    validation = validate_canonical_inspection_dataset(dataset)
    if not validation.processing_eligible:
        raise CanonicalInspectionDataError(
            "CANONICAL_PROCESSING_INELIGIBLE",
            "Canonical inspection data is not eligible for S4 processing.",
            next_action="Resolve the canonical validation issues before creating a processing run.",
        )
    primary_channel = dataset.channels[0]
    calibration = next(
        item
        for item in dataset.calibrations
        if item.calibration_id == dataset.primary_calibration_id
    )
    settings = {item.name: item.value for item in dataset.acquisition_settings}
    return ProcessingSourceManifest(
        dataset_id=dataset.dataset_id,
        scope=dataset.scope,
        artifact=dataset.source.artifact,
        dataset_sha256=dataset.manifest_sha256,
        origin=dataset.origin,
        method_code=dataset.method_code,
        structure_id=dataset.topology.structure_id,
        component_id=dataset.topology.component_id,
        location_id=dataset.topology.location_id,
        coordinate_reference=dataset.topology.coordinates.reference,
        channel_count=len(dataset.channels),
        sample_count=primary_channel.sample_count,
        sample_rate_hz=primary_channel.sample_rate_hz,
        signal_dimension=primary_channel.dimension,
        signal_unit=primary_channel.unit,
        acquisition_settings=settings,
        instrument_id=dataset.instrument.instrument_id,
        instrument_version=dataset.instrument.instrument_version,
        calibration_id=calibration.calibration_id,
        calibration_version=calibration.calibration_version,
        calibration_valid_from=calibration.valid_from,
        calibration_valid_until=calibration.valid_until,
        operator_id=dataset.operator.operator_id,
        acquired_at=dataset.acquired_at,
    )


def validate_processing_source_manifest(
    dataset: CanonicalInspectionDataset,
    source: ProcessingSourceManifest,
    *,
    parser_version: str,
) -> None:
    """Fail closed when an S4 source does not equal the canonical projection."""

    expected = to_processing_source_manifest(dataset)
    if source != expected or parser_version != dataset.source.parser_version:
        raise CanonicalInspectionDataError(
            "CANONICAL_S4_SOURCE_MISMATCH",
            "The S4 processing source or parser does not match the canonical manifest.",
            next_action="Recreate the S4 source from the exact canonical manifest.",
        )


def _validate_non_overlapping_channel_ranges(
    channels: tuple[InspectionChannel, ...],
) -> None:
    by_artifact: dict[UUID, list[tuple[int, int]]] = {}
    for channel in channels:
        by_artifact.setdefault(channel.data_artifact.artifact_id, []).append(
            (channel.byte_offset, channel.byte_offset + channel.byte_length)
        )
    for ranges in by_artifact.values():
        ordered = sorted(ranges)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current[0] < previous[1]:
                raise ValueError("channel byte ranges cannot overlap within one artifact")


def _bind_artifact_identity(
    identities: dict[UUID, ArtifactRef],
    artifact: ArtifactRef,
) -> None:
    prior = identities.get(artifact.artifact_id)
    if prior is not None and prior != artifact:
        raise ValueError("one immutable artifact identity cannot have conflicting metadata")
    identities[artifact.artifact_id] = artifact


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{label} must use UTC")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalInspectionDataError(
                "CANONICAL_DUPLICATE_KEY",
                "Canonical inspection data contains a duplicate JSON key.",
                next_action="Regenerate the manifest with unique object fields.",
            )
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise CanonicalInspectionDataError(
        "CANONICAL_NON_FINITE_NUMBER",
        f"Canonical inspection data contains non-finite number {value}.",
        next_action="Use finite Decimal values only.",
    )


def _issue(
    code: str,
    severity: Literal["INFO", "WARNING", "ERROR", "CRITICAL"],
    message: str,
    affected_path: str,
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
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise CanonicalInspectionDataError(
            "CANONICAL_VALUE_INVALID",
            "Canonical inspection data contains a non-JSON value.",
            next_action="Use only strict V1 contract values.",
        ) from error


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
