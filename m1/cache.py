"""
m1/cache.py — MVP normalized-exact investigation cache.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from .config import CONFIG
from .models import CacheFreshness, InvestigationResult

logger = logging.getLogger(__name__)


def _normalize(question: str) -> str:
    q = (question or "").strip().lower()
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"[^\w\s\-]", "", q)
    return q


def _hash_key(normalized: str, domain: str = "") -> str:
    payload = f"{domain}::{normalized}"
    return hashlib.md5(payload.encode()).hexdigest()


class InvestigationCache:
    """
    MVP normalized-exact cache with freshness tracking.

    NOT a semantic cache — this is deliberate for hackathon MVP.
    Upgrade path: swap with embedding-based lookup later.
    """

    def __init__(self):
        self._store: dict[str, dict] = {}

    def get(
        self, question: str, domain: str = "GENERAL"
    ) -> Optional[InvestigationResult]:
        key = _hash_key(_normalize(question), domain)
        entry = self._store.get(key)
        if not entry:
            logger.info("Cache MISS: %s", question[:60])
            return None

        age = datetime.now() - entry["created_at"]
        if age > timedelta(hours=CONFIG.CACHE_STALE_HOURS):
            logger.info("Cache EXPIRED (age %s): %s", age, question[:60])
            del self._store[key]
            return None

        # Return a deep copy so callers cannot mutate cache
        result: InvestigationResult = copy.deepcopy(entry["result"])
        result.from_cache = True

        if age > timedelta(hours=CONFIG.CACHE_FRESH_HOURS):
            logger.info("Cache STALE (age %s): %s (reusing with warning)", age, question[:60])
            result.trace_summary.insert(0, "[cache STALE — consider refresh]")
        else:
            logger.info("Cache FRESH HIT: %s", question[:60])
            result.trace_summary.insert(0, "[cache FRESH hit]")

        return result

    def put(
        self,
        question: str,
        result: InvestigationResult,
        domain: str = "GENERAL",
    ) -> None:
        key = _hash_key(_normalize(question), domain)
        self._store[key] = {
            "result": copy.deepcopy(result),
            "created_at": datetime.now(),
            "domain": domain,
        }
        logger.info("Cache STORED: %s", question[:60])

    def clear(self) -> None:
        self._store.clear()