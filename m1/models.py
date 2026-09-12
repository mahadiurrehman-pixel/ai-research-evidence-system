"""
m1/models.py — All Pydantic data models for M1.

FIX: Added raw_evidence field to InvestigationState using standard Pydantic Field
to allow engine.py to sync evidence cumulatively across rounds.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────

class InvestigationStatus(str, Enum):
    CREATED = "CREATED"
    ROUTING = "ROUTING"
    CACHE_CHECK = "CACHE_CHECK"
    PLANNING = "PLANNING"
    SEARCHING = "SEARCHING"
    VERIFYING = "VERIFYING"
    NEEDS_MORE_RESEARCH = "NEEDS_MORE_RESEARCH"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NO_RESEARCH_NEEDED = "NO_RESEARCH_NEEDED"
    FAILED = "FAILED"


class QuestionComplexity(str, Enum):
    SIMPLE = "SIMPLE"
    MODERATE = "MODERATE"
    COMPLEX = "COMPLEX"


class ResearchIntent(str, Enum):
    FACT_CHECK = "FACT_CHECK"
    CLAIM_VERIFICATION = "CLAIM_VERIFICATION"
    RESEARCH_SYNTHESIS = "RESEARCH_SYNTHESIS"
    COMPARATIVE_RESEARCH = "COMPARATIVE_RESEARCH"
    CAUSALITY_ANALYSIS = "CAUSALITY_ANALYSIS"
    LITERATURE_REVIEW = "LITERATURE_REVIEW"
    TREND_ANALYSIS = "TREND_ANALYSIS"


class InvestigationLevel(str, Enum):
    DIRECT = "DIRECT"       # No research; direct answer
    LIGHT = "LIGHT"         # 1 round, 2-3 sources
    STANDARD = "STANDARD"   # 1-2 rounds, 5-8 sources
    DEEP = "DEEP"           # 2-3 rounds, 10+ sources


class QueryTrack(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    MIXED_FINDINGS = "MIXED_FINDINGS"
    SYSTEMATIC_REVIEWS = "SYSTEMATIC_REVIEWS"
    CONTEXT = "CONTEXT"
    METHODOLOGY = "METHODOLOGY"
    RECENT = "RECENT"
    FOLLOW_UP = "FOLLOW_UP"


class CacheFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


# ── Router ────────────────────────────────────

class RouterOutput(BaseModel):
    intent: ResearchIntent = ResearchIntent.RESEARCH_SYNTHESIS
    domain: str = "GENERAL"
    complexity: QuestionComplexity = QuestionComplexity.MODERATE
    needs_research: bool = True
    investigation_level: InvestigationLevel = InvestigationLevel.STANDARD
    requires_balanced_evidence: bool = True
    reason: str = ""


# ── Planner ───────────────────────────────────

class SearchQuery(BaseModel):
    query_id: str = Field(default_factory=lambda: f"q_{uuid.uuid4().hex[:8]}")
    query: str
    track: QueryTrack = QueryTrack.SUPPORTING
    purpose: str = ""
    max_results: int = 8


class ResearchPlan(BaseModel):
    main_question: str
    sub_questions: list[str] = Field(default_factory=list)
    queries: list[SearchQuery] = Field(default_factory=list)
    evidence_target: int = 10
    max_rounds: int = 3


# ── State & Trace ────────────────────────────

class TraceEvent(BaseModel):
    round_num: int = 0
    action: str
    details: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class InvestigationState(BaseModel):
    investigation_id: str = Field(
        default_factory=lambda: f"inv_{uuid.uuid4().hex[:12]}"
    )
    question: str = ""
    status: InvestigationStatus = InvestigationStatus.CREATED
    complexity: QuestionComplexity = QuestionComplexity.MODERATE
    intent: ResearchIntent = ResearchIntent.RESEARCH_SYNTHESIS
    domain: str = "GENERAL"
    investigation_level: InvestigationLevel = InvestigationLevel.STANDARD
    current_round: int = 0
    max_rounds: int = 3
    evidence_collected: int = 0
    completed_queries: list[str] = Field(default_factory=list)
    completed_tracks: list[str] = Field(default_factory=list)
    pending_gaps: list[str] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    # ★ FIX: Correct Pydantic field definition for raw_evidence
    # Uses Any to avoid circular import from verification.models
    raw_evidence: list[Any] = Field(default_factory=list)

    def log(self, action: str, details: str = "") -> None:
        self.trace.append(
            TraceEvent(
                round_num=self.current_round,
                action=action,
                details=details,
            )
        )
        self.updated_at = datetime.now()


# ── Request / Response ────────────────────────

class InvestigationRequest(BaseModel):
    question: str
    max_rounds: int = 3
    mode: str = "auto"

    @field_validator("question")
    @classmethod
    def _q_min_length(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 5:
            raise ValueError("question must be at least 5 characters")
        if len(v) > 1000:
            raise ValueError("question must be under 1000 characters")
        return v

    @field_validator("max_rounds")
    @classmethod
    def _rounds_range(cls, v: int) -> int:
        if v < 1 or v > 3:
            raise ValueError("max_rounds must be 1..3")
        return v

    @field_validator("mode")
    @classmethod
    def _mode_valid(cls, v: str) -> str:
        allowed = {"auto", "shallow", "deep"}
        if v not in allowed:
            raise ValueError(f"mode must be one of {allowed}")
        return v


class RouteMetadata(BaseModel):
    intent: ResearchIntent
    domain: str
    complexity: QuestionComplexity
    investigation_level: InvestigationLevel
    needs_research: bool
    reason: str


class InvestigationResult(BaseModel):
    investigation_id: str
    status: InvestigationStatus
    question: str
    verdict: Optional[Any] = None
    rounds_used: int = 0
    evidence_count: int = 0
    trace_summary: list[str] = Field(default_factory=list)
    time_taken: str = ""
    route_metadata: Optional[RouteMetadata] = None
    errors: list[str] = Field(default_factory=list)
    from_cache: bool = False
    raw_evidence_summary: list[dict] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


# ── Cache metadata ────────────────────────────

class CachedEntry(BaseModel):
    normalized_question: str
    domain: str = "GENERAL"
    scope: str = ""
    verdict_type: str = ""
    confidence: str = ""
    evidence_count: int = 0
    result_json: str = ""
    created_at: datetime
    last_validated_at: datetime
    freshness: CacheFreshness = CacheFreshness.FRESH