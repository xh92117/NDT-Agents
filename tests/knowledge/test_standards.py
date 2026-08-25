"""S3-08 standard identity, lineage, applicability, and retrieval tests."""

from __future__ import annotations

import hashlib
from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import TenantScope
from ndt_agents.knowledge.normalization import LocatorType
from ndt_agents.knowledge.retrieval import (
    DeterministicHashEmbedding,
    IndexRecord,
    IndexSnapshot,
    IndexStatus,
    InMemoryKnowledgeIndex,
    RetrievalQuery,
    tokenize,
)
from ndt_agents.knowledge.standards import (
    ApplicabilityReason,
    RightsBasis,
    StandardApplicabilityRequest,
    StandardApplicabilityService,
    StandardCatalog,
    StandardLifecycle,
    StandardRetrievalRequest,
    StandardRetrievalService,
    StandardVersion,
    StandardVersionDraft,
    finalize_standard_version,
)

TENANT = UUID("00000000-0000-4000-8000-000000000101")
PROJECT = UUID("00000000-0000-4000-8000-000000000201")
USER = UUID("00000000-0000-4000-8000-000000000301")
EMBEDDING = DeterministicHashEmbedding(dimension=64)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def scope(
    *,
    tenant: UUID = TENANT,
    project: UUID = PROJECT,
    user: UUID = USER,
    roles: tuple[str, ...] = ("knowledge-reader",),
    permission: str = "permissions-1",
) -> TenantScope:
    return TenantScope(
        tenant_id=tenant,
        project_id=project,
        user_id=user,
        role_codes=roles,
        permission_version=permission,
    )


def version(
    owner: TenantScope,
    key: str = "GB-T-1",
    *,
    standard_type: str = "NATIONAL",
    edition: str = "2026",
    publication: date = date(2026, 1, 1),
    effective: date = date(2026, 6, 1),
    expiry: date | None = None,
    regions: tuple[str, ...] = ("CN",),
    lifecycle: StandardLifecycle = StandardLifecycle.CURRENT,
    rights: RightsBasis = RightsBasis.LICENSED,
    rights_reference: str | None = "rights://register/GB-T-1",
    roles: tuple[str, ...] = (),
    replaces: tuple[str, ...] = (),
) -> StandardVersion:
    return finalize_standard_version(
        StandardVersionDraft(
            scope=owner,
            standard_type=standard_type,
            standard_identifier=key,
            edition=edition,
            title=f"Inspection standard {key} {edition}",
            publication_date=publication,
            effective_date=effective,
            expiry_date=expiry,
            regions=regions,
            lifecycle=lifecycle,
            rights_basis=rights,
            rights_reference=rights_reference,
            required_roles=roles,
            replaces=replaces,
        )
    )


def applicability(
    *,
    as_of: date = date(2026, 8, 25),
    region: str = "CN",
    types: tuple[str, ...] = (),
) -> StandardApplicabilityRequest:
    return StandardApplicabilityRequest(as_of=as_of, region=region, standard_types=types)


def snapshot(
    owner: TenantScope,
    key: str,
    text: str,
    standard_id: str | None,
    *,
    status: IndexStatus = IndexStatus.PUBLISHED,
) -> IndexSnapshot:
    chunk_id = digest(f"chunk:{key}")
    vector = EMBEDDING.embed((text,))[0]
    record = IndexRecord(
        chunk_id=chunk_id,
        document_id=digest(f"document:{key}"),
        document_sha256=digest(f"document-content:{key}"),
        artifact_id="00000000-0000-4000-8000-000000000001",
        artifact_version="source-v1",
        source_sha256=digest(f"source:{key}"),
        source_title=f"Source {key}",
        source_media_type="application/pdf",
        parser_name="mineru",
        parser_version="3.0.0",
        normalizer_version="1.0.0",
        page_index=0,
        section_path=("Scope",),
        locator_type=LocatorType.PAGE,
        locator="page:1",
        text=text,
        content_sha256=digest(text),
        tokens=tokenize(text),
        vector=vector,
    )
    metadata = {"standard_version_id": standard_id} if standard_id else {}
    return IndexSnapshot(
        snapshot_id=digest(f"snapshot:{key}"),
        scope=owner,
        corpus_id="ndt-standards",
        corpus_version="corpus-v1",
        index_version="index-v1",
        status=status,
        document_id=record.document_id,
        document_sha256=record.document_sha256,
        embedding_version=EMBEDDING.version,
        embedding_dimension=EMBEDDING.dimension,
        metadata=metadata,
        records=(record,),
    )


