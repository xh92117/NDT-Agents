"""S2-08 SEC-CACHE version-key and isolation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import JsonValue, ValidationError

from ndt_agents.cache import (
    CacheClass,
    CacheGetRequest,
    CacheKeyInput,
    CacheKeyVersions,
    CachePolicy,
    CachePutRequest,
    CacheService,
    InMemoryCacheBackend,
    build_cache_key,
    cache_value_sha256,
    normalize_cache_request,
)
from ndt_agents.contracts.v1 import TenantScope

NOW = datetime(2026, 8, 24, 16, 0, tzinfo=UTC)
SCOPE = TenantScope(
    tenant_id=UUID("00000000-0000-4000-8000-000000000001"),
    project_id=UUID("00000000-0000-4000-8000-000000000002"),
    user_id=UUID("00000000-0000-4000-8000-000000000003"),
    role_codes=("REVIEWER", "ENGINEER"),
    permission_version="perm-1",
)


def key_input() -> CacheKeyInput:
    return CacheKeyInput(
        scope=SCOPE,
        cache_class=CacheClass.RETRIEVAL,
        request_text="  Inspect   bridge\nsection  ",
        task_type="technical-qa",
        request_parameters={"region": "CN", "limit": 5},
        versions=CacheKeyVersions(
            rbac_policy_version="rbac-1",
            route_policy_version="route-1",
            graph_version="graph-1",
            model_version="model-1",
            prompt_versions={"main": "prompt-1", "review": "review-1"},
            skill_versions={"qa": "skill-1"},
            tool_name="knowledge.search",
            tool_version="tool-1",
            adapter_version="adapter-1",
            knowledge_corpus_version="corpus-1",
            knowledge_document_versions={"doc-a": "3"},
            public_schema_version="schema-1",
            parser_version="parser-1",
            context_policy_version="context-1",
        ),
        extra_dimensions={"reranker": "rank-1"},
    )


def mutate(path: str, value: object) -> CacheKeyInput:
    payload = key_input().model_dump(mode="python")
    target = payload
    segments = path.split(".")
    for segment in segments[:-1]:
        target = target[segment]
    target[segments[-1]] = value
    return CacheKeyInput.model_validate(payload)


def test_key_is_canonical_across_mapping_and_role_order() -> None:
    original = key_input()
    reordered = original.model_copy(
        update={
            "scope": original.scope.model_copy(
                update={"role_codes": tuple(reversed(original.scope.role_codes))}
            ),
            "versions": original.versions.model_copy(
                update={"prompt_versions": {"review": "review-1", "main": "prompt-1"}}
            ),
        }
    )

    assert build_cache_key(original) == build_cache_key(reordered)
    assert normalize_cache_request(original.request_text) == "Inspect bridge section"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("scope.tenant_id", UUID("00000000-0000-4000-8000-000000000101")),
        ("scope.project_id", UUID("00000000-0000-4000-8000-000000000102")),
        ("scope.user_id", UUID("00000000-0000-4000-8000-000000000103")),
        ("scope.permission_version", "perm-2"),
        ("versions.rbac_policy_version", "rbac-2"),
        ("versions.route_policy_version", "route-2"),
        ("versions.graph_version", "graph-2"),
        ("versions.model_version", "model-2"),
        ("versions.prompt_versions", {"main": "prompt-2"}),
        ("versions.skill_versions", {"qa": "skill-2"}),
        ("versions.tool_version", "tool-2"),
        ("versions.adapter_version", "adapter-2"),
        ("versions.knowledge_corpus_version", "corpus-2"),
        ("versions.knowledge_document_versions", {"doc-a": "4"}),
        ("versions.public_schema_version", "schema-2"),
        ("versions.parser_version", "parser-2"),
        ("versions.context_policy_version", "context-2"),
        ("request_text", "Inspect another bridge"),
        ("request_parameters", {"region": "EU", "limit": 5}),
        ("extra_dimensions", {"reranker": "rank-2"}),
    ],
)
def test_every_correctness_or_authorization_change_produces_distinct_key(
    path: str, value: object
) -> None:
    assert (
        build_cache_key(mutate(path, value)).cache_key_sha256
        != build_cache_key(key_input()).cache_key_sha256
    )


def test_scope_isolation_prevents_cross_user_project_and_revocation_hits() -> None:
    material = build_cache_key(key_input())
    cache = CacheService(InMemoryCacheBackend(), CachePolicy(policy_version="cache-policy-1"))
    value: dict[str, JsonValue] = {"result": "scoped"}
    cache.put(
        CachePutRequest(
            cache_entry_id=UUID("00000000-0000-4000-8000-000000000010"),
            scope=SCOPE,
            cache_class=CacheClass.RETRIEVAL,
            cache_key_sha256=material.cache_key_sha256,
            value=value,
            value_sha256=cache_value_sha256(value),
            version_manifest=material.version_manifest,
            provenance={"source": "test"},
            task_class="G0",
            created_at=NOW,
        )
    )
    for changed_scope in (
        SCOPE.model_copy(update={"user_id": UUID("00000000-0000-4000-8000-000000000099")}),
        SCOPE.model_copy(update={"project_id": UUID("00000000-0000-4000-8000-000000000098")}),
        SCOPE.model_copy(update={"permission_version": "revoked-2"}),
    ):
        assert (
            cache.get(
                CacheGetRequest(
                    scope=changed_scope,
                    cache_class=CacheClass.RETRIEVAL,
                    cache_key_sha256=material.cache_key_sha256,
                    current_version_manifest=material.version_manifest,
                    now=NOW + timedelta(seconds=1),
                )
            )
            is None
        )


def test_version_manifest_rejects_stale_record_even_with_same_external_key() -> None:
    original = build_cache_key(key_input())
    changed = build_cache_key(mutate("versions.model_version", "model-2"))
    assert original.version_manifest != changed.version_manifest
    assert original.cache_key_sha256 != changed.cache_key_sha256


def test_control_characters_unknown_fields_and_empty_versions_fail_closed() -> None:
    with pytest.raises(ValueError, match="control character"):
        normalize_cache_request("unsafe\x00request")
    payload = key_input().model_dump()
    payload["unknown"] = True
    with pytest.raises(ValidationError):
        CacheKeyInput.model_validate(payload)
    versions = key_input().versions.model_dump()
    versions["prompt_versions"] = {}
    with pytest.raises(ValidationError):
        CacheKeyVersions.model_validate(versions)
