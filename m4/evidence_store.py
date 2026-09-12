"""
m4/evidence_store.py — Persistent evidence vector store.

Fixes:
- NO auto shutil.rmtree() on failure
- delete_by_investigation_id() for cleanup
- Safe metadata cleaning
- where filter only passed when non-None
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime
from typing import Optional

import chromadb

from .config import CHROMA_DIR, EVIDENCE_COLLECTION, EVIDENCE_TOP_K
from .embeddings import get_chroma_embedding_function

logger = logging.getLogger(__name__)


def _clean_metadata(meta: dict) -> dict:
    """Remove None and empty values that ChromaDB rejects."""
    return {
        k: v for k, v in meta.items()
        if v is not None and v != "" and isinstance(v, (str, int, float, bool))
    }


class EvidenceStore:
    def __init__(self):
        try:
            self._client = chromadb.PersistentClient(path=CHROMA_DIR)
            self._collection = self._client.get_or_create_collection(
                name=EVIDENCE_COLLECTION,
                embedding_function=get_chroma_embedding_function(),
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.error(
                "EvidenceStore init failed at %s. Investigate manually.",
                CHROMA_DIR,
            )
            raise RuntimeError(
                f"EvidenceStore init failed: {e}. "
                f"Manual intervention required for {CHROMA_DIR}."
            ) from e

        logger.info(
            "EvidenceStore ready: %s (items=%d)", CHROMA_DIR, self._collection.count()
        )

    def add_evidence(
        self,
        evidence_id: str,
        text: str,
        investigation_id: Optional[str] = None,
        source_id: Optional[str] = None,
        title: Optional[str] = None,
        extra_metadata: Optional[dict] = None,
    ) -> None:
        clean_text = (text or "").strip()
        if not clean_text:
            return

        meta = {"stored_at": datetime.now().isoformat(timespec="seconds")}
        if investigation_id:
            meta["investigation_id"] = investigation_id
        if source_id:
            meta["source_id"] = source_id
        if title:
            meta["title"] = title
        if extra_metadata:
            meta.update(extra_metadata)

        meta = _clean_metadata(meta)

        self._collection.upsert(
            ids=[str(evidence_id)],
            documents=[clean_text],
            metadatas=[meta],
        )

    def add_batch(
        self,
        items: list[dict],
        investigation_id: Optional[str] = None,
    ) -> int:
        if not items:
            return 0

        ids, docs, metas = [], [], []
        for item in items:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            ids.append(f"ev_{uuid.uuid4().hex[:12]}")
            docs.append(text)
            m = {"stored_at": datetime.now().isoformat(timespec="seconds")}
            if investigation_id:
                m["investigation_id"] = investigation_id
            if item.get("source_id"):
                m["source_id"] = str(item["source_id"])
            if item.get("title"):
                m["title"] = str(item["title"])
            extra = item.get("extra_metadata") or {}
            for k, v in extra.items():
                m[k] = v
            metas.append(_clean_metadata(m))

        if not ids:
            return 0

        self._collection.add(ids=ids, documents=docs, metadatas=metas)
        logger.info("Batch stored: %d items for inv=%s", len(ids), investigation_id)
        return len(ids)

    def search(
        self,
        query: str,
        top_k: int = EVIDENCE_TOP_K,
        investigation_id: Optional[str] = None,
    ) -> list[dict]:
        clean = (query or "").strip()
        if not clean or self._collection.count() == 0:
            return []

        query_kwargs = {
            "query_texts": [clean],
            "n_results": min(top_k, self._collection.count()),
            "include": ["documents", "distances", "metadatas"],
        }
        if investigation_id:
            query_kwargs["where"] = {"investigation_id": investigation_id}

        try:
            results = self._collection.query(**query_kwargs)
        except Exception as e:
            logger.warning("Evidence search failed: %s", e)
            return []

        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        return [
            {"text": doc, "distance": float(dist), "metadata": meta or {}}
            for doc, dist, meta in zip(docs, distances, metas)
        ]

    def delete_by_investigation_id(self, investigation_id: str) -> int:
        """Delete all evidence entries linked to an investigation."""
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
                    "Evidence DELETED: %d items for inv=%s", len(ids), investigation_id
                )
            return len(ids)
        except Exception as e:
            logger.warning("Evidence delete failed for inv=%s: %s", investigation_id, e)
            return 0

    def count(self) -> int:
        return self._collection.count()


_instance: Optional[EvidenceStore] = None
_lock = threading.Lock()


def get_evidence_store() -> EvidenceStore:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = EvidenceStore()
    return _instance