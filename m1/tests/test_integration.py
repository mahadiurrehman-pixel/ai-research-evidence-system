"""Integration test: engine + mock M2 + fake M3 end-to-end."""

from __future__ import annotations

from m1.engine import InvestigationEngine
from m1.models import InvestigationRequest, InvestigationStatus


class _V:
    class _V2:
        value = "PARTIALLY_SUPPORTED"
    class _C:
        value = "MEDIUM"
    verdict = _V2()
    confidence = _C()
    summary = "integration test verdict"
    detailed_reasoning = "test"
    supporting_evidence = []
    contradicting_evidence = []
    limitations = []


class _FakeM3:
    def __init__(self):
        self.calls = 0

    def run(self, question, evidence, complexity=None, **kwargs):
        self.calls += 1
        class R:
            verdict = _V()
            needs_more_research = False
            research_focus = ""
            research_gaps = []
            state = object()
            max_rounds_reached = False
        return R()

    def run_continue(self, state, new_evidence, complexity=None, **kwargs):
        return self.run("", new_evidence)


class _FakeGw:
    def has_providers(self):
        return False

    def structured_call(self, system, user, response_model, **kwargs):
        return response_model()

    def text_call(self, system, user, **kwargs):
        return "ok"


def test_end_to_end_with_mock_m2_and_fake_m3():
    engine = InvestigationEngine(
        m2_search_fn=lambda **kw: [],
        m3_pipeline=_FakeM3(),
        gateway=_FakeGw(),
    )
    r = engine.run(
        InvestigationRequest(
            question="Does structured tutoring improve student outcomes",
            max_rounds=2,
        )
    )
    assert r.status in (InvestigationStatus.INCONCLUSIVE, InvestigationStatus.FAILED)