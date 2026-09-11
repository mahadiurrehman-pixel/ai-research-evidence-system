"""
pipeline.py — Wires the verification steps together.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .contradiction import ContradictionDetector
from .decomposer import QuestionDecomposer
from .errors import PipelineStateError
from .evidence_analyzer import EvidenceAnalyzer
from .judge import ResearchJudge
from .llm_client import LLMClient, default_llm_client
from .models import (
    AnalyzedEvidence,
    ContradictionResult,
    DecompositionResult,
    FinalVerdict,
    QuestionComplexity,
    RawEvidence,
    ResearchGap,
    VerificationResult,
)
from .verifier import EvidenceVerifier

logger = logging.getLogger(__name__)


@dataclass
class PipelineState:
    original_question: str = ""
    decomposition: Optional[DecompositionResult] = None
    raw_evidence: list[RawEvidence] = field(default_factory=list)
    analyzed_evidence: list[AnalyzedEvidence] = field(default_factory=list)
    contradictions: Optional[ContradictionResult] = None
    verification: Optional[VerificationResult] = None
    final_verdict: Optional[FinalVerdict] = None
    current_round: int = 1
    status: str = "idle"
    complexity_override: Optional[QuestionComplexity] = None


@dataclass
class PipelineResult:
    verdict: Optional[FinalVerdict]
    needs_more_research: bool
    research_focus: str
    research_gaps: list[ResearchGap]
    state: PipelineState
    max_rounds_reached: bool


class VerificationPipeline:
    def __init__(
        self,
        llm: LLMClient | None = None,
        max_rounds: int = 3,
    ):
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.llm = llm or default_llm_client()
        self.max_rounds = max_rounds

        self.decomposer = QuestionDecomposer(self.llm)
        self.analyzer = EvidenceAnalyzer(self.llm)
        self.detector = ContradictionDetector(self.llm)
        self.verifier = EvidenceVerifier(self.llm)
        self.judge = ResearchJudge(self.llm)

    def run(
        self,
        question: str,
        evidence: list[RawEvidence],
        complexity: QuestionComplexity | None = None,
    ) -> PipelineResult:
        state = PipelineState(
            original_question=question,
            raw_evidence=list(evidence),
            current_round=1,
            complexity_override=complexity,
        )
        state.status = "decomposing"
        state.decomposition = self.decomposer.decompose(question)
        if complexity is not None:
            state.decomposition.complexity = complexity
        return self._analyze_verify_maybe_judge(state, evidence)

    def run_continue(
        self,
        state: PipelineState,
        new_evidence: list[RawEvidence],
        complexity: QuestionComplexity | None = None,
    ) -> PipelineResult:
        if state.decomposition is None:
            raise PipelineStateError(
                "run_continue called before run(); no decomposition in state."
            )
        if complexity is not None:
            state.complexity_override = complexity
            state.decomposition.complexity = complexity

        if state.current_round >= self.max_rounds:
            logger.info(
                "run_continue blocked: already at max_rounds=%s",
                self.max_rounds,
            )
            return self._finalize(state, force_judge=True)

        state.current_round += 1
        state.raw_evidence.extend(new_evidence)
        return self._analyze_verify_maybe_judge(state, new_evidence)

    def _analyze_verify_maybe_judge(
        self,
        state: PipelineState,
        evidence_to_analyze: list[RawEvidence],
    ) -> PipelineResult:
        assert state.decomposition is not None

        state.status = "analyzing"
        new_analyzed = self.analyzer.analyze(
            sub_questions=state.decomposition.sub_questions,
            evidence=evidence_to_analyze,
            original_question=state.original_question,
        )
        state.analyzed_evidence.extend(new_analyzed)

        state.status = "checking"
        state.contradictions = self.detector.detect(
            state.analyzed_evidence,
            raw_evidence=state.raw_evidence,
        )

        effective_complexity = (
            state.complexity_override
            if state.complexity_override is not None
            else state.decomposition.complexity
        )
        state.verification = self.verifier.verify(
            analyzed_evidence=state.analyzed_evidence,
            contradictions=state.contradictions,
            original_question=state.original_question,
            complexity=effective_complexity,
            max_research_rounds=self.max_rounds,
            current_round=state.current_round,
        )

        return self._finalize(state)

    def _finalize(
        self,
        state: PipelineState,
        force_judge: bool = False,
    ) -> PipelineResult:
        assert state.verification is not None
        assert state.decomposition is not None
        assert state.contradictions is not None

        max_reached = state.current_round >= self.max_rounds
        sufficient = state.verification.is_sufficient

        if sufficient or max_reached or force_judge:
            state.status = "judging"
            # ★ Pass raw_evidence to judge for accurate group counting
            state.final_verdict = self.judge.judge(
                decomposition=state.decomposition,
                analyzed_evidence=state.analyzed_evidence,
                contradictions=state.contradictions,
                verification=state.verification,
                raw_evidence=state.raw_evidence,
            )
            state.status = "done"
            return PipelineResult(
                verdict=state.final_verdict,
                needs_more_research=False,
                research_focus="",
                research_gaps=[],
                state=state,
                max_rounds_reached=max_reached,
            )

        state.status = "needs_more"
        return PipelineResult(
            verdict=None,
            needs_more_research=True,
            research_focus=state.verification.research_focus,
            research_gaps=state.verification.research_gaps,
            state=state,
            max_rounds_reached=False,
        )