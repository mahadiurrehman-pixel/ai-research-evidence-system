"""
m4/config.py — Configuration for M4 storage paths and thresholds.
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()
import os
from pathlib import Path

# ── Base storage directory ──────────────────
_storage_env = os.getenv("M4_STORAGE_DIR", "storage")
BASE_DIR = Path(_storage_env)
BASE_DIR.mkdir(parents=True, exist_ok=True)

# ── SQLite (source of truth) ────────────────
SQLITE_DB_PATH: str = str(BASE_DIR / "research_history.db")

# ── ChromaDB (persistent vector storage) ───
CHROMA_DIR: str = str(BASE_DIR / "chroma_db")
Path(CHROMA_DIR).mkdir(parents=True, exist_ok=True)

# Collection names
CACHE_COLLECTION: str = "semantic_cache"
EVIDENCE_COLLECTION: str = "research_evidence"

# ── Embedding model (shared across all modules) ──
EMBEDDING_MODEL: str = os.getenv(
    "M4_EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)

# ── Semantic cache thresholds ──────────────
SEMANTIC_CACHE_DISTANCE_THRESHOLD: float = float(
    os.getenv("M4_CACHE_DISTANCE_THRESHOLD", "0.25")
)

# Cache freshness (hours)
CACHE_FRESH_HOURS: int = int(os.getenv("M4_CACHE_FRESH_HOURS", "24"))
CACHE_STALE_HOURS: int = int(os.getenv("M4_CACHE_STALE_HOURS", "168"))  # 7 days

# ── Evidence search defaults ────────────────
EVIDENCE_TOP_K: int = int(os.getenv("M4_EVIDENCE_TOP_K", "5"))