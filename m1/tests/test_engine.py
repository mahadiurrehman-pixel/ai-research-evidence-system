"""Engine unit tests with fake M2 and fake M3."""

from __future__ import annotations

from typing import Any

import pytest

from m1.engine import InvestigationEngine
from m1.models import (
    InvestigationLevel,
    InvestigationRequest,
    InvestigationStatus,
    QuestionComplexity,
    ResearchIntent,
    RouterOutput,
)


# ── Fakes ─────────────────────────────────────

class _FakeEvidence:
    def __init__(self, sid: str, title: str, passage: str):
        self.source_id = sid
        self.title = title
        self.relevant_passage = passage


class _FakeVerdict:
    class _V:
        value = "SUPPORTED"
    class _C:
        value = "HIGH"
    verdict = _V()
    confidence = _C()
    summary = "test summary"
    detailed_reasoning = "test reasoning"
    supporting_evidence = []
    contradicting_evidence = []
    limitations = []


class _FakeM3Result:
    def __init__(self, verdict=None, needs_more=False, max_reached=False):
        self.verdict = verdict
        self.needs_more_research = needs_more
        self.research_focus = "some focus" if needs_more else ""
        self.research_gaps = []
        self.state = object()
        self.max_rounds_reached = max_reached


class _FakeM3Pipeline:
    def __init__(self, sequence: list[_FakeM3Result]):
        self._seq = list(sequence)
        self.run_calls = 0
        self.continue_calls = 0

    # ★ FIX: Added **kwargs to safely accept sub_questions and other optional args
    def run(self, question, evidence, complexity=None, **kwargs):
        self.run_calls += 1
        return self._pop()

    def run_continue(self, state, new_evidence, complexity=None, **kwargs):
        self.continue_calls += 1
        return self._pop()

    def _pop(self):
        if self._seq:
            return self._seq.pop(0)
        return _FakeM3Result(verdict=_FakeVerdict())


class _FakeGateway:
    def __init__(self, route_output=None, plan_output=None):
        self._route = route_output
        self._plan = plan_output

    def has_providers(self):
        return True

    def structured_call(self, system, user, response_model, **kwargs):
        name = response_model.__name__
        if name == "RouterOutput" and self._route:
            return self._route
        if name == "ResearchPlan" and self._plan:
            return self._plan
        return response_model()

    def text_call(self, system, user, **kwargs):
        return "ok"


def _mock_m2_search(query, max_results=8, round_num=1, **kw):
    return [
        _FakeEvidence(f"ev{round_num}_{i}", f"Title {i}", f"passage about {query}")
        for i in range(3)
    ]


# ── Tests ─────────────────────────────────────

def test_invalid_question_returns_failed():
    engine = InvestigationEngine(
        m2_search_fn=_mock_m2_search,
        m3_pipeline=_FakeM3Pipeline([]),
        gateway=_FakeGateway(),
    )
    r = engine.run({"question": "x", "max_rounds": 1})
    assert r.status == InvestigationStatus.FAILED


def test_simple_question_skips_research():
    route = RouterOutput(
        intent=ResearchIntent.FACT_CHECK,
        domain="GENERAL",
        complexity=QuestionComplexity.SIMPLE,
        needs_research=False,
        investigation_level=InvestigationLevel.DIRECT,
        requires_balanced_evidence=False,
        reason="factual",
    )
    engine = InvestigationEngine(
        m2_search_fn=_mock_m2_search,
        m3_pipeline=_FakeM3Pipeline([]),
        gateway=_FakeGateway(route_output=route),
    )
    r = engine.run(InvestigationRequest(question="What is the capital of France"))
    assert r.status == InvestigationStatus.NO_RESEARCH_NEEDED
    assert r.verdict is None


def test_complex_question_runs_full_flow():
    from m1.models import ResearchPlan, SearchQuery, QueryTrack
    route = RouterOutput(
        intent=ResearchIntent.RESEARCH_SYNTHESIS,
        domain="EDUCATION",
        complexity=QuestionComplexity.COMPLEX,
        needs_research=True,
        investigation_level=InvestigationLevel.DEEP,
        requires_balanced_evidence=True,
        reason="research",
    )
    plan = ResearchPlan(
        main_question="Q",
        queries=[
            SearchQuery(query="q1 supporting", track=QueryTrack.SUPPORTING),
            SearchQuery(query="q2 contradicting", track=QueryTrack.CONTRADICTING),
        ],
        evidence_target=6,
        max_rounds=3,
    )
    m3 = _FakeM3Pipeline([_FakeM3Result(verdict=_FakeVerdict(), needs_more=False)])
    engine = InvestigationEngine(
        m2_search_fn=_mock_m2_search,
        m3_pipeline=m3,
        gateway=_FakeGateway(route_output=route, plan_output=plan),
    )
    r = engine.run(InvestigationRequest(question="Does A improve B in students"))
    assert r.status == InvestigationStatus.COMPLETED
    assert m3.run_calls == 1
    assert m3.continue_calls == 0
    assert r.evidence_count > 0


def test_engine_stops_at_max_rounds():
    from m1.models import ResearchPlan, SearchQuery, QueryTrack
    route = RouterOutput(
        intent=ResearchIntent.RESEARCH_SYNTHESIS,
        domain="G", complexity=QuestionComplexity.COMPLEX,
        needs_research=True, investigation_level=InvestigationLevel.DEEP,
        requires_balanced_evidence=True, reason="r",
    )
    plan = ResearchPlan(
        main_question="Q",
        queries=[SearchQuery(query="q", track=QueryTrack.SUPPORTING)],
    )
    m3 = _FakeM3Pipeline([
        _FakeM3Result(verdict=_FakeVerdict(), needs_more=True),
        _FakeM3Result(verdict=_FakeVerdict(), needs_more=True),
        _FakeM3Result(verdict=_FakeVerdict(), needs_more=True),
    ])
    engine = InvestigationEngine(
        m2_search_fn=_mock_m2_search,
        m3_pipeline=m3,
        gateway=_FakeGateway(route_output=route, plan_output=plan),
    )
    r = engine.run(InvestigationRequest(question="Does A improve B", max_rounds=3))
    assert r.rounds_used <= 3
    assert m3.continue_calls <= 2


def test_m2_empty_response_handled():
    from m1.models import ResearchPlan, SearchQuery, QueryTrack
    route = RouterOutput(
        intent=ResearchIntent.RESEARCH_SYNTHESIS,
        domain="G", complexity=QuestionComplexity.COMPLEX,
        needs_research=True, investigation_level=InvestigationLevel.DEEP,
        requires_balanced_evidence=True, reason="r",
    )
    plan = ResearchPlan(
        main_question="Q",
        queries=[SearchQuery(query="q", track=QueryTrack.SUPPORTING)],
    )

    def empty_m2(**kw):
        return []

    m3 = _FakeM3Pipeline([])
    engine = InvestigationEngine(
        m2_search_fn=empty_m2,
        m3_pipeline=m3,
        gateway=_FakeGateway(route_output=route, plan_output=plan),
    )
    r = engine.run(InvestigationRequest(question="Does A improve B"))
    assert r.status in (InvestigationStatus.INCONCLUSIVE, InvestigationStatus.FAILED)
    assert r.evidence_count == 0