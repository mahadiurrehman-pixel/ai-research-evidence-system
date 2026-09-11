"""
relevance.py — Cheap prefilter + batched LLM relevance mapping.

Design:
    For each evidence item, compute candidate subquestion IDs via a cheap
    deterministic keyword filter. Then:
      - if only tiny inputs, defer to per-item LLM mapping (backward compat),
      - otherwise batch multiple items per LLM call.

    Items that have ZERO plausible candidates locally can be filtered
    without any LLM call.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from .errors import LLMError, LLMParseError
from .llm_client import LLMClient
from .models import RawEvidence, SubQuestion

logger = logging.getLogger(__name__)


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "were", "have",
    "been", "which", "study", "studies", "effect", "results", "result",
    "between", "using", "based", "among", "into", "such", "also", "found",
    "show", "shows", "showed", "not", "are", "was", "its", "their", "they",
    "them", "who", "how", "why", "what", "when", "where", "than", "about",
    "over", "under", "more", "less", "does", "will", "can", "any",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower())
            if len(t) > 3 and t not in _STOPWORDS}


class RelevanceMap(BaseModel):
    """Per-item mapping used both stand-alone and inside batch responses."""
    question_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""


class _BatchItem(BaseModel):
    source_id: str
    question_ids: list[str] = Field(default_factory=list)


class _BatchResponse(BaseModel):
    items: list[_BatchItem] = Field(default_factory=list)


RELEVANCE_SYSTEM = """\
You decide which sub-questions a piece of evidence is meaningfully
relevant to. Evidence may be relevant to ONE, MANY, or ZERO sub-questions.

