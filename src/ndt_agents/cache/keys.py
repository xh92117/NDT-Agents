"""Canonical cache keys covering every correctness and authorization version."""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from ndt_agents.cache.models import CacheClass, CacheModel
from ndt_agents.context.assembly import canonical_json_bytes
from ndt_agents.contracts.v1 import TenantScope


class CacheKeyVersions(CacheModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    rbac_policy_version: str = Field(min_length=1, max_length=128)
    route_policy_version: str = Field(min_length=1, max_length=128)
    graph_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    prompt_versions: dict[str, str] = Field(min_length=1, max_length=32)
    skill_versions: dict[str, str] = Field(min_length=1, max_length=32)
    tool_name: str = Field(min_length=1, max_length=128)
    tool_version: str = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=128)
    knowledge_corpus_version: str = Field(min_length=1, max_length=128)
    knowledge_document_versions: dict[str, str] = Field(min_length=1, max_length=32)
    public_schema_version: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    context_policy_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_maps(self) -> Self:
        for label, values in (
            ("prompt versions", self.prompt_versions),
            ("Skill versions", self.skill_versions),
            ("knowledge document versions", self.knowledge_document_versions),
        ):
            if any(not key or not value for key, value in values.items()):
                raise ValueError(f"{label} contain an empty key or value")
        return self


class CacheKeyInput(CacheModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    scope: TenantScope
    cache_class: CacheClass
    request_text: str = Field(min_length=1, max_length=32000)
    task_type: str = Field(min_length=1, max_length=128)
    request_parameters: dict[str, JsonValue]
    versions: CacheKeyVersions
    extra_dimensions: dict[str, str] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def validate_input(self) -> Self:
        if len(self.scope.role_codes) != len(set(self.scope.role_codes)):
            raise ValueError("cache-key role codes must be unique")
        if any(not key or not value for key, value in self.extra_dimensions.items()):
            raise ValueError("extra cache dimensions contain an empty key or value")
        normalize_cache_request(self.request_text)
        return self


class CacheKeyResult(CacheModel):
    cache_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_manifest: dict[str, str] = Field(min_length=1, max_length=64)


def build_cache_key(value: CacheKeyInput) -> CacheKeyResult:
    normalized = normalize_cache_request(value.request_text)
    authorization = cache_authorization_sha256(value.scope, value.versions.rbac_policy_version)
    version_manifest = cache_version_manifest(value.versions)
    payload = {
        "schema_version": value.schema_version,
        "authorization_sha256": authorization,
        "cache_class": value.cache_class.value,
        "normalized_request": normalized,
        "task_type": value.task_type,
        "request_parameters": value.request_parameters,
        "versions": value.versions.model_dump(mode="json"),
        "extra_dimensions": value.extra_dimensions,
    }
    return CacheKeyResult(
        cache_key_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        authorization_sha256=authorization,
        normalized_request_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        version_manifest=version_manifest,
    )


def cache_authorization_sha256(scope: TenantScope, rbac_policy_version: str) -> str:
    payload = {
        "tenant_id": str(scope.tenant_id),
        "project_id": str(scope.project_id),
        "user_id": str(scope.user_id),
        "role_codes": sorted(scope.role_codes),
        "permission_version": scope.permission_version,
        "rbac_policy_version": rbac_policy_version,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def cache_version_manifest(versions: CacheKeyVersions) -> dict[str, str]:
    return {
        "rbac_policy": versions.rbac_policy_version,
        "route_policy": versions.route_policy_version,
        "graph": versions.graph_version,
        "model": versions.model_version,
        "prompts": _mapping_hash(versions.prompt_versions),
        "skills": _mapping_hash(versions.skill_versions),
        "tool": f"{versions.tool_name}@{versions.tool_version}",
        "adapter": versions.adapter_version,
        "knowledge_corpus": versions.knowledge_corpus_version,
        "knowledge_documents": _mapping_hash(versions.knowledge_document_versions),
        "schema": versions.public_schema_version,
        "parser": versions.parser_version,
        "context_policy": versions.context_policy_version,
    }


def normalize_cache_request(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    if any(
        unicodedata.category(char).startswith("C") and not char.isspace() for char in normalized
    ):
        raise ValueError("cache request contains a forbidden control character")
    collapsed = " ".join(normalized.split())
    if not collapsed:
        raise ValueError("cache request is empty after normalization")
    return collapsed


def _mapping_hash(value: dict[str, str]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
