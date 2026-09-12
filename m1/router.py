"""
m1/router.py — Combined Route & Plan Classifier.

UPDATE: Instructs the LLM to output both routing details and the initial search
plan (sub_questions, queries) in a single transaction, saving ~4.0s.
"""

from __future__ import annotations

import logging
import re

from .errors import LLMProviderError
from .gateway import LLMGateway
from .models import (
    InvestigationLevel,
    QuestionComplexity,
    ResearchIntent,
    RouterOutput,
)

logger = logging.getLogger(__name__)


ROUTER_SYSTEM = """\
You classify research questions and generate initial balanced research plans.

1. CLASSIFY QUESTION:
- INTENT: FACT_CHECK | CLAIM_VERIFICATION | RESEARCH_SYNTHESIS | COMPARATIVE_RESEARCH | CAUSALITY_ANALYSIS | LITERATURE_REVIEW
- DOMAIN: One-word category (e.g., EDUCATION, TECHNOLOGY)
- COMPLEXITY: SIMPLE | MODERATE | COMPLEX
- INVESTIGATION_LEVEL: DIRECT (no research) | LIGHT (1 round) | STANDARD (1-2 rounds) | DEEP (2-3 rounds)

2. GENERATE PLAN (If needs_research is true):
- sub_questions: 2-4 sub-questions decomposing the query.
- queries: 4-6 balanced search queries.
  * Must contain at least one query in SUPPORTING (positive effect), CONTRADICTING (null/negative effect), and SYSTEMATIC_REVIEWS (meta-analysis/review) tracks.
  * Keep query strings under 8 words.

Return the exact JSON schema.
"""

_FACT_PATTERNS = [
    r"^\s*what\s+is\s+the\s+capital\s+of\s+",
    r"^\s*who\s+wrote\s+",
    r"^\s*when\s+was\s+.+\s+born\b",
    r"^\s*how\s+many\s+.+\s+in\s+a\s+",
]


def _looks_like_simple_fact(question: str) -> bool:
    q = question.strip().lower()
    return any(re.search(pat, q) for pat in _FACT_PATTERNS)


class QuestionRouter:
    def __init__(self, gateway: LLMGateway | None = None):
        self.gateway = gateway

    def route(self, question: str) -> RouterOutput:
        if _looks_like_simple_fact(question):
            return RouterOutput(
                intent=ResearchIntent.FACT_CHECK,
                domain="GENERAL",
                complexity=QuestionComplexity.SIMPLE,
                needs_research=False,
                investigation_level=InvestigationLevel.DIRECT,
                requires_balanced_evidence=False,
                reason="Pattern match: simple factual lookup",
            )

        if self.gateway and self.gateway.has_providers():
            try:
                result = self.gateway.structured_call(
                    system=ROUTER_SYSTEM,
                    user=f'Route and plan for: "{question}"',
                    response_model=RouterOutput,
                    task_type="classification",
                )
                return result
            except LLMProviderError as e:
                logger.warning("Router LLM failed (%s); using fallback.", e)

        return self._deterministic_fallback(question)

    @staticmethod
    def _deterministic_fallback(question: str) -> RouterOutput:
        q = question.lower()
        research_indicators = (
            "does", "do ", "how does", "why does", "impact", "effect",
            "improve", "cause", "compare", "versus", "vs ",
            "meta-analysis", "review", "evidence",
        )
        is_research = any(ind in q for ind in research_indicators)

        if is_research:
            return RouterOutput(
                intent=ResearchIntent.RESEARCH_SYNTHESIS,
                domain="GENERAL",
                complexity=QuestionComplexity.COMPLEX,
                needs_research=True,
                investigation_level=InvestigationLevel.DEEP,
                requires_balanced_evidence=True,
                reason="Fallback heuristic: research-style question",
            )

        return RouterOutput(
            intent=ResearchIntent.CLAIM_VERIFICATION,
            domain="GENERAL",
            complexity=QuestionComplexity.MODERATE,
            needs_research=True,
            investigation_level=InvestigationLevel.STANDARD,
            requires_balanced_evidence=True,
            reason="Fallback heuristic: default to standard investigation",
        )