def retrieval_request(text: str, policy: StandardApplicabilityRequest) -> StandardRetrievalRequest:
    return StandardRetrievalRequest(
        retrieval=RetrievalQuery(
            text=text,
            corpus_id="ndt-standards",
            corpus_version="corpus-v1",
            index_version="index-v1",
            embedding_version=EMBEDDING.version,
        ),
        applicability=policy,
    )


def test_version_identity_is_stable_and_tamper_evident() -> None:
    first = version(scope())
    second = version(scope())

    assert first == second
    assert first.regions == ("CN",)
    with pytest.raises(ValidationError, match="immutable payload"):
        StandardVersion.model_validate({**first.model_dump(), "edition": "2027"})


@pytest.mark.parametrize(
    "changes",
    [
        {"publication_date": date(2026, 7, 1), "effective_date": date(2026, 6, 1)},
        {"effective_date": date(2026, 6, 1), "expiry_date": date(2026, 5, 31)},
        {"regions": ("CN", "GLOBAL")},
        {"regions": ("US", "CN")},
        {"required_roles": ("z", "a")},
        {"rights_basis": RightsBasis.LICENSED, "rights_reference": None},
    ],
)
def test_invalid_dates_canonical_sets_and_rights_evidence_are_denied(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "scope": scope(),
        "standard_type": "NATIONAL",
        "standard_identifier": "GB-T-1",
        "edition": "2026",
        "title": "Inspection standard",
        "publication_date": date(2026, 1, 1),
        "effective_date": date(2026, 6, 1),
        "regions": ("CN",),
        "lifecycle": StandardLifecycle.CURRENT,
        "rights_basis": RightsBasis.LICENSED,
        "rights_reference": "rights://record/1",
    }
    values.update(changes)

    with pytest.raises(ValidationError):
        StandardVersionDraft.model_validate(values)


def test_catalog_registration_is_idempotent_and_scope_isolated() -> None:
    catalog = StandardCatalog()
    item = version(scope())

    assert catalog.register(scope(), item) is item
    assert catalog.register(scope(), item) == item
    assert catalog.get(scope(permission="permissions-2"), item.version_id) is None
    with pytest.raises(PermissionError, match="SCOPE_DENIED"):
        catalog.register(scope(permission="permissions-2"), item)


def test_replacement_requires_existing_same_scope_and_lineage() -> None:
    catalog = StandardCatalog()
    other_scope = scope(project=UUID("00000000-0000-4000-8000-000000000202"))
    foreign = version(other_scope, edition="2020")
    catalog.register(other_scope, foreign)

    with pytest.raises(PermissionError, match="REPLACEMENT_SCOPE_DENIED"):
        catalog.register(scope(), version(scope(), edition="2026", replaces=(foreign.version_id,)))

    old = version(scope(), edition="2020")
    catalog.register(scope(), old)
    with pytest.raises(ValueError, match="LINEAGE_MISMATCH"):
        catalog.register(
            scope(), version(scope(), key="GB-T-2", edition="2026", replaces=(old.version_id,))
        )


def test_replacement_cycle_is_denied_defensively() -> None:
    catalog = StandardCatalog()
    item = version(scope())
    tampered = item.model_copy(update={"replaces": (item.version_id,)})

    with pytest.raises(ValueError, match="REPLACEMENT_CYCLE"):
        catalog.register(scope(), tampered)


def test_new_current_version_supersedes_old_version() -> None:
    catalog = StandardCatalog()
    old = version(scope(), edition="2020")
    catalog.register(scope(), old)
    new = version(scope(), edition="2026", replaces=(old.version_id,))
    catalog.register(scope(), new)
    policy = StandardApplicabilityService(catalog)

    old_result = policy.evaluate(scope(), old, applicability())
    new_result = policy.evaluate(scope(), new, applicability())

    assert old_result.reasons == (ApplicabilityReason.SUPERSEDED,)
    assert new_result.applicable


@pytest.mark.parametrize(
    ("rights", "permitted"),
    [
        (RightsBasis.PUBLIC_DOMAIN, True),
        (RightsBasis.LICENSED, True),
        (RightsBasis.OWNER_AUTHORIZED, True),
        (RightsBasis.UNKNOWN, False),
        (RightsBasis.EXPIRED, False),
        (RightsBasis.PROHIBITED, False),
    ],
)
def test_rights_basis_controls_applicability(rights: RightsBasis, permitted: bool) -> None:
    catalog = StandardCatalog()
    reference = "rights://record/1" if permitted else None
    item = version(scope(), rights=rights, rights_reference=reference)
    catalog.register(scope(), item)

    result = StandardApplicabilityService(catalog).evaluate(scope(), item, applicability())

    assert result.applicable is permitted
    assert (ApplicabilityReason.RIGHTS_DENIED in result.reasons) is (not permitted)


