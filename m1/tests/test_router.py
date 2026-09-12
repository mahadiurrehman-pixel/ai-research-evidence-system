"""Router unit tests."""

from __future__ import annotations

import pytest

from m1.models import (
    InvestigationLevel,
    QuestionComplexity,
    ResearchIntent,
    RouterOutput,
)
from m1.router import QuestionRouter


class _FakeGateway:
    def __init__(self, output: RouterOutput | None = None, fail: bool = False):
        self._output = output
        self._fail = fail

    def has_providers(self) -> bool:
        return True

    def structured_call(self, system, user, response_model, **kwargs):
        if self._fail:
            from m1.errors import LLMProviderError
            raise LLMProviderError("simulated")
        return self._output

    def text_call(self, system, user, **kwargs):
        if self._fail:
            from m1.errors import LLMProviderError
            raise LLMProviderError("simulated")
        return "ok"


def test_simple_factual_bypasses_llm():
    router = QuestionRouter(gateway=_FakeGateway(fail=True))
    r = router.route("What is the capital of France?")
    assert r.needs_research is False
    assert r.intent == ResearchIntent.FACT_CHECK


def test_complex_research_question_routes_deep():
    router = QuestionRouter(gateway=None)
    r = router.route("Does AI-assisted learning improve student performance")
    assert r.needs_research is True
    assert r.complexity in (QuestionComplexity.COMPLEX, QuestionComplexity.MODERATE)


def test_llm_success_used_when_available():
    forced = RouterOutput(
        intent=ResearchIntent.CAUSALITY_ANALYSIS,
        domain="EDUCATION",
        complexity=QuestionComplexity.COMPLEX,
        needs_research=True,
        investigation_level=InvestigationLevel.DEEP,
        requires_balanced_evidence=True,
        reason="LLM classified",
    )
    router = QuestionRouter(gateway=_FakeGateway(output=forced))
    r = router.route("Does exercise cause improved cognition")
    assert r.intent == ResearchIntent.CAUSALITY_ANALYSIS
    assert r.domain == "EDUCATION"


def test_llm_failure_falls_back_to_heuristic():
    router = QuestionRouter(gateway=_FakeGateway(fail=True))
    r = router.route("Does meditation reduce anxiety in adults")
    assert r.needs_research is True