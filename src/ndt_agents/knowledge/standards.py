"""S3-08 typed standard lineage, applicability, and retrieval admission."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel, TenantScope
from ndt_agents.knowledge.retrieval import (
    EmbeddingPort,
    HybridRetrievalService,
    IndexSnapshot,
    IndexStatus,
    InMemoryKnowledgeIndex,
    RetrievalQuery,
    RetrievalResult,
)

STANDARD_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
_REGION = re.compile(r"^(?:GLOBAL|[A-Z]{2}(?:-[A-Z0-9]{1,8})*)$")
_STANDARD_TYPE = re.compile(r"^[A-Z][A-Z0-9_-]{0,63}$")
_USABLE_RIGHTS = frozenset({"PUBLIC_DOMAIN", "LICENSED", "OWNER_AUTHORIZED"})


class StandardLifecycle(StrEnum):
    CURRENT = "CURRENT"
    RESTRICTED = "RESTRICTED"
    DRAFT = "DRAFT"
    REPLACED = "REPLACED"
    WITHDRAWN = "WITHDRAWN"


class RightsBasis(StrEnum):
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    LICENSED = "LICENSED"
    OWNER_AUTHORIZED = "OWNER_AUTHORIZED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"
    PROHIBITED = "PROHIBITED"


class StandardVersionDraft(StrictModel):
    schema_version: Literal["1.0.0"] = STANDARD_CONTRACT_VERSION
    scope: TenantScope
    standard_type: str = Field(pattern=_STANDARD_TYPE.pattern)
    standard_identifier: str = Field(min_length=1, max_length=256)
    edition: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=1_000)
    publication_date: date
    effective_date: date
    expiry_date: date | None = None
    regions: tuple[str, ...] = Field(min_length=1, max_length=64)
    lifecycle: StandardLifecycle
    rights_basis: RightsBasis
    rights_reference: str | None = Field(default=None, max_length=2_048)
    required_roles: tuple[str, ...] = Field(default=(), max_length=32)
    replaces: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_policy_fields(self) -> Self:
        if self.publication_date > self.effective_date:
            raise ValueError("publication date must not follow effective date")
        if self.expiry_date is not None and self.expiry_date < self.effective_date:
            raise ValueError("expiry date must not precede effective date")
        if self.regions != tuple(sorted(set(self.regions))):
            raise ValueError("regions must be sorted and unique")
        if any(not _REGION.fullmatch(region) for region in self.regions):
            raise ValueError("region code is invalid")
        if "GLOBAL" in self.regions and len(self.regions) != 1:
            raise ValueError("GLOBAL cannot be combined with another region")
        if self.required_roles != tuple(sorted(set(self.required_roles))):
            raise ValueError("required roles must be sorted and unique")
        if self.replaces != tuple(sorted(set(self.replaces))):
            raise ValueError("replacement IDs must be sorted and unique")
        if any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in self.replaces):
            raise ValueError("replacement ID must be a SHA-256 value")
        if self.rights_basis.value in _USABLE_RIGHTS and not self.rights_reference:
            raise ValueError("usable rights require an evidence reference")
        return self


class StandardVersion(StandardVersionDraft):
    version_id: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = _canonical_hash(self.model_dump(mode="json", exclude={"version_id"}))
        if self.version_id != expected:
            raise ValueError("standard version ID does not match its immutable payload")
        if self.version_id in self.replaces:
            raise ValueError("a standard version cannot replace itself")
        return self


def finalize_standard_version(draft: StandardVersionDraft) -> StandardVersion:
    payload = draft.model_dump(mode="json")
    return StandardVersion.model_validate({**payload, "version_id": _canonical_hash(payload)})


class StandardCatalog:
    def __init__(self) -> None:
        self._versions: dict[tuple[str, ...], StandardVersion] = {}

    @staticmethod
    def _scope_key(scope: TenantScope) -> tuple[str, ...]:
        return (
            str(scope.tenant_id),
            str(scope.project_id),
            str(scope.user_id),
            scope.permission_version,
            *scope.role_codes,
        )

    def register(self, scope: TenantScope, version: StandardVersion) -> StandardVersion:
        if version.scope != scope:
            raise PermissionError("STANDARD_SCOPE_DENIED")
        key = (*self._scope_key(scope), version.version_id)
        existing = self._versions.get(key)
        if existing is not None:
            if existing != version:
                raise ValueError("STANDARD_IMMUTABLE_CONFLICT")
            return existing
        if version.version_id in version.replaces:
            raise ValueError("STANDARD_REPLACEMENT_CYCLE")
        for target_id in version.replaces:
            target = self.get(scope, target_id)
            if target is None:
                if any(item.version_id == target_id for item in self._versions.values()):
                    raise PermissionError("STANDARD_REPLACEMENT_SCOPE_DENIED")
                raise ValueError("STANDARD_REPLACEMENT_MISSING")
            if (
                target.standard_type != version.standard_type
                or target.standard_identifier != version.standard_identifier
            ):
                raise ValueError("STANDARD_REPLACEMENT_LINEAGE_MISMATCH")
        if self._has_cycle(scope, version):
            raise ValueError("STANDARD_REPLACEMENT_CYCLE")
        self._versions[key] = version
        return version

    def get(self, scope: TenantScope, version_id: str) -> StandardVersion | None:
        return self._versions.get((*self._scope_key(scope), version_id))

    def list_for_scope(self, scope: TenantScope) -> tuple[StandardVersion, ...]:
        prefix = self._scope_key(scope)
        return tuple(
            sorted(
                (item for key, item in self._versions.items() if key[: len(prefix)] == prefix),
                key=lambda item: item.version_id,
            )
        )

    def is_superseded(self, scope: TenantScope, version_id: str) -> bool:
        return any(
            version.lifecycle in {StandardLifecycle.CURRENT, StandardLifecycle.RESTRICTED}
            and version_id in version.replaces
            for version in self.list_for_scope(scope)
        )

    def _has_cycle(self, scope: TenantScope, candidate: StandardVersion) -> bool:
        graph = {version.version_id: version.replaces for version in self.list_for_scope(scope)}
        graph[candidate.version_id] = candidate.replaces
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(target) for target in graph.get(node, ()) if target in graph):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in graph)


class ApplicabilityReason(StrEnum):
    SCOPE_DENIED = "SCOPE_DENIED"
    LIFECYCLE_DENIED = "LIFECYCLE_DENIED"
    NOT_EFFECTIVE = "NOT_EFFECTIVE"
    EXPIRED = "EXPIRED"
    REGION_DENIED = "REGION_DENIED"
    TYPE_DENIED = "TYPE_DENIED"
    RIGHTS_DENIED = "RIGHTS_DENIED"
    RIGHTS_EVIDENCE_MISSING = "RIGHTS_EVIDENCE_MISSING"
    ROLE_DENIED = "ROLE_DENIED"
    SUPERSEDED = "SUPERSEDED"
    STANDARD_BINDING_MISSING = "STANDARD_BINDING_MISSING"
    STANDARD_UNREGISTERED = "STANDARD_UNREGISTERED"
    INDEX_NOT_PUBLISHED = "INDEX_NOT_PUBLISHED"


class StandardApplicabilityRequest(StrictModel):
    schema_version: Literal["1.0.0"] = STANDARD_CONTRACT_VERSION
    as_of: date
    region: str = Field(pattern=_REGION.pattern)
    standard_types: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_types(self) -> Self:
        if self.standard_types != tuple(sorted(set(self.standard_types))):
            raise ValueError("standard types must be sorted and unique")
        if any(not _STANDARD_TYPE.fullmatch(item) for item in self.standard_types):
            raise ValueError("standard type is invalid")
        return self


class StandardApplicabilityDecision(StrictModel):
    version_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    applicable: bool
    reasons: tuple[ApplicabilityReason, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.applicable == bool(self.reasons):
            raise ValueError("applicable decisions have no denial reasons")
        return self


class StandardApplicabilityService:
    def __init__(self, catalog: StandardCatalog) -> None:
        self._catalog = catalog

    def evaluate(
        self,
        scope: TenantScope,
        version: StandardVersion,
        request: StandardApplicabilityRequest,
    ) -> StandardApplicabilityDecision:
        reasons: list[ApplicabilityReason] = []
        if version.scope != scope:
            reasons.append(ApplicabilityReason.SCOPE_DENIED)
        if version.lifecycle not in {StandardLifecycle.CURRENT, StandardLifecycle.RESTRICTED}:
            reasons.append(ApplicabilityReason.LIFECYCLE_DENIED)
        if request.as_of < version.effective_date:
            reasons.append(ApplicabilityReason.NOT_EFFECTIVE)
        if version.expiry_date is not None and request.as_of > version.expiry_date:
            reasons.append(ApplicabilityReason.EXPIRED)
        if "GLOBAL" not in version.regions and request.region not in version.regions:
            reasons.append(ApplicabilityReason.REGION_DENIED)
        if request.standard_types and version.standard_type not in request.standard_types:
            reasons.append(ApplicabilityReason.TYPE_DENIED)
        if version.rights_basis.value not in _USABLE_RIGHTS:
            reasons.append(ApplicabilityReason.RIGHTS_DENIED)
        elif not version.rights_reference:
            reasons.append(ApplicabilityReason.RIGHTS_EVIDENCE_MISSING)
        if not set(version.required_roles).issubset(scope.role_codes):
            reasons.append(ApplicabilityReason.ROLE_DENIED)
        if version.scope == scope and self._catalog.is_superseded(scope, version.version_id):
            reasons.append(ApplicabilityReason.SUPERSEDED)
        return StandardApplicabilityDecision(
            version_id=version.version_id,
            applicable=not reasons,
            reasons=tuple(dict.fromkeys(reasons)),
        )


class SnapshotApplicability(StrictModel):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    standard_version_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    applicable: bool
    reasons: tuple[ApplicabilityReason, ...] = Field(max_length=16)


class StandardRetrievalRequest(StrictModel):
    schema_version: Literal["1.0.0"] = STANDARD_CONTRACT_VERSION
    retrieval: RetrievalQuery
    applicability: StandardApplicabilityRequest


class StandardRetrievalResult(StrictModel):
    schema_version: Literal["1.0.0"] = STANDARD_CONTRACT_VERSION
    admitted_snapshot_count: int = Field(ge=0)
    decisions: tuple[SnapshotApplicability, ...]
    retrieval: RetrievalResult


class StandardRetrievalService:
    def __init__(
        self,
        repository: InMemoryKnowledgeIndex,
        catalog: StandardCatalog,
        embedding: EmbeddingPort,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._embedding = embedding
        self._applicability = StandardApplicabilityService(catalog)

    def retrieve(
        self, scope: TenantScope, request: StandardRetrievalRequest
    ) -> StandardRetrievalResult:
        admitted = InMemoryKnowledgeIndex()
        decisions: list[SnapshotApplicability] = []
        for snapshot in self._repository.list_for_scope(scope):
            decision = self._assess_snapshot(scope, snapshot, request.applicability)
            decisions.append(decision)
            if decision.applicable:
                admitted.replace(snapshot)
        result = HybridRetrievalService(admitted, self._embedding).retrieve(
            scope, request.retrieval
        )
        return StandardRetrievalResult(
            admitted_snapshot_count=sum(item.applicable for item in decisions),
            decisions=tuple(decisions),
            retrieval=result,
        )

    def _assess_snapshot(
        self,
        scope: TenantScope,
        snapshot: IndexSnapshot,
        request: StandardApplicabilityRequest,
    ) -> SnapshotApplicability:
        standard_id = snapshot.metadata.get("standard_version_id")
        if standard_id is None or not re.fullmatch(r"[0-9a-f]{64}", standard_id):
            return _snapshot_denial(snapshot, None, ApplicabilityReason.STANDARD_BINDING_MISSING)
        version = self._catalog.get(scope, standard_id)
        if version is None:
            return _snapshot_denial(
                snapshot, standard_id, ApplicabilityReason.STANDARD_UNREGISTERED
            )
        evaluation = self._applicability.evaluate(scope, version, request)
        reasons = list(evaluation.reasons)
        if snapshot.status is not IndexStatus.PUBLISHED:
            reasons.append(ApplicabilityReason.INDEX_NOT_PUBLISHED)
        return SnapshotApplicability(
            snapshot_id=snapshot.snapshot_id,
            standard_version_id=standard_id,
            applicable=not reasons,
            reasons=tuple(dict.fromkeys(reasons)),
        )


def _snapshot_denial(
    snapshot: IndexSnapshot,
    standard_id: str | None,
    reason: ApplicabilityReason,
) -> SnapshotApplicability:
    return SnapshotApplicability(
        snapshot_id=snapshot.snapshot_id,
        standard_version_id=standard_id,
        applicable=False,
        reasons=(reason,),
    )


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
