"""Cache tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from m1.cache import InvestigationCache
from m1.models import InvestigationResult, InvestigationStatus


def _mk_result(question: str, verdict: str = "SUPPORTED") -> InvestigationResult:
    return InvestigationResult(
        investigation_id="inv_test",
        status=InvestigationStatus.COMPLETED,
        question=question,
        verdict=None,
        rounds_used=1,
        evidence_count=3,
        trace_summary=["test"],
        time_taken="0.5s",
    )


def test_cache_hit_returns_deep_copy():
    cache = InvestigationCache()
    q = "Does A improve B"
    original = _mk_result(q)
    cache.put(q, original)
    hit = cache.get(q)
    assert hit is not None
    assert hit.from_cache is True
    # Mutating hit must not affect the stored entry
    hit.trace_summary.append("MUTATED")
    hit2 = cache.get(q)
    assert "MUTATED" not in hit2.trace_summary


def test_cache_miss_on_different_question():
    cache = InvestigationCache()
    cache.put("Does A improve B", _mk_result("Does A improve B"))
    assert cache.get("Does A improve C") is None


def test_cache_normalization_whitespace():
    cache = InvestigationCache()
    cache.put("  Does  A improve   B?  ", _mk_result("q"))
    assert cache.get("Does A improve B") is not None


def test_cache_expiry_removes_entry():
    cache = InvestigationCache()
    q = "expire me"
    cache.put(q, _mk_result(q))
    # Force expiry
    key = list(cache._store.keys())[0]
    cache._store[key]["created_at"] = datetime.now() - timedelta(hours=1000)
    assert cache.get(q) is None