"""
m4 — Frontend, Database, and Cache Layer.

Architecture:
  SQLite   = Permanent source of truth (investigations, verdicts, history)
  ChromaDB = Persistent semantic cache + evidence vector store
  M1       = Research orchestration (via engine_integration)
  M3       = Verification pipeline (invoked through M1)
"""

from .database import (
    InvestigationRecord,
    save_investigation,
    get_investigation,
    get_history,
    delete_investigation,
    init_database,
)
from .semantic_cache import SemanticCache, get_semantic_cache
from .evidence_store import EvidenceStore, get_evidence_store
from .engine_integration import run_investigation
from .verdict_formatter import format_verdict_for_display

__all__ = [
    "InvestigationRecord",
    "save_investigation",
    "get_investigation",
    "get_history",
    "delete_investigation",
    "init_database",
    "SemanticCache",
    "get_semantic_cache",
    "EvidenceStore",
    "get_evidence_store",
    "run_investigation",
    "format_verdict_for_display",
]