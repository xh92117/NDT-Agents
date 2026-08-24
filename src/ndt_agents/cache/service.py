"""Five-class cache service with expiry, poisoning denial, and metrics."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from ndt_agents.cache.models import (
    CacheClass,
    CacheGetRequest,
    CacheMetrics,
    CachePolicy,
    CachePutRequest,
    CacheRecord,
    CacheSideEffect,
    CacheValidationState,
)
from ndt_agents.contracts.v1 import TenantScope


class CacheError(RuntimeError):
    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class InMemoryCacheBackend:
    def __init__(self) -> None:
        self._records: dict[tuple[str, ...], CacheRecord] = {}

    def get(self, scope: TenantScope, cache_class: CacheClass, key: str) -> CacheRecord | None:
        return self._records.get(_backend_key(scope, cache_class, key))

    def put(self, record: CacheRecord, *, refresh: bool) -> None:
        key = _backend_key(record.scope, record.cache_class, record.cache_key_sha256)
        existing = self._records.get(key)
        if existing is not None and not refresh:
            if existing.value_sha256 == record.value_sha256:
                return
            raise CacheError(
                code="CACHE_KEY_COLLISION",
                message="The cache key already holds a different immutable value.",
                next_action="Reject the candidate and rebuild the complete versioned cache key.",
            )
        self._records[key] = record

    def delete(self, scope: TenantScope, cache_class: CacheClass, key: str) -> None:
        self._records.pop(_backend_key(scope, cache_class, key), None)

    def invalidate(self, predicate: Callable[[CacheRecord], bool]) -> int:
        targets = [key for key, value in self._records.items() if predicate(value)]
        for key in targets:
            del self._records[key]
        return len(targets)


class CacheService:
    def __init__(self, backend: InMemoryCacheBackend, policy: CachePolicy) -> None:
        self._backend = backend
        self._policy = policy
        self._hits = 0
        self._misses = 0
        self._stale = 0
        self._bypasses = 0
        self._saved_tokens = 0

    def put(self, request: CachePutRequest) -> CacheRecord:
        self._validate_put(request)
        record = CacheRecord(
            cache_entry_id=request.cache_entry_id,
            scope=request.scope,
            cache_class=request.cache_class,
            cache_key_sha256=request.cache_key_sha256,
            value=request.value,
            value_sha256=request.value_sha256,
            version_manifest=request.version_manifest,
            provenance=request.provenance,
            validation_state=CacheValidationState.VALID,
            saved_tokens=request.saved_tokens,
            created_at=request.created_at,
            expires_at=request.created_at + timedelta(seconds=self._ttl(request.cache_class)),
        )
        self._backend.put(record, refresh=request.refresh)
        return record

    def get(self, request: CacheGetRequest) -> CacheRecord | None:
        if request.current_information_required:
            self._bypasses += 1
            self._misses += 1
            return None
        record = self._backend.get(request.scope, request.cache_class, request.cache_key_sha256)
        if record is None:
            self._misses += 1
            return None
        if (
            record.expires_at <= request.now
            or record.validation_state is not CacheValidationState.VALID
            or record.version_manifest != request.current_version_manifest
        ):
            self._backend.delete(request.scope, request.cache_class, request.cache_key_sha256)
            self._stale += 1
            self._misses += 1
            return None
        self._hits += 1
        self._saved_tokens += record.saved_tokens
        return record

    def invalidate(self, *, version_name: str, version_value: str | None = None) -> int:
        return self._backend.invalidate(
            lambda record: (
                version_name in record.version_manifest
                and (
                    version_value is None
                    or record.version_manifest.get(version_name) == version_value
                )
            )
        )

    def metrics(self) -> CacheMetrics:
        return CacheMetrics(
            hits=self._hits,
            misses=self._misses,
            stale_rejections=self._stale,
            bypasses=self._bypasses,
            saved_tokens=self._saved_tokens,
        )

    def _validate_put(self, request: CachePutRequest) -> None:
        if request.contains_secret:
            raise _unsafe("CACHE_SECRET_DENIED", "Secrets cannot be cached.")
        if request.contains_authorization_decision:
            raise _unsafe("CACHE_AUTHORIZATION_DENIED", "Authorization decisions cannot be cached.")
        if not request.stable:
            raise _unsafe("CACHE_UNSTABLE_DENIED", "Unstable values cannot be cached.")
        if request.side_effect is CacheSideEffect.WRITE:
            raise _unsafe("CACHE_SIDE_EFFECT_DENIED", "Write side effects cannot be cached.")
        if (
            request.cache_class is CacheClass.TOOL
            and request.side_effect is not CacheSideEffect.PURE
        ):
            raise _unsafe("CACHE_TOOL_NOT_PURE", "Only pure tool results can be cached.")
        if request.cache_class is CacheClass.SEMANTIC:
            if request.task_class not in {"G0", "P1"}:
                raise _unsafe(
                    "CACHE_SEMANTIC_TASK_DENIED",
                    "Semantic caching is restricted to G0 and P1 tasks.",
                )
            if (
                request.semantic_similarity is None
                or request.semantic_similarity < self._policy.semantic_minimum_similarity
            ):
                raise _unsafe(
                    "CACHE_SEMANTIC_SIMILARITY_DENIED",
                    "Semantic similarity is below the active threshold.",
                )

    def _ttl(self, cache_class: CacheClass) -> int:
        return {
            CacheClass.EXACT: self._policy.exact_ttl_seconds,
            CacheClass.RETRIEVAL: self._policy.retrieval_ttl_seconds,
            CacheClass.TOOL: self._policy.tool_ttl_seconds,
            CacheClass.PARSE: self._policy.parse_ttl_seconds,
            CacheClass.SEMANTIC: self._policy.semantic_ttl_seconds,
        }[cache_class]


def _backend_key(scope: TenantScope, cache_class: CacheClass, key: str) -> tuple[str, ...]:
    return (
        str(scope.tenant_id),
        str(scope.project_id),
        str(scope.user_id),
        scope.permission_version,
        cache_class.value,
        key,
    )


def _unsafe(code: str, message: str) -> CacheError:
    return CacheError(
        code=code,
        message=message,
        next_action="Bypass the cache and execute the authorized source operation.",
    )
