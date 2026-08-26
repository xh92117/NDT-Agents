"""S5-07 inspection-model profiles and deterministic applicability registry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel
from ndt_agents.inspection_data import CanonicalInspectionDataset
from ndt_agents.models.registry import (
    CatalogOrigin,
    ModelApiRegistry,
    ResolvedModelRoute,
    canonical_sha256,
)
from ndt_agents.professional.qa import (
    SUPPORTED_MATERIALS,
    SUPPORTED_METHODS,
    SUPPORTED_STRUCTURES,
)

INSPECTION_MODEL_PROFILE_VERSION: Literal["1.0.0"] = "1.0.0"


class ModelEvidenceOrigin(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    LABORATORY = "LABORATORY"
    PRODUCTION = "PRODUCTION"
    EXTERNAL = "EXTERNAL"


class MetricThresholdDirection(StrEnum):
    MINIMUM = "MINIMUM"
    MAXIMUM = "MAXIMUM"


class ModelRuntimeKind(StrEnum):
    HOSTED_API = "HOSTED_API"
    LOCAL_LIBRARY = "LOCAL_LIBRARY"
    LOCAL_PROCESS = "LOCAL_PROCESS"
    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"


class ModelReportEligibility(StrEnum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    PRELIMINARY_REVIEW = "PRELIMINARY_REVIEW"
    FORMAL_HUMAN_REQUIRED = "FORMAL_HUMAN_REQUIRED"


class ModelEvidenceScope(StrictModel):
    scope_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    origin: ModelEvidenceOrigin
    method_codes: tuple[str, ...] = Field(min_length=1, max_length=64)
    structure_classes: tuple[str, ...] = Field(min_length=1, max_length=64)
    material_classes: tuple[str, ...] = Field(min_length=1, max_length=64)
    record_count: int = Field(ge=1, le=1_000_000_000)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_verified: bool
    deidentified: bool
    evaluated_on: date

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        _require_sorted_registered(self.method_codes, SUPPORTED_METHODS, "method")
        _require_sorted_registered(self.structure_classes, SUPPORTED_STRUCTURES, "structure")
        _require_sorted_registered(self.material_classes, SUPPORTED_MATERIALS, "material")
        return self


class ModelMetricThreshold(StrictModel):
    metric: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    direction: MetricThresholdDirection
    value: Decimal


class ModelRuntimeProfile(StrictModel):
    kind: ModelRuntimeKind
    runtime_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    runtime_version: str = Field(min_length=1, max_length=128)
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    precision: str = Field(min_length=1, max_length=64)
    deterministic: bool
    network_required: bool

    @model_validator(mode="after")
    def validate_runtime(self) -> Self:
        if self.kind is ModelRuntimeKind.HOSTED_API:
            if not self.network_required or self.artifact_sha256 is not None:
                raise ValueError("hosted runtime must use network and no local artifact")
        elif self.network_required or self.artifact_sha256 is None:
            raise ValueError("local or fixture runtime requires a pinned artifact and no network")
        if self.kind is ModelRuntimeKind.DETERMINISTIC_FIXTURE and not self.deterministic:
            raise ValueError("deterministic fixture runtime must be deterministic")
        return self


class ModelResourceProfile(StrictModel):
    cpu_cores: int = Field(ge=1, le=1_024)
    memory_mb: int = Field(ge=1, le=16_777_216)
    accelerator: str | None = Field(default=None, max_length=128)
    accelerator_memory_mb: int = Field(default=0, ge=0, le=16_777_216)
    max_concurrency: int = Field(ge=1, le=64)
    max_output_bytes: int = Field(ge=1, le=100_000_000)

    @model_validator(mode="after")
    def validate_accelerator(self) -> Self:
        if (self.accelerator is None) != (self.accelerator_memory_mb == 0):
            raise ValueError("accelerator identity and memory must be declared together")
        return self


class InspectionModelProfile(StrictModel):
    schema_version: Literal["1.0.0"] = INSPECTION_MODEL_PROFILE_VERSION
    origin: Literal[CatalogOrigin.APPLICATION] = CatalogOrigin.APPLICATION
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    profile_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    model_snapshot: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    method_codes: tuple[str, ...] = Field(min_length=1, max_length=64)
    structure_classes: tuple[str, ...] = Field(min_length=1, max_length=64)
    material_classes: tuple[str, ...] = Field(min_length=1, max_length=64)
    input_schema_id: Literal["canonical-inspection-data@1.0.0"] = "canonical-inspection-data@1.0.0"
    input_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
    output_schema: dict[str, Any]
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_scope: ModelEvidenceScope
    validation_scope: ModelEvidenceScope
    thresholds: tuple[ModelMetricThreshold, ...] = Field(min_length=1, max_length=64)
    runtime: ModelRuntimeProfile
    resources: ModelResourceProfile
    declared_error_codes: tuple[str, ...] = Field(max_length=64)
    retryable_error_codes: tuple[str, ...] = Field(max_length=64)
    report_eligibility: ModelReportEligibility
    independently_validated: bool
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        _require_sorted_registered(self.method_codes, SUPPORTED_METHODS, "method")
        _require_sorted_registered(self.structure_classes, SUPPORTED_STRUCTURES, "structure")
        _require_sorted_registered(self.material_classes, SUPPORTED_MATERIALS, "material")
        if not set(self.method_codes).issubset(self.validation_scope.method_codes):
            raise ValueError("profile methods must be covered by validation scope")
        if not set(self.structure_classes).issubset(self.validation_scope.structure_classes):
            raise ValueError("profile structures must be covered by validation scope")
        if not set(self.material_classes).issubset(self.validation_scope.material_classes):
            raise ValueError("profile materials must be covered by validation scope")
        if self.input_schema_sha256 != canonical_inspection_input_schema_sha256():
            raise ValueError("profile canonical input schema hash is invalid")
        _validate_output_schema(self.output_schema)
        if self.output_schema_sha256 != canonical_sha256(self.output_schema):
            raise ValueError("profile output schema hash is invalid")
        metrics = tuple(item.metric for item in self.thresholds)
        if metrics != tuple(sorted(set(metrics))):
            raise ValueError("model thresholds must be sorted and unique")
        if self.declared_error_codes != tuple(sorted(set(self.declared_error_codes))):
            raise ValueError("declared provider errors must be sorted and unique")
        if self.retryable_error_codes != tuple(sorted(set(self.retryable_error_codes))):
            raise ValueError("retryable provider errors must be sorted and unique")
        if not set(self.retryable_error_codes).issubset(self.declared_error_codes):
            raise ValueError("retryable provider errors must be declared")
        if self.report_eligibility is ModelReportEligibility.FORMAL_HUMAN_REQUIRED:
            if (
                not self.independently_validated
                or not self.validation_scope.rights_verified
                or not self.validation_scope.deidentified
                or self.validation_scope.origin is not ModelEvidenceOrigin.PRODUCTION
            ):
                raise ValueError(
                    "formal profile requires independent, rights-verified production validation"
                )
        if self.profile_sha256 != inspection_model_profile_sha256(self):
            raise ValueError("inspection-model profile hash is invalid")
        return self


class InspectionModelProfileRegistry:
    """Bind inspection profiles to exact entries in the API registry."""

    def __init__(
        self,
        api_registry: ModelApiRegistry,
        profiles: Sequence[InspectionModelProfile],
    ) -> None:
        if not profiles:
            raise InspectionModelProfileError(
                "MODEL_PROFILE_REGISTRY_EMPTY",
                "At least one inspection-model profile is required.",
                next_action="Publish a validated application-owned profile.",
            )
        catalog_models = {
            (item.provider_id, item.model_id): item for item in api_registry.catalog.models
        }
        by_id: dict[str, InspectionModelProfile] = {}
        for profile in profiles:
            if profile.profile_id in by_id:
                raise InspectionModelProfileError(
                    "MODEL_PROFILE_DUPLICATE",
                    "The inspection-model profile ID is duplicated.",
                    next_action="Publish one immutable version per profile ID.",
                )
            model = catalog_models.get((profile.provider_id, profile.model_id))
            if model is None or model.model_snapshot != profile.model_snapshot:
                raise InspectionModelProfileError(
                    "MODEL_PROFILE_CATALOG_MISMATCH",
                    "The inspection profile does not bind an exact catalog model snapshot.",
                    next_action="Use the current provider, model ID, and model snapshot.",
                )
            by_id[profile.profile_id] = profile
        self._api_registry = api_registry
        self._profiles = by_id
        self._version = canonical_sha256(
            {
                "api_registry_version": api_registry.version,
                "profiles": [by_id[key].model_dump(mode="json") for key in sorted(by_id)],
            }
        )

    @property
    def version(self) -> str:
        return self._version

    @property
    def profiles(self) -> tuple[InspectionModelProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    @property
    def api_registry(self) -> ModelApiRegistry:
        return self._api_registry

    def resolve(
        self,
        *,
        profile_id: str,
        expected_registry_version: str,
        expected_profile_sha256: str,
        route: ResolvedModelRoute,
        dataset: CanonicalInspectionDataset,
    ) -> InspectionModelProfile:
        if expected_registry_version != self.version:
            raise InspectionModelProfileError(
                "MODEL_PROFILE_REGISTRY_STALE",
                "The inspection-model profile registry is stale.",
                next_action="Refresh the exact profile registry snapshot.",
            )
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise InspectionModelProfileError(
                "MODEL_PROFILE_NOT_FOUND",
                "The inspection-model profile is not published.",
                next_action="Use a profile from the current registry snapshot.",
            )
        if expected_profile_sha256 != profile.profile_sha256:
            raise InspectionModelProfileError(
                "MODEL_PROFILE_STALE",
                "The requested inspection-model profile hash is stale.",
                next_action="Use the exact current profile hash.",
            )
        if (
            route.provider_id != profile.provider_id
            or route.model_id != profile.model_id
            or route.model_snapshot != profile.model_snapshot
        ):
            raise InspectionModelProfileError(
                "MODEL_PROFILE_ROUTE_MISMATCH",
                "The authorized route does not match the inspection-model profile.",
                next_action="Resolve a route for the exact profiled provider and model snapshot.",
            )
        if (
            dataset.method_code not in profile.method_codes
            or dataset.topology.structure_class not in profile.structure_classes
            or dataset.topology.material_class not in profile.material_classes
        ):
            raise InspectionModelProfileError(
                "MODEL_PROFILE_NOT_APPLICABLE",
                "The inspection-model profile does not cover this canonical dataset.",
                next_action=(
                    "Select a validated profile for the exact method, structure, and material."
                ),
            )
        return profile


class InspectionModelProfileError(RuntimeError):
    def __init__(self, code: str, message: str, *, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


def canonical_inspection_input_schema_sha256() -> str:
    return canonical_sha256(CanonicalInspectionDataset.model_json_schema())


def inspection_model_profile_sha256(profile: InspectionModelProfile) -> str:
    return canonical_sha256(profile.model_dump(mode="json", exclude={"profile_sha256"}))


def build_inspection_model_profile(
    payload: Mapping[str, object],
) -> InspectionModelProfile:
    content = dict(payload)
    content.pop("profile_sha256", None)
    content.setdefault("schema_version", INSPECTION_MODEL_PROFILE_VERSION)
    content.setdefault("origin", CatalogOrigin.APPLICATION)
    content.setdefault("input_schema_id", "canonical-inspection-data@1.0.0")
    content["profile_sha256"] = canonical_sha256(_profile_json(content))
    return InspectionModelProfile.model_validate(content)


def _profile_json(value: object) -> object:
    if isinstance(value, StrictModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _profile_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_profile_json(item) for item in value]
    if isinstance(value, (StrEnum, date, datetime, Decimal)):
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    return value


def _require_sorted_registered(
    values: tuple[str, ...],
    registry: frozenset[str],
    label: str,
) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"profile {label} values must be sorted and unique")
    if not set(values).issubset(registry):
        raise ValueError(f"profile {label} value is not registered")


def _validate_output_schema(schema: dict[str, Any]) -> None:
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError("model output schema must be a strict object")
    if not isinstance(schema.get("properties"), dict) or not isinstance(
        schema.get("required"), list
    ):
        raise ValueError("model output schema requires properties and required fields")
    _reject_external_references(schema, schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError("model output schema is invalid") from error


def _reject_external_references(value: object, root: Mapping[str, object]) -> None:
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if reference is not None and (
            not isinstance(reference, str) or not reference.startswith("#/")
        ):
            raise ValueError("model output schema references must remain local")
        if isinstance(reference, str):
            _resolve_local_reference(root, reference)
        for item in value.values():
            _reject_external_references(item, root)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_external_references(item, root)


def _resolve_local_reference(root: Mapping[str, object], reference: str) -> None:
    current: object = root
    for raw_token in reference[2:].split("/"):
        if "~" in raw_token.replace("~0", "").replace("~1", ""):
            raise ValueError("model output schema contains a malformed local reference")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
            continue
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            try:
                current = current[int(token)]
                continue
            except (IndexError, ValueError):
                pass
        raise ValueError("model output schema contains an unresolved local reference")
