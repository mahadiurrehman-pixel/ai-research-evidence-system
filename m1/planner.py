"""
m1/planner.py — Balanced Research Planner.

UPDATE: Passes task_type to gateway for appropriate tier routing.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .errors import LLMProviderError
from .gateway import LLMGateway
from .models import (
    QuestionComplexity,
    QueryTrack,
    ResearchPlan,
    SearchQuery,
)

logger = logging.getLogger(__name__)


PLANNER_SYSTEM = """\
You create BALANCED research plans. Never search only confirming evidence.

Generate:
1. 2-4 sub-questions decomposing the main question.
2. 4-8 search queries covering:
   - SUPPORTING, CONTRADICTING, SYSTEMATIC_REVIEWS (at least one each)
   - MIXED_FINDINGS, CONTEXT, METHODOLOGY, RECENT (as needed)

Queries must be concise (5-12 words), academically searchable.
Do NOT hardcode specific years — say "recent" or "latest".

Return the exact JSON schema.
"""


class ResearchPlanner:
    def __init__(self, gateway: LLMGateway | None = None):
        self.gateway = gateway

    def plan(self, question: str, complexity: QuestionComplexity) -> ResearchPlan:
        max_rounds, target = _limits_for(complexity)

        if self.gateway and self.gateway.has_providers():
            try:
                # ★ task_type="search_planning" → fast tier
                result = self.gateway.structured_call(
                    system=PLANNER_SYSTEM,
                    user=(
                        f'QUESTION: "{question}"\n'
                        f"COMPLEXITY: {complexity.value}\n"
                        f"TARGET EVIDENCE: {target} papers\n"
                        "Generate balanced queries."
                    ),
                    response_model=ResearchPlan,
                    task_type="search_planning",
                )
                result.main_question = question
                result.max_rounds = max_rounds
                result.evidence_target = target
                if not result.queries:
                    result.queries = self._fallback_queries(question)
                self._ensure_balance(result, question)
                return result
            except LLMProviderError as e:
                logger.warning("Planner LLM failed (%s); using fallback.", e)

        return ResearchPlan(
            main_question=question,
            sub_questions=[question],
            queries=self._fallback_queries(question),
            evidence_target=target,
            max_rounds=max_rounds,
        )

    def generate_followup_queries(
        self,
        question: str,
        research_focus: str,
        research_gaps_texts: list[str],
    ) -> list[SearchQuery]:
        if not research_focus and not research_gaps_texts:
            return []

        gaps_text = "\n".join(f"- {g}" for g in research_gaps_texts) if research_gaps_texts else "None"

        if self.gateway and self.gateway.has_providers():
            try:
                # ★ task_type="query_generation" → fast tier
                result = self.gateway.structured_call(
                    system=(
                        "Generate 2-4 targeted follow-up search queries to fill "
                        "specific research gaps. Return the exact JSON schema."
                    ),
                    user=(
                        f"ORIGINAL QUESTION: {question}\n"
                        f"RESEARCH FOCUS: {research_focus}\n"
                        f"IDENTIFIED GAPS:\n{gaps_text}\n"
                    ),
                    response_model=ResearchPlan,
                    task_type="query_generation",
                )
                for q in result.queries:
                    q.track = QueryTrack.FOLLOW_UP
                return result.queries[:4]
            except LLMProviderError as e:
                logger.warning("Follow-up planner failed (%s).", e)

        return [
            SearchQuery(
                query=research_focus or question,
                track=QueryTrack.FOLLOW_UP,
                purpose="Fill identified research gap (fallback)",
            )
        ]

    def _ensure_balance(self, plan: ResearchPlan, question: str) -> None:
        tracks_present = {q.track for q in plan.queries}
        if QueryTrack.SUPPORTING not in tracks_present:
            plan.queries.append(SearchQuery(
                query=f"{question} evidence supporting",
                track=QueryTrack.SUPPORTING,
            ))
        if QueryTrack.CONTRADICTING not in tracks_present:
            plan.queries.append(SearchQuery(
                query=f"{question} no significant effect null results",
                track=QueryTrack.CONTRADICTING,
            ))

    def _fallback_queries(self, question: str) -> list[SearchQuery]:
        return [
            SearchQuery(query=f"{question} systematic review meta-analysis",
                        track=QueryTrack.SYSTEMATIC_REVIEWS),
            SearchQuery(query=f"{question} randomized controlled trial",
                        track=QueryTrack.SUPPORTING),
            SearchQuery(query=f"{question} no significant effect null results",
                        track=QueryTrack.CONTRADICTING),
            SearchQuery(query=f"{question} different populations moderators",
                        track=QueryTrack.CONTEXT),
            SearchQuery(query=f"{question} recent research latest",
                        track=QueryTrack.RECENT),
        ]


def _limits_for(complexity: QuestionComplexity) -> tuple[int, int]:
    if complexity == QuestionComplexity.SIMPLE:
        return 1, 3
    if complexity == QuestionComplexity.MODERATE:
        return 2, 8
    return 3, 15