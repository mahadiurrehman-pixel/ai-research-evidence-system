"""
verification/judge.py — Calibrated Final Verdict with deterministic counts.

FIXES:
1. Counts are now computed deterministically from analyzed_evidence,
   NOT hallucinated by the LLM.
2. Deterministic counts are injected into the LLM prompt so the
   reasoning text matches reality.
3. LLM-generated counts in reasoning are overridden post-hoc.
4. Stage timing is logged for latency profiling.
"""

from __future__ import annotations

import logging
import sys
import time
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
You are a senior research judge. Produce a preliminary verdict.

VALID VERDICTS: SUPPORTED, PARTIALLY_SUPPORTED, NOT_SUPPORTED, CONTRADICTED, INCONCLUSIVE.
VALID CONFIDENCE: HIGH, MEDIUM, LOW.

CRITICAL RULES:
- Use the EXACT counts provided in the EVIDENCE STATISTICS section.
  Do NOT invent your own counts.
- If findings vary by context → PARTIALLY_SUPPORTED.
- If evidence has both positive AND null/negative findings → PARTIALLY_SUPPORTED.
- Only use SUPPORTED when evidence is strongly consistent.
- Only use CONTRADICTED when evidence is strongly negative.
- Prefer PARTIALLY_SUPPORTED over INCONCLUSIVE when there is substantial
  supporting evidence, even if some findings are neutral or mixed.
- INCONCLUSIVE is reserved for cases with fewer than 2 relevant sources
  or when evidence is genuinely too sparse to draw any conclusion.
- Do NOT say "no contradictory evidence exists" — say "none identified
  in the analyzed set".
