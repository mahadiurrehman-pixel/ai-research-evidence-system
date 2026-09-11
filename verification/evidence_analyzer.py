"""
evidence_analyzer.py — Batched Single-Call Evidence Analyzer.

Saves APIs and token bandwidth by analyzing all evidence items and mapping
their relevance to subquestions in exactly ONE structured LLM call.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

from .errors import LLMError, LLMParseError
from .llm_client import LLMClient, default_llm_client
from .models import (
    AnalyzedEvidence,
    RawEvidence,
    Relevance,
    Strength,
    SubQuestion,
    SupportLevel,
)

logger = logging.getLogger(__name__)


# ── Batched Schema Models ────────────────────

class AnalyzedEvidenceItem(BaseModel):
    source_id: str = Field(description="Matches the exact raw source_id.")
    question_ids: list[str] = Field(
        default_factory=list,
        description="IDs of sub-questions this source is directly relevant to."
    )
    support_level: SupportLevel = Field(
        description="SUPPORTS (positive effect/improvement), CONTRADICTS (no significant difference/negative effect), NEUTRAL (descriptive/no stance)."
    )
    strength: Strength = Field(
        description="HIGH (RCT/Meta-analysis with large sample), MEDIUM (cohort/survey), LOW (opinions/case study n<30)."
    )
    relevance: Relevance = Field(
        description="HIGH (direct assessment of sub-question), MEDIUM (related/indirect), LOW (tangential)."
    )
    reason: str = Field(description="1-2 sentences on why this support level was chosen.")
    key_claim: str = Field(description="1-sentence summary of the main finding.")
    methodology_note: str = Field(default="", description="e.g. 'RCT, n=800'")


class BatchedAnalysisResult(BaseModel):
    items: list[AnalyzedEvidenceItem] = Field(default_factory=list)


BATCH_ANALYZER_SYSTEM = """\
You are a senior research analyst. You evaluate multiple evidence sources
against a primary research question and its sub-questions.

Evaluate all sources and return their metrics in the requested JSON structure.

CRITICAL RULES FOR SUPPORT_LEVEL:
- SUPPORTS: Reports a POSITIVE effect, improvement, or academic gain.
- CONTRADICTS: Reports NO difference, NO improvement, NO measurable benefit,
  or a negative effect. (e.g., "no significant difference in grades" = CONTRADICTS).
- NEUTRAL: Discusses the technology/methods without evaluating outcomes.

Ensure 'source_id' maps exactly to the evaluated raw sources.
Return the exact structured schema. Write compact reasoning to conserve tokens.
"""


class EvidenceAnalyzer:
    def __init__(
        self,
        llm: LLMClient | None = None,
        mapper: Any | None = None,
        batch_size: int = 10,
        small_batch_threshold: int = 6,
    ):
        self.llm = llm or default_llm_client()
        self._original_question: str = ""

    def analyze(
        self,
        sub_questions: list[SubQuestion],
        evidence: list[RawEvidence],
        original_question: str = "",
    ) -> list[AnalyzedEvidence]:
        if not sub_questions or not evidence:
            return []

        if original_question:
            self._original_question = original_question
        elif sub_questions:
            self._original_question = sub_questions[0].text

        # Prepare compact contextual strings to fit 8K TPM limits
        sub_qs_text = "\n".join(f"- {q.id}: {q.text}" for q in sub_questions)
        raw_items = []
        for ev in evidence:
            raw_items.append({
                "source_id": ev.source_id,
                "title": ev.title,
                "study_design": ev.study_design or "Unknown",
                "sample_size": ev.sample_size,
                "peer_reviewed": ev.peer_reviewed,
                "passage": (ev.relevant_passage or ev.abstract or "")[:350]  # strictly truncated
            })

        user_prompt = (
            f"PRIMARY RESEARCH QUESTION: {self._original_question}\n\n"
            f"SUB-QUESTIONS:\n{sub_qs_text}\n\n"
            f"RAW EVIDENCE ITEMS TO ANALYZE:\n{json.dumps(raw_items, ensure_ascii=False)}\n\n"
            "Analyze all items simultaneously. Map each source to the sub-question IDs it addresses "
            "and assign support_level, strength, and relevance. Keep reasoning extremely brief."
        )

        try:
            batch_result = self.llm.structured_call(
                system=BATCH_ANALYZER_SYSTEM,
                user=user_prompt,
                response_model=BatchedAnalysisResult
            )
        except (LLMError, LLMParseError) as e:
            logger.warning("Batched analyzer LLM failed (%s). Using fallback stubs.", e)
            return [self._safe_neutral_stub(ev, [sub_questions[0].id]) for ev in evidence]

        # Convert back to legacy AnalyzedEvidence models for compatibility
        item_map = {item.source_id: item for item in batch_result.items}
        out: list[AnalyzedEvidence] = []
        
        for ev in evidence:
            analyzed_item = item_map.get(ev.source_id)
            if analyzed_item:
                out.append(AnalyzedEvidence(
                    source_id=ev.source_id,
                    title=ev.title,
                    question_ids=analyzed_item.question_ids,
                    question_id=analyzed_item.question_ids[0] if analyzed_item.question_ids else None,
                    support_level=analyzed_item.support_level,
                    strength=analyzed_item.strength,
                    relevance=analyzed_item.relevance,
                    reason=analyzed_item.reason,
                    key_claim=analyzed_item.key_claim,
                    methodology_note=analyzed_item.methodology_note
                ))
            else:
                out.append(self._safe_neutral_stub(ev, [sub_questions[0].id]))

        return out

    def _safe_neutral_stub(self, ev: RawEvidence, q_ids: list[str]) -> AnalyzedEvidence:
        return AnalyzedEvidence(
            source_id=ev.source_id,
            title=ev.title,
            question_ids=q_ids,
            question_id=q_ids[0] if q_ids else None,
            support_level=SupportLevel.NEUTRAL,
            strength=Strength.LOW,
            relevance=Relevance.LOW,
            reason="LLM batched analysis omitted or failed; neutral fallback.",
            key_claim=(ev.relevant_passage or ev.title)[:150],
            methodology_note=ev.methodology or ""
        )