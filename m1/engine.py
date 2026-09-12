"""
m1/engine.py — High-Speed Investigation Engine.

Orchestrates: validate → cache → route & plan (combined!) → parallel M2 → M3 → follow-up → finalize.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from pydantic import ValidationError as PydanticValidationError

# M3 imports (from verified project structure)
from verification import (
    QuestionComplexity as M3Complexity,
    VerificationPipeline,
)

from .cache import InvestigationCache
from .config import CONFIG
from .errors import ValidationError as M1ValidationError
from .gateway import LLMGateway
from .models import (
    InvestigationLevel,
    InvestigationRequest,
    InvestigationResult,
    InvestigationState,
    InvestigationStatus,
    QuestionComplexity,
    ResearchPlan,
    RouteMetadata,
    SearchQuery,
)
from .planner import ResearchPlanner
from .router import QuestionRouter
from .state import StateManager

logger = logging.getLogger(__name__)


_COMPLEXITY_MAP = {
    QuestionComplexity.SIMPLE: M3Complexity.SIMPLE,
    QuestionComplexity.MODERATE: M3Complexity.MODERATE,
    QuestionComplexity.COMPLEX: M3Complexity.COMPLEX,
}


def _safe_str(val: Any) -> str:
    """Safely convert any value to string, treating None as empty."""
    if val is None:
        return ""
    return str(val)


class InvestigationEngine:
    def __init__(
        self,
        m2_search_fn: Optional[Callable] = None,
        m3_pipeline: Optional[VerificationPipeline] = None,
        gateway: Optional[LLMGateway] = None,
    ):
        self.gateway = gateway or LLMGateway()

        self.router = QuestionRouter(self.gateway)
        self.planner = ResearchPlanner(self.gateway)

        self.state_mgr = StateManager()
        self.cache = InvestigationCache()

        if m2_search_fn is not None:
            self._m2_search = m2_search_fn
        else:
            from .mock_m2 import make_mock_m2_search_fn
            self._m2_search = make_mock_m2_search_fn()

        self._m3 = m3_pipeline or VerificationPipeline(
            llm=self.gateway if self.gateway.has_providers() else None,
            max_rounds=CONFIG.DEFAULT_MAX_ROUNDS,
        )

    def run(self, request_data: Any) -> InvestigationResult:
        start_time = time.time()

        # ── 1. Validate ────────────────────────
        try:
            if isinstance(request_data, InvestigationRequest):
                request = request_data
            else:
                request = InvestigationRequest.model_validate(request_data)
        except (PydanticValidationError, M1ValidationError) as e:
            return InvestigationResult(
                investigation_id="invalid",
                status=InvestigationStatus.FAILED,
                question=str(request_data),
                trace_summary=[f"validation_failed: {e}"],
                errors=[str(e)],
            )

        # ── 2. Cache check ─────────────────────
        cached = self.cache.get(request.question)
        if cached:
            return cached

        # ── 3. Create state ────────────────────
        state = self.state_mgr.create(
            question=request.question,
            max_rounds=request.max_rounds,
        )

        try:
            return self._run_pipeline(state, request, start_time)
        except Exception as e:
            logger.exception("Fatal M1 error: %s", e)
            state.errors.append(str(e))
            state.log("fatal_error", str(e))
            return self._finalize(state, start_time, verdict=None, route_meta=None)

    # ── Main pipeline ─────────────────────────

    def _run_pipeline(
        self,
        state: InvestigationState,
        request: InvestigationRequest,
        start_time: float,
    ) -> InvestigationResult:
        # ── ROUTE & PLAN (Combined!) ───────────
        self.state_mgr.update_status(state, InvestigationStatus.ROUTING)
        route = self.router.route(request.question)

        state.intent = route.intent
        state.domain = route.domain
        state.complexity = route.complexity
        state.investigation_level = route.investigation_level

        capped_rounds = min(
            request.max_rounds,
            _max_rounds_for(route.complexity),
        )
        state.max_rounds = capped_rounds

        state.log(
            "routed",
            f"intent={route.intent.value} complexity={route.complexity.value} "
            f"level={route.investigation_level.value} rounds<={capped_rounds}",
        )

        route_meta = RouteMetadata(
            intent=route.intent,
            domain=route.domain,
            complexity=route.complexity,
            investigation_level=route.investigation_level,
            needs_research=route.needs_research,
            reason=route.reason,
        )

        if not route.needs_research or route.investigation_level == InvestigationLevel.DIRECT:
            state.log("no_research_needed", "Direct answer regime")
            self.state_mgr.update_status(state, InvestigationStatus.NO_RESEARCH_NEEDED)
            return self._finalize(
                state, start_time, verdict=None, route_meta=route_meta,
                override_status=InvestigationStatus.NO_RESEARCH_NEEDED,
            )

        # ★ SPEED BOOST: If combined routing & planning succeeded, reuse queries!
        if route.needs_research and route.queries:
            plan = ResearchPlan(
                main_question=request.question,
                sub_questions=route.sub_questions,
                queries=route.queries,
                evidence_target=_limits_for(route.complexity)[1],
                max_rounds=capped_rounds
            )
            state.log("planned_combined", f"Combined Route & Plan success: {len(plan.queries)} queries")
        else:
            # Fallback to separate planning if LLM failed combined parsing
            self.state_mgr.update_status(state, InvestigationStatus.PLANNING)
            plan = self.planner.plan(request.question, route.complexity)
            state.log("planned_separate", f"Separate planning fallback: {len(plan.queries)} queries")

        # ── RESEARCH LOOP ─────────────────────
        all_evidence: list = []
        seen_source_ids: set[str] = set()
        m3_result = None
        m3_state = None

        for round_num in range(1, state.max_rounds + 1):
            state.current_round = round_num

            # Total timeout guard
            if time.time() - start_time > CONFIG.TOTAL_TIMEOUT:
                state.log("total_timeout", f"exceeded {CONFIG.TOTAL_TIMEOUT}s")
                break

            # ── M2 SEARCH (CONCURRENT!) ────────
            self.state_mgr.update_status(state, InvestigationStatus.SEARCHING)

            if round_num == 1:
                current_queries = plan.queries[: CONFIG.M2_MAX_QUERIES_PER_ROUND]
            else:
                current_queries = self._build_followup_queries(request.question, m3_result)
                if not current_queries:
                    state.log("no_followup_queries", "No follow-up queries generated; stopping")
                    break

            # Execute searches concurrently
            round_evidence = self._execute_search_round(
                current_queries, round_num, state, seen_source_ids
            )
            all_evidence.extend(round_evidence)
            state.evidence_collected = len(all_evidence)

            state.raw_evidence = list(all_evidence)

            if not all_evidence:
                state.log("no_evidence", "No evidence collected so far")
                if round_num == state.max_rounds:
                    break
                continue

            # ── M3 VERIFY ─────────────────────
            self.state_mgr.update_status(state, InvestigationStatus.VERIFYING)
            m3_complexity = _COMPLEXITY_MAP.get(state.complexity, M3Complexity.MODERATE)

            try:
                if round_num == 1:
                    # ★ Try with sub_questions to skip decomposer LLM call; fallback safely if mock doesn't take it
                    try:
                        m3_result = self._m3.run(
                            question=request.question,
                            evidence=all_evidence,
                            complexity=m3_complexity,
                            sub_questions=plan.sub_questions,
                        )
                    except TypeError:
                        m3_result = self._m3.run(
                            question=request.question,
                            evidence=all_evidence,
                            complexity=m3_complexity,
                        )
                    m3_state = m3_result.state
                else:
                    if m3_state is None:
                        m3_result = self._m3.run(
                            question=request.question,
                            evidence=all_evidence,
                            complexity=m3_complexity,
                        )
                        m3_state = m3_result.state
                    else:
                        m3_result = self._m3.run_continue(
                            m3_state,
                            round_evidence,
                        )
                        m3_state = m3_result.state

                verdict_str = (
                    m3_result.verdict.verdict.value
                    if m3_result and m3_result.verdict else "None"
                )
                state.log(
                    "m3_completed",
                    f"verdict={verdict_str} needs_more={m3_result.needs_more_research}",
                )
            except Exception as e:
                logger.warning("M3 round %d failed: %s", round_num, e)
                state.errors.append(f"M3 round {round_num}: {e}")
                state.log("m3_error", str(e))
                break

            # ── DECIDE NEXT ───────────────────
            if not m3_result.needs_more_research:
                state.log("sufficient", "M3 says evidence sufficient")
                break

            if m3_result.max_rounds_reached:
                state.log("max_rounds", "M3 max rounds reached")
                break

            self.state_mgr.update_status(state, InvestigationStatus.NEEDS_MORE_RESEARCH)
            state.log("followup_needed", f"focus={m3_result.research_focus}")

        # ── FINALIZE ──────────────────────────
        verdict = m3_result.verdict if m3_result else None
        return self._finalize(state, start_time, verdict=verdict, route_meta=route_meta)

    # ── Helpers (CONCURRENT!) ─────────────────

    def _execute_search_round(
        self,
        queries: list[SearchQuery],
        round_num: int,
        state: InvestigationState,
        seen_source_ids: set[str],
    ) -> list:
        """Parallelize all M2 queries to execute concurrently, saving ~2.0s."""
        results: list = []
        lock = threading.Lock()

        def _search_single(query: SearchQuery):
            attempts = 0
            while attempts <= CONFIG.M2_RETRY_ATTEMPTS:
                try:
                    resp = self._m2_search(
                        query=query.query,
                        max_results=query.max_results,
                        round_num=round_num,
                        investigation_id=state.investigation_id,
                        track=query.track.value,
                    )
                    validated = _validate_m2_response(resp)
                    with lock:
                        state.completed_queries.append(query.query)
                        state.completed_tracks.append(query.track.value)
                        for ev in validated:
                            sid = getattr(ev, "source_id", None) or id(ev)
                            if sid not in seen_source_ids:
                                seen_source_ids.add(sid)
                                results.append(ev)
                    break  # success
                except Exception as e:
                    attempts += 1
                    if attempts > CONFIG.M2_RETRY_ATTEMPTS:
                        logger.warning("M2 query failed: %s — %s", query.query[:30], e)
                        break
                    time.sleep(CONFIG.M2_RETRY_DELAY)

        # ★ Run up to 5 parallel M2 queries
        with ThreadPoolExecutor(max_workers=min(5, len(queries))) as executor:
            executor.map(_search_single, queries)

        return results

    def _build_followup_queries(
        self, question: str, m3_result: Any
    ) -> list[SearchQuery]:
        if m3_result is None or not m3_result.needs_more_research:
            return []

        research_focus = getattr(m3_result, "research_focus", "") or ""
        gaps = getattr(m3_result, "research_gaps", []) or []
        gaps_texts = _extract_gap_texts(gaps)

        return self.planner.generate_followup_queries(
            question=question,
            research_focus=research_focus,
            research_gaps_texts=gaps_texts,
        )

    def _finalize(
        self,
        state: InvestigationState,
        start_time: float,
        verdict: Any,
        route_meta: Optional[RouteMetadata],
        override_status: Optional[InvestigationStatus] = None,
    ) -> InvestigationResult:
        elapsed = time.time() - start_time

        if override_status is not None:
            status = override_status
        elif verdict is not None:
            status = InvestigationStatus.COMPLETED
        elif state.errors:
            status = InvestigationStatus.FAILED
        else:
            status = InvestigationStatus.INCONCLUSIVE

        self.state_mgr.update_status(state, status)

        trace_summary = [
            f"{e.action}: {e.details}" if e.details else e.action
            for e in state.trace
        ]

        evidence_summary = []
        raw_evidence_list = getattr(state, "raw_evidence", []) or []

        for ev in raw_evidence_list:
            try:
                summary = {
                    "source_id": _safe_str(getattr(ev, "source_id", "")),
                    "title": _safe_str(getattr(ev, "title", "")),
                    "relevant_passage": _safe_str(getattr(ev, "relevant_passage", "")),
                    "url": _safe_str(getattr(ev, "url", "")),
                    "study_design": _safe_str(getattr(ev, "study_design", "")),
                }
                year = getattr(ev, "year", None)
                if year is not None:
                    summary["year"] = int(year)
                peer_reviewed = getattr(ev, "peer_reviewed", None)
                if peer_reviewed is not None:
                    summary["peer_reviewed"] = bool(peer_reviewed)
                evidence_summary.append(summary)
            except Exception as e:
                logger.debug("Skipping malformed evidence item: %s", e)
                continue

        actual_evidence_count = max(
            state.evidence_collected,
            len(evidence_summary),
        )

        result = InvestigationResult(
            investigation_id=state.investigation_id,
            status=status,
            question=state.question,
            verdict=verdict,
            rounds_used=state.current_round,
            evidence_count=actual_evidence_count,
            trace_summary=trace_summary,
            time_taken=f"{elapsed:.1f}s",
            route_metadata=route_meta,
            errors=list(state.errors),
            from_cache=False,
            raw_evidence_summary=evidence_summary,
        )

        # Cache only completed results
        if status == InvestigationStatus.COMPLETED:
            self.cache.put(state.question, result, state.domain)

        return result


# ── Module helpers ────────────────────────────

def _max_rounds_for(complexity: QuestionComplexity) -> int:
    if complexity == QuestionComplexity.SIMPLE:
        return CONFIG.SIMPLE_MAX_ROUNDS
    if complexity == QuestionComplexity.MODERATE:
        return CONFIG.MODERATE_MAX_ROUNDS
    return CONFIG.COMPLEX_MAX_ROUNDS


def _limits_for(complexity: QuestionComplexity) -> tuple[int, int]:
    if complexity == QuestionComplexity.SIMPLE:
        return 1, 3
    if complexity == QuestionComplexity.MODERATE:
        return 2, 8
    return 3, 15  # COMPLEX


def _validate_m2_response(resp: Any) -> list:
    """Robustly validate whatever M2 returned into a list of evidence records."""
    if resp is None:
        return []
    if not isinstance(resp, (list, tuple)):
        return []
    valid = []
    for item in resp:
        # Must have at least an identifier and some text
        title = getattr(item, "title", None) or getattr(item, "source_id", None)
        text = (
            getattr(item, "relevant_passage", None)
            or getattr(item, "abstract", None)
            or getattr(item, "title", None)
        )
        if title and text:
            valid.append(item)
    return valid


def _extract_gap_texts(gaps: Any) -> list[str]:
    """Safely extract text descriptions from research_gaps (could be strings or objects)."""
    out: list[str] = []
    if not gaps:
        return out
    for g in gaps:
        if isinstance(g, str):
            out.append(g)
        else:
            # Try common attribute names
            text = (
                getattr(g, "topic", None)
                or getattr(g, "reason", None)
                or getattr(g, "suggested_query", None)
                or str(g)
            )
            if text:
                out.append(str(text))
    return out