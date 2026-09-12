"""
verification/calibration.py — Verdict & Confidence Calibration Layer.

FIX: recalibrate_verdict() now counts NEUTRAL-with-negative-claims as
effective contradictions in the ratio calculation. This prevents the
paradox where 5 SUPPORTS + 13 NEUTRAL (many with negative claims)
produces INCONCLUSIVE because contradicts_ratio = 0%.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .models import (
    AnalyzedEvidence,
    Confidence,
    ContradictionResult,
    FinalVerdict,
    Relevance,
    Strength,
    SupportLevel,
    VerdictType,
    VerificationResult,
)

logger = logging.getLogger(__name__)


@dataclass
class CalibrationSignals:
    total_relevant: int
    supports_count: int
    contradicts_count: int
    neutral_count: int
    independent_groups: int
    high_quality_count: int
    meta_analysis_count: int
    rct_count: int
    peer_reviewed_count: int
    has_genuine_contradiction: bool
    has_context_variation: bool
    context_variation_count: int
    supports_ratio: float
    contradicts_ratio: float
    # ★ NEW: effective counts including neutral-negative
    effective_contradicts_count: int = 0
    effective_contradicts_ratio: float = 0.0

    @property
    def has_mixed_findings(self) -> bool:
        return self.supports_count > 0 and self.effective_contradicts_count > 0

    @property
    def is_evidence_narrow(self) -> bool:
        return self.independent_groups < 3 or self.high_quality_count < 2

    @property
    def is_evidence_broad(self) -> bool:
        return self.independent_groups >= 4 and self.high_quality_count >= 3


_NEGATIVE_SIGNALS = [
    "no significant", "no improvement", "no benefit",
    "no difference", "did not", "zero", "fail",
    "not produce", "not improve",
]


def _count_neutral_negative(evidence: list[AnalyzedEvidence]) -> int:
    count = 0
    for e in evidence:
        if e.support_level == SupportLevel.NEUTRAL:
            text = (e.key_claim + " " + e.reason).lower()
            if any(sig in text for sig in _NEGATIVE_SIGNALS):
                count += 1
    return count


def extract_signals(
    analyzed_evidence: list[AnalyzedEvidence],
    contradictions: ContradictionResult,
    verification: VerificationResult,
    independent_groups: int = 0,
) -> CalibrationSignals:
    relevant = [e for e in analyzed_evidence
                if e.support_level != SupportLevel.IRRELEVANT]
    supports = sum(1 for e in relevant if e.support_level == SupportLevel.SUPPORTS)
    contradicts = sum(1 for e in relevant if e.support_level == SupportLevel.CONTRADICTS)
    neutral = sum(1 for e in relevant if e.support_level == SupportLevel.NEUTRAL)
    total = len(relevant)

    high_q = sum(1 for e in relevant if e.strength == Strength.HIGH)
    meta_count = sum(
        1 for e in relevant
        if any(k in (e.methodology_note or "").lower()
               for k in ["meta", "systematic"])
    )
    rct_count = sum(
        1 for e in relevant
        if "rct" in (e.methodology_note or "").lower()
    )
    peer_count = high_q

    has_genuine = contradictions.has_contradictions
    has_context = len(contradictions.context_differences) > 0
    context_count = len(contradictions.context_differences)

    # ★ FIX: Count neutral-negative as effective contradictions
    neutral_neg = _count_neutral_negative(relevant)
    effective_contradicts = contradicts + neutral_neg

    supports_ratio = supports / total if total > 0 else 0.0
    contradicts_ratio = contradicts / total if total > 0 else 0.0
    effective_contradicts_ratio = effective_contradicts / total if total > 0 else 0.0

    return CalibrationSignals(
        total_relevant=total,
        supports_count=supports,
        contradicts_count=contradicts,
        neutral_count=neutral,
        independent_groups=independent_groups or total,
        high_quality_count=high_q,
        meta_analysis_count=meta_count,
        rct_count=rct_count,
        peer_reviewed_count=peer_count,
        has_genuine_contradiction=has_genuine,
        has_context_variation=has_context,
        context_variation_count=context_count,
        supports_ratio=supports_ratio,
        contradicts_ratio=contradicts_ratio,
        effective_contradicts_count=effective_contradicts,
        effective_contradicts_ratio=effective_contradicts_ratio,
    )


def recalibrate_verdict(signals: CalibrationSignals) -> VerdictType:
    if signals.total_relevant == 0:
        return VerdictType.INCONCLUSIVE

    # Strong genuine contradiction dominates
    if signals.has_genuine_contradiction and signals.effective_contradicts_ratio > 0.4:
        return VerdictType.CONTRADICTED

    # Overwhelming contradiction without support
    if signals.effective_contradicts_ratio > 0.7 and signals.supports_ratio < 0.2:
        return VerdictType.CONTRADICTED

    # ★ FIX: Use effective_contradicts_ratio instead of contradicts_ratio
    # Strong consensus AND broad evidence AND no mixed findings
    if (signals.supports_ratio >= 0.8
            and signals.is_evidence_broad
            and not signals.has_mixed_findings
            and not signals.has_genuine_contradiction
            and not signals.has_context_variation):
        return VerdictType.SUPPORTED

    # Strong support but with context variation or mixed findings
    if signals.supports_ratio >= 0.5 and (
        signals.has_context_variation
        or signals.has_mixed_findings
        or signals.is_evidence_narrow
    ):
        return VerdictType.PARTIALLY_SUPPORTED

    # ★ FIX: Substantial support with some effective contradictions
    # This prevents INCONCLUSIVE when there are 5+ supports but also
    # neutral-negative items
    if signals.supports_ratio >= 0.25 and signals.supports_count >= 3:
        if signals.effective_contradicts_count > 0:
            return VerdictType.PARTIALLY_SUPPORTED
        if signals.total_relevant >= 3:
            return VerdictType.PARTIALLY_SUPPORTED

    # Balanced support with substantial base
    if signals.supports_ratio >= 0.5 and signals.total_relevant >= 3:
        return VerdictType.PARTIALLY_SUPPORTED

    # ★ FIX: Only return INCONCLUSIVE when evidence is genuinely sparse
    # Not when there are many sources with mixed signals
    if signals.total_relevant < 2:
        return VerdictType.INCONCLUSIVE

    if signals.supports_ratio < 0.2 and signals.effective_contradicts_ratio < 0.2:
        return VerdictType.INCONCLUSIVE

    # Default: partially supported (safe middle ground)
    return VerdictType.PARTIALLY_SUPPORTED


def recalibrate_confidence(signals: CalibrationSignals) -> Confidence:
    if signals.total_relevant == 0:
        return Confidence.LOW

    score = 0

    if signals.independent_groups >= 5:
        score += 2
    elif signals.independent_groups >= 3:
        score += 1

    if signals.meta_analysis_count >= 3:
        score += 2
    elif signals.meta_analysis_count >= 1:
        score += 1

    if signals.rct_count >= 2:
        score += 1

    if signals.high_quality_count >= 4:
        score += 2
    elif signals.high_quality_count >= 2:
        score += 1

    if signals.has_mixed_findings:
        score -= 1
    if signals.has_genuine_contradiction:
        score -= 2
    if signals.context_variation_count >= 3:
        score -= 1
    if signals.is_evidence_narrow:
        score -= 1

    if score >= 5:
        return Confidence.HIGH
    elif score >= 2:
        return Confidence.MEDIUM
    else:
        return Confidence.LOW


def build_verdict_language(verdict: VerdictType, signals: CalibrationSignals) -> str:
    if verdict == VerdictType.SUPPORTED:
        return "SUPPORTED"
    if verdict == VerdictType.CONTRADICTED:
        return "CONTRADICTED"
    if verdict == VerdictType.INCONCLUSIVE:
        return "INCONCLUSIVE"
    if verdict == VerdictType.NOT_SUPPORTED:
        return "NOT_SUPPORTED"
    if verdict == VerdictType.PARTIALLY_SUPPORTED:
        if signals.has_context_variation and signals.supports_ratio >= 0.25:
            return "SUPPORTED_WITH_LIMITATIONS"
        elif signals.has_mixed_findings and abs(
            signals.supports_ratio - signals.effective_contradicts_ratio
        ) < 0.3:
            return "MIXED / CONTEXT-DEPENDENT"
        else:
            return "PARTIALLY_SUPPORTED"
    return verdict.value


def build_calibrated_summary(
    verdict: VerdictType,
    signals: CalibrationSignals,
    original_question: str,
) -> str:
    label = build_verdict_language(verdict, signals)

    if verdict == VerdictType.INCONCLUSIVE:
        return (
            "The analyzed evidence is insufficient to draw a reliable conclusion. "
            "More independent, high-quality sources are needed."
        )

    if verdict == VerdictType.CONTRADICTED:
        return (
            "The analyzed evidence predominantly opposes the claim. "
            "Multiple independent sources report negative or null findings."
        )

    if verdict == VerdictType.SUPPORTED:
        base = (
            "The analyzed evidence broadly supports the claim, with consistent "
            "findings across multiple independent, high-quality sources."
        )
        if signals.independent_groups >= 5:
            base += (
                f" Support comes from {signals.independent_groups} independent "
                f"evidence groups, including {signals.meta_analysis_count} meta-analyses."
            )
        return base

    if label == "SUPPORTED_WITH_LIMITATIONS":
        return (
            "The analyzed evidence generally supports the claim, but effect "
            "magnitude and applicability vary by context, population, and "
            "implementation. The conclusion should not be interpreted as "
            "universally applicable across all settings."
        )

    if label == "MIXED / CONTEXT-DEPENDENT":
        return (
            "The analyzed evidence shows genuinely mixed findings. Positive "
            "effects appear in some contexts while other studies report null "
            "or negative results."
        )

    return (
        "The analyzed evidence partially supports the claim, but important "
        "limitations, contextual variation, or gaps prevent a stronger conclusion."
    )


def build_calibrated_reasoning(
    verdict: VerdictType,
    signals: CalibrationSignals,
    contradictions: ContradictionResult,
    verification: VerificationResult,
    llm_reasoning: str = "",
) -> str:
    sections = []

    if signals.supports_ratio >= 0.5:
        direction = "leans toward supporting the claim"
    elif signals.effective_contradicts_ratio >= 0.5:
        direction = "leans toward not supporting the claim"
    else:
        direction = "is mixed or context-dependent"

    sections.append(
        f"1. OVERALL EVIDENCE DIRECTION: The analyzed evidence {direction} "
        f"({signals.supports_count} supporting, "
        f"{signals.effective_contradicts_count} effectively contradicting "
        f"(including {signals.effective_contradicts_count - signals.contradicts_count} "
        f"neutral with negative claims), "
        f"{signals.neutral_count} neutral across "
        f"{signals.independent_groups} independent groups)."
    )

    if signals.supports_count > 0:
        support_quality = []
        if signals.meta_analysis_count > 0:
            support_quality.append(
                f"{signals.meta_analysis_count} meta-analysis/systematic review"
                + ("es" if signals.meta_analysis_count > 1 else "")
            )
        if signals.rct_count > 0:
            support_quality.append(
                f"{signals.rct_count} RCT" + ("s" if signals.rct_count > 1 else "")
            )
        quality_str = ", ".join(support_quality) if support_quality else "multiple studies"
        sections.append(
            f"2. MAIN SUPPORTING EVIDENCE: Includes {quality_str}. "
            f"{signals.high_quality_count} of the analyzed sources are high-quality."
        )
    else:
        sections.append(
            "2. MAIN SUPPORTING EVIDENCE: No substantial supporting evidence identified."
        )

    if signals.has_mixed_findings or signals.neutral_count > 0:
        limit_bits = []
        if signals.contradicts_count > 0:
            limit_bits.append(f"{signals.contradicts_count} explicit contradicting source(s)")
        if signals.effective_contradicts_count > signals.contradicts_count:
            limit_bits.append(
                f"{signals.effective_contradicts_count - signals.contradicts_count} "
                f"neutral source(s) with negative claims"
            )
        if signals.context_variation_count > 0:
            limit_bits.append(f"{signals.context_variation_count} contextual variation(s)")
        sections.append(f"3. LIMITING / MIXED EVIDENCE: {'; '.join(limit_bits)}.")
    else:
        sections.append("3. LIMITING / MIXED EVIDENCE: None identified.")

    if signals.has_genuine_contradiction:
        n = sum(
            1 for p in contradictions.contradiction_pairs
            if p.is_genuine_contradiction
        )
        sections.append(
            f"4. CONTRADICTION STATUS: {n} genuine contradiction(s) identified."
        )
    else:
        sections.append(
            "4. CONTRADICTION STATUS: No genuine contradiction was identified "
            "among the analyzed evidence (this reflects only the analyzed set, "
            "not the entire literature)."
        )

    if signals.is_evidence_broad:
        scope = "The evidence base is broad enough to support a general conclusion, though effect sizes vary."
    elif signals.is_evidence_narrow:
        scope = "The evidence base is narrow; conclusions should be interpreted as preliminary."
    else:
        scope = "The evidence base is moderate; conclusions apply with reasonable confidence to comparable contexts."
    sections.append(f"5. SCOPE OF CONCLUSION: {scope}")

    conf = recalibrate_confidence(signals)
    conf_reasoning = []
    if signals.meta_analysis_count >= 2:
        conf_reasoning.append(f"{signals.meta_analysis_count} meta-analyses")
    if signals.rct_count >= 1:
        conf_reasoning.append(f"{signals.rct_count} RCT(s)")
    if signals.has_mixed_findings:
        conf_reasoning.append("mixed findings temper confidence")
    if signals.has_genuine_contradiction:
        conf_reasoning.append("genuine contradiction lowers confidence")
    if signals.is_evidence_narrow:
        conf_reasoning.append("limited evidence base")
    rationale = "; ".join(conf_reasoning) if conf_reasoning else "based on evidence quality and coverage"
    sections.append(f"6. CALIBRATED CONFIDENCE: {conf.value} ({rationale}).")

    return "\n\n".join(sections)


def calibrate_final_verdict(
    verdict: FinalVerdict,
    analyzed_evidence: list[AnalyzedEvidence],
    contradictions: ContradictionResult,
    verification: VerificationResult,
    independent_groups: int = 0,
) -> FinalVerdict:
    signals = extract_signals(
        analyzed_evidence, contradictions, verification, independent_groups
    )

    calibrated_verdict = recalibrate_verdict(signals)
    calibrated_confidence = recalibrate_confidence(signals)

    if verdict.verdict != calibrated_verdict:
        logger.info(
            "Calibration adjusted verdict: %s -> %s",
            verdict.verdict.value, calibrated_verdict.value,
        )
        verdict.verdict = calibrated_verdict

    if verdict.confidence != calibrated_confidence:
        logger.info(
            "Calibration adjusted confidence: %s -> %s",
            verdict.confidence.value, calibrated_confidence.value,
        )
        verdict.confidence = calibrated_confidence

    verdict.summary = build_calibrated_summary(
        calibrated_verdict, signals, verdict.original_question
    )

    verdict.detailed_reasoning = build_calibrated_reasoning(
        calibrated_verdict, signals, contradictions, verification,
        verdict.detailed_reasoning,
    )

    if not verdict.limitations:
        limitations = []
        if signals.has_context_variation:
            limitations.append(
                f"Contextual variation observed in {signals.context_variation_count} evidence pair(s)."
            )
        if signals.is_evidence_narrow:
            limitations.append("Evidence base is limited.")
        if signals.has_mixed_findings:
            limitations.append("Mixed findings suggest effect may not apply universally.")
        if not limitations:
            limitations.append(
                "No detected contradictions in the analyzed set does not prove "
                "absence of contradictions in the broader literature."
            )
        verdict.limitations = limitations

    return verdict