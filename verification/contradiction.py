"""
contradiction.py — Multi-stage contradiction pipeline with batched scheduling.

UPDATE: Contradiction pair comparisons now go through the RequestScheduler
for controlled concurrency, inter-batch delays, and 429 cooldown.
"""

from __future__ import annotations

import logging
import re
from itertools import combinations
from typing import Any, Callable, Optional, Sequence

from .errors import LLMError, LLMParseError
from .llm_client import LLMClient, default_llm_client
from .models import (
    AnalyzedEvidence,
    ContradictionClass,
    ContradictionPair,
    ContradictionResult,
    Confidence,
    RawEvidence,
    Relevance,
    Strength,
    SupportLevel,
)
from .scheduler import RequestScheduler, get_default_scheduler
from .source_identity import (
    get_source_group,
    group_evidence,
    independence_factor,
)
from .weighting import calculate_evidence_weight

logger = logging.getLogger(__name__)


CONTRADICTION_SYSTEM = """\
You are an expert academic peer reviewer. Evaluate whether two pieces of evidence genuinely contradict each other.

Choose EXACTLY one classification:
- CONTRADICTORY       : Incompatible claims under substantially comparable conditions.
- CONTEXT_DIFFERENCE  : Differing outcomes explained by population, intervention, metric, or setting differences.
- NOT_CONTRADICTORY   : Findings are aligned or do not conflict.
- UNCERTAIN           : Insufficient detail to evaluate.

CRITICAL: Do NOT classify as CONTRADICTORY solely because one reports positive and another null. They MUST test comparable interventions on comparable populations with comparable metrics.

Set is_genuine_contradiction = true ONLY for CONTRADICTORY.
Return the exact structured schema. Keep explanations brief.
"""


_STOPWORDS = {
    "the","and","for","with","that","this","from","were","have","been",
    "which","study","studies","effect","results","result","between",
    "using","based","among","into","such","also","found","show","shows",
    "showed","not","are","was","its","their","they","them","who","how",
    "why","what","when","where","than","about","over","under","more","less",
    "does","will","can","any","measured","measurable","significant",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower())
            if len(t) > 3 and t not in _STOPWORDS}


def _ngrams(text: str, n: int = 3) -> set[str]:
    s = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