Rules:
- Only include an ID if the evidence directly addresses that sub-question.
- Prefer precision over recall. Empty list is fine.
Return the exact structured schema.
"""

BATCH_RELEVANCE_SYSTEM = """\
You decide which sub-questions each evidence item is meaningfully
relevant to. For each item, return only its source_id and the list of
sub-question IDs it directly addresses. Empty list is allowed.
Return the exact structured schema (a list of items).
"""


class RelevanceMapper:
    """
    Public helper used by the analyzer.

    Small inputs (<= small_batch_threshold items and <= few subquestions):
        route to single-item LLM calls (preserves existing accuracy).

    Larger inputs:
        - cheap keyword prefilter → drop clearly-irrelevant items
        - batch remaining items into one LLM call per `batch_size`.
    """

    def __init__(
        self,
        llm: LLMClient,
        batch_size: int = 10,
        small_batch_threshold: int = 6,
        min_token_overlap: int = 1,
    ):
        self.llm = llm
        self.batch_size = max(1, batch_size)
        self.small_batch_threshold = small_batch_threshold
        self.min_token_overlap = max(1, min_token_overlap)

    # ── Cheap deterministic prefilter ────────

    def prefilter_candidates(
        self,
        evidence: list[RawEvidence],
        sub_questions: list[SubQuestion],
    ) -> dict[str, list[str]]:
        """
        Returns {source_id: [candidate_qids]} using local keyword overlap.
        Items with an empty list are locally irrelevant.
        """
        q_tokens: dict[str, set[str]] = {
            q.id: _tokens(f"{q.text} {q.purpose}") for q in sub_questions
        }
        out: dict[str, list[str]] = {}
        for ev in evidence:
            ev_text = f"{ev.title} {ev.abstract} {ev.relevant_passage}"
            e_toks = _tokens(ev_text)
            if not e_toks:
                out[ev.source_id] = []
                continue
            cands = [
                qid for qid, qtoks in q_tokens.items()
                if len(e_toks & qtoks) >= self.min_token_overlap
            ]
            out[ev.source_id] = cands
        return out

    # ── Public API ───────────────────────────

    def map_batch(
        self,
        evidence: list[RawEvidence],
        sub_questions: list[SubQuestion],
    ) -> dict[str, list[str]]:
        """
        Returns {source_id: [confirmed_qids]}.

        Uses per-item LLM calls for small inputs (backward compat),
        otherwise prefilter + batched LLM calls.
        """
        if not evidence or not sub_questions:
            return {ev.source_id: [] for ev in evidence}

        valid_ids = {q.id for q in sub_questions}
        candidates = self.prefilter_candidates(evidence, sub_questions)

        # Small-input path preserves the previous per-item behavior.
        if len(evidence) <= self.small_batch_threshold:
            return self._per_item_map(evidence, sub_questions, valid_ids)

        # Large-input path: skip zero-candidate items entirely (no LLM cost).
        to_llm: list[RawEvidence] = [
            ev for ev in evidence if candidates.get(ev.source_id)
        ]
        results: dict[str, list[str]] = {
            ev.source_id: [] for ev in evidence
            if not candidates.get(ev.source_id)
        }

        # Batch the rest.
        for batch in _chunks(to_llm, self.batch_size):
            batch_map = self._llm_batch_call(batch, sub_questions, candidates)
            # Restrict returned IDs to (a) valid subquestions and
            # (b) the candidate set from prefilter (defense-in-depth).
            for ev in batch:
                allowed = set(candidates.get(ev.source_id, [])) & valid_ids
                got = set(batch_map.get(ev.source_id, [])) & allowed
                results[ev.source_id] = sorted(got)
        return results

    # ── Internals ────────────────────────────

    def _per_item_map(
        self,
        evidence: list[RawEvidence],
        sub_questions: list[SubQuestion],
        valid_ids: set[str],
    ) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        q_block = "\n".join(f"- {q.id}: {q.text}" for q in sub_questions)
        for ev in evidence:
            passage = ev.relevant_passage or ev.abstract or ev.title
            user = (
                f"SUB-QUESTIONS:\n{q_block}\n\n"
                f"EVIDENCE:\nTitle: {ev.title}\nPassage: {passage}\n\n"
                "Which sub-question IDs is this evidence meaningfully relevant to?"
            )
            try:
                mapping = self.llm.structured_call(
                    system=RELEVANCE_SYSTEM,
                    user=user,
                    response_model=RelevanceMap,
                )
                out[ev.source_id] = [q for q in mapping.question_ids
                                     if q in valid_ids]
            except (LLMError, LLMParseError) as e:
                logger.warning(
                    "Per-item relevance LLM failed for %s (%s); using keyword fallback.",
                    ev.source_id, e,
                )
                # keyword fallback
                cands = self.prefilter_candidates([ev], sub_questions)
                out[ev.source_id] = cands.get(ev.source_id, [])
        return out

    def _llm_batch_call(
        self,
        batch: list[RawEvidence],
        sub_questions: list[SubQuestion],
        candidates: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        q_block = "\n".join(f"- {q.id}: {q.text}" for q in sub_questions)
        items_block = json.dumps([
            {
                "source_id": ev.source_id,
                "title": ev.title,
                "passage": (ev.relevant_passage or ev.abstract or "")[:600],
                "candidate_ids": candidates.get(ev.source_id, []),
            }
            for ev in batch
        ], ensure_ascii=False)

        user = (
            f"SUB-QUESTIONS:\n{q_block}\n\n"
            f"EVIDENCE ITEMS (JSON, each with candidate_ids from local prefilter):\n"
            f"{items_block}\n\n"
            "For each item, return only the sub-question IDs it directly "
            "addresses (subset of candidate_ids, or empty)."
        )
        try:
            resp = self.llm.structured_call(
                system=BATCH_RELEVANCE_SYSTEM,
                user=user,
                response_model=_BatchResponse,
            )
        except (LLMError, LLMParseError) as e:
            logger.warning(
                "Batch relevance LLM failed (%s); using candidates fallback.", e,
            )
            return {ev.source_id: candidates.get(ev.source_id, []) for ev in batch}
        return {item.source_id: item.question_ids for item in resp.items}


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]