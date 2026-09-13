from __future__ import annotations

import time
from threading import Lock

from verification.contradiction import ContradictionDetector
from verification.models import (
    AnalyzedEvidence,
    ContradictionClass,
    ContradictionPair,
    Confidence,
    RawEvidence,
    Relevance,
    Strength,
    SupportLevel,
)
from verification.scheduler import RequestScheduler
from m1.gateway import LLMGateway
from verification.models import FinalVerdict, VerdictType, Confidence


class _TimedContradictionLLM:
    available_provider_names = ["groq-1", "groq-2", "groq-3", "groq-4"]

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.calls: list[tuple[str, str | None]] = []
        self._lock = Lock()

    def structured_call(self, system, user, response_model, **kwargs):
        time.sleep(self.delay)
        source_ids = [line.split(":", 1)[0].strip() for line in user.splitlines()[:2]]
        with self._lock:
            self.calls.append(("|".join(source_ids), kwargs.get("provider_hint")))
        return ContradictionPair(
            evidence_a_id=source_ids[0],
            evidence_b_id=source_ids[1],
            claim_a="supporting finding",
            claim_b="contradicting finding",
            is_genuine_contradiction=False,
            explanation="Different contexts.",
            severity=Strength.LOW,
            classification=ContradictionClass.CONTEXT_DIFFERENCE,
            confidence=Confidence.MEDIUM,
        )


def _evidence() -> list[AnalyzedEvidence]:
    return [
        AnalyzedEvidence(
            source_id=f"S{index}",
            title=f"Study {index}",
            question_ids=["Q1"],
            support_level=SupportLevel.SUPPORTS if index % 2 else SupportLevel.CONTRADICTS,
            strength=Strength.HIGH,
            relevance=Relevance.HIGH,
            reason="",
            key_claim=f"finding {index}",
        )
        for index in range(1, 7)
    ]


def _raw_evidence() -> list[RawEvidence]:
    return [RawEvidence(source_id=f"S{index}", title=f"Study {index}") for index in range(1, 7)]


def test_contradiction_pairs_are_deduplicated_across_rounds_and_distributed():
    llm = _TimedContradictionLLM()
    scheduler = RequestScheduler(
        max_concurrency=6,
        batch_size=5,
        batch_delay=0,
        max_retries=0,
        cooldown_seconds=1,
    )
    detector = ContradictionDetector(llm=llm, max_pairs=5, scheduler=scheduler)

    started = time.perf_counter()
    first = detector.detect(_evidence(), raw_evidence=_raw_evidence())
    first_duration = time.perf_counter() - started
    second = detector.detect(_evidence(), raw_evidence=_raw_evidence())
    third = detector.detect(_evidence(), raw_evidence=_raw_evidence())
    scheduler.shutdown()

    assert len(first.contradiction_pairs) == 5
    assert len(second.contradiction_pairs) == 9
    assert len(third.contradiction_pairs) == 9
    assert len(llm.calls) == 9
    assert len({call[0] for call in llm.calls}) == 9
    assert {call[1] for call in llm.calls} == set(llm.available_provider_names[:3]) | {"groq-4"}
    assert first_duration < 0.25


class _Provider:
    def __init__(self, name: str, behavior: str):
        self.name = name
        self.model = "test-model"
        self.behavior = behavior
        self.calls = 0
        self.max_tokens = None

    def structured(self, **kwargs):
        self.calls += 1
        self.max_tokens = kwargs.get("max_tokens")
        if self.behavior == "rate_limit":
            raise Exception("429 rate limit exceeded")
        if self.behavior == "success":
            return FinalVerdict(
                original_question="Q",
                verdict=VerdictType.PARTIALLY_SUPPORTED,
                confidence=Confidence.MEDIUM,
                summary="ok",
                detailed_reasoning="ok",
            )
        raise AssertionError("provider should not be reached")


def test_contradiction_fallback_stops_after_two_provider_attempts():
    scheduler = RequestScheduler(max_concurrency=4, max_retries=0, cooldown_seconds=1)
    gateway = LLMGateway(scheduler=scheduler, max_retries_per_provider=1)
    first = _Provider("groq-1", "rate_limit")
    second = _Provider("groq-2", "success")
    third = _Provider("groq-3", "unexpected")
    gateway._providers = [first, second, third]
    gateway._provider_map = {p.name: p for p in gateway._providers}

    result = gateway.structured_call(
        system="system",
        user="user",
        response_model=FinalVerdict,
        task_type="contradiction_detection",
        provider_hint="groq-1",
        max_provider_attempts=2,
    )
    scheduler.shutdown()

    assert result.summary == "ok"
    assert first.calls == 1
    assert second.calls == 1
    assert third.calls == 0
    assert first.max_tokens == 512