@pytest.mark.parametrize(
    ("item", "owner", "policy_request", "reason"),
    [
        (
            version(scope(), lifecycle=StandardLifecycle.DRAFT),
            scope(),
            applicability(),
            ApplicabilityReason.LIFECYCLE_DENIED,
        ),
        (
            version(scope(), effective=date(2027, 1, 1), publication=date(2026, 1, 1)),
            scope(),
            applicability(),
            ApplicabilityReason.NOT_EFFECTIVE,
        ),
        (
            version(scope(), expiry=date(2026, 7, 1)),
            scope(),
            applicability(),
            ApplicabilityReason.EXPIRED,
        ),
        (
            version(scope(), regions=("US",)),
            scope(),
            applicability(region="CN"),
            ApplicabilityReason.REGION_DENIED,
        ),
        (
            version(scope(), standard_type="INDUSTRY"),
            scope(),
            applicability(types=("NATIONAL",)),
            ApplicabilityReason.TYPE_DENIED,
        ),
        (
            version(scope(), lifecycle=StandardLifecycle.RESTRICTED, roles=("standard-reader",)),
            scope(),
            applicability(),
            ApplicabilityReason.ROLE_DENIED,
        ),
        (
            version(scope()),
            scope(permission="permissions-2"),
            applicability(),
            ApplicabilityReason.SCOPE_DENIED,
        ),
    ],
)
def test_stable_applicability_denial_reasons(
    item: StandardVersion,
    owner: TenantScope,
    policy_request: StandardApplicabilityRequest,
    reason: ApplicabilityReason,
) -> None:
    catalog = StandardCatalog()
    catalog.register(item.scope, item)

    result = StandardApplicabilityService(catalog).evaluate(owner, item, policy_request)

    assert not result.applicable
    assert reason in result.reasons


def test_global_and_role_authorized_restricted_version_is_applicable() -> None:
    owner = scope(roles=("knowledge-reader", "standard-reader"))
    item = version(
        owner,
        regions=("GLOBAL",),
        lifecycle=StandardLifecycle.RESTRICTED,
        roles=("standard-reader",),
    )
    catalog = StandardCatalog()
    catalog.register(owner, item)

    result = StandardApplicabilityService(catalog).evaluate(owner, item, applicability(region="US"))

    assert result.applicable


def test_retrieval_admits_only_applicable_bound_published_snapshots() -> None:
    owner = scope()
    catalog = StandardCatalog()
    current = version(owner, key="GB-CURRENT")
    denied = version(owner, key="GB-DENIED", rights=RightsBasis.PROHIBITED, rights_reference=None)
    catalog.register(owner, current)
    catalog.register(owner, denied)
    repository = InMemoryKnowledgeIndex()
    snapshots = (
        snapshot(owner, "allowed", "allowed bridge crack threshold", current.version_id),
        snapshot(owner, "denied", "secret exact bridge crack threshold", denied.version_id),
        snapshot(owner, "missing", "missing bridge crack threshold", None),
        snapshot(
            owner,
            "draft-index",
            "draft bridge crack threshold",
            current.version_id,
            status=IndexStatus.DRAFT,
        ),
    )
    for item in snapshots:
        repository.replace(item)
    service = StandardRetrievalService(repository, catalog, EMBEDDING)

    result = service.retrieve(
        owner,
        retrieval_request("secret exact bridge crack threshold", applicability()),
    )

    assert result.admitted_snapshot_count == 1
    assert result.retrieval.authorized_snapshot_count == 1
    assert [hit.text for hit in result.retrieval.hits] == ["allowed bridge crack threshold"]
    reasons = {reason for item in result.decisions for reason in item.reasons}
    assert ApplicabilityReason.RIGHTS_DENIED in reasons
    assert ApplicabilityReason.STANDARD_BINDING_MISSING in reasons
    assert ApplicabilityReason.INDEX_NOT_PUBLISHED in reasons


def test_unregistered_standard_binding_is_denied_before_scoring() -> None:
    owner = scope()
    repository = InMemoryKnowledgeIndex()
    repository.replace(snapshot(owner, "unregistered", "unregistered unique", "f" * 64))

    result = StandardRetrievalService(repository, StandardCatalog(), EMBEDDING).retrieve(
        owner, retrieval_request("unregistered unique", applicability())
    )

    assert result.admitted_snapshot_count == 0
    assert result.retrieval.hits == ()
    assert result.decisions[0].reasons == (ApplicabilityReason.STANDARD_UNREGISTERED,)
