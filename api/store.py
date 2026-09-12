"""
api/store.py — In-memory investigation store.

Stores investigation state and results. In production, replace with
SQLite/PostgreSQL via M4's database module.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

from m1.models import InvestigationResult


class InvestigationStore:
    """Thread-safe in-memory store for investigations."""

    def __init__(self):
        self._store: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, investigation_id: str, question: str) -> None:
        with self._lock:
            self._store[investigation_id] = {
                "investigation_id": investigation_id,
                "question": question,
                "status": "SEARCHING",
                "result": None,
                "created_at": datetime.now().isoformat(),
            }

    def update_status(self, investigation_id: str, status: str) -> None:
        with self._lock:
            if investigation_id in self._store:
                self._store[investigation_id]["status"] = status

    def complete(self, investigation_id: str, result: InvestigationResult) -> None:
        with self._lock:
            if investigation_id in self._store:
                self._store[investigation_id]["status"] = "COMPLETED"
                self._store[investigation_id]["result"] = result

    def fail(self, investigation_id: str, error: str) -> None:
        with self._lock:
            if investigation_id in self._store:
                self._store[investigation_id]["status"] = "FAILED"
                self._store[investigation_id]["error"] = error

    def get(self, investigation_id: str) -> Optional[dict]:
        with self._lock:
            return self._store.get(investigation_id)

    def get_history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            items = sorted(
                self._store.values(),
                key=lambda x: x["created_at"],
                reverse=True,
            )
            return items[:limit]


# Global singleton
store = InvestigationStore()