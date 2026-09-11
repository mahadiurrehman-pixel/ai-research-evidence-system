"""
models.py — Shared Pydantic models.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────

class SupportLevel(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"
    IRRELEVANT = "IRRELEVANT"


class Strength(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Relevance(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VerdictType(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class SourceType(str, Enum):
    PEER_REVIEWED = "PEER_REVIEWED"
    PREPRINT = "PREPRINT"              # ← NEW
    TRIAL_REGISTRY = "TRIAL_REGISTRY"  # ← NEW
    GOVERNMENT = "GOVERNMENT"
    NEWS = "NEWS"
    BLOG = "BLOG"
    ENCYCLOPEDIA = "ENCYCLOPEDIA"
    BOOK = "BOOK"
    OTHER = "OTHER"


class QuestionComplexity(str, Enum):
    SIMPLE = "SIMPLE"
    MODERATE = "MODERATE"
    COMPLEX = "COMPLEX"
    CONTROVERSIAL = "CONTROVERSIAL"


class ContradictionClass(str, Enum):
    CONTRADICTORY = "CONTRADICTORY"
    NOT_CONTRADICTORY = "NOT_CONTRADICTORY"
    CONTEXT_DIFFERENCE = "CONTEXT_DIFFERENCE"
    UNCERTAIN = "UNCERTAIN"


# ── Decomposer ───────────────────────────────

class SubQuestion(BaseModel):
    id: str = Field(description="Q1, Q2, Q3...")
    text: str
    purpose: str


class DecompositionResult(BaseModel):
    original_question: str
    sub_questions: list[SubQuestion]
    reasoning: str
    complexity: QuestionComplexity = QuestionComplexity.MODERATE


# ── Raw Evidence ─────────────────────────────

class RawEvidence(BaseModel):
    source_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    publication_date: Optional[date] = None
    abstract: str = ""
    relevant_passage: str = ""
    methodology: str = ""
    sample_size: Optional[int] = None
    url: str = ""

    source_type: Optional[SourceType] = None
    publisher: Optional[str] = None
    peer_reviewed: Optional[bool] = None
    study_design: Optional[str] = None
    source_quality: Optional[Strength] = None
    source_group: Optional[str] = None


# ── Analyzed Evidence ────────────────────────

class AnalyzedEvidence(BaseModel):
    source_id: str
    title: str

    question_ids: list[str] = Field(default_factory=list)
    question_id: Optional[str] = None

    support_level: SupportLevel
    strength: Strength
    relevance: Relevance
    reason: str
    key_claim: str
    methodology_note: str = ""


# ── Contradiction ────────────────────────────

class ContradictionPair(BaseModel):
    evidence_a_id: str
    evidence_b_id: str
    claim_a: str
    claim_b: str
    is_genuine_contradiction: bool
    explanation: str
    severity: Strength
    context_difference: Optional[str] = None
    classification: ContradictionClass = ContradictionClass.NOT_CONTRADICTORY
    confidence: Confidence = Confidence.MEDIUM
    shared_question: Optional[str] = None


class ContradictionResult(BaseModel):
    has_contradictions: bool
    contradiction_pairs: list[ContradictionPair]
    overall_consensus: str
    context_differences: list[str] = Field(default_factory=list)


# ── Verification ─────────────────────────────

class ResearchGap(BaseModel):
    topic: str
    reason: str
    suggested_query: str


class VerificationResult(BaseModel):
    is_sufficient: bool
    confidence: Confidence
    evidence_count: int
    supporting_count: int
    contradicting_count: int
    neutral_count: int
    source_quality: str
    reasoning: str
    research_gaps: list[ResearchGap] = Field(default_factory=list)
    additional_research_needed: bool = False
    research_focus: str = ""
    max_rounds_reached: bool = False


# ── Judge output ─────────────────────────────

class EvidenceCitation(BaseModel):
    source_id: str
    title: str = ""
    claim: str
    reason: str = ""


class FinalVerdict(BaseModel):
    original_question: str
    verdict: VerdictType
    confidence: Confidence
    summary: str
    detailed_reasoning: str
    supporting_evidence: list[EvidenceCitation] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceCitation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    sub_question_answers: dict[str, str] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)