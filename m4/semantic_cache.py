"""
m4/semantic_cache.py — Persistent semantic cache with freshness + fail-safe init.

Fixes:
- NO automatic shutil.rmtree() on failure. Logs error and raises.
- STALE and EXPIRED entries are never served.
- Cache saving is caller-responsibility (only save COMPLETED verdicts).
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

import chromadb

from .config import (
    CACHE_COLLECTION,
    CACHE_FRESH_HOURS,
    CACHE_STALE_HOURS,
    CHROMA_DIR,
    SEMANTIC_CACHE_DISTANCE_THRESHOLD,
)
from .embeddings import get_chroma_embedding_function

logger = logging.getLogger(__name__)


class SemanticCache:
    def __init__(self):
        try:
            self._client = chromadb.PersistentClient(path=CHROMA_DIR)
            self._collection = self._client.get_or_create_collection(
                name=CACHE_COLLECTION,
                embedding_function=get_chroma_embedding_function(),
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            # ★ Do NOT auto-delete. Fail safely with clear diagnostic.
            logger.error(
                "SemanticCache initialization failed at %s. "
                "This may be caused by an incompatible existing ChromaDB. "
                "Manual intervention required: back up %s, then delete it and retry.",
                CHROMA_DIR, CHROMA_DIR,
            )
            raise RuntimeError(
                f"SemanticCache init failed: {e}. "
                f"Investigate manually — do not auto-delete {CHROMA_DIR}."
            ) from e

        logger.info(
            "SemanticCache ready: %s (items=%d)", CHROMA_DIR, self._collection.count()
        )

    def save(self, question: str, investigation_id: str) -> None:
        """Store question → investigation_id mapping. Caller must ensure investigation is COMPLETED."""
        clean = (question or "").strip()
        if not clean or not investigation_id:
            return

        cache_id = f"cache_{uuid.uuid4().hex[:12]}"
        self._collection.add(
            ids=[cache_id],
            documents=[clean],
            metadatas=[{
                "investigation_id": investigation_id,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }],
        )
        logger.info("Cache STORED: inv=%s q='%s'", investigation_id, clean[:50])

    def lookup(self, question: str, threshold: Optional[float] = None) -> Optional[dict]:
        """
        Look up a similar question. Returns match ONLY if FRESH.
        STALE and EXPIRED return None.
        """
        clean = (question or "").strip()
        if not clean or self._collection.count() == 0:
            return None

        threshold = threshold if threshold is not None else SEMANTIC_CACHE_DISTANCE_THRESHOLD

        try:
            results = self._collection.query(
                query_texts=[clean],
                n_results=1,
                include=["documents", "distances", "metadatas"],
            )
        except Exception as e:
            logger.warning("Cache query failed: %s", e)
            return None

        docs = results.get("documents", [[]])[0]
        if not docs:
            return None

        distance = results["distances"][0][0]
        if distance > threshold:
            return None

        metadata = results["metadatas"][0][0]
        investigation_id = metadata.get("investigation_id")
        created_at_str = metadata.get("created_at", "")

        try:
            created_at = datetime.fromisoformat(created_at_str)
            age_hours = (datetime.now() - created_at).total_seconds() / 3600.0

            if age_hours > CACHE_STALE_HOURS:
                logger.info("Cache EXPIRED (%.1fh): '%s'", age_hours, clean[:50])
                return None

            if age_hours > CACHE_FRESH_HOURS:
                logger.info(
                    "Cache STALE (%.1fh > %dh): '%s'. Not serving.",
                    age_hours, CACHE_FRESH_HOURS, clean[:50],
                )
                return None

        except (ValueError, TypeError):
            logger.warning("Cache entry has invalid timestamp. Not serving.")
            return None

        logger.info(
            "Cache HIT (FRESH, dist=%.3f, age=%.1fh): '%s' → inv=%s",
            distance, age_hours, clean[:50], investigation_id,
        )

        return {
            "investigation_id": investigation_id,
            "matched_question": docs[0],
            "distance": distance,
            "freshness": "FRESH",
            "age_hours": age_hours,
        }

    def delete_by_investigation_id(self, investigation_id: str) -> int:
        """Delete all cache entries linked to an investigation."""
        if not investigation_id or self._collection.count() == 0:
            return 0

        try:
            results = self._collection.get(
                where={"investigation_id": investigation_id},
                include=[],
            )
            ids = results.get("ids", [])
            if ids:
                self._collection.delete(ids=ids)
                logger.info(
                    "Cache DELETED: %d entries for inv=%s", len(ids), investigation_id
                )
            return len(ids)
        except Exception as e:
            logger.warning("Cache delete failed for inv=%s: %s", investigation_id, e)
            return 0

    def clear(self) -> None:
        """Explicit user-triggered clear (never automatic)."""
        try:
            self._client.delete_collection(CACHE_COLLECTION)
        except Exception as e:
            logger.warning("Could not delete collection: %s", e)
        self._collection = self._client.get_or_create_collection(
            name=CACHE_COLLECTION,
            embedding_function=get_chroma_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )
        logger.warning("Semantic cache cleared by user request.")

    def count(self) -> int:
        return self._collection.count()


_instance: Optional[SemanticCache] = None
_lock = threading.Lock()


def get_semantic_cache() -> SemanticCache:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = SemanticCache()
    return _instance