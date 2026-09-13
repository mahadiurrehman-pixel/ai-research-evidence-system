"""
api/main.py — FastAPI Backend for Reality Checker.

Connects M1 InvestigationEngine to the Next.js frontend via REST API.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from m1.engine import InvestigationEngine
from m1.models import InvestigationRequest, InvestigationResult
from .store import store

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-5s | %(message)s",
)

app = FastAPI(
    title="Reality Checker API",
    description="AI Research Evidence Verification System",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ai-research-evidence-system.vercel.app",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_engine: Optional[InvestigationEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> InvestigationEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                logger.info("Initializing M1 InvestigationEngine...")
                _engine = InvestigationEngine()
                logger.info("M1 InvestigationEngine ready.")
    return _engine


class ResearchRequest(BaseModel):
    question: str
    max_rounds: int = 3
    mode: str = "auto"


class ResearchResponse(BaseModel):
    investigation_id: str
    status: str
    question: str
    message: str


class InvestigationDetail(BaseModel):
    investigation_id: str
    question: str
    status: str
    verdict: Optional[dict] = None
    rounds_used: int = 0
    evidence_count: int = 0
    time_taken: str = ""
    created_at: str = ""
    route_metadata: Optional[dict] = None
    trace_summary: list[str] = []
    error: Optional[str] = None


def run_investigation_task(investigation_id: str, question: str, max_rounds: int) -> None:
    try:
        logger.info("[BG] Starting investigation %s: '%s'", investigation_id, question[:60])
        engine = get_engine()
        request = InvestigationRequest(question=question, max_rounds=max_rounds)
        result: InvestigationResult = engine.run(request)
        store.complete(investigation_id, result)
        logger.info("[BG] Investigation %s completed: %s (%s)", investigation_id, result.status.value, result.time_taken)
    except Exception as e:
        logger.error("[BG] Investigation %s failed: %s\n%s", investigation_id, e, traceback.format_exc())
        store.fail(investigation_id, str(e))


@app.get("/api/health")
async def health_check():
    return {"status": "online", "service": "Reality Checker API", "version": "1.0.0"}


@app.post("/api/research", response_model=ResearchResponse)
async def start_research(request: ResearchRequest, background_tasks: BackgroundTasks):
    if not request.question or len(request.question.strip()) < 5:
        raise HTTPException(status_code=400, detail="Question must be at least 5 characters.")

    if request.max_rounds < 1 or request.max_rounds > 3:
        raise HTTPException(status_code=400, detail="max_rounds must be between 1 and 3.")

    investigation_id = f"inv_{uuid.uuid4().hex[:12]}"
    store.create(investigation_id, request.question)

    background_tasks.add_task(
        run_investigation_task,
        investigation_id=investigation_id,
        question=request.question.strip(),
        max_rounds=request.max_rounds,
    )

    return ResearchResponse(
        investigation_id=investigation_id,
        status="SEARCHING",
        question=request.question,
        message="Investigation started. Poll /api/research/{id} for results.",
    )


# ★ CRITICAL FIX: Defined BEFORE /api/research/{investigation_id} so "history" isn't captured as an ID!
@app.get("/api/research/history")
async def get_history(limit: int = 50):
    records = store.get_history(limit=limit)
    results = []
    for record in records:
        result: Optional[InvestigationResult] = record.get("result")
        item = {
            "investigation_id": record["investigation_id"],
            "question": record["question"],
            "status": record["status"],
            "created_at": record["created_at"],
            "rounds_used": 0,
            "evidence_count": 0,
            "time_taken": "",
            "verdict": None,
        }
        if result:
            item["status"] = result.status.value
            item["rounds_used"] = result.rounds_used
            item["evidence_count"] = result.evidence_count
            item["time_taken"] = result.time_taken
            if result.verdict:
                item["verdict"] = result.verdict.model_dump()
        results.append(item)
    return results


@app.get("/api/research/{investigation_id}", response_model=InvestigationDetail)
async def get_investigation(investigation_id: str):
    record = store.get(investigation_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"Investigation '{investigation_id}' not found.")

    result: Optional[InvestigationResult] = record.get("result")

    detail = InvestigationDetail(
        investigation_id=record["investigation_id"],
        question=record["question"],
        status=record["status"],
        created_at=record["created_at"],
    )

    if result is not None:
        detail.status = result.status.value
        detail.rounds_used = result.rounds_used
        detail.evidence_count = result.evidence_count
        detail.time_taken = result.time_taken
        detail.trace_summary = result.trace_summary
        detail.error = result.errors[-1] if result.errors else None

        if result.route_metadata:
            detail.route_metadata = result.route_metadata.model_dump()

        if result.verdict:
            detail.verdict = result.verdict.model_dump()

    return detail


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)