"""S4-01 Technical QA Skill with exact citation and claim-support validation."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import AgentStatus, Issue, StrictModel, TenantScope
from ndt_agents.knowledge.retrieval import (
    EmbeddingPort,
    IndexRecord,
    IndexSnapshot,
    IndexStatus,
    InMemoryKnowledgeIndex,
    RetrievalCitation,
    RetrievalHit,
    RetrievalQuery,
    tokenize,
)

QA_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
SUPPORTED_METHODS = frozenset({"UT", "GPR", "IE", "RT", "AE", "MV"})
SUPPORTED_STRUCTURES = frozenset(
    {
        "ROAD",
        "BRIDGE",
        "TUNNEL",
        "HYDRAULIC_STRUCTURE",
        "MUNICIPAL_BUILDING",
        "ENERGY_INFRASTRUCTURE_BUILDING",
    }
)
SUPPORTED_MATERIALS = frozenset(
    {
        "PLAIN_CONCRETE",
        "REINFORCED_CONCRETE",
        "STRUCTURAL_STEEL",
        "CONCRETE_FILLED_STEEL_TUBE",
        "OTHER_VERSIONED_MATERIAL",
    }
)
_ZERO_SHA256 = "0" * 64


class ClaimSeverity(StrEnum):
    INFORMATIONAL = "INFORMATIONAL"
    MATERIAL = "MATERIAL"
    CRITICAL = "CRITICAL"


class ClaimApplicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CONDITIONAL = "CONDITIONAL"
    UNKNOWN = "UNKNOWN"


class ClaimConclusionLevel(StrEnum):
    EVIDENCE_STATEMENT = "EVIDENCE_STATEMENT"
    PRELIMINARY_ASSESSMENT = "PRELIMINARY_ASSESSMENT"
    FORMAL_CONCLUSION = "FORMAL_CONCLUSION"


class TechnicalQARequest(StrictModel):
    schema_version: Literal["1.0.0"] = QA_CONTRACT_VERSION
    task_id: UUID
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    question: str = Field(min_length=1, max_length=8_000)
    method_code: str | None = Field(default=None, min_length=1, max_length=32)
    structure_class: str | None = Field(default=None, min_length=1, max_length=128)
    material_class: str | None = Field(default=None, min_length=1, max_length=128)
    corpus_id: str = Field(min_length=1, max_length=128)
    corpus_version: str = Field(min_length=1, max_length=64)
    index_version: str = Field(min_length=1, max_length=64)
    embedding_version: str = Field(min_length=1, max_length=128)
    required_metadata: dict[str, str] = Field(default_factory=dict, max_length=32)
    top_k: int = Field(default=6, ge=1, le=10)
    candidate_limit: int = Field(default=50, ge=1, le=100)


class QAClaimSupport(StrictModel):
    chunk_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    quote: str = Field(min_length=1, max_length=1_200)
    matching_terms: tuple[str, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_terms(self) -> Self:
        canonical = tuple(sorted(set(term.casefold().strip() for term in self.matching_terms)))
        if not all(canonical) or canonical != self.matching_terms:
            raise ValueError("support matching terms must be canonical, sorted, and unique")
        return self


class TechnicalQACandidateClaim(StrictModel):
    statement: str = Field(min_length=1, max_length=4_000)
    severity: ClaimSeverity
    applicability: ClaimApplicability
    conclusion_level: ClaimConclusionLevel
    limitations: tuple[str, ...] = Field(min_length=1, max_length=16)
    uncertainty: str = Field(min_length=1, max_length=2_000)
    supports: tuple[QAClaimSupport, ...] = Field(default=(), max_length=8)
    human_confirmation_required: bool = False

    @model_validator(mode="after")
    def validate_safety_shape(self) -> Self:
        if self.limitations != tuple(dict.fromkeys(self.limitations)):
            raise ValueError("claim limitations must be unique and ordered")
        if self.severity is ClaimSeverity.CRITICAL and not self.human_confirmation_required:
            raise ValueError("critical claims require human confirmation")
        if (
            self.conclusion_level is ClaimConclusionLevel.FORMAL_CONCLUSION
            and not self.human_confirmation_required
        ):
            raise ValueError("formal conclusions require human confirmation")
        if self.applicability is ClaimApplicability.UNKNOWN and self.conclusion_level is not (
            ClaimConclusionLevel.EVIDENCE_STATEMENT
        ):
            raise ValueError("unknown applicability cannot produce an assessment conclusion")
        identities = tuple((item.chunk_id, item.quote) for item in self.supports)
        if len(set(identities)) != len(identities):
            raise ValueError("claim supports must be unique")
        return self


class TechnicalQACandidate(StrictModel):
    schema_version: Literal["1.0.0"] = QA_CONTRACT_VERSION
    summary: str = Field(min_length=1, max_length=8_000)
    claims: tuple[TechnicalQACandidateClaim, ...] = Field(min_length=1, max_length=32)
    missing_inputs: tuple[str, ...] = Field(default=(), max_length=32)
    overall_limitation: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if self.missing_inputs != tuple(sorted(set(self.missing_inputs))):
            raise ValueError("candidate missing inputs must be sorted and unique")
        identities = tuple(_claim_identity(item) for item in self.claims)
        if len(set(identities)) != len(identities):
            raise ValueError("candidate claims must be unique")
        return self


class QACitation(StrictModel):
    schema_version: Literal["1.0.0"] = QA_CONTRACT_VERSION
    claim_id: str = Field(pattern=r"^claim-[0-9a-f]{16}$")
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_id: str = Field(min_length=36, max_length=36)
    artifact_version: str = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_title: str = Field(min_length=1, max_length=1_000)
    source_media_type: str = Field(min_length=1, max_length=255)
    parser_name: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    normalizer_version: str = Field(min_length=1, max_length=128)
    page_index: int = Field(ge=0, lt=2_000)
    locator_type: str = Field(min_length=1, max_length=32)
    locator: str = Field(min_length=1, max_length=512)
    quote: str = Field(min_length=1, max_length=1_200)
    matching_terms: tuple[str, ...] = Field(min_length=1, max_length=12)


class TechnicalQAClaim(StrictModel):
    claim_id: str = Field(pattern=r"^claim-[0-9a-f]{16}$")
    statement: str = Field(min_length=1, max_length=4_000)
    severity: ClaimSeverity
    applicability: ClaimApplicability
    conclusion_level: ClaimConclusionLevel
    limitations: tuple[str, ...]
    uncertainty: str
    citations: tuple[QACitation, ...] = Field(max_length=8)
    human_confirmation_required: bool


class TechnicalQAResult(StrictModel):
    schema_version: Literal["1.0.0"] = QA_CONTRACT_VERSION
    skill_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    scope: TenantScope
    task_id: UUID
    request_id: str
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AgentStatus
    summary: str = Field(min_length=1, max_length=8_000)
    claims: tuple[TechnicalQAClaim, ...] = Field(max_length=32)
    missing_inputs: tuple[str, ...] = Field(max_length=32)
    issues: tuple[Issue, ...] = Field(max_length=64)
    evidence_snapshot_ids: tuple[str, ...] = Field(max_length=10)
    human_confirmation_required: bool
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status is AgentStatus.SUCCESS and not self.claims:
            raise ValueError("successful QA output requires at least one claim")
        if self.status is AgentStatus.SUCCESS and any(
            item.severity in {"ERROR", "CRITICAL"} for item in self.issues
        ):
            raise ValueError("successful QA output cannot retain blocking findings")
        if self.status is AgentStatus.HUMAN_REQUIRED and not self.human_confirmation_required:
            raise ValueError("human-required QA output must set the confirmation boundary")
        if self.evidence_snapshot_ids != tuple(sorted(set(self.evidence_snapshot_ids))):
            raise ValueError("evidence snapshot IDs must be sorted and unique")
        if self.result_sha256 != technical_qa_result_sha256(self):
            raise ValueError("QA result hash does not match its immutable content")
        return self


class TechnicalQASkill:
    """Finalize a candidate answer without trusting candidate citations or conclusions."""

    def __init__(
        self,
        repository: InMemoryKnowledgeIndex,
        embedding: EmbeddingPort,
        *,
        skill_version: str = "technical-qa-skill-1.0.0",
        prompt_version: str = "technical-qa-prompt-1.1.0",
    ) -> None:
        self._repository = repository
        self._embedding = embedding
        self.skill_version = skill_version
        self.prompt_version = prompt_version

    def execute(
        self,
        scope: TenantScope,
        request: TechnicalQARequest,
        candidate: TechnicalQACandidate | None,
    ) -> TechnicalQAResult:
        request_hash = _canonical_hash(request.model_dump(mode="json"))
        missing = tuple(
            name
            for name, value in (
                ("method_code", request.method_code),
                ("structure_class", request.structure_class),
                ("material_class", request.material_class),
            )
            if value is None
        )
        if missing:
            return self._terminal(
                scope,
                request,
                request_hash,
                AgentStatus.NEEDS_USER,
                "Required applicability inputs are missing.",
                missing_inputs=missing,
                issues=tuple(
                    _issue(
                        "QA_REQUIRED_INPUT_MISSING",
                        "ERROR",
                        f"The required applicability field '{name}' is missing.",
                        f"request.{name}",
                        "Provide the exact method, structure class, and material class.",
                    )
                    for name in missing
                ),
            )
        unsupported = tuple(
            (name, value)
            for name, value, supported in (
                ("method_code", request.method_code, SUPPORTED_METHODS),
                ("structure_class", request.structure_class, SUPPORTED_STRUCTURES),
                ("material_class", request.material_class, SUPPORTED_MATERIALS),
            )
            if value not in supported
        )
        if unsupported:
            return self._terminal(
                scope,
                request,
                request_hash,
                AgentStatus.HUMAN_REQUIRED,
                "The question is outside the declared V1 professional domain.",
                issues=tuple(
                    _issue(
                        "QA_DOMAIN_OUT_OF_SCOPE",
                        "CRITICAL",
                        f"The value '{value}' is outside the registered V1 {name} domain.",
                        f"request.{name}",
                        "Route to a qualified domain owner or register a versioned "
                        "Skill extension.",
                    )
                    for name, value in unsupported
                ),
                human_confirmation_required=True,
            )
        if candidate is None:
            return self._terminal(
                scope,
                request,
                request_hash,
                AgentStatus.NEEDS_USER,
                "No candidate answer was supplied for deterministic validation.",
                issues=(
                    _issue(
                        "QA_CANDIDATE_MISSING",
                        "ERROR",
                        "The Technical QA child did not return a candidate answer.",
                        "candidate",
                        "Run the authorized Technical QA child and submit its typed candidate.",
                    ),
                ),
            )

        query = RetrievalQuery(
            text=request.question,
            corpus_id=request.corpus_id,
            corpus_version=request.corpus_version,
            index_version=request.index_version,
            embedding_version=request.embedding_version,
            top_k=request.top_k,
            candidate_limit=request.candidate_limit,
            required_metadata=request.required_metadata,
        )
        from ndt_agents.knowledge.retrieval import HybridRetrievalService

        retrieval = HybridRetrievalService(self._repository, self._embedding).retrieve(scope, query)
        hits = {item.chunk_id: item for item in retrieval.hits}
        snapshots = {
            item.snapshot_id: item
            for item in self._repository.list_for_scope(scope)
            if _snapshot_matches_request(item, scope, request)
        }
        claims: list[TechnicalQAClaim] = []
        issues: list[Issue] = []
        snapshot_ids: set[str] = set()

        for index, draft in enumerate(candidate.claims):
            claim_id = _claim_id(draft)
            citations: list[QACitation] = []
            for support in draft.supports:
                hit = hits.get(support.chunk_id)
                if hit is None:
                    issues.append(
                        _issue(
                            "QA_SUPPORT_NOT_RETRIEVED",
                            "ERROR",
                            "A claimed support chunk was not in the authorized retrieval result.",
                            f"claims.{index}.supports",
                            "Remove the support or retrieve current authorized evidence.",
                        )
                    )
                    continue
                snapshot = snapshots.get(hit.snapshot_id)
                record = _find_record(snapshot, hit.chunk_id) if snapshot is not None else None
                if snapshot is None or record is None or not _hit_matches_record(hit, record):
                    issues.append(
                        _issue(
                            "QA_CITATION_IDENTITY_INVALID",
                            "CRITICAL",
                            "Citation identity, state, or hash failed exact evidence validation.",
                            f"claims.{index}.supports",
                            "Stop and retrieve the current published source again.",
                        )
                    )
                    continue
                support_issue = _validate_support(draft.statement, support, hit)
                if support_issue is not None:
                    issues.append(
                        support_issue.model_copy(
                            update={"affected_path": f"claims.{index}.supports"}
                        )
                    )
                    continue
                citations.append(_qa_citation(claim_id, snapshot, hit, support))
                snapshot_ids.add(snapshot.snapshot_id)
            if not citations:
                severity: Literal["ERROR", "CRITICAL"] = (
                    "CRITICAL"
                    if draft.severity is ClaimSeverity.CRITICAL
                    or draft.conclusion_level is ClaimConclusionLevel.FORMAL_CONCLUSION
                    else "ERROR"
                )
                issues.append(
                    _issue(
                        "QA_CLAIM_UNSUPPORTED",
                        severity,
                        "A material technical claim has no validated supporting citation.",
                        f"claims.{index}",
                        "Revise the claim, retrieve applicable evidence, or escalate to a human.",
                    )
                )
            if draft.conclusion_level is ClaimConclusionLevel.FORMAL_CONCLUSION:
                issues.append(
                    _issue(
                        "QA_FORMAL_CONCLUSION_REQUIRES_HUMAN",
                        "CRITICAL",
                        "A Technical QA Skill cannot issue an unapproved formal conclusion.",
                        f"claims.{index}.conclusion_level",
                        "Route the evidence-bound result to a qualified human approval workflow.",
                    )
                )
            claims.append(
                TechnicalQAClaim(
                    claim_id=claim_id,
                    statement=draft.statement,
                    severity=draft.severity,
                    applicability=draft.applicability,
                    conclusion_level=draft.conclusion_level,
                    limitations=draft.limitations,
                    uncertainty=draft.uncertainty,
                    citations=tuple(citations),
                    human_confirmation_required=draft.human_confirmation_required,
                )
            )

        blocking = any(item.severity in {"ERROR", "CRITICAL"} for item in issues)
        human_required = any(item.severity == "CRITICAL" for item in issues) or any(
            item.human_confirmation_required for item in candidate.claims
        )
        status = (
            AgentStatus.HUMAN_REQUIRED
            if human_required
            else AgentStatus.PARTIAL_SUCCESS
            if blocking or candidate.missing_inputs
            else AgentStatus.SUCCESS
        )
        return self._result(
            scope=scope,
            request=request,
            request_hash=request_hash,
            retrieval_query_sha256=retrieval.query_sha256,
            status=status,
            summary=candidate.summary,
            claims=tuple(claims),
            missing_inputs=candidate.missing_inputs,
            issues=tuple(issues),
            snapshot_ids=tuple(sorted(snapshot_ids)),
            human_confirmation_required=human_required,
        )

    def _terminal(
        self,
        scope: TenantScope,
        request: TechnicalQARequest,
        request_hash: str,
        status: AgentStatus,
        summary: str,
        *,
        missing_inputs: tuple[str, ...] = (),
        issues: tuple[Issue, ...] = (),
        human_confirmation_required: bool = False,
    ) -> TechnicalQAResult:
        return self._result(
            scope=scope,
            request=request,
            request_hash=request_hash,
            retrieval_query_sha256=_ZERO_SHA256,
            status=status,
            summary=summary,
            claims=(),
            missing_inputs=missing_inputs,
            issues=issues,
            snapshot_ids=(),
            human_confirmation_required=human_confirmation_required,
        )

    def _result(
        self,
        *,
        scope: TenantScope,
        request: TechnicalQARequest,
        request_hash: str,
        retrieval_query_sha256: str,
        status: AgentStatus,
        summary: str,
        claims: tuple[TechnicalQAClaim, ...],
        missing_inputs: tuple[str, ...],
        issues: tuple[Issue, ...],
        snapshot_ids: tuple[str, ...],
        human_confirmation_required: bool,
    ) -> TechnicalQAResult:
        payload = {
            "schema_version": QA_CONTRACT_VERSION,
            "skill_version": self.skill_version,
            "prompt_version": self.prompt_version,
            "scope": scope,
            "task_id": request.task_id,
            "request_id": request.request_id,
            "request_sha256": request_hash,
            "retrieval_query_sha256": retrieval_query_sha256,
            "status": status,
            "summary": summary,
            "claims": claims,
            "missing_inputs": missing_inputs,
            "issues": issues,
            "evidence_snapshot_ids": snapshot_ids,
            "human_confirmation_required": human_confirmation_required,
        }
        return TechnicalQAResult.model_validate(
            {**payload, "result_sha256": _canonical_hash(_jsonable(payload))}
        )


def technical_qa_result_sha256(result: TechnicalQAResult) -> str:
    return _canonical_hash(result.model_dump(mode="json", exclude={"result_sha256"}))


def _snapshot_matches_request(
    snapshot: IndexSnapshot, scope: TenantScope, request: TechnicalQARequest
) -> bool:
    return (
        snapshot.scope == scope
        and snapshot.status is IndexStatus.PUBLISHED
        and snapshot.corpus_id == request.corpus_id
        and snapshot.corpus_version == request.corpus_version
        and snapshot.index_version == request.index_version
        and snapshot.embedding_version == request.embedding_version
        and set(snapshot.required_roles).issubset(scope.role_codes)
        and all(
            snapshot.metadata.get(key) == value for key, value in request.required_metadata.items()
        )
    )


def _find_record(snapshot: IndexSnapshot | None, chunk_id: str) -> IndexRecord | None:
    if snapshot is None:
        return None
    return next((item for item in snapshot.records if item.chunk_id == chunk_id), None)


def _hit_matches_record(hit: RetrievalHit, record: IndexRecord) -> bool:
    citation = hit.citation
    expected = RetrievalCitation(
        artifact_id=record.artifact_id,
        artifact_version=record.artifact_version,
        source_sha256=record.source_sha256,
        source_title=record.source_title,
        source_media_type=record.source_media_type,
        parser_name=record.parser_name,
        parser_version=record.parser_version,
        normalizer_version=record.normalizer_version,
        document_id=record.document_id,
        document_sha256=record.document_sha256,
        chunk_id=record.chunk_id,
        content_sha256=record.content_sha256,
        page_index=record.page_index,
        section_path=record.section_path,
        locator_type=record.locator_type,
        locator=record.locator,
    )
    return hit.text == record.text and citation == expected


def _validate_support(statement: str, support: QAClaimSupport, hit: RetrievalHit) -> Issue | None:
    if support.quote.casefold() not in hit.text.casefold():
        return _issue(
            "QA_SUPPORT_QUOTE_INVALID",
            "ERROR",
            "The support quote is not an exact substring of the cited chunk.",
            None,
            "Use an exact bounded quote from the retrieved evidence.",
        )
    statement_tokens = set(tokenize(statement))
    quote_tokens = set(tokenize(support.quote))
    if any(
        term not in statement.casefold()
        or term not in support.quote.casefold()
        or not set(tokenize(term)).issubset(statement_tokens & quote_tokens)
        for term in support.matching_terms
    ):
        return _issue(
            "QA_SUPPORT_UNRELATED",
            "ERROR",
            "The claim and cited quote do not share every declared support term.",
            None,
            "Bind the claim to evidence that directly contains its material support terms.",
        )
    return None


def _qa_citation(
    claim_id: str,
    snapshot: IndexSnapshot,
    hit: RetrievalHit,
    support: QAClaimSupport,
) -> QACitation:
    item = hit.citation
    return QACitation(
        claim_id=claim_id,
        snapshot_id=snapshot.snapshot_id,
        chunk_id=item.chunk_id,
        content_sha256=item.content_sha256,
        document_id=item.document_id,
        document_sha256=item.document_sha256,
        artifact_id=item.artifact_id,
        artifact_version=item.artifact_version,
        source_sha256=item.source_sha256,
        source_title=item.source_title,
        source_media_type=item.source_media_type,
        parser_name=item.parser_name,
        parser_version=item.parser_version,
        normalizer_version=item.normalizer_version,
        page_index=item.page_index,
        locator_type=item.locator_type.value,
        locator=item.locator,
        quote=support.quote,
        matching_terms=support.matching_terms,
    )


def _claim_identity(claim: TechnicalQACandidateClaim) -> str:
    return _canonical_hash(
        claim.model_dump(mode="json", exclude={"supports", "human_confirmation_required"})
    )


def _claim_id(claim: TechnicalQACandidateClaim) -> str:
    return f"claim-{_claim_identity(claim)[:16]}"


def _issue(
    code: str,
    severity: Literal["INFO", "WARNING", "ERROR", "CRITICAL"],
    message: str,
    affected_path: str | None,
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
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    return value


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
