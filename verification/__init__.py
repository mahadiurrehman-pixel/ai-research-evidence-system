"""
verification — M3 Evidence & Verification module.
"""

from .calibration import (
    CalibrationSignals,
    build_calibrated_reasoning,
    build_calibrated_summary,
    build_verdict_language,
    calibrate_final_verdict,
    extract_signals,
    recalibrate_confidence,
    recalibrate_verdict,
)
from .errors import (
    LLMError,
    LLMParseError,
    PermanentLLMError,
    PipelineStateError,
    TransientLLMError,
    VerificationError,
)
from .llm_client import LLMClient, OpenAICompatibleLLMClient
from .models import (
    AnalyzedEvidence,
    Confidence,
    ContradictionClass,
    ContradictionPair,
    ContradictionResult,
    DecompositionResult,
    EvidenceCitation,
    FinalVerdict,
    QuestionComplexity,
    RawEvidence,
    Relevance,
    ResearchGap,
    SourceType,
    Strength,
    SubQuestion,
    SupportLevel,
    VerdictType,
    VerificationResult,
)
from .pipeline import PipelineResult, PipelineState, VerificationPipeline
from .real_dataset import get_real_evidence
from .relevance import RelevanceMapper
from .source_identity import (
    get_source_group,
    group_evidence,
    independence_factor,
    normalize_domain,
    normalize_title,
)
from .weighting import WeightBreakdown, calculate_evidence_weight

__all__ = [
    # Pipeline
    "VerificationPipeline",
    "PipelineState",
    "PipelineResult",
    # Models
    "RawEvidence",
    "AnalyzedEvidence",
    "FinalVerdict",
    "DecompositionResult",
    "ContradictionResult",
    "ContradictionPair",
    "VerificationResult",
    "SubQuestion",
    "ResearchGap",
    "EvidenceCitation",
    # Enums
    "SupportLevel",
    "Strength",
    "Relevance",
    "Confidence",
    "VerdictType",
    "SourceType",
    "QuestionComplexity",
    "ContradictionClass",
    # LLM
    "LLMClient",
    "OpenAICompatibleLLMClient",
    # Source Identity & Weighting
    "get_source_group",
    "group_evidence",
    "independence_factor",
    "normalize_domain",
    "normalize_title",
    "WeightBreakdown",
    "calculate_evidence_weight",
    "RelevanceMapper",
    # Dataset
    "get_real_evidence",
    # Calibration
    "CalibrationSignals",
    "calibrate_final_verdict",
    "extract_signals",
    "recalibrate_verdict",
    "recalibrate_confidence",
    "build_verdict_language",
    "build_calibrated_summary",
    "build_calibrated_reasoning",
    # Errors
    "VerificationError",
    "LLMError",
    "LLMParseError",
    "TransientLLMError",
    "PermanentLLMError",
    "PipelineStateError",
]