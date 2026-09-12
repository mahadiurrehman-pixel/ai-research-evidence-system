"""
m4/verdict_formatter.py — Convert M3 FinalVerdict to display-ready structure.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def verdict_to_dict(verdict: Any) -> dict:
    """
    Serialize a Pydantic FinalVerdict to a plain dict (safe for JSON/SQLite).
    Handles both actual FinalVerdict objects and fallback dict-likes.
    """
    if verdict is None:
        return {}

    # Pydantic v2
    if hasattr(verdict, "model_dump"):
        try:
            return verdict.model_dump(mode="json")
        except Exception:
            pass

    # Pydantic v1
    if hasattr(verdict, "dict"):
        try:
            return verdict.dict()
        except Exception:
            pass

    # Dict already
    if isinstance(verdict, dict):
        return verdict

    # Fallback: extract common attributes
    def _val(attr, default=""):
        v = getattr(verdict, attr, default)
        if hasattr(v, "value"):
            return v.value
        return v

    return {
        "verdict": _val("verdict", "UNKNOWN"),
        "confidence": _val("confidence", "UNKNOWN"),
        "summary": _val("summary", ""),
        "detailed_reasoning": _val("detailed_reasoning", ""),
        "supporting_evidence": [
            _citation_to_dict(c) for c in getattr(verdict, "supporting_evidence", []) or []
        ],
        "contradicting_evidence": [
            _citation_to_dict(c) for c in getattr(verdict, "contradicting_evidence", []) or []
        ],
        "limitations": list(getattr(verdict, "limitations", []) or []),
    }


def _citation_to_dict(c: Any) -> dict:
    if hasattr(c, "model_dump"):
        try:
            return c.model_dump(mode="json")
        except Exception:
            pass
    return {
        "source_id": getattr(c, "source_id", ""),
        "title": getattr(c, "title", ""),
        "claim": getattr(c, "claim", ""),
        "reason": getattr(c, "reason", ""),
    }


def verdict_to_json(verdict: Any) -> str:
    """Serialize a verdict to a JSON string for SQLite storage."""
    d = verdict_to_dict(verdict)
    try:
        return json.dumps(d, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        logger.warning("verdict_to_json failed: %s", e)
        return json.dumps({"error": str(e), "raw": str(verdict)})


def json_to_verdict_dict(verdict_json: str) -> dict:
    """Load JSON string back to dict (for display)."""
    if not verdict_json:
        return {}
    try:
        return json.loads(verdict_json)
    except (TypeError, ValueError):
        return {"error": "invalid JSON", "raw": verdict_json}


def format_verdict_for_display(verdict_data: Any) -> dict:
    """
    Normalize a verdict (dict, JSON string, or Pydantic object) into a
    standard display dict.
    """
    if isinstance(verdict_data, str):
        d = json_to_verdict_dict(verdict_data)
    elif isinstance(verdict_data, dict):
        d = verdict_data
    else:
        d = verdict_to_dict(verdict_data)

    return {
        "verdict": _safe(d, "verdict", "UNKNOWN"),
        "confidence": _safe(d, "confidence", "UNKNOWN"),
        "summary": _safe(d, "summary", "No summary available."),
        "detailed_reasoning": _safe(d, "detailed_reasoning", ""),
        "supporting_evidence": d.get("supporting_evidence", []) or [],
        "contradicting_evidence": d.get("contradicting_evidence", []) or [],
        "limitations": d.get("limitations", []) or [],
    }


def _safe(d: dict, key: str, default: str) -> str:
    val = d.get(key, default)
    if hasattr(val, "value"):
        return val.value
    return str(val) if val else default