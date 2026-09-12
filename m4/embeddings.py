"""
m4/embeddings.py — Single shared embedding model.
"""

from __future__ import annotations

import logging
import threading

from .config import EMBEDDING_MODEL

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_chroma_ef = None


def get_chroma_embedding_function():
    """
    Return the shared ChromaDB embedding function.
    Uses the FULL model name (e.g. 'sentence-transformers/all-MiniLM-L6-v2').
    """
    global _chroma_ef
    if _chroma_ef is None:
        with _lock:
            if _chroma_ef is None:
                from chromadb.utils.embedding_functions import (
                    SentenceTransformerEmbeddingFunction,
                )
                logger.info("Loading Chroma embedding function: %s", EMBEDDING_MODEL)
                _chroma_ef = SentenceTransformerEmbeddingFunction(
                    model_name=EMBEDDING_MODEL  # ★ Full name, NOT split
                )
    return _chroma_ef