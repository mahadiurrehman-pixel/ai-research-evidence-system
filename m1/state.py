"""
m1/state.py — Investigation state manager.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .models import InvestigationState, InvestigationStatus

logger = logging.getLogger(__name__)


class StateManager:
    def __init__(self):
        self._states: dict[str, InvestigationState] = {}

    def create(self, question: str, max_rounds: int) -> InvestigationState:
        state = InvestigationState(question=question, max_rounds=max_rounds)
        self._states[state.investigation_id] = state
        state.log("investigation_created", f"max_rounds={max_rounds}")
        return state

    def get(self, inv_id: str) -> Optional[InvestigationState]:
        return self._states.get(inv_id)

    def update_status(self, state: InvestigationState, status: InvestigationStatus) -> None:
        old = state.status
        state.status = status
        state.updated_at = datetime.now()
        state.log("status_change", f"{old.value} → {status.value}")
        logger.info(
            "[%s] Status: %s → %s",
            state.investigation_id[:12], old.value, status.value,
        )