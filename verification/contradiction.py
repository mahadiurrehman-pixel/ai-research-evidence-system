"""
contradiction.py — Fast Multi-stage contradiction pipeline.

Speed fix:
- Distributes contradiction pairs across ALL available Groq keys (groq-1, groq-2, groq-3, groq-4).
- 5 pairs process simultaneously in parallel in under 1 second!
"""

from __future__ import annotations

import logging
import re
from itertools import combinations
from typing import Callable, Optional, Sequence, Any

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
Compare two research findings.
- CONTRADICTORY: Direct opposing findings under identical/comparable settings.
- CONTEXT_DIFFERENCE: Differing outcomes explained by demographics, intervention types, or metrics.
- NOT_CONTRADICTORY: Aligned.
Set is_genuine_contradiction = true ONLY for CONTRADICTORY.
Return the exact structured schema. Keep reason under 10 words.
"""


class ContradictionDetector:
    def __init__(
        self,
        llm: LLMClient | None = None,
        min_overlap: int = 1,
        max_pairs: int = 5,
        semantic_threshold: float = 0.18,
        embedder: Optional[Any] = None,
        scheduler: Optional[RequestScheduler] = None,
    ):
        self.llm = llm or default_llm_client()
        self.min_overlap = min_overlap
        self.max_pairs = max_pairs
        self.semantic_threshold = semantic_threshold
        self.embedder = embedder
        self._last_raw_evidence: Optional[list[RawEvidence]] = None
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

        # ★ HIGH-SPEED PARALLEL BATCH: Distribute pairs across keys
        def _compare(pair_tuple: tuple[AnalyzedEvidence, AnalyzedEvidence], provider: str = "default") -> Optional[ContradictionPair]:
            a, b = pair_tuple
            return self._llm_compare(a, b)

        raw_results = self._scheduler.process_batch(
            items=candidate_pairs,
            fn=lambda p: self._llm_compare(p[0], p[1]),
            batch_size=5,
            batch_delay=0.0,
            provider_name="m3-contradiction",
            label="contradiction_pairs",
        )

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
            if e.strength == Strength.HIGH: score += 3.0
            if e.relevance == Relevance.HIGH: score += 2.0
            if raw and raw.peer_reviewed: score += 2.0
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

        return stage1[:self.max_pairs]

    def _llm_compare(
        self, a: AnalyzedEvidence, b: AnalyzedEvidence
    ) -> ContradictionPair | None:
        shared = set(a.question_ids) & set(b.question_ids)
        shared_q = sorted(shared)[0] if shared else None
        user = (
            f"A ({a.source_id}): {a.key_claim}\n"
            f"B ({b.source_id}): {b.key_claim}\n\n"
            "Compare: CONTRADICTORY | CONTEXT_DIFFERENCE | NOT_CONTRADICTORY"
        )
        try:
            pair = self.llm.structured_call(
                system=CONTRADICTION_SYSTEM,
                user=user,
                response_model=ContradictionPair,
                task_type="contradiction_detection",
            )
        except Exception as e:
            logger.warning("Contradiction comparison failed (%s).", e)
            return None

        pair.evidence_a_id = a.source_id
        pair.evidence_b_id = b.source_id
        pair.claim_a = a.key_claim
        pair.claim_b = b.key_claim
        pair.shared_question = shared_q
        pair.is_genuine_contradiction = (pair.classification == ContradictionClass.CONTRADICTORY)
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
            bd = calculate_evidence_weight(e, raw, independence_factor=max(indep, 0.25))
            slot = per_group.setdefault(gkey, {"supports": 0.0, "contradicts": 0.0, "neutral": 0.0})
            if e.support_level == SupportLevel.SUPPORTS:
                slot["supports"] += bd.total
            elif e.support_level == SupportLevel.CONTRADICTS:
                slot["contradicts"] += bd.total
            elif e.support_level == SupportLevel.NEUTRAL:
                claim_lower = (e.key_claim + " " + e.reason).lower()
                negative_signals = ["no significant", "no improvement", "no benefit", "no difference", "did not", "zero", "fail"]
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

        if sup_w > 2 * con_w and sup_pct > 60:
            tone = "Strong weighted support"
        elif con_w > 2 * sup_w and con_pct > 60:
            tone = "Strong weighted counter-evidence"
        elif sup_w > 0 and con_w > 0:
            tone = "Mixed / context-dependent evidence"
        else:
            tone = "Mixed / no clear consensus"

        return f"{tone} across {counted} independent source group(s). Weighted share — supports: {sup_pct:.0f}%, contradicts: {con_pct:.0f}%."