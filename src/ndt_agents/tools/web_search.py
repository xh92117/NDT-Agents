"""Policy-bound Web Search adapter with exact citations and retrieval caching."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol, Self, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from ndt_agents.cache import (
    CacheClass,
    CacheGetRequest,
    CachePutRequest,
    CacheService,
    CacheSideEffect,
    cache_value_sha256,
)
from ndt_agents.contracts.v1 import StrictModel, ToolResult, ToolStatus
from ndt_agents.tools.registry import (
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolDataDestination,
    ToolDataScope,
    ToolDefinition,
    ToolInvocation,
    ToolKind,
    ToolRecoveryPolicy,
    ToolTransport,
    canonical_sha256,
)

WEB_SEARCH_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
DEFAULT_WEB_QUERIES = 2
HARD_WEB_QUERIES: Literal[4] = 4
DEFAULT_WEB_PAGES = 4
HARD_WEB_PAGES: Literal[8] = 8

_DOMAIN_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN_PATTERN = rf"^(?:{_DOMAIN_LABEL})(?:\.(?:{_DOMAIN_LABEL}))*$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_.-]{0,127}$"
_INSTRUCTION_PATTERNS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "developer message",
    "execute this command",
    "call this tool",
)


class WebSourceClass(StrEnum):
    GOVERNMENT = "GOVERNMENT"
    STANDARDS_BODY = "STANDARDS_BODY"
    VENDOR = "VENDOR"
    PRIMARY_RESEARCH = "PRIMARY_RESEARCH"


class WebCacheState(StrEnum):
    MISS = "MISS"
    HIT = "HIT"
    BYPASS = "BYPASS"
    NOT_STORED = "NOT_STORED"


class WebDomainRule(StrictModel):
    domain: str = Field(pattern=_DOMAIN_PATTERN)
    include_subdomains: bool = False
    source_class: WebSourceClass

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_domain(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return _normalize_domain(value)


class WebSearchPolicy(StrictModel):
    schema_version: Literal["1.0.0"] = WEB_SEARCH_CONTRACT_VERSION
    policy_version: str = Field(pattern=_IDENTIFIER_PATTERN)
    domain_rules: tuple[WebDomainRule, ...] = Field(min_length=1, max_length=64)
    active_query_limit: int = Field(default=DEFAULT_WEB_QUERIES, ge=1, le=HARD_WEB_QUERIES)
    hard_query_limit: Literal[4] = HARD_WEB_QUERIES
    active_page_limit: int = Field(default=DEFAULT_WEB_PAGES, ge=1, le=HARD_WEB_PAGES)
    hard_page_limit: Literal[8] = HARD_WEB_PAGES
    current_max_age_seconds: int = Field(default=604_800, ge=60, le=2_592_000)
    max_content_bytes: int = Field(default=200_000, ge=1_000, le=1_000_000)
    max_excerpt_bytes: int = Field(default=5_000, ge=100, le=20_000)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        domains = tuple(rule.domain for rule in self.domain_rules)
        if domains != tuple(sorted(set(domains))):
            raise ValueError("Web domain rules must be sorted and unique")
        if self.active_query_limit > self.hard_query_limit:
            raise ValueError("active Web query limit exceeds the hard limit")
        if self.active_page_limit > self.hard_page_limit:
            raise ValueError("active Web page limit exceeds the hard limit")
        if self.max_excerpt_bytes > self.max_content_bytes:
            raise ValueError("Web excerpt bytes cannot exceed page content bytes")
        return self


class WebSearchRequest(StrictModel):
    schema_version: Literal["1.0.0"] = WEB_SEARCH_CONTRACT_VERSION
    queries: tuple[str, ...] = Field(min_length=1, max_length=HARD_WEB_QUERIES)
    allowed_domains: tuple[str, ...] = Field(default=(), max_length=32)
    current_information_required: bool = False

    @field_validator("queries", mode="before")
    @classmethod
    def normalize_queries(cls, value: object) -> object:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return value
        normalized = tuple(_normalize_query(item) for item in value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Web queries must be unique after normalization")
        return normalized

    @field_validator("allowed_domains", mode="before")
    @classmethod
    def normalize_domains(cls, value: object) -> object:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return value
        normalized = tuple(sorted(_normalize_domain(item) for item in value))
        if len(set(normalized)) != len(normalized):
            raise ValueError("requested Web domains must be unique")
        return normalized


class WebSearchHit(StrictModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    published_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _bounded_web_text(value, "search-hit title")

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        _require_utc_or_none(self.published_at, "search-hit publication time")
        return self


class WebSearchPage(StrictModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    published_at: datetime | None = None
    content: str = Field(min_length=1, max_length=1_000_000)

    @field_validator("title", "content")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _bounded_web_text(value, "page text")

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        _require_utc_or_none(self.published_at, "page publication time")
        return self


class WebEvidence(StrictModel):
    schema_version: Literal["1.0.0"] = WEB_SEARCH_CONTRACT_VERSION
    evidence_id: str = Field(pattern=r"^web-[0-9a-f]{24}$")
    canonical_url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    source_class: WebSourceClass
    published_at: datetime | None = None
    accessed_at: datetime
    locator: str = Field(pattern=r"^body:utf8-bytes:0-[0-9]+$")
    excerpt: str = Field(min_length=1, max_length=20_000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_name: str = Field(pattern=_IDENTIFIER_PATTERN)
    provider_version: str = Field(min_length=1, max_length=128)
    trust: Literal["UNTRUSTED"] = "UNTRUSTED"
    publication_state: Literal["CANDIDATE"] = "CANDIDATE"
    contains_instruction_like_text: bool
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        _require_utc_or_none(self.published_at, "evidence publication time")
        _require_utc(self.accessed_at, "evidence access time")
        if self.excerpt_sha256 != _text_sha256(self.excerpt):
            raise ValueError("Web evidence excerpt hash is invalid")
        if self.evidence_sha256 != web_evidence_sha256(self):
            raise ValueError("Web evidence hash is invalid")
        return self


class WebCitation(StrictModel):
    schema_version: Literal["1.0.0"] = WEB_SEARCH_CONTRACT_VERSION
    citation_id: str = Field(pattern=r"^web-cite-[0-9a-f]{24}$")
    evidence_id: str = Field(pattern=r"^web-[0-9a-f]{24}$")
    canonical_url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    source_class: WebSourceClass
    published_at: datetime | None = None
    accessed_at: datetime
    locator: str = Field(min_length=1, max_length=128)
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    citation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_citation(self) -> Self:
        _require_utc_or_none(self.published_at, "citation publication time")
        _require_utc(self.accessed_at, "citation access time")
        if self.citation_sha256 != web_citation_sha256(self):
            raise ValueError("Web citation hash is invalid")
        return self


class WebSearchSnapshot(StrictModel):
    schema_version: Literal["1.0.0"] = WEB_SEARCH_CONTRACT_VERSION
    source_policy_version: str = Field(pattern=_IDENTIFIER_PATTERN)
    provider_name: str = Field(pattern=_IDENTIFIER_PATTERN)
    provider_version: str = Field(min_length=1, max_length=128)
    evidence: tuple[WebEvidence, ...] = Field(min_length=1, max_length=HARD_WEB_PAGES)
    citations: tuple[WebCitation, ...] = Field(min_length=1, max_length=HARD_WEB_PAGES)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if len(self.evidence) != len(self.citations):
            raise ValueError("Web evidence and citation counts must match")
        if tuple(item.evidence_id for item in self.evidence) != tuple(
            item.evidence_id for item in self.citations
        ):
            raise ValueError("Web citations must bind the ordered evidence set")
        if self.snapshot_sha256 != web_snapshot_sha256(self):
            raise ValueError("Web Search snapshot hash is invalid")
        return self


class WebSearchResult(StrictModel):
    schema_version: Literal["1.0.0"] = WEB_SEARCH_CONTRACT_VERSION
    complete: bool
    error_code: str | None = Field(default=None, pattern=r"^WEB_[A-Z0-9_]+$")
    cache_state: WebCacheState
    source_policy_version: str = Field(pattern=_IDENTIFIER_PATTERN)
    provider_name: str = Field(pattern=_IDENTIFIER_PATTERN)
    provider_version: str = Field(min_length=1, max_length=128)
    queries_requested: int = Field(ge=1, le=HARD_WEB_QUERIES)
    queries_executed: int = Field(ge=0, le=HARD_WEB_QUERIES)
    candidates_seen: int = Field(ge=0, le=HARD_WEB_QUERIES * HARD_WEB_PAGES)
    pages_opened: int = Field(ge=0, le=HARD_WEB_PAGES)
    pages_rejected: int = Field(ge=0, le=HARD_WEB_QUERIES * HARD_WEB_PAGES)
    provider_calls: int = Field(ge=0, le=HARD_WEB_QUERIES + HARD_WEB_PAGES)
    evidence: tuple[WebEvidence, ...] = Field(max_length=HARD_WEB_PAGES)
    citations: tuple[WebCitation, ...] = Field(max_length=HARD_WEB_PAGES)
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.complete != (self.error_code is None and bool(self.evidence)):
            raise ValueError("Web Search completion state is inconsistent")
        if len(self.evidence) != len(self.citations):
            raise ValueError("Web Search evidence and citation counts must match")
        if tuple(item.evidence_id for item in self.evidence) != tuple(
            item.evidence_id for item in self.citations
        ):
            raise ValueError("Web Search citations do not bind the evidence set")
        if self.provider_calls != self.queries_executed + self.pages_opened:
            raise ValueError("Web provider-call count is inconsistent")
        if self.cache_state is WebCacheState.HIT and self.provider_calls != 0:
            raise ValueError("Web cache hits cannot contain provider calls")
        if self.result_sha256 != web_result_sha256(self):
            raise ValueError("Web Search result hash is invalid")
        return self


class WebProviderError(RuntimeError):
    def __init__(self, code: Literal["WEB_PROVIDER_OFFLINE", "WEB_PROVIDER_FAILED"]) -> None:
        self.code = code
        super().__init__("The Web provider did not return a usable response.")


class _WebUrlError(ValueError):
    def __init__(self, code: Literal["WEB_SOURCE_POLICY_DENIED", "WEB_UNSAFE_URL"]) -> None:
        self.code = code
        super().__init__("The provider URL was rejected by Web source policy.")


class WebSearchProvider(Protocol):
    name: str
    version: str

    async def search(self, query: str, *, max_results: int) -> Sequence[WebSearchHit]: ...

    async def open(self, url: str) -> WebSearchPage: ...


class WebSearchAdapter:
    """Validated ToolAdapter for deterministic or live provider implementations."""

    def __init__(
        self,
        provider: WebSearchProvider,
        policy: WebSearchPolicy,
        cache: CacheService,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if re.fullmatch(_IDENTIFIER_PATTERN, provider.name) is None or not provider.version:
            raise ValueError("Web provider name and version must be stable")
        self._provider = provider
        self._policy = policy
        self._cache = cache
        self._clock = clock

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        started = time.monotonic()
        try:
            request = WebSearchRequest.model_validate(invocation.arguments, strict=True)
        except PydanticValidationError:
            return self._tool_result(
                invocation,
                self._failure(
                    queries_requested=1,
                    cache_state=WebCacheState.NOT_STORED,
                    code="WEB_RESPONSE_INVALID",
                ),
                status=ToolStatus.FAILED,
                retryable=False,
                started=started,
            )
        if len(request.queries) > self._policy.active_query_limit:
            return self._tool_result(
                invocation,
                self._failure(
                    queries_requested=len(request.queries),
                    cache_state=WebCacheState.NOT_STORED,
                    code="WEB_BUDGET_EXCEEDED",
                ),
                status=ToolStatus.DENIED,
                retryable=False,
                started=started,
            )
        requested_domains = self._requested_domains(request)
        if requested_domains is None:
            return self._tool_result(
                invocation,
                self._failure(
                    queries_requested=len(request.queries),
                    cache_state=WebCacheState.NOT_STORED,
                    code="WEB_SOURCE_POLICY_DENIED",
                ),
                status=ToolStatus.DENIED,
                retryable=False,
                started=started,
            )
        cache_key = self._cache_key(invocation, request, requested_domains)
        version_manifest = self._version_manifest(invocation)
        now = self._clock()
        cache_record = self._cache.get(
            CacheGetRequest(
                scope=invocation.context.scope,
                cache_class=CacheClass.RETRIEVAL,
                cache_key_sha256=cache_key,
                current_version_manifest=version_manifest,
                current_information_required=request.current_information_required,
                now=now,
            )
        )
        if cache_record is not None:
            try:
                snapshot = WebSearchSnapshot.model_validate(
                    cache_record.value["snapshot"], strict=True
                )
            except (KeyError, PydanticValidationError, TypeError):
                return self._tool_result(
                    invocation,
                    self._failure(
                        queries_requested=len(request.queries),
                        cache_state=WebCacheState.HIT,
                        code="WEB_RESPONSE_INVALID",
                    ),
                    status=ToolStatus.FAILED,
                    retryable=False,
                    started=started,
                )
            result = self._success(
                request,
                snapshot,
                cache_state=WebCacheState.HIT,
                queries_executed=0,
                candidates_seen=0,
                pages_opened=0,
                pages_rejected=0,
            )
            return self._tool_result(
                invocation,
                result,
                status=ToolStatus.SUCCESS,
                retryable=False,
                started=started,
            )

        queries_executed = 0
        pages_opened = 0
        candidates_seen = 0
        pages_rejected = 0
        freshness_rejections = 0
        rejection_codes: set[str] = set()
        try:
            candidates: dict[str, tuple[WebSearchHit, WebDomainRule]] = {}
            for query in request.queries:
                raw_hits = await self._provider.search(
                    query,
                    max_results=self._policy.hard_page_limit,
                )
                queries_executed += 1
                if len(raw_hits) > self._policy.hard_page_limit:
                    raise ValueError("Web provider exceeded the requested result limit")
                for raw_hit in raw_hits:
                    candidates_seen += 1
                    hit = WebSearchHit.model_validate(raw_hit, strict=True)
                    try:
                        selected = self._allowed_url(hit.url, requested_domains)
                    except _WebUrlError as error:
                        pages_rejected += 1
                        rejection_codes.add(error.code)
                        continue
                    canonical_url, rule = selected
                    candidates.setdefault(canonical_url, (hit, rule))
            ordered = sorted(
                candidates.items(),
                key=lambda item: _candidate_rank(item[0], item[1][0], item[1][1]),
            )
            evidence: list[WebEvidence] = []
            citations: list[WebCitation] = []
            opened_urls: set[str] = set()
            for candidate_url, (_hit, _rule) in ordered:
                if pages_opened >= self._policy.active_page_limit:
                    break
                raw_page = await self._provider.open(candidate_url)
                pages_opened += 1
                page = WebSearchPage.model_validate(raw_page, strict=True)
                try:
                    selected_page = self._allowed_url(page.url, requested_domains)
                except _WebUrlError as error:
                    pages_rejected += 1
                    rejection_codes.add(error.code)
                    continue
                canonical_page_url, page_rule = selected_page
                if canonical_page_url in opened_urls:
                    pages_rejected += 1
                    continue
                opened_urls.add(canonical_page_url)
                content_bytes = page.content.encode("utf-8")
                if len(content_bytes) > self._policy.max_content_bytes:
                    pages_rejected += 1
                    rejection_codes.add("WEB_RESPONSE_INVALID")
                    continue
                if request.current_information_required and not self._is_current(page, now):
                    pages_rejected += 1
                    freshness_rejections += 1
                    continue
                item = self._evidence(page, canonical_page_url, page_rule, now)
                evidence.append(item)
                citations.append(_citation(item))
        except WebProviderError as error:
            result = self._failure(
                queries_requested=len(request.queries),
                cache_state=(
                    WebCacheState.BYPASS
                    if request.current_information_required
                    else WebCacheState.MISS
                ),
                code=error.code,
                queries_executed=queries_executed,
                candidates_seen=candidates_seen,
                pages_opened=pages_opened,
                pages_rejected=pages_rejected,
            )
            return self._tool_result(
                invocation,
                result,
                status=(
                    ToolStatus.BLOCKED
                    if error.code == "WEB_PROVIDER_OFFLINE"
                    else ToolStatus.FAILED
                ),
                retryable=True,
                started=started,
            )
        except (PydanticValidationError, UnicodeError, ValueError, TypeError):
            result = self._failure(
                queries_requested=len(request.queries),
                cache_state=(
                    WebCacheState.BYPASS
                    if request.current_information_required
                    else WebCacheState.MISS
                ),
                code="WEB_RESPONSE_INVALID",
                queries_executed=queries_executed,
                candidates_seen=candidates_seen,
                pages_opened=pages_opened,
                pages_rejected=pages_rejected,
            )
            return self._tool_result(
                invocation,
                result,
                status=ToolStatus.FAILED,
                retryable=False,
                started=started,
            )
        except Exception:
            result = self._failure(
                queries_requested=len(request.queries),
                cache_state=(
                    WebCacheState.BYPASS
                    if request.current_information_required
                    else WebCacheState.MISS
                ),
                code="WEB_PROVIDER_FAILED",
                queries_executed=queries_executed,
                candidates_seen=candidates_seen,
                pages_opened=pages_opened,
                pages_rejected=pages_rejected,
            )
            return self._tool_result(
                invocation,
                result,
                status=ToolStatus.FAILED,
                retryable=True,
                started=started,
            )

        if not evidence:
            if request.current_information_required and freshness_rejections:
                code = "WEB_FRESHNESS_UNSATISFIED"
            elif "WEB_UNSAFE_URL" in rejection_codes:
                code = "WEB_UNSAFE_URL"
            elif "WEB_SOURCE_POLICY_DENIED" in rejection_codes:
                code = "WEB_SOURCE_POLICY_DENIED"
            elif "WEB_RESPONSE_INVALID" in rejection_codes:
                code = "WEB_RESPONSE_INVALID"
            else:
                code = "WEB_EVIDENCE_EMPTY"
            result = self._failure(
                queries_requested=len(request.queries),
                cache_state=(
                    WebCacheState.BYPASS
                    if request.current_information_required
                    else WebCacheState.MISS
                ),
                code=code,
                queries_executed=queries_executed,
                candidates_seen=candidates_seen,
                pages_opened=pages_opened,
                pages_rejected=pages_rejected,
            )
            return self._tool_result(
                invocation,
                result,
                status=(
                    ToolStatus.DENIED
                    if code in {"WEB_SOURCE_POLICY_DENIED", "WEB_UNSAFE_URL"}
                    else ToolStatus.FAILED
                    if code == "WEB_RESPONSE_INVALID"
                    else ToolStatus.BLOCKED
                ),
                retryable=False,
                started=started,
            )

        snapshot = _snapshot(
            self._policy.policy_version,
            self._provider.name,
            self._provider.version,
            tuple(evidence),
            tuple(citations),
        )
        cache_state = (
            WebCacheState.BYPASS if request.current_information_required else WebCacheState.MISS
        )
        if not request.current_information_required:
            cache_value = cast(
                dict[str, JsonValue],
                {"snapshot": snapshot.model_dump(mode="json")},
            )
            self._cache.put(
                CachePutRequest(
                    cache_entry_id=uuid4(),
                    scope=invocation.context.scope,
                    cache_class=CacheClass.RETRIEVAL,
                    cache_key_sha256=cache_key,
                    value=cache_value,
                    value_sha256=cache_value_sha256(cache_value),
                    version_manifest=version_manifest,
                    provenance={
                        "provider": f"{self._provider.name}@{self._provider.version}",
                        "snapshot_sha256": snapshot.snapshot_sha256,
                    },
                    contains_secret=False,
                    contains_authorization_decision=False,
                    stable=True,
                    side_effect=CacheSideEffect.READ,
                    task_class="G0",
                    refresh=True,
                    created_at=now,
                )
            )
        result = self._success(
            request,
            snapshot,
            cache_state=cache_state,
            queries_executed=queries_executed,
            candidates_seen=candidates_seen,
            pages_opened=pages_opened,
            pages_rejected=pages_rejected,
        )
        return self._tool_result(
            invocation,
            result,
            status=ToolStatus.SUCCESS,
            retryable=False,
            started=started,
        )

    def _requested_domains(self, request: WebSearchRequest) -> frozenset[str] | None:
        policy_domains = {rule.domain for rule in self._policy.domain_rules}
        requested = frozenset(request.allowed_domains or tuple(sorted(policy_domains)))
        if not requested <= policy_domains:
            return None
        return requested

    def _allowed_url(
        self,
        raw_url: str,
        requested_domains: frozenset[str],
    ) -> tuple[str, WebDomainRule]:
        try:
            canonical_url, host = _canonical_web_url(raw_url)
        except ValueError as error:
            raise _WebUrlError("WEB_UNSAFE_URL") from error
        for rule in self._policy.domain_rules:
            if rule.domain not in requested_domains:
                continue
            if host == rule.domain or (
                rule.include_subdomains and host.endswith(f".{rule.domain}")
            ):
                return canonical_url, rule
        raise _WebUrlError("WEB_SOURCE_POLICY_DENIED")

    def _is_current(self, page: WebSearchPage, now: datetime) -> bool:
        return bool(
            page.published_at is not None
            and timedelta(0)
            <= now - page.published_at
            <= timedelta(seconds=self._policy.current_max_age_seconds)
        )

    def _evidence(
        self,
        page: WebSearchPage,
        canonical_url: str,
        rule: WebDomainRule,
        now: datetime,
    ) -> WebEvidence:
        content_bytes = page.content.encode("utf-8")
        excerpt = content_bytes[: self._policy.max_excerpt_bytes].decode("utf-8", errors="ignore")
        excerpt_bytes = excerpt.encode("utf-8")
        content_sha256 = hashlib.sha256(content_bytes).hexdigest()
        excerpt_sha256 = hashlib.sha256(excerpt_bytes).hexdigest()
        identity = canonical_sha256(
            {
                "canonical_url": canonical_url,
                "content_sha256": content_sha256,
                "accessed_at": now.isoformat(),
                "provider": f"{self._provider.name}@{self._provider.version}",
            }
        )
        payload: dict[str, Any] = {
            "schema_version": WEB_SEARCH_CONTRACT_VERSION,
            "evidence_id": f"web-{identity[:24]}",
            "canonical_url": canonical_url,
            "title": page.title,
            "source_class": rule.source_class,
            "published_at": page.published_at,
            "accessed_at": now,
            "locator": f"body:utf8-bytes:0-{len(excerpt_bytes)}",
            "excerpt": excerpt,
            "content_sha256": content_sha256,
            "excerpt_sha256": excerpt_sha256,
            "provider_name": self._provider.name,
            "provider_version": self._provider.version,
            "trust": "UNTRUSTED",
            "publication_state": "CANDIDATE",
            "contains_instruction_like_text": _contains_instruction_like_text(excerpt),
        }
        return WebEvidence.model_validate(
            {**payload, "evidence_sha256": canonical_sha256(_jsonable(payload))}
        )

    def _cache_key(
        self,
        invocation: ToolInvocation,
        request: WebSearchRequest,
        requested_domains: frozenset[str],
    ) -> str:
        return canonical_sha256(
            {
                "schema_version": WEB_SEARCH_CONTRACT_VERSION,
                "scope": invocation.context.scope.model_dump(mode="json"),
                "queries": request.queries,
                "domains": sorted(requested_domains),
                "current_information_required": request.current_information_required,
                "source_policy_version": self._policy.policy_version,
                "provider": f"{self._provider.name}@{self._provider.version}",
                "active_query_limit": self._policy.active_query_limit,
                "active_page_limit": self._policy.active_page_limit,
                "max_content_bytes": self._policy.max_content_bytes,
                "max_excerpt_bytes": self._policy.max_excerpt_bytes,
            }
        )

    def _version_manifest(self, invocation: ToolInvocation) -> dict[str, str]:
        return {
            "web_policy": self._policy.policy_version,
            "provider": f"{self._provider.name}@{self._provider.version}",
            "schema": WEB_SEARCH_CONTRACT_VERSION,
            "permission": invocation.context.scope.permission_version,
        }

    def _success(
        self,
        request: WebSearchRequest,
        snapshot: WebSearchSnapshot,
        *,
        cache_state: WebCacheState,
        queries_executed: int,
        candidates_seen: int,
        pages_opened: int,
        pages_rejected: int,
    ) -> WebSearchResult:
        payload: dict[str, Any] = {
            "schema_version": WEB_SEARCH_CONTRACT_VERSION,
            "complete": True,
            "error_code": None,
            "cache_state": cache_state,
            "source_policy_version": self._policy.policy_version,
            "provider_name": self._provider.name,
            "provider_version": self._provider.version,
            "queries_requested": len(request.queries),
            "queries_executed": queries_executed,
            "candidates_seen": candidates_seen,
            "pages_opened": pages_opened,
            "pages_rejected": pages_rejected,
            "provider_calls": queries_executed + pages_opened,
            "evidence": snapshot.evidence,
            "citations": snapshot.citations,
        }
        return WebSearchResult.model_validate(
            {**payload, "result_sha256": canonical_sha256(_jsonable(payload))}
        )

    def _failure(
        self,
        *,
        queries_requested: int,
        cache_state: WebCacheState,
        code: str,
        queries_executed: int = 0,
        candidates_seen: int = 0,
        pages_opened: int = 0,
        pages_rejected: int = 0,
    ) -> WebSearchResult:
        payload: dict[str, Any] = {
            "schema_version": WEB_SEARCH_CONTRACT_VERSION,
            "complete": False,
            "error_code": code,
            "cache_state": cache_state,
            "source_policy_version": self._policy.policy_version,
            "provider_name": self._provider.name,
            "provider_version": self._provider.version,
            "queries_requested": queries_requested,
            "queries_executed": queries_executed,
            "candidates_seen": candidates_seen,
            "pages_opened": pages_opened,
            "pages_rejected": pages_rejected,
            "provider_calls": queries_executed + pages_opened,
            "evidence": (),
            "citations": (),
        }
        return WebSearchResult.model_validate(
            {**payload, "result_sha256": canonical_sha256(_jsonable(payload))}
        )

    def _tool_result(
        self,
        invocation: ToolInvocation,
        result: WebSearchResult,
        *,
        status: ToolStatus,
        retryable: bool,
        started: float,
    ) -> ToolResult:
        output = result.model_dump(mode="json")
        return ToolResult(
            call_id=invocation.call_id,
            task_id=invocation.context.task_id,
            run_id=invocation.context.run_id,
            scope=invocation.context.scope,
            tool_name=invocation.definition.name,
            tool_version=invocation.definition.version,
            status=status,
            output=output,
            exit_code=0 if status is ToolStatus.SUCCESS else None,
            stdout="",
            stderr="",
            encoding="utf-8",
            truncated=False,
            artifacts=(),
            idempotency_key=invocation.idempotency_key,
            input_sha256=invocation.input_sha256,
            output_sha256=canonical_sha256(output),
            error_code=None if status is ToolStatus.SUCCESS else result.error_code,
            retryable=retryable,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            completed_at=self._clock(),
        )


def web_search_tool_definition(
    *,
    version: str,
    timeout_ms: int = 20_000,
    secret_purposes: frozenset[str] = frozenset(),
) -> ToolDefinition:
    input_schema = WebSearchRequest.model_json_schema()
    output_schema = WebSearchResult.model_json_schema()
    input_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    output_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return ToolDefinition(
        name="web.search",
        version=version,
        purpose="Retrieve bounded untrusted Web evidence with exact citations.",
        kind=ToolKind.WEB_SEARCH,
        transport=ToolTransport.HTTP_API,
        data_scope=ToolDataScope.TASK,
        data_destination=ToolDataDestination.APPROVED_EXTERNAL,
        side_effect=SideEffectClass.READ_ONLY,
        input_schema=input_schema,
        output_schema=output_schema,
        required_permissions=frozenset({"web.search"}),
        timeout_ms=timeout_ms,
        max_attempts=2,
        max_concurrency=3,
        max_input_bytes=32_000,
        max_output_bytes=500_000,
        max_tokens=0,
        idempotency=IdempotencyPolicy.NONE,
        secret_purposes=secret_purposes,
        network=NetworkPolicy.RESTRICTED,
        declared_error_codes=frozenset(
            {
                "WEB_BUDGET_EXCEEDED",
                "WEB_EVIDENCE_EMPTY",
                "WEB_FRESHNESS_UNSATISFIED",
                "WEB_PROVIDER_FAILED",
                "WEB_PROVIDER_OFFLINE",
                "WEB_RESPONSE_INVALID",
                "WEB_SOURCE_POLICY_DENIED",
                "WEB_UNSAFE_URL",
            }
        ),
        recovery_policy=ToolRecoveryPolicy.RETRY_READ_ONLY,
        audit_owner="web-tool-runtime",
        test_owner="web-tool-runtime",
        test_groups=frozenset({"INT-WEB", "SEC-TOOLS", "EVAL-QA", "EVAL-TOKEN"}),
    )


def web_evidence_sha256(value: WebEvidence) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"evidence_sha256"}))


def web_citation_sha256(value: WebCitation) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"citation_sha256"}))


def web_snapshot_sha256(value: WebSearchSnapshot) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"snapshot_sha256"}))


def web_result_sha256(value: WebSearchResult) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"result_sha256"}))


def _snapshot(
    policy_version: str,
    provider_name: str,
    provider_version: str,
    evidence: tuple[WebEvidence, ...],
    citations: tuple[WebCitation, ...],
) -> WebSearchSnapshot:
    payload: dict[str, Any] = {
        "schema_version": WEB_SEARCH_CONTRACT_VERSION,
        "source_policy_version": policy_version,
        "provider_name": provider_name,
        "provider_version": provider_version,
        "evidence": evidence,
        "citations": citations,
    }
    return WebSearchSnapshot.model_validate(
        {**payload, "snapshot_sha256": canonical_sha256(_jsonable(payload))}
    )


def _citation(evidence: WebEvidence) -> WebCitation:
    identity = canonical_sha256(
        {
            "evidence_id": evidence.evidence_id,
            "excerpt_sha256": evidence.excerpt_sha256,
            "locator": evidence.locator,
        }
    )
    payload: dict[str, Any] = {
        "schema_version": WEB_SEARCH_CONTRACT_VERSION,
        "citation_id": f"web-cite-{identity[:24]}",
        "evidence_id": evidence.evidence_id,
        "canonical_url": evidence.canonical_url,
        "title": evidence.title,
        "source_class": evidence.source_class,
        "published_at": evidence.published_at,
        "accessed_at": evidence.accessed_at,
        "locator": evidence.locator,
        "excerpt_sha256": evidence.excerpt_sha256,
    }
    return WebCitation.model_validate(
        {**payload, "citation_sha256": canonical_sha256(_jsonable(payload))}
    )


def _candidate_rank(
    url: str,
    hit: WebSearchHit,
    rule: WebDomainRule,
) -> tuple[int, float, str]:
    priorities = {
        WebSourceClass.GOVERNMENT: 0,
        WebSourceClass.STANDARDS_BODY: 1,
        WebSourceClass.PRIMARY_RESEARCH: 2,
        WebSourceClass.VENDOR: 3,
    }
    timestamp = hit.published_at.timestamp() if hit.published_at is not None else 0.0
    return priorities[rule.source_class], -timestamp, url


def _canonical_web_url(value: str) -> tuple[str, str]:
    if (
        not value
        or len(value) > 2_048
        or any(char.isspace() or unicodedata.category(char).startswith("C") for char in value)
    ):
        raise ValueError("Web URL contains unsafe text")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Web URL port is invalid") from error
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise ValueError("Web URL violates the HTTPS source policy")
    host = _normalize_domain(parsed.hostname)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("literal IP addresses are not allowed")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("localhost is not an allowed Web source")
    canonical = urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    return canonical, host


def _normalize_query(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Web queries must be strings")
    normalized = unicodedata.normalize("NFKC", value)
    if any(
        unicodedata.category(char).startswith("C") and not char.isspace() for char in normalized
    ):
        raise ValueError("Web query contains a forbidden control character")
    collapsed = " ".join(normalized.split())
    if not collapsed or len(collapsed) > 1_000:
        raise ValueError("Web query length is invalid")
    return collapsed


def _normalize_domain(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Web domains must be strings")
    raw = value.strip().rstrip(".").lower()
    try:
        domain = raw.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("Web domain IDNA encoding is invalid") from error
    if re.fullmatch(_DOMAIN_PATTERN, domain) is None:
        raise ValueError("Web domain is invalid")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError("literal IP domains are not allowed")
    if domain == "localhost" or domain.endswith(".localhost"):
        raise ValueError("localhost is not an allowed Web domain")
    return domain


def _contains_instruction_like_text(value: str) -> bool:
    lowered = unicodedata.normalize("NFKC", value).lower()
    return any(pattern in lowered for pattern in _INSTRUCTION_PATTERNS)


def _bounded_web_text(value: str, label: str) -> str:
    if any(
        unicodedata.category(char).startswith("C") and char not in {"\n", "\r", "\t"}
        for char in value
    ):
        raise ValueError(f"{label} contains a forbidden control character")
    return value


def _require_utc(value: datetime, label: str) -> None:
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{label} must use UTC")


def _require_utc_or_none(value: datetime | None, label: str) -> None:
    if value is not None:
        _require_utc(value, label)


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _jsonable(value: Mapping[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], {key: _json_value(item) for key, item in value.items()})


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value
