"""Planner unit tests."""

from __future__ import annotations

from m1.models import QuestionComplexity, QueryTrack, ResearchPlan, SearchQuery
from m1.planner import ResearchPlanner


class _FakeGateway:
    def __init__(self, output=None, fail=False):
        self._output = output
        self._fail = fail

    def has_providers(self):
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


def test_fallback_plan_has_supporting_and_contradicting_queries():
    planner = ResearchPlanner(gateway=_FakeGateway(fail=True))
    plan = planner.plan("Does X improve Y", QuestionComplexity.COMPLEX)
    tracks = {q.track for q in plan.queries}
    assert QueryTrack.SUPPORTING in tracks
    assert QueryTrack.CONTRADICTING in tracks
    assert QueryTrack.SYSTEMATIC_REVIEWS in tracks


def test_planner_ensures_balance_when_llm_omits_tracks():
    llm_output = ResearchPlan(
        main_question="Q",
        queries=[
            SearchQuery(query="a", track=QueryTrack.SUPPORTING),
            SearchQuery(query="b", track=QueryTrack.RECENT),
        ],
    )
    planner = ResearchPlanner(gateway=_FakeGateway(output=llm_output))
    plan = planner.plan("Q", QuestionComplexity.COMPLEX)
    tracks = {q.track for q in plan.queries}
    assert QueryTrack.CONTRADICTING in tracks


def test_no_gateway_uses_deterministic_fallback():
    planner = ResearchPlanner(gateway=None)
    plan = planner.plan("test question", QuestionComplexity.MODERATE)
    assert plan.queries
    assert plan.max_rounds == 2


def test_followup_queries_marked_as_followup_track():
    llm_output = ResearchPlan(
        main_question="Q",
        queries=[
            SearchQuery(query="fx1", track=QueryTrack.SUPPORTING),
            SearchQuery(query="fx2", track=QueryTrack.RECENT),
        ],
    )
    planner = ResearchPlanner(gateway=_FakeGateway(output=llm_output))
    q = planner.generate_followup_queries(
        question="Q",
        research_focus="k-12 null results",
        research_gaps_texts=["Need more K-12 evidence"],
    )
    assert q
    assert all(x.track == QueryTrack.FOLLOW_UP for x in q)


def test_followup_empty_when_no_focus_and_no_gaps():
    planner = ResearchPlanner(gateway=None)
    assert planner.generate_followup_queries("Q", "", []) == []