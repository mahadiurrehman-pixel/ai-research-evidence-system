"""
decomposer.py — Decompose a research question into subquestions.
"""

from __future__ import annotations

import logging

from .errors import LLMError, LLMParseError
from .llm_client import LLMClient, default_llm_client
from .models import (
    DecompositionResult,
    QuestionComplexity,
    SubQuestion,
)

logger = logging.getLogger(__name__)


DECOMPOSER_SYSTEM = """\
You decompose a research question into 2-6 focused sub-questions.

Guidelines:
- Prefer FEWER, higher-signal subquestions.
- Simple factual questions can have 1-2 subquestions.
- Complex/controversial questions may have 4-6.
- Include definitional, evidence-seeking, counter-evidence, and contextual
  angles WHERE THEY GENUINELY APPLY.
- Also classify overall complexity:
    SIMPLE       — one authoritative source could answer
    MODERATE     — needs a few good sources
    COMPLEX      — research/causal, needs multiple independent sources
    CONTROVERSIAL— actively seek disagreement
Return the exact structured schema.
"""


class QuestionDecomposer:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or default_llm_client()

    def decompose(self, question: str) -> DecompositionResult:
        user = (
            f'Decompose this research question:\n\n"{question}"\n\n'
            "Choose the minimum number of sub-questions that actually help."
        )
        try:
            result = self.llm.structured_call(
                system=DECOMPOSER_SYSTEM,
                user=user,
                response_model=DecompositionResult,
            )
        except (LLMError, LLMParseError) as e:
            logger.warning("Decomposer LLM failed (%s) — using passthrough.", e)
            return DecompositionResult(
                original_question=question,
                sub_questions=[
                    SubQuestion(
                        id="Q1",
                        text=question,
                        purpose="Direct restatement (decomposition unavailable).",
                    )
                ],
                reasoning="LLM unavailable; passthrough decomposition.",
                complexity=QuestionComplexity.MODERATE,
            )

        result.original_question = question
        for i, sq in enumerate(result.sub_questions, start=1):
            if not sq.id:
                sq.id = f"Q{i}"
        if not result.sub_questions:
            result.sub_questions = [
                SubQuestion(id="Q1", text=question, purpose="Restatement.")
            ]
        return result