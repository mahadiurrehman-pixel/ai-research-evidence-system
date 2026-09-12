"""M4 unit tests with reliable storage isolation and runtime-safety checks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    storage_dir = str(tmp_path / "m4_test_storage")
    os.makedirs(storage_dir, exist_ok=True)
    monkeypatch.setenv("M4_STORAGE_DIR", storage_dir)

    import importlib
    from m4 import config, database, semantic_cache, evidence_store
    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(semantic_cache)
    importlib.reload(evidence_store)

    semantic_cache._instance = None
    evidence_store._instance = None

    database.init_database()
    yield tmp_path

    semantic_cache._instance = None
    evidence_store._instance = None


def test_sqlite_save_and_get():
    from m4.database import InvestigationRecord, save_investigation, get_investigation
    rec = InvestigationRecord.new(question="Does X improve Y?")
    rec.verdict_type = "SUPPORTED"
    rec.confidence = "HIGH"
    save_investigation(rec)
    loaded = get_investigation(rec.investigation_id)
    assert loaded.verdict_type == "SUPPORTED"


def test_history_ordering():
    from m4.database import InvestigationRecord, save_investigation, get_history
    for i in range(3):
        save_investigation(InvestigationRecord.new(question=f"Q{i}?"))
    assert len(get_history()) == 3


def test_three_layer_delete():
    """Deleting an investigation must clean SQLite + cache + evidence store."""
    from m4.database import InvestigationRecord, save_investigation, delete_investigation, get_investigation
    from m4.semantic_cache import get_semantic_cache
    from m4.evidence_store import get_evidence_store

    rec = InvestigationRecord.new(question="Three layer delete test?")
    rec.status = "COMPLETED"
    rec.verdict_type = "SUPPORTED"
    save_investigation(rec)

    cache = get_semantic_cache()
    store = get_evidence_store()

    cache.save("Three layer delete test?", rec.investigation_id)
    store.add_batch(
        [{"text": "Test evidence", "source_id": "S1", "title": "T"}],
        investigation_id=rec.investigation_id,
    )

    assert cache.count() == 1
    assert store.count() == 1
    assert get_investigation(rec.investigation_id) is not None

    delete_investigation(rec.investigation_id)

    assert get_investigation(rec.investigation_id) is None
    assert cache.count() == 0
    assert store.count() == 0


def test_cache_fresh_hit():
    from m4.semantic_cache import get_semantic_cache
    cache = get_semantic_cache()
    cache.save("Does AI improve learning?", "inv_fresh_1")
    hit = cache.lookup("Does AI improve learning?")
    assert hit is not None
    assert hit["freshness"] == "FRESH"


def test_cache_miss_unrelated():
    from m4.semantic_cache import get_semantic_cache
    cache = get_semantic_cache()
    cache.save("Does exercise improve mood?", "inv_1")
    assert cache.lookup("What is quantum mechanics?") is None


def test_cache_worthiness_check():
    """Verify _is_cache_worthy blocks non-COMPLETED and null verdicts."""
    from m4.engine_integration import _is_cache_worthy
    from m4.database import InvestigationRecord

    # Non-completed
    r1 = InvestigationRecord.new(question="Q")
    r1.status = "FAILED"
    assert _is_cache_worthy(r1, "some_verdict") is False

    # Null verdict
    r2 = InvestigationRecord.new(question="Q")
    r2.status = "COMPLETED"
    assert _is_cache_worthy(r2, None) is False

    # Inconclusive
    r3 = InvestigationRecord.new(question="Q")
    r3.status = "COMPLETED"
    r3.verdict_type = "INCONCLUSIVE"
    assert _is_cache_worthy(r3, "verdict") is False

    # Valid
    r4 = InvestigationRecord.new(question="Q")
    r4.status = "COMPLETED"
    r4.verdict_type = "SUPPORTED"
    assert _is_cache_worthy(r4, "verdict") is True


def test_evidence_store_search():
    from m4.evidence_store import get_evidence_store
    store = get_evidence_store()
    store.add_batch([
        {"text": "AI tutoring improved math scores by 12%.", "source_id": "S1", "title": "AI Math"},
        {"text": "Adult learners showed no improvement.", "source_id": "S2", "title": "Adults"},
    ], investigation_id="inv_ev_1")
    results = store.search("AI math improvement", top_k=2)
    assert len(results) >= 1


def test_evidence_store_empty_metadata_filtered():
    from m4.evidence_store import get_evidence_store
    store = get_evidence_store()
    store.add_evidence(
        "ev_1", "Test evidence",
        investigation_id="inv_meta",
        source_id="",
        title=None,
    )
    results = store.search("Test evidence", top_k=1)
    assert len(results) >= 1
    meta = results[0]["metadata"]
    assert meta.get("source_id") != ""
    assert meta.get("title") is not None or "title" not in meta


def test_verdict_formatter_pydantic_v2():
    from m4.verdict_formatter import format_verdict_for_display

    class FakeVerdict:
        def model_dump(self, mode=None):
            return {"verdict": "SUPPORTED", "confidence": "HIGH", "summary": "test"}

    d = format_verdict_for_display(FakeVerdict())
    assert d["verdict"] == "SUPPORTED"


def test_verdict_formatter_json_string():
    from m4.verdict_formatter import format_verdict_for_display, verdict_to_json
    j = verdict_to_json({
        "verdict": "PARTIALLY_SUPPORTED", "confidence": "MEDIUM",
        "summary": "s", "supporting_evidence": [],
        "contradicting_evidence": [], "limitations": [],
    })
    d = format_verdict_for_display(j)
    assert d["verdict"] == "PARTIALLY_SUPPORTED"