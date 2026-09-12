"""
decomposer.py — Fast Decomposer for research sub-questions.
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
Decompose the research question into 2-4 focused sub-questions.
Complexity: SIMPLE | MODERATE | COMPLEX | CONTROVERSIAL.
Keep purpose field under 6 words to optimize latency.
"""


class QuestionDecomposer:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or default_llm_client()

    def decompose(self, question: str) -> DecompositionResult:
        user = f'Decompose: "{question}"'
        try:
            result = self.llm.structured_call(
                system=DECOMPOSER_SYSTEM,
                user=user,
                response_model=DecompositionResult,
                task_type="decomposition",
            )
        except (LLMError, LLMParseError) as e:
            logger.warning("Decomposer failed (%s) — using passthrough.", e)
            return DecompositionResult(
                original_question=question,
                sub_questions=[
                    SubQuestion(
                        id="Q1",
                        text=question,
                        purpose="Direct restatement.",
                    )
                ],
                reasoning="Passthrough.",
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