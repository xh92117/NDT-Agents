"""S2-07 SEC-CACHE five-class service tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import JsonValue

from ndt_agents.cache import (
    CacheClass,
    CacheError,
    CacheGetRequest,
    CachePolicy,
    CachePutRequest,
    CacheService,
    CacheSideEffect,
    InMemoryCacheBackend,
    cache_value_sha256,
)
from ndt_agents.contracts.v1 import TenantScope

NOW = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000001"),
    project_id=UUID("00000000-0000-4000-8000-000000000002"),
    user_id=UUID("00000000-0000-4000-8000-000000000003"),
    role_codes=("ENGINEER",),
    permission_version="perm-1",
)
VERSIONS = {"schema": "1", "model": "model-1"}


def service() -> CacheService:
    return CacheService(InMemoryCacheBackend(), CachePolicy(policy_version="cache-policy-1"))


def put_request(
    cache_class: CacheClass,
    *,
    key: str = "a" * 64,
    value_text: str = "cached",
    **updates: object,
) -> CachePutRequest:
    value: dict[str, JsonValue] = {"result": value_text}
    base: dict[str, object] = {
        "cache_entry_id": UUID("00000000-0000-4000-8000-000000000010"),
        "scope": SCOPE,
        "cache_class": cache_class,
        "cache_key_sha256": key,
        "value": value,
        "value_sha256": cache_value_sha256(value),
        "version_manifest": VERSIONS,
        "provenance": {"source": "test-1"},
        "task_class": "G0",
        "semantic_similarity": 0.96 if cache_class is CacheClass.SEMANTIC else None,
        "saved_tokens": 100,
        "created_at": NOW,
    }
    base.update(updates)
    return CachePutRequest.model_validate(base)


def get_request(
    cache_class: CacheClass,
    *,
    now: datetime = NOW + timedelta(seconds=1),
    versions: dict[str, str] | None = None,
    current: bool = False,
) -> CacheGetRequest:
    return CacheGetRequest(
        scope=SCOPE,
        cache_class=cache_class,
        cache_key_sha256="a" * 64,
        current_version_manifest=versions or VERSIONS,
        current_information_required=current,
        now=now,
    )


@pytest.mark.parametrize("cache_class", tuple(CacheClass))
def test_all_five_cache_classes_round_trip_with_class_ttl(cache_class: CacheClass) -> None:
    cache = service()
    record = cache.put(put_request(cache_class))

    assert cache.get(get_request(cache_class)) == record
    expected = {
        CacheClass.EXACT: 86400,
        CacheClass.RETRIEVAL: 21600,
        CacheClass.TOOL: 2592000,
        CacheClass.PARSE: 7776000,
        CacheClass.SEMANTIC: 3600,
    }[cache_class]
    assert (record.expires_at - record.created_at).total_seconds() == expected


def test_expired_or_version_stale_entry_is_rejected_and_removed() -> None:
    cache = service()
    cache.put(put_request(CacheClass.SEMANTIC))
    assert cache.get(get_request(CacheClass.SEMANTIC, now=NOW + timedelta(seconds=3600))) is None
    cache.put(put_request(CacheClass.EXACT, refresh=True))
    assert (
        cache.get(get_request(CacheClass.EXACT, versions={"schema": "2", "model": "model-1"}))
        is None
    )
    assert cache.metrics().stale_rejections == 2


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"contains_secret": True}, "CACHE_SECRET_DENIED"),
        ({"contains_authorization_decision": True}, "CACHE_AUTHORIZATION_DENIED"),
        ({"stable": False}, "CACHE_UNSTABLE_DENIED"),
        ({"side_effect": CacheSideEffect.WRITE}, "CACHE_SIDE_EFFECT_DENIED"),
    ],
)
def test_unsafe_values_are_never_cached(updates: dict[str, object], code: str) -> None:
    payload = put_request(CacheClass.EXACT).model_dump()
    payload.update(updates)
    with pytest.raises(CacheError) as denied:
        service().put(CachePutRequest.model_validate(payload))
    assert denied.value.code == code


def test_tool_cache_requires_pure_operation() -> None:
    with pytest.raises(CacheError, match="pure") as denied:
        service().put(put_request(CacheClass.TOOL, side_effect=CacheSideEffect.READ))
    assert denied.value.code == "CACHE_TOOL_NOT_PURE"


@pytest.mark.parametrize(
    ("task_class", "similarity", "code"),
    [
        ("P2", 0.99, "CACHE_SEMANTIC_TASK_DENIED"),
        ("P1", 0.949, "CACHE_SEMANTIC_SIMILARITY_DENIED"),
    ],
)
def test_semantic_cache_is_restricted(task_class: str, similarity: float, code: str) -> None:
    with pytest.raises(CacheError) as denied:
        service().put(
            put_request(
                CacheClass.SEMANTIC,
                task_class=task_class,
                semantic_similarity=similarity,
            )
        )
    assert denied.value.code == code


def test_key_collision_denies_poisoning_but_explicit_refresh_replaces() -> None:
    cache = service()
    first = cache.put(put_request(CacheClass.EXACT, value_text="first"))
    with pytest.raises(CacheError, match="different") as collision:
        cache.put(put_request(CacheClass.EXACT, value_text="poison"))
    assert collision.value.code == "CACHE_KEY_COLLISION"

    refreshed = cache.put(put_request(CacheClass.EXACT, value_text="fresh", refresh=True))
    assert refreshed.value_sha256 != first.value_sha256
    assert cache.get(get_request(CacheClass.EXACT)) == refreshed


def test_current_information_bypasses_cache_and_metrics_are_separate() -> None:
    cache = service()
    cache.put(put_request(CacheClass.RETRIEVAL))
    assert cache.get(get_request(CacheClass.RETRIEVAL)) is not None
    assert cache.get(get_request(CacheClass.RETRIEVAL, current=True)) is None
    metrics = cache.metrics()
    assert metrics.hits == 1
    assert metrics.misses == 1
    assert metrics.bypasses == 1
    assert metrics.saved_tokens == 100


def test_version_invalidation_removes_matching_entries() -> None:
    cache = service()
    cache.put(put_request(CacheClass.EXACT))
    assert cache.invalidate(version_name="model", version_value="model-1") == 1
    assert cache.get(get_request(CacheClass.EXACT)) is None