- Return the exact structured schema.
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
        t_start = time.time()

        if not verification.is_sufficient:
            verdict = self._inconclusive_verdict(
                decomposition, analyzed_evidence, verification
            )
            logger.info("⏱️ Judge (insufficient path): %.2fs", time.time() - t_start)
            return verdict

        # ★ FIX 1: Compute deterministic counts from actual evidence
        counts = self._compute_deterministic_counts(analyzed_evidence)

        # ★ FIX 2: Build citations deterministically BEFORE LLM call
        supporting_citations = self._citations(analyzed_evidence, SupportLevel.SUPPORTS)
        contradicting_citations = self._citations(analyzed_evidence, SupportLevel.CONTRADICTS)

        context = self._build_compact_context(
            decomposition, analyzed_evidence, contradictions,
            verification, counts,
        )

        t_llm_start = time.time()
        try:
            verdict = self.llm.structured_call(
                system=JUDGE_SYSTEM,
                user=context + (
                    "\n\nSynthesize the final verdict now. "
                    "Use the EXACT counts from EVIDENCE STATISTICS. "
                    "Prefer PARTIALLY_SUPPORTED over INCONCLUSIVE when "
                    "substantial evidence exists."
                ),
                response_model=FinalVerdict,
                task_type="final_verdict",
            )
        except (LLMError, LLMParseError) as e:
            print(f"\n⚠️  JUDGE LLM DIAGNOSTIC: {type(e).__name__}: {e}", file=sys.stderr)
            logger.warning("Judge LLM failed (%s). Returning INCONCLUSIVE.", e)
            verdict = self._inconclusive_verdict(
                decomposition, analyzed_evidence, verification,
                reason_override=f"Judge LLM failed: {type(e).__name__}: {e}.",
            )
            logger.info("⏱️ Judge (LLM failure path): %.2fs", time.time() - t_start)
            return verdict

        t_llm_end = time.time()
        logger.info("⏱️ Judge LLM call: %.2fs", t_llm_end - t_llm_start)

        verdict.original_question = decomposition.original_question

        # ★ FIX 3: Override LLM's potentially hallucinated citation lists
        # with deterministic ground truth
        verdict.supporting_evidence = supporting_citations
        verdict.contradicting_evidence = contradicting_citations

        # ★ FIX 4: Patch the reasoning text to replace hallucinated counts
        verdict.detailed_reasoning = self._patch_reasoning_counts(
            verdict.detailed_reasoning, counts,
        )

        # Apply calibration layer
        t_cal_start = time.time()
        independent_groups = self._count_groups(raw_evidence)
        verdict = calibrate_final_verdict(
            verdict=verdict,
            analyzed_evidence=analyzed_evidence,
            contradictions=contradictions,
            verification=verification,
            independent_groups=independent_groups,
        )
        logger.info("⏱️ Calibration: %.2fs", time.time() - t_cal_start)
        logger.info("⏱️ Judge total: %.2fs", time.time() - t_start)

        return verdict

    # ── Deterministic Counting ────────────────

    def _compute_deterministic_counts(
        self, evidence: list[AnalyzedEvidence]
    ) -> dict[str, int]:
        """
        Compute exact counts from the analyzed evidence list.
        Includes 'effective_contradicts' which counts NEUTRAL items
        that contain negative claims.
        """
        relevant = [e for e in evidence if e.support_level != SupportLevel.IRRELEVANT]
        supports = sum(1 for e in relevant if e.support_level == SupportLevel.SUPPORTS)
        contradicts = sum(1 for e in relevant if e.support_level == SupportLevel.CONTRADICTS)
        neutral = sum(1 for e in relevant if e.support_level == SupportLevel.NEUTRAL)
        irrelevant = sum(1 for e in evidence if e.support_level == SupportLevel.IRRELEVANT)

        # Count neutral items with negative claims as "effective contradicting"
        negative_signals = [
            "no significant", "no improvement", "no benefit",
            "no difference", "did not", "zero", "fail",
            "not produce", "not improve",
        ]
        neutral_negative = 0
        for e in relevant:
            if e.support_level == SupportLevel.NEUTRAL:
                text = (e.key_claim + " " + e.reason).lower()
                if any(sig in text for sig in negative_signals):
                    neutral_negative += 1

        return {
            "total": len(evidence),
            "relevant": len(relevant),
            "supports": supports,
            "contradicts": contradicts,
            "neutral": neutral,
            "neutral_negative": neutral_negative,
            "irrelevant": irrelevant,
            "effective_contradicts": contradicts + neutral_negative,
        }

    def _patch_reasoning_counts(
        self, reasoning: str, counts: dict[str, int]
    ) -> str:
        """
        Replace any LLM-hallucinated count patterns in the reasoning text
        with the deterministic ground truth.
        """
        import re

        # Pattern: "X supporting, Y contradicting, Z neutral"
        pattern = r"\d+\s+supporting.*?\d+\s+contradicting.*?\d+\s+neutral"
        replacement = (
            f"{counts['supports']} supporting, "
            f"{counts['effective_contradicts']} contradicting "
            f"(including {counts['neutral_negative']} neutral with negative claims), "
            f"{counts['neutral'] - counts['neutral_negative']} neutral"
        )
        patched = re.sub(pattern, replacement, reasoning, flags=re.IGNORECASE)

        # If no pattern matched, prepend the canonical counts
        if patched == reasoning:
            header = (
                f"[Evidence Statistics: {counts['supports']} supporting, "
                f"{counts['effective_contradicts']} contradicting, "
                f"{counts['neutral']} neutral, "
                f"{counts['irrelevant']} irrelevant "
                f"out of {counts['total']} total]\n\n"
            )
            patched = header + reasoning

        return patched

    # ── Context Building ──────────────────────

    def _build_compact_context(
        self,
        decomposition: DecompositionResult,
        analyzed_evidence: list[AnalyzedEvidence],
        contradictions: ContradictionResult,
        verification: VerificationResult,
        counts: dict[str, int],
    ) -> str:
        ev_lines = []
        for e in analyzed_evidence:
            claim = " ".join(e.key_claim.split())[:160]
            ev_lines.append(
                f"  [{e.source_id}] {e.support_level.value} | "
                f"Quality: {e.strength.value}\n"
                f"    Claim: {claim}"
            )
        ev_summary = "\n".join(ev_lines) or "  (none)"

        contra_summary = "No genuine contradictions in analyzed set."
        if contradictions.has_contradictions:
            contra_lines = []
            for p in contradictions.contradiction_pairs:
                if p.is_genuine_contradiction:
                    contra_lines.append(
                        f"  - {p.evidence_a_id} vs {p.evidence_b_id}: "
                        f"{p.explanation}"
                    )
            if contra_lines:
                contra_summary = "Genuine conflicts:\n" + "\n".join(contra_lines)

        context_diffs = ""
        if contradictions.context_differences:
            context_diffs = (
                f"\nContext variations ({len(contradictions.context_differences)}):\n"
                + "\n".join(f"  - {c}" for c in contradictions.context_differences[:5])
            )

        # ★ Inject deterministic counts into the prompt
        stats_block = (
            f"EVIDENCE STATISTICS (USE THESE EXACT NUMBERS):\n"
            f"  Total evidence: {counts['total']}\n"
            f"  Relevant: {counts['relevant']}\n"
            f"  Supporting: {counts['supports']}\n"
            f"  Contradicting (explicit): {counts['contradicts']}\n"
            f"  Neutral with negative claims: {counts['neutral_negative']}\n"
            f"  Effective contradicting total: {counts['effective_contradicts']}\n"
            f"  Neutral (no negative claim): {counts['neutral'] - counts['neutral_negative']}\n"
            f"  Irrelevant: {counts['irrelevant']}"
        )

        return (
            f"QUESTION: {decomposition.original_question}\n"
            f"COMPLEXITY: {decomposition.complexity.value}\n\n"
            f"{stats_block}\n\n"
            f"EVIDENCE DETAILS:\n{ev_summary}\n\n"
            f"CONTRADICTION ANALYSIS:\n{contra_summary}{context_diffs}\n\n"
            f"CONSENSUS: {contradictions.overall_consensus}\n\n"
            f"VERIFICATION: sufficient={verification.is_sufficient} "
            f"confidence={verification.confidence.value}"
        )

    # ── Helpers ───────────────────────────────

    def _count_groups(self, raw_evidence: Optional[list[RawEvidence]]) -> int:
        if not raw_evidence:
            return 0
        try:
            from .source_identity import group_evidence
            return len(group_evidence(raw_evidence))
        except Exception:
            return len(raw_evidence)

    def _citations(
        self, evidence: list[AnalyzedEvidence], level: SupportLevel
    ) -> list[EvidenceCitation]:
        return [
            EvidenceCitation(
                source_id=e.source_id,
                title=e.title,
                claim=e.key_claim,
                reason=e.reason,
            )
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
            limitations=[base_reason],
        )