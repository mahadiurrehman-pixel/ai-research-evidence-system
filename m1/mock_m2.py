"""
m1/mock_m2.py — Mock M2 for testing (uses real_dataset at project root).

Safely handles missing dataset and RawEvidence field variations.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _try_load_real_dataset() -> list:
    """
    Try loading real_dataset from project root.
    Returns [] safely if not available.
    """
    try:
        # Project-root location
        from real_dataset import get_real_evidence  # type: ignore
        return list(get_real_evidence())
    except ImportError:
        pass

    try:
        # Fallback: check inside verification package
        from verification.real_dataset import get_real_evidence  # type: ignore
        return list(get_real_evidence())
    except ImportError:
        pass

    logger.warning("real_dataset not found (root or verification/). MockM2 empty.")
    return []


class MockM2:
    """
    Simulates M2 using real_dataset. Filters by keyword overlap.
    """

    def __init__(self, dataset: Optional[list] = None):
        self._all = dataset if dataset is not None else _try_load_real_dataset()

    def search(
        self,
        query: str,
        max_results: int = 8,
        round_num: int = 1,
        investigation_id: str = "",
        track: str = "",
    ) -> list:
        if not self._all:
            logger.warning("MockM2 has no dataset loaded.")
            return []

        q_lower = (query or "").lower()
        q_tokens = {t for t in q_lower.split() if len(t) > 3}

        scored = []
        for ev in self._all:
            text = _extract_searchable_text(ev).lower()
            if not text:
                continue
            score = sum(1 for t in q_tokens if t in text)
            if score > 0:
                scored.append((score, ev))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [ev for _, ev in scored[:max_results]]

        # If no keyword match, rotate through dataset to avoid empty results
        if not results:
            start = ((round_num - 1) * max_results) % max(1, len(self._all))
            results = self._all[start:start + max_results]

        logger.info(
            "MockM2 query='%s' → %d results (round=%d, track=%s)",
            query[:50], len(results), round_num, track,
        )
        return results


def _extract_searchable_text(ev) -> str:
    """
    Safely extract searchable text from an evidence record,
    regardless of exact schema.
    """
    parts = []
    for attr in ("title", "relevant_passage", "abstract"):
        val = getattr(ev, attr, None)
        if val:
            parts.append(str(val))
    return " ".join(parts)


# Callable convenience — matches typical M2 search signature
def make_mock_m2_search_fn() -> Callable:
    m2 = MockM2()

    def _search(query: str, max_results: int = 8, round_num: int = 1, **kwargs):
        return m2.search(
            query=query,
            max_results=max_results,
            round_num=round_num,
            investigation_id=kwargs.get("investigation_id", ""),
            track=kwargs.get("track", ""),
        )

    return _search