class ContradictionDetector:
    def __init__(
        self,
        llm: LLMClient | None = None,
        min_overlap: int = 1,
        max_pairs: int = 200,
        semantic_threshold: float = 0.18,
        embedder: Optional[Embedder] = None,
        scheduler: Optional[RequestScheduler] = None,  # ★ NEW
    ):
        self.llm = llm or default_llm_client()
        self.min_overlap = max(0, min_overlap)
        self.max_pairs = max(1, max_pairs)
        self.semantic_threshold = semantic_threshold
        self.embedder = embedder
        self._last_raw_evidence: Optional[list[RawEvidence]] = None
        # ★ Use provided scheduler or global default
        self._scheduler = scheduler or get_default_scheduler()

    def detect(
        self,
        analyzed_evidence: list[AnalyzedEvidence],
        raw_evidence: list[RawEvidence] | None = None,
    ) -> ContradictionResult:
        self._last_raw_evidence = raw_evidence

        relevant = [
            e for e in analyzed_evidence
            if e.support_level != SupportLevel.IRRELEVANT
        ]
        if len(relevant) < 2:
            return ContradictionResult(
                has_contradictions=False,
                contradiction_pairs=[],
                overall_consensus="Insufficient evidence for comparison.",
                context_differences=[],
            )

        raw_by_id = {r.source_id: r for r in (raw_evidence or [])}
        candidate_pairs = self._candidate_pairs(relevant)

        if not candidate_pairs:
            return ContradictionResult(
                has_contradictions=False,
                contradiction_pairs=[],
                overall_consensus="No comparable opposing evidence pairs found.",
                context_differences=[],
            )

        # ★ BATCHED pair comparison via scheduler
        # Instead of sequential loop, process in batches of 2 with delays
                # ★ BATCHED pair comparison via scheduler
        # batch_size=6 for high throughput, small delay between batches
        def _compare(pair_tuple):
            a, b = pair_tuple
            return self._llm_compare(a, b)

        raw_results = self._scheduler.process_batch(
            items=candidate_pairs,
            fn=_compare,
            batch_size=6,          # ★ was 2, now 6
            batch_delay=0.3,       # ★ was 1.5, now 0.3
            provider_name="contradiction",
            label="contradiction_pairs",
        )

        # Filter out None (failed) results
        pairs: list[ContradictionPair] = [r for r in raw_results if r is not None]

        consensus = self._weighted_consensus(relevant, raw_by_id)

        context_diffs = [
            (p.context_difference or p.explanation)
            for p in pairs
            if not p.is_genuine_contradiction
            and p.classification == ContradictionClass.CONTEXT_DIFFERENCE
        ]
        genuine = [p for p in pairs if p.is_genuine_contradiction]

        return ContradictionResult(
            has_contradictions=len(genuine) > 0,
            contradiction_pairs=pairs,
            overall_consensus=consensus,
            context_differences=context_diffs,
        )

    def _candidate_pairs(
        self, evidence: list[AnalyzedEvidence]
    ) -> list[tuple[AnalyzedEvidence, AnalyzedEvidence]]:
        raw_by_id = {r.source_id: r for r in (self._last_raw_evidence or [])}

        groups: dict[str, list[AnalyzedEvidence]] = {}
        for e in evidence:
            if e.support_level == SupportLevel.IRRELEVANT:
                continue
            raw = raw_by_id.get(e.source_id)
            gkey = get_source_group(raw) if raw else f"id:{e.source_id}"
            groups.setdefault(gkey, []).append(e)

        def _quality_score(e: AnalyzedEvidence) -> float:
            raw = raw_by_id.get(e.source_id)
            score = 0.0
            if e.strength == Strength.HIGH:
                score += 3.0
            elif e.strength == Strength.MEDIUM:
                score += 2.0
            else:
                score += 1.0
            if e.relevance == Relevance.HIGH:
                score += 2.0
            elif e.relevance == Relevance.MEDIUM:
                score += 1.0
            if raw:
                if raw.peer_reviewed:
                    score += 2.0
                if raw.sample_size and raw.sample_size > 100:
                    score += 1.0
                if raw.study_design and raw.study_design.lower() in (
                    "rct", "meta-analysis", "systematic review"
                ):
                    score += 2.0
            return score

        representatives: list[AnalyzedEvidence] = []
        for gkey, members in groups.items():
            best = max(members, key=_quality_score)
            representatives.append(best)

        stage1: list[tuple[AnalyzedEvidence, AnalyzedEvidence]] = []
        for a, b in combinations(representatives, 2):
            if a.support_level == b.support_level:
                continue
            shared = set(a.question_ids) & set(b.question_ids)
            if not shared:
                continue
            stage1.append((a, b))

        if not stage1:
            for a, b in combinations(evidence, 2):
                if a.support_level == b.support_level:
                    continue
                if SupportLevel.IRRELEVANT in {a.support_level, b.support_level}:
                    continue
                shared = set(a.question_ids) & set(b.question_ids)
                if not shared:
                    continue
                stage1.append((a, b))

        if not stage1:
            return []

        if len(stage1) <= 5:
            return stage1[:self.max_pairs]

        scored: list[tuple[float, AnalyzedEvidence, AnalyzedEvidence]] = []
        texts_a = [f"{p[0].key_claim} {p[0].reason}" for p in stage1]
        texts_b = [f"{p[1].key_claim} {p[1].reason}" for p in stage1]

        embeds_a = embeds_b = None
        if self.embedder is not None:
            try:
                embeds_a = self.embedder(texts_a)
                embeds_b = self.embedder(texts_b)
            except Exception as e:
                logger.warning("Embedder failed (%s); falling back.", e)

        for i, (a, b) in enumerate(stage1):
            lex = _jaccard(_tokens(texts_a[i]), _tokens(texts_b[i]))
            if embeds_a is not None and embeds_b is not None:
                sem = _cosine(embeds_a[i], embeds_b[i])
            else:
                sem = _jaccard(_ngrams(texts_a[i]), _ngrams(texts_b[i]))
            score = max(lex, sem)
            token_overlap = len(_tokens(texts_a[i]) & _tokens(texts_b[i]))
            if token_overlap >= self.min_overlap or sem >= self.semantic_threshold:
                scored.append((score, a, b))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [(a, b) for _, a, b in scored[: self.max_pairs]]

    def _llm_compare(
        self, a: AnalyzedEvidence, b: AnalyzedEvidence
    ) -> ContradictionPair | None:
        shared = set(a.question_ids) & set(b.question_ids)
        shared_q = sorted(shared)[0] if shared else None
        user = (
            "EVIDENCE A:\n"
            f"- Source: {a.source_id} ({a.title})\n"
            f"- Claim: {a.key_claim}\n"
            f"- Support: {a.support_level.value}\n"
            f"- Strength: {a.strength.value}\n"
            f"- Methodology: {a.methodology_note}\n"
            f"- Reason: {a.reason}\n\n"
            "EVIDENCE B:\n"
            f"- Source: {b.source_id} ({b.title})\n"
            f"- Claim: {b.key_claim}\n"
            f"- Support: {b.support_level.value}\n"
            f"- Strength: {b.strength.value}\n"
            f"- Methodology: {b.methodology_note}\n"
            f"- Reason: {b.reason}\n\n"
            "Classify the relationship. Evaluate comparability before deciding contradiction."
        )
        try:
            pair = self.llm.structured_call(
                system=CONTRADICTION_SYSTEM,
                user=user,
                response_model=ContradictionPair,
            )
        except (LLMError, LLMParseError) as e:
            logger.warning(
                "Contradiction LLM failed for %s vs %s (%s). Skipping pair.",
                a.source_id, b.source_id, e,
            )
            return None

        pair.evidence_a_id = a.source_id
        pair.evidence_b_id = b.source_id
        pair.claim_a = a.key_claim
        pair.claim_b = b.key_claim
        pair.shared_question = shared_q
        if pair.classification == ContradictionClass.CONTRADICTORY:
            pair.is_genuine_contradiction = True
        else:
            pair.is_genuine_contradiction = False
        if pair.confidence is None:
            pair.confidence = Confidence.MEDIUM
        return pair

    def _weighted_consensus(
        self,
        evidence: list[AnalyzedEvidence],
        raw_by_id: dict[str, RawEvidence],
    ) -> str:
        raws = [raw_by_id.get(e.source_id) for e in evidence]
        raws_present = [r for r in raws if r is not None]
        groups = group_evidence(raws_present) if raws_present else {}

        source_to_group: dict[str, str] = {}
        group_size: dict[str, int] = {}
        for gkey, items in groups.items():
            group_size[gkey] = len(items)
            for it in items:
                source_to_group[it.source_id] = gkey

        per_group: dict[str, dict[str, float]] = {}

        for e in evidence:
            raw = raw_by_id.get(e.source_id)
            gkey = source_to_group.get(e.source_id, f"id:{e.source_id}")
            gsize = group_size.get(gkey, 1)
            indep = independence_factor(gsize) / max(1, gsize)
            bd = calculate_evidence_weight(
                e, raw, independence_factor=max(indep, 0.25),
            )
            slot = per_group.setdefault(
                gkey, {"supports": 0.0, "contradicts": 0.0, "neutral": 0.0}
            )
            if e.support_level == SupportLevel.SUPPORTS:
                slot["supports"] += bd.total
            elif e.support_level == SupportLevel.CONTRADICTS:
                slot["contradicts"] += bd.total
            elif e.support_level == SupportLevel.NEUTRAL:
                claim_lower = (e.key_claim + " " + e.reason).lower()
                negative_signals = [
                    "no significant", "no improvement", "no benefit",
                    "no difference", "did not", "zero", "fail",
                    "not produce", "not improve",
                ]
                if any(sig in claim_lower for sig in negative_signals):
                    slot["contradicts"] += bd.total * 0.7
                    slot["neutral"] += bd.total * 0.3
                else:
                    slot["neutral"] += bd.total

        sup_w = sum(s["supports"] for s in per_group.values())
        con_w = sum(s["contradicts"] for s in per_group.values())
        neu_w = sum(s["neutral"] for s in per_group.values())
        total = sup_w + con_w + neu_w
        counted = len(per_group)
        if total <= 0:
            return "No weighted evidence available."

        sup_pct = sup_w / total * 100
        con_pct = con_w / total * 100
        neu_pct = neu_w / total * 100

        if sup_w > 2 * con_w and sup_pct > 60:
            tone = "Strong weighted support"
        elif con_w > 2 * sup_w and con_pct > 60:
            tone = "Strong weighted counter-evidence"
        elif sup_w > con_w and con_w > 0:
            tone = "Mixed evidence, leaning toward support"
        elif con_w > sup_w and sup_w > 0:
            tone = "Mixed evidence, leaning toward contradiction"
        elif sup_w > 0 and con_w > 0:
            tone = "Mixed / context-dependent evidence"
        elif sup_w > con_w:
            tone = "Leans toward support"
        elif con_w > sup_w:
            tone = "Leans toward contradiction"
        else:
            tone = "Mixed / no clear consensus"

        return (
            f"{tone} across {counted} independent source group(s). "
            f"Weighted share — supports: {sup_pct:.0f}%, "
            f"contradicts: {con_pct:.0f}%, neutral: {neu_pct:.0f}%."
        )


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    la = sum(x * x for x in a) ** 0.5
    lb = sum(x * x for x in b) ** 0.5
    if la == 0 or lb == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, dot / (la * lb)))