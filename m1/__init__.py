"""
m1 — Research Investigation Orchestrator.

Manages: Route → Plan → Search (M2) → Verify (M3) → Follow-up → Verdict
"""

from .engine import InvestigationEngine
from .models import (
    InvestigationRequest,
    InvestigationResult,
    InvestigationState,
    InvestigationStatus,
    QuestionComplexity,
    ResearchIntent,
    InvestigationLevel,
    ResearchPlan,
    SearchQuery,
    QueryTrack,
    RouterOutput,
)

__all__ = [
    "InvestigationEngine",
    "InvestigationRequest",
    "InvestigationResult",
    "InvestigationState",
    "InvestigationStatus",
    "QuestionComplexity",
    "ResearchIntent",
    "InvestigationLevel",
    "ResearchPlan",
    "SearchQuery",
    "QueryTrack",
    "RouterOutput",
]