"""
m4/engine_integration.py — Bridge M4 ↔ M1 InvestigationEngine.

Rules:
- Only cache investigations that are COMPLETED and have a non-null verdict.
- Never cache FAILED or INCONCLUSIVE results.
- STALE cache entries never served (handled inside SemanticCache.lookup).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from .database import InvestigationRecord, get_investigation, save_investigation
from .evidence_store import get_evidence_store
from .semantic_cache import get_semantic_cache
from .verdict_formatter import format_verdict_for_display, verdict_to_dict, verdict_to_json

logger = logging.getLogger(__name__)

_engine: Optional[Any] = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                try:
                    from m1 import InvestigationEngine
                    _engine = InvestigationEngine()
                    logger.info("M1 InvestigationEngine initialized.")
                except ImportError as e:
                    logger.error("Cannot import M1: %s", e)
                    raise
    return _engine


def _safe_enum_value(val: Any, default: str = "UNKNOWN") -> str:
    if val is None:
        return default
    if hasattr(val, "value"):
        return str(val.value)
    return str(val)


def _is_cache_worthy(record: InvestigationRecord, verdict: Any) -> bool:
    """
    Only cache genuine COMPLETED investigations with a valid verdict.
    Never cache FAILED, INCONCLUSIVE, NO_RESEARCH_NEEDED.
    """
    if verdict is None:
        return False
    if record.status != "COMPLETED":
        return False
    if record.verdict_type in ("INCONCLUSIVE", "UNKNOWN", ""):
        return False
    return True


def run_investigation(
    question: str,
    max_rounds: int = 3,
    use_cache: bool = True,
) -> dict:
    """Run investigation with cache lookup + persistence."""
    question = (question or "").strip()
    if not question or len(question) < 5:
        raise ValueError("Question must be at least 5 characters.")

    cache = get_semantic_cache()

    # ── 1. Cache lookup (FRESH only) ────────
    if use_cache:
        hit = cache.lookup(question)
        if hit is not None:
            inv_id = hit["investigation_id"]
            record = get_investigation(inv_id)
            if record is not None:
                logger.info("Serving from FRESH cache: %s", inv_id)
                return {
                    "record": record,
                    "from_cache": True,
                    "cache_freshness": "FRESH",
                    "cache_distance": hit["distance"],
                    "verdict_dict": format_verdict_for_display(record.verdict_json),
                }
            else:
                logger.warning("Cache hit but SQLite record missing: %s", inv_id)

    # ── 2. Run M1 engine ───────────────────
    engine = _get_engine()

    try:
        from m1 import InvestigationRequest
        request = InvestigationRequest(question=question, max_rounds=max_rounds)
    except ImportError:
        request = {"question": question, "max_rounds": max_rounds}

    result = engine.run(request)

    # ── 3. Build record ────────────────────
    record = InvestigationRecord.new(question=question)
    record.investigation_id = getattr(result, "investigation_id", record.investigation_id)
    record.status = _safe_enum_value(getattr(result, "status", None), "UNKNOWN")
    record.rounds_used = getattr(result, "rounds_used", 0) or 0
    record.evidence_count = getattr(result, "evidence_count", 0) or 0
    record.time_taken = getattr(result, "time_taken", "") or ""

    verdict = getattr(result, "verdict", None)
    if verdict is not None:
        vd = verdict_to_dict(verdict)
        record.verdict_type = _safe_enum_value(vd.get("verdict"), "UNKNOWN")
        record.confidence = _safe_enum_value(vd.get("confidence"), "UNKNOWN")
        record.summary = vd.get("summary", "") or ""
        record.verdict_json = verdict_to_json(verdict)
    else:
        record.verdict_type = "INCONCLUSIVE"
        record.confidence = "LOW"
        record.summary = "No verdict generated."

    # ── 4. Persist to SQLite (always) ──────
    save_investigation(record)

    # ── 5. Cache ONLY if cache-worthy ──────
    if use_cache and _is_cache_worthy(record, verdict):
        cache.save(question, record.investigation_id)
    else:
        logger.info(
            "Skipping cache save: status=%s verdict=%s",
            record.status, record.verdict_type,
        )

    # ── 6. Populate evidence store ──────────
    _populate_evidence_store(result, record.investigation_id)

    return {
        "record": record,
        "from_cache": False,
        "cache_freshness": None,
        "cache_distance": None,
        "verdict_dict": format_verdict_for_display(record.verdict_json),
    }


def _populate_evidence_store(result: Any, investigation_id: str) -> None:
    """
    Store evidence using result.raw_evidence_summary (new M1 field).
    Falls back gracefully if the field doesn't exist.
    """
    try:
        evidence_summary = getattr(result, "raw_evidence_summary", None) or []
        if not evidence_summary:
            logger.debug("No raw_evidence_summary; skipping evidence store.")
            return

        items = []
        for ev_data in evidence_summary:
            text = ev_data.get("relevant_passage", "") or ev_data.get("title", "")
            if not text:
                continue
            items.append({
                "text": text,
                "source_id": ev_data.get("source_id"),
                "title": ev_data.get("title"),
                "extra_metadata": {
                    "url": ev_data.get("url", ""),
                    "year": ev_data.get("year"),
                    "study_design": ev_data.get("study_design", ""),
                    "peer_reviewed": ev_data.get("peer_reviewed"),
                },
            })

        if items:
            store = get_evidence_store()
            store.add_batch(items, investigation_id=investigation_id)
    except Exception as e:
        logger.warning("Failed to populate evidence store: %s", e)