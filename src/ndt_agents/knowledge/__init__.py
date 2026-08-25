"""Knowledge Agent entry graph and typed start contracts."""

from ndt_agents.knowledge.entry import (
    InMemoryKnowledgeTaskRepository,
    KnowledgeEntryGraph,
    knowledge_entry_candidate_sha256,
)
from ndt_agents.knowledge.fallback import (
    FallbackResult,
    FallbackStage,
    FallbackStatus,
    IndependentOcrAdapter,
    ParserFallbackPipeline,
    ParserQualityGate,
    QualityDecision,
    QualityExpectation,
)
from ndt_agents.knowledge.intake import (
    EncodingHint,
    IntakeRequest,
    IntakeResult,
    IntakeStatus,
    KnowledgeIntakeService,
)
from ndt_agents.knowledge.models import (
    KnowledgeEntryResult,
    KnowledgeEntryTrigger,
    KnowledgeIntent,
    KnowledgeStartRequest,
    KnowledgeUiStartRequest,
)
from ndt_agents.knowledge.normalization import (
    CanonicalDocument,
    CanonicalElement,
    ElementKind,
    KnowledgeChunk,
    KnowledgeNormalizer,
    NormalizationRequest,
    NormalizationResult,
    NormalizationStatus,
)
from ndt_agents.knowledge.parsing import (
    MinerUAdapter,
    MinerUCliRunner,
    MinerUMethod,
    MinerUParseRequest,
    ParsedDocument,
    ParseResult,
    ParseStatus,
)

__all__ = [
    "InMemoryKnowledgeTaskRepository",
    "EncodingHint",
    "FallbackResult",
    "FallbackStage",
    "FallbackStatus",
    "CanonicalDocument",
    "CanonicalElement",
    "IntakeRequest",
    "IntakeResult",
    "IntakeStatus",
    "IndependentOcrAdapter",
    "KnowledgeEntryGraph",
    "KnowledgeEntryResult",
    "KnowledgeEntryTrigger",
    "KnowledgeIntent",
    "KnowledgeIntakeService",
    "KnowledgeChunk",
    "KnowledgeNormalizer",
    "MinerUAdapter",
    "MinerUCliRunner",
    "MinerUMethod",
    "MinerUParseRequest",
    "NormalizationRequest",
    "NormalizationResult",
    "NormalizationStatus",
    "ParseResult",
    "ParseStatus",
    "ParserFallbackPipeline",
    "ParserQualityGate",
    "ParsedDocument",
    "QualityDecision",
    "QualityExpectation",
    "ElementKind",
    "KnowledgeStartRequest",
    "KnowledgeUiStartRequest",
    "knowledge_entry_candidate_sha256",
]
