"""
m4/database.py — SQLite (source of truth) with 3-layer delete.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .config import SQLITE_DB_PATH

logger = logging.getLogger(__name__)

_db_lock = threading.Lock()


@dataclass
class InvestigationRecord:
    investigation_id: str
    question: str
    verdict_type: str = "UNKNOWN"
    confidence: str = "UNKNOWN"
    status: str = "COMPLETED"
    summary: str = ""
    verdict_json: str = ""
    rounds_used: int = 0
    evidence_count: int = 0
    time_taken: str = ""
    created_at: str = ""

    @classmethod
    def new(cls, question: str) -> "InvestigationRecord":
        return cls(
            investigation_id=f"inv_{uuid.uuid4().hex[:12]}",
            question=question,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )


def _get_connection() -> sqlite3.Connection:
    from . import config
    db_path = getattr(config, "SQLITE_DB_PATH", SQLITE_DB_PATH)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY,
    question         TEXT NOT NULL,
    verdict_type     TEXT DEFAULT 'UNKNOWN',
    confidence       TEXT DEFAULT 'UNKNOWN',
    status           TEXT DEFAULT 'COMPLETED',
    summary          TEXT DEFAULT '',
    verdict_json     TEXT DEFAULT '',
    rounds_used      INTEGER DEFAULT 0,
    evidence_count   INTEGER DEFAULT 0,
    time_taken       TEXT DEFAULT '',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_created ON investigations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_status  ON investigations(status);
"""


def init_database() -> None:
    with _db_lock:
        conn = _get_connection()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def save_investigation(record: InvestigationRecord) -> str:
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO investigations (
                    investigation_id, question, verdict_type, confidence,
                    status, summary, verdict_json, rounds_used,
                    evidence_count, time_taken, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.investigation_id, record.question,
                    record.verdict_type, record.confidence,
                    record.status, record.summary, record.verdict_json,
                    record.rounds_used, record.evidence_count,
                    record.time_taken, record.created_at,
                ),
            )
            conn.commit()
            return record.investigation_id
        finally:
            conn.close()


def get_investigation(investigation_id: str) -> Optional[InvestigationRecord]:
    with _db_lock:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            return _row_to_record(row) if row else None
        finally:
            conn.close()


def get_history(limit: int = 100) -> list[InvestigationRecord]:
    with _db_lock:
        conn = _get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM investigations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [_row_to_record(r) for r in rows]
        finally:
            conn.close()


def delete_investigation(investigation_id: str) -> bool:
    """Delete investigation from SQLite + cache + evidence store (all 3 layers)."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            )
            conn.commit()
            deleted = cursor.rowcount > 0
        finally:
            conn.close()

    if deleted:
        try:
            from .semantic_cache import get_semantic_cache
            get_semantic_cache().delete_by_investigation_id(investigation_id)
        except Exception as e:
            logger.warning("Cache cleanup failed: %s", e)

        try:
            from .evidence_store import get_evidence_store
            get_evidence_store().delete_by_investigation_id(investigation_id)
        except Exception as e:
            logger.warning("Evidence cleanup failed: %s", e)

    return deleted


def _row_to_record(row) -> InvestigationRecord:
    return InvestigationRecord(
        investigation_id=row["investigation_id"],
        question=row["question"],
        verdict_type=row["verdict_type"],
        confidence=row["confidence"],
        status=row["status"],
        summary=row["summary"],
        verdict_json=row["verdict_json"],
        rounds_used=row["rounds_used"],
        evidence_count=row["evidence_count"],
        time_taken=row["time_taken"],
        created_at=row["created_at"],
    )