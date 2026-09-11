"""
verifier.py — 100% Deterministic Python Verification.
"""

from __future__ import annotations

import logging
from typing import Any
from .models import (
    AnalyzedEvidence,
    Confidence,
    ContradictionResult,
    QuestionComplexity,
    Relevance,
    ResearchGap,
    Strength,
    SupportLevel,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class EvidenceVerifier:
    def __init__(self, llm: Any | None = None):
        pass

    def verify(
        self,
        analyzed_evidence: list[AnalyzedEvidence],
        contradictions: ContradictionResult,
        original_question: str,
        complexity: QuestionComplexity = QuestionComplexity.MODERATE,
        max_research_rounds: int = 3,
        current_round: int = 1,
    ) -> VerificationResult:
        stats = self._stats(analyzed_evidence)
        max_reached = current_round >= max_research_rounds

        if stats["relevant"] == 0:
            return self._insufficient_result(
                original_question,
                "No relevant evidence was found.",
                stats,
                not max_reached,
                max_reached
            )

        is_sufficient, reason = self._evaluate_sufficiency(
            analyzed_evidence, contradictions, complexity
        )

        gaps = []
        if not is_sufficient and not max_reached:
            gaps.append(ResearchGap(
                topic=original_question,
                reason=reason,
                suggested_query=f"{original_question} peer reviewed research paper"
            ))

        result = VerificationResult(
            is_sufficient=is_sufficient,
            confidence=Confidence.HIGH if stats["high_quality"] >= 2 else Confidence.MEDIUM,
            evidence_count=stats["relevant"],
            supporting_count=stats["support"],
            contradicting_count=stats["contradict"],
            neutral_count=stats["neutral"],
            source_quality="Good" if stats["high_quality"] >= 1 else "Low Quality",
            reasoning=reason,
            research_gaps=gaps,
            additional_research_needed=not is_sufficient and not max_reached,
            research_focus=original_question if (not is_sufficient and not max_reached) else "",
            max_rounds_reached=max_reached
        )

        if max_reached and not result.is_sufficient:
            result.additional_research_needed = False
            result.reasoning += " (Max research rounds reached. Forcing synthesis on existing data.)"

        return result

    def _stats(self, evidence: list[AnalyzedEvidence]) -> dict:
        relevant = [e for e in evidence if e.support_level != SupportLevel.IRRELEVANT]
        return {
            "relevant": len(relevant),
            "support": sum(1 for e in relevant if e.support_level == SupportLevel.SUPPORTS),
            "contradict": sum(1 for e in relevant if e.support_level == SupportLevel.CONTRADICTS),
            "neutral": sum(1 for e in relevant if e.support_level == SupportLevel.NEUTRAL),
            "high_quality": sum(1 for e in relevant if e.strength == Strength.HIGH),
            "high_relevance": sum(1 for e in relevant if e.relevance == Relevance.HIGH),
        }

    def _evaluate_sufficiency(
        self,
        evidence: list[AnalyzedEvidence],
        contradictions: ContradictionResult,
        complexity: QuestionComplexity,
    ) -> tuple[bool, str]:
        relevant = [e for e in evidence if e.support_level != SupportLevel.IRRELEVANT]
        high_q = sum(1 for e in relevant if e.strength == Strength.HIGH)
        high_r = sum(1 for e in relevant if e.relevance == Relevance.HIGH)

        if complexity == QuestionComplexity.SIMPLE:
            ok = len(relevant) >= 1 and high_r >= 1
            return ok, f"SIMPLE question: need 1+ relevant source (got {len(relevant)})."

        if complexity == QuestionComplexity.MODERATE:
            ok = len(relevant) >= 2 and high_q >= 1
            return ok, f"MODERATE complexity: need 2+ relevant sources with 1+ high quality (got {len(relevant)} relevant, {high_q} high quality)."

        ok = len(relevant) >= 2 and high_q >= 2
        return ok, f"COMPLEX complexity: need 2+ high-quality independent sources (got {high_q} high quality, {len(relevant)} relevant)."

    def _insufficient_result(
        self,
        original_question: str,
        reason: str,
        stats: dict,
        additional_needed: bool,
        max_reached: bool,
    ) -> VerificationResult:
        return VerificationResult(
            is_sufficient=False,
            confidence=Confidence.LOW,
            evidence_count=stats["relevant"],
            supporting_count=stats["support"],
            contradicting_count=stats["contradict"],
            neutral_count=stats["neutral"],
            source_quality="None",
            reasoning=reason,
            research_gaps=[ResearchGap(
                topic=original_question,
                reason=reason,
                suggested_query=original_question
            )] if additional_needed else [],
            additional_research_needed=additional_needed,
            research_focus=original_question if additional_needed else "",
            max_rounds_reached=max_reached
        )