"""
judge.py — Compressed Tokens Prompt Judge + Calibration Layer.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from .calibration import calibrate_final_verdict
from .errors import LLMError, LLMParseError
from .llm_client import LLMClient, default_llm_client
from .models import (
    AnalyzedEvidence,
    Confidence,
    ContradictionResult,
    DecompositionResult,
    EvidenceCitation,
    FinalVerdict,
    RawEvidence,
    SupportLevel,
    VerdictType,
    VerificationResult,
)

logger = logging.getLogger(__name__)


JUDGE_SYSTEM = """\
You are a senior research judge. Produce a preliminary verdict that will be
calibrated afterwards. Focus on accurate evidence synthesis, not certainty.

VALID VERDICTS: SUPPORTED, PARTIALLY_SUPPORTED, NOT_SUPPORTED, CONTRADICTED, INCONCLUSIVE.
VALID CONFIDENCE: HIGH, MEDIUM, LOW.

CRITICAL RULES:
- If findings vary by context, population, or implementation -> PARTIALLY_SUPPORTED.
- If evidence has both positive AND null/negative findings -> PARTIALLY_SUPPORTED.
- Only use SUPPORTED when evidence is strongly consistent across many independent sources.
- Only use CONTRADICTED when evidence is strongly negative.
- Prefer PARTIALLY_SUPPORTED over SUPPORTED when in doubt.
- Do NOT overclaim. Do NOT say "consistently" if effects vary.
- Do NOT say "no contradictory evidence exists" — say "none identified in analyzed set".
- Return the exact structured schema. Use ONLY valid enum values.
"""


class ResearchJudge:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or default_llm_client()

    def judge(
        self,
        decomposition: DecompositionResult,
        analyzed_evidence: list[AnalyzedEvidence],
        contradictions: ContradictionResult,
        verification: VerificationResult,
        raw_evidence: Optional[list[RawEvidence]] = None,
    ) -> FinalVerdict:
        if not verification.is_sufficient:
            return self._inconclusive_verdict(
                decomposition, analyzed_evidence, verification
            )

        independent_groups = self._count_independent_groups(
            analyzed_evidence, raw_evidence
        )

        context = self._build_compact_context(
            decomposition, analyzed_evidence, contradictions, verification
        )

        try:
            verdict = self.llm.structured_call(
                system=JUDGE_SYSTEM,
                user=context + "\n\nSynthesize a preliminary verdict. Prefer PARTIALLY_SUPPORTED when findings vary.",
                response_model=FinalVerdict,
            )
        except (LLMError, LLMParseError) as e:
            print(f"\n⚠️  JUDGE LLM DIAGNOSTIC: {type(e).__name__}: {e}", file=sys.stderr)
            logger.warning("Judge LLM failed (%s). Returning INCONCLUSIVE.", e)
            # Return immediately on LLM failure without overwriting via calibration
            return self._inconclusive_verdict(
                decomposition, analyzed_evidence, verification,
                reason_override=f"Judge LLM failed: {type(e).__name__}: {e}. Returning INCONCLUSIVE to avoid unsafe over-confidence."
            )

        verdict.original_question = decomposition.original_question

        if not verdict.supporting_evidence:
            verdict.supporting_evidence = self._citations(
                analyzed_evidence, SupportLevel.SUPPORTS
            )
        if not verdict.contradicting_evidence:
            verdict.contradicting_evidence = self._citations(
                analyzed_evidence, SupportLevel.CONTRADICTS
            )

        # Apply calibration layer
        verdict = calibrate_final_verdict(
            verdict=verdict,
            analyzed_evidence=analyzed_evidence,
            contradictions=contradictions,
            verification=verification,
            independent_groups=independent_groups,
        )

        return verdict

    def _count_independent_groups(
        self,
        analyzed_evidence: list[AnalyzedEvidence],
        raw_evidence: Optional[list[RawEvidence]] = None,
    ) -> int:
        if raw_evidence:
            from .source_identity import group_evidence
            groups = group_evidence(raw_evidence)
            return len(groups)
        return len({e.source_id for e in analyzed_evidence
                    if e.support_level != SupportLevel.IRRELEVANT})

    def _build_compact_context(
        self,
        decomposition: DecompositionResult,
        analyzed_evidence: list[AnalyzedEvidence],
        contradictions: ContradictionResult,
        verification: VerificationResult,
    ) -> str:
        ev_lines = []
        for e in analyzed_evidence:
            ev_lines.append(
                f"• [{e.source_id}] {e.support_level.value} | Quality: {e.strength.value}\n"
                f"  Claim: {e.key_claim}"
            )
        ev_summary = "\n".join(ev_lines)

        contra_summary = "No genuine contradictions in analyzed set."
        if contradictions.has_contradictions:
            contra_summary = "Genuine conflicts found:\n" + "\n".join(
                f"- {p.evidence_a_id} vs {p.evidence_b_id}: {p.explanation}"
                for p in contradictions.contradiction_pairs
                if p.is_genuine_contradiction
            )

        context_diffs = ""
        if contradictions.context_differences:
            context_diffs = (
                f"\nContext variations ({len(contradictions.context_differences)}):\n"
                + "\n".join(f"- {c}" for c in contradictions.context_differences[:5])
            )

        return (
            f"QUESTION: {decomposition.original_question}\n\n"
            f"EVIDENCE METRICS:\n{ev_summary}\n\n"
            f"CONTRADICTION ANALYSIS:\n{contra_summary}{context_diffs}\n\n"
            f"CONSENSUS: {contradictions.overall_consensus}"
        )

    def _citations(
        self, evidence: list[AnalyzedEvidence], level: SupportLevel
    ) -> list[EvidenceCitation]:
        return [
            EvidenceCitation(source_id=e.source_id, title=e.title,
                             claim=e.key_claim, reason=e.reason)
            for e in evidence if e.support_level == level
        ]

    def _inconclusive_verdict(
        self,
        decomposition: DecompositionResult,
        analyzed_evidence: list[AnalyzedEvidence],
        verification: VerificationResult,
        reason_override: Optional[str] = None,
    ) -> FinalVerdict:
        base_reason = reason_override or verification.reasoning
        return FinalVerdict(
            original_question=decomposition.original_question,
            verdict=VerdictType.INCONCLUSIVE,
            confidence=Confidence.LOW,
            summary="Insufficient reliable evidence to draw a conclusion.",
            detailed_reasoning=base_reason,
            supporting_evidence=self._citations(analyzed_evidence, SupportLevel.SUPPORTS),
            contradicting_evidence=self._citations(analyzed_evidence, SupportLevel.CONTRADICTS),
            limitations=[base_reason]
        )