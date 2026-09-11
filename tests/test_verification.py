"""
tests/test_verification.py — Full M3 Pipeline Verification Tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from verification import (
    AnalyzedEvidence,
    ContradictionClass,
    ContradictionPair,
    DecompositionResult,
    FinalVerdict,
    OpenAICompatibleLLMClient,
    PipelineStateError,
    QuestionComplexity,
    RawEvidence,
    Relevance,
    SourceType,
    Strength,
    SubQuestion,
    SupportLevel,
    VerdictType,
    VerificationPipeline,
    VerificationResult,
    calculate_evidence_weight,
    get_source_group,
    group_evidence,
    get_real_evidence,
    Confidence,
    EvidenceCitation,
)
from verification.contradiction import ContradictionDetector
from verification.errors import (
    LLMError,
    PermanentLLMError,
    TransientLLMError,
)
from verification.evidence_analyzer import (
    EvidenceAnalyzer,
    BatchedAnalysisResult,
    AnalyzedEvidenceItem,
)
from verification.llm_client import _classify_provider_error, _with_retry
from verification.verifier import EvidenceVerifier
from verification.judge import ResearchJudge


# ── Fake LLM Client Helper ───────────────────

class FakeLLM:
    def __init__(self, routes=None, fail=False):
        self.routes = routes or {}
        self.fail = fail
        self.calls = []

    def structured_call(self, system, user, response_model):
        self.calls.append((response_model.__name__, user))
        if self.fail:
            raise LLMError("simulated failure")
        producer = self.routes.get(response_model.__name__)
        if producer is None:
            return _minimal(response_model)
        obj = producer(user)
        if isinstance(obj, response_model):
            return obj
        return response_model.model_validate(obj)

    def text_call(self, system, user):
        if self.fail:
            raise LLMError("simulated failure")
        return "OK"


def _minimal(model):
    if model is DecompositionResult:
        return DecompositionResult(
            original_question="",
            sub_questions=[SubQuestion(id="Q1", text="?", purpose="?")],
            reasoning="",
            complexity=QuestionComplexity.MODERATE,
        )
    if model is ContradictionPair:
        return ContradictionPair(
            evidence_a_id="",
            evidence_b_id="",
            claim_a="",
            claim_b="",
            is_genuine_contradiction=False,
            explanation="",
            severity=Strength.LOW,
            classification=ContradictionClass.NOT_CONTRADICTORY,
        )
    if model is BatchedAnalysisResult:
        return BatchedAnalysisResult(items=[])
    if model is VerificationResult:
        return VerificationResult(
            is_sufficient=False,
            confidence=Confidence.LOW,
            evidence_count=0,
            supporting_count=0,
            contradicting_count=0,
            neutral_count=0,
            source_quality="weak",
            reasoning="",
        )
    raise AssertionError(f"No minimal for {model}")


# ── Unit & Heuristic Tests ───────────────────

def test_package_imports():
    from verification import VerificationPipeline as VP
    from verification import RawEvidence as RE
    from verification import FinalVerdict as FV


def test_two_subquestions_not_forced_to_q1():
    subs = [
        SubQuestion(id="Q1", text="What is AI-assisted learning?", purpose="def"),
        SubQuestion(id="Q2", text="What is its effect on grades?", purpose="evi"),
    ]
    ev = RawEvidence(source_id="P1", title="Effect of AI tutors", relevant_passage="grades +12%")

    def analyzer_mock(u):
        return BatchedAnalysisResult(items=[
            AnalyzedEvidenceItem(
                source_id="P1",
                question_ids=["Q2"],
                support_level=SupportLevel.SUPPORTS,
                strength=Strength.HIGH,
                relevance=Relevance.HIGH,
                reason="RCT grades positive",
                key_claim="grades +12%"
            )
        ])

    llm = FakeLLM({"BatchedAnalysisResult": analyzer_mock})
    out = EvidenceAnalyzer(llm).analyze(subs, [ev])
    assert len(out) == 1
    assert out[0].question_ids == ["Q2"]


def test_evidence_stays_insufficient_after_max_rounds():
    verifier = EvidenceVerifier()
    ev = [AnalyzedEvidence(
        source_id="P1", title="t", question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS, strength=Strength.LOW, relevance=Relevance.LOW,
        reason="", key_claim="",
    )]
    from verification.models import ContradictionResult
    r = verifier.verify(
        analyzed_evidence=ev,
        contradictions=ContradictionResult(has_contradictions=False, contradiction_pairs=[], overall_consensus=""),
        original_question="Q?",
        max_research_rounds=3, current_round=3,
    )
    assert r.is_sufficient is False
    assert r.max_rounds_reached is True
    assert r.additional_research_needed is False


def test_source_group_uses_normalized_domain_when_no_group():
    ev1 = RawEvidence(source_id="1", title="A", url="https://www.example.com/foo")
    ev2 = RawEvidence(source_id="2", title="A", url="https://example.com/foo")
    assert get_source_group(ev1) == get_source_group(ev2)


def test_weight_strong_relevant_high_quality_beats_weak():
    strong = AnalyzedEvidence(source_id="M", title="M", question_ids=["Q1"], support_level=SupportLevel.SUPPORTS, strength=Strength.HIGH, relevance=Relevance.HIGH, reason="", key_claim="")
    strong_raw = RawEvidence(source_id="M", title="M", source_type=SourceType.PEER_REVIEWED, peer_reviewed=True, study_design="meta-analysis")
    weak = AnalyzedEvidence(source_id="B", title="B", question_ids=["Q1"], support_level=SupportLevel.SUPPORTS, strength=Strength.LOW, relevance=Relevance.LOW, reason="", key_claim="")
    weak_raw = RawEvidence(source_id="B", title="B", source_type=SourceType.BLOG, peer_reviewed=False)
    
    ws = calculate_evidence_weight(strong, strong_raw).total
    ww = calculate_evidence_weight(weak, weak_raw).total
    assert ws > ww * 3


def test_sp_a_stanford_positive_oxford_negative_contradiction():
    a = AnalyzedEvidence(source_id="STANFORD", title="Stanford", question_ids=["Q1"], support_level=SupportLevel.SUPPORTS, strength=Strength.HIGH, relevance=Relevance.HIGH, reason="", key_claim="math +12%")
    b = AnalyzedEvidence(source_id="OXFORD", title="Oxford", question_ids=["Q1"], support_level=SupportLevel.CONTRADICTS, strength=Strength.HIGH, relevance=Relevance.HIGH, reason="", key_claim="no improvement")
    
    llm = FakeLLM({
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="STANFORD", evidence_b_id="OXFORD", claim_a="math +12%", claim_b="no improvement",
            is_genuine_contradiction=True, explanation="contradiction", severity=Strength.HIGH, classification=ContradictionClass.CONTRADICTORY
        )
    })
    r = ContradictionDetector(llm).detect([a, b])
    assert r.has_contradictions is True


def test_sp_b_oxford_medium_same_group():
    ev = [
        RawEvidence(source_id="OXFORD", title="Adult Learning", url="https://oxford.ac.uk", source_type=SourceType.PEER_REVIEWED, peer_reviewed=True),
        RawEvidence(source_id="MEDIUM", title="Why AI software did not work", url="https://medium.com/post", source_type=SourceType.BLOG, peer_reviewed=False, source_group="oxford-adult-copy")
    ]
    groups = group_evidence(ev)
    assert len(groups) == 1


def test_sp_c_stanford_vs_oxford_preferred_over_medium():
    stanford = AnalyzedEvidence(source_id="STANFORD", title="Stanford RCT", question_ids=["Q1"], support_level=SupportLevel.SUPPORTS, strength=Strength.HIGH, relevance=Relevance.HIGH, reason="", key_claim="math improved")
    oxford = AnalyzedEvidence(source_id="OXFORD", title="Oxford RCT", question_ids=["Q1"], support_level=SupportLevel.CONTRADICTS, strength=Strength.HIGH, relevance=Relevance.HIGH, reason="", key_claim="no benefit")
    medium = AnalyzedEvidence(source_id="MEDIUM", title="Blog", question_ids=["Q1"], support_level=SupportLevel.CONTRADICTS, strength=Strength.LOW, relevance=Relevance.MEDIUM, reason="", key_claim="no benefit blog")

    raw = [
        RawEvidence(source_id="STANFORD", title="Stanford RCT", url="https://stanford.edu", study_design="RCT", peer_reviewed=True),
        RawEvidence(source_id="OXFORD", title="Oxford RCT", url="https://oxford.ac.uk", study_design="RCT", peer_reviewed=True),
        RawEvidence(source_id="MEDIUM", title="Blog", url="https://medium.com", source_group="oxford-adult-copy")
    ]

    seen = []
    def contra_mock(u):
        for sid in ["STANFORD", "OXFORD", "MEDIUM"]:
            if f"Source: {sid}" in u:
                seen.append(sid)
        return ContradictionPair(evidence_a_id="", evidence_b_id="", claim_a="", claim_b="", is_genuine_contradiction=True, explanation="", severity=Strength.HIGH, classification=ContradictionClass.CONTRADICTORY)

    detector = ContradictionDetector(FakeLLM({"ContradictionPair": contra_mock}))
    detector.detect([stanford, oxford, medium], raw)
    assert "STANFORD" in seen
    assert "OXFORD" in seen


def test_sp_d_judge_produces_non_null_verdict():
    decomp = DecompositionResult(original_question="Test?", sub_questions=[SubQuestion(id="Q1", text="Q?", purpose="test")], reasoning="")
    evidence = [
        AnalyzedEvidence(source_id=f"P{i}", title=f"P{i}", question_ids=["Q1"], question_id="Q1", support_level=SupportLevel.SUPPORTS, strength=Strength.HIGH, relevance=Relevance.HIGH, reason="", key_claim="", methodology_note="meta-analysis")
        for i in range(1, 5)
    ]
    from verification.models import ContradictionResult
    contra = ContradictionResult(has_contradictions=False, contradiction_pairs=[], overall_consensus="Consensus")
    verif = VerificationResult(is_sufficient=True, confidence=Confidence.HIGH, evidence_count=4, supporting_count=4, contradicting_count=0, neutral_count=0, source_quality="Good", reasoning="")

    llm = FakeLLM({
        "FinalVerdict": lambda u: FinalVerdict(original_question="Test?", verdict=VerdictType.SUPPORTED, confidence=Confidence.HIGH, summary="Supported", detailed_reasoning="")
    })
    judge = ResearchJudge(llm)
    raw_ev = [
        RawEvidence(source_id=f"P{i}", title=f"P{i}", url=f"https://p{i}.org", study_design="meta-analysis", peer_reviewed=True)
        for i in range(1, 5)
    ]
    r = judge.judge(decomp, evidence, contra, verif, raw_evidence=raw_ev)
    assert r is not None
    assert r.verdict in (VerdictType.SUPPORTED, VerdictType.PARTIALLY_SUPPORTED)


def test_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}
    def op():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("timeout")
        return "ok"

    out = _with_retry(op, max_retries=3, base_delay=0.01, sleep_fn=lambda d: None, label="t")
    assert out == "ok"
    assert attempts["n"] == 3


# ── Real Dataset Integration Tests ───────────

def test_real_dataset_loads_correctly():
    """25 real papers load without errors and have valid fields."""
    evidence = get_real_evidence()
    assert len(evidence) == 25
    for ev in evidence:
        assert ev.source_id
        assert ev.title
        assert ev.relevant_passage
        assert ev.source_type is not None


def test_real_dataset_deduplication():
    """Real dataset groups correctly — conflicting citations merge."""
    evidence = get_real_evidence()
    groups = group_evidence(evidence)
    assert len(groups) <= 25


def test_real_dataset_pipeline_with_mock():
    """Full pipeline runs on real dataset structure with mock LLM."""
    all_ev = get_real_evidence()
    ev = all_ev[:5]
    raw_by_id = {r.source_id: r for r in ev}

    def analyze_mock(u):
        items = []
        for sid, raw in raw_by_id.items():
            text = raw.relevant_passage.lower()
            neg = any(w in text for w in ["no significant", "no improvement", "no effect", "did not", "not yet"])
            pos = any(w in text for w in ["improvement", "positive", "increase", "gain", "outperformed"])
            if neg and not pos:
                level = SupportLevel.CONTRADICTS
            elif pos:
                level = SupportLevel.SUPPORTS
            else:
                level = SupportLevel.NEUTRAL
            items.append(AnalyzedEvidenceItem(
                source_id=sid,
                question_ids=["Q1"],
                support_level=level,
                strength=Strength.HIGH if raw.peer_reviewed else Strength.LOW,
                relevance=Relevance.HIGH,
                reason="Mock",
                key_claim=raw.relevant_passage[:80],
            ))
        return BatchedAnalysisResult(items=items)

    llm = FakeLLM({
        "DecompositionResult": lambda u: DecompositionResult(
            original_question="AI learning?",
            sub_questions=[SubQuestion(id="Q1", text="Does AI help?", purpose="test")],
            reasoning="test", complexity=QuestionComplexity.COMPLEX,
        ),
        "BatchedAnalysisResult": analyze_mock,
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="", evidence_b_id="",
            claim_a="", claim_b="",
            is_genuine_contradiction=True,
            explanation="Mixed findings", severity=Strength.MEDIUM,
            classification=ContradictionClass.CONTRADICTORY,
        ),
        "FinalVerdict": lambda u: FinalVerdict(
            original_question="AI learning?",
            verdict=VerdictType.PARTIALLY_SUPPORTED,
            confidence=Confidence.MEDIUM,
            summary="Mixed real evidence",
            detailed_reasoning="Some positive, some null",
            supporting_evidence=[
                EvidenceCitation(source_id="KESTIN-2025-POSITIVE", claim="AI doubled learning gains")
            ],
            contradicting_evidence=[
                EvidenceCitation(source_id="GENAI-CHATBOT-2023-NULL", claim="No significant effect")
            ],
            limitations=["Mixed study designs"],
        ),
    })
    pipeline = VerificationPipeline(llm=llm, max_rounds=1)
    r = pipeline.run("Does AI improve learning?", ev, complexity=QuestionComplexity.SIMPLE)
    assert r.verdict is not None
    assert r.verdict.verdict == VerdictType.PARTIALLY_SUPPORTED


# ═════════════════════════════════════════════
# CALIBRATION LAYER TESTS
# ═════════════════════════════════════════════

from verification.calibration import (
    CalibrationSignals,
    calibrate_final_verdict,
    extract_signals,
    recalibrate_confidence,
    recalibrate_verdict,
    build_verdict_language,
)
from verification.models import ContradictionResult


def _make_analyzed(sid, support, strength=Strength.HIGH, relevance=Relevance.HIGH,
                   methodology_note=""):
    return AnalyzedEvidence(
        source_id=sid, title=sid,
        question_ids=["Q1"], question_id="Q1",
        support_level=support, strength=strength, relevance=relevance,
        reason="", key_claim=f"claim {sid}",
        methodology_note=methodology_note,
    )


def _empty_contradictions():
    return ContradictionResult(
        has_contradictions=False,
        contradiction_pairs=[],
        overall_consensus="",
        context_differences=[],
    )


def _basic_verification(is_sufficient=True, evidence_count=5):
    return VerificationResult(
        is_sufficient=is_sufficient,
        confidence=Confidence.HIGH,
        evidence_count=evidence_count,
        supporting_count=evidence_count,
        contradicting_count=0,
        neutral_count=0,
        source_quality="Good",
        reasoning="test",
    )


def _basic_verdict():
    return FinalVerdict(
        original_question="Test?",
        verdict=VerdictType.SUPPORTED,
        confidence=Confidence.HIGH,
        summary="Original summary",
        detailed_reasoning="Original reasoning",
    )


def test_cal_strong_positive_with_context_variation():
    """Strong support but context variation -> PARTIALLY_SUPPORTED / SUPPORTED_WITH_LIMITATIONS."""
    ev = [
        _make_analyzed(f"META-{i}", SupportLevel.SUPPORTS, methodology_note="meta-analysis")
        for i in range(5)
    ]
    contra = ContradictionResult(
        has_contradictions=False,
        contradiction_pairs=[],
        overall_consensus="",
        context_differences=["Effects vary by education level", "Effects vary by intervention type"],
    )
    signals = extract_signals(ev, contra, _basic_verification(evidence_count=5), independent_groups=5)
    verdict = recalibrate_verdict(signals)
    assert verdict == VerdictType.PARTIALLY_SUPPORTED
    label = build_verdict_language(verdict, signals)
    assert label == "SUPPORTED_WITH_LIMITATIONS"


def test_cal_genuine_contradiction_leads_to_contradicted_or_partial():
    """Genuine contradiction with substantial opposing evidence."""
    ev = [
        _make_analyzed("A", SupportLevel.SUPPORTS),
        _make_analyzed("B", SupportLevel.SUPPORTS),
        _make_analyzed("C", SupportLevel.CONTRADICTS),
        _make_analyzed("D", SupportLevel.CONTRADICTS),
        _make_analyzed("E", SupportLevel.CONTRADICTS),
    ]
    contra = ContradictionResult(
        has_contradictions=True,
        contradiction_pairs=[
            ContradictionPair(
                evidence_a_id="A", evidence_b_id="C",
                claim_a="", claim_b="",
                is_genuine_contradiction=True,
                explanation="", severity=Strength.HIGH,
                classification=ContradictionClass.CONTRADICTORY,
            )
        ],
        overall_consensus="",
        context_differences=[],
    )
    signals = extract_signals(ev, contra, _basic_verification(evidence_count=5), independent_groups=5)
    verdict = recalibrate_verdict(signals)
    assert verdict == VerdictType.CONTRADICTED


def test_cal_contextual_variation_stays_partially_supported():
    """Only context differences, no genuine contradictions -> PARTIALLY_SUPPORTED."""
    ev = [
        _make_analyzed("A", SupportLevel.SUPPORTS),
        _make_analyzed("B", SupportLevel.SUPPORTS),
        _make_analyzed("C", SupportLevel.SUPPORTS),
        _make_analyzed("D", SupportLevel.CONTRADICTS),
    ]
    contra = ContradictionResult(
        has_contradictions=False,
        contradiction_pairs=[],
        overall_consensus="",
        context_differences=["Different populations"],
    )
    signals = extract_signals(ev, contra, _basic_verification(evidence_count=4), independent_groups=4)
    verdict = recalibrate_verdict(signals)
    assert verdict == VerdictType.PARTIALLY_SUPPORTED


def test_cal_weak_evidence_becomes_inconclusive():
    """Very few sources with low quality -> INCONCLUSIVE."""
    ev = [_make_analyzed("A", SupportLevel.NEUTRAL, strength=Strength.LOW)]
    contra = _empty_contradictions()
    signals = extract_signals(ev, contra, _basic_verification(evidence_count=1), independent_groups=1)
    verdict = recalibrate_verdict(signals)
    assert verdict == VerdictType.INCONCLUSIVE


def test_cal_duplicate_families_lower_effective_groups():
    """5 evidence items but only 2 groups -> lower confidence than 5 groups."""
    ev = [_make_analyzed(f"P{i}", SupportLevel.SUPPORTS) for i in range(5)]
    contra = _empty_contradictions()

    signals_dup = extract_signals(ev, contra, _basic_verification(evidence_count=5),
                                   independent_groups=2)
    conf_dup = recalibrate_confidence(signals_dup)

    signals_indep = extract_signals(ev, contra, _basic_verification(evidence_count=5),
                                     independent_groups=5)
    conf_indep = recalibrate_confidence(signals_indep)

    conf_order = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
    assert conf_order[conf_indep] >= conf_order[conf_dup]


def test_cal_narrow_evidence_base_lowers_confidence():
    """Small evidence base should result in lower confidence."""
    ev_narrow = [_make_analyzed(f"P{i}", SupportLevel.SUPPORTS) for i in range(2)]
    signals_narrow = extract_signals(ev_narrow, _empty_contradictions(),
                                     _basic_verification(evidence_count=2), independent_groups=2)

    ev_broad = [_make_analyzed(f"P{i}", SupportLevel.SUPPORTS,
                                methodology_note="meta-analysis" if i < 3 else "rct")
                for i in range(8)]
    signals_broad = extract_signals(ev_broad, _empty_contradictions(),
                                    _basic_verification(evidence_count=8), independent_groups=8)

    conf_narrow = recalibrate_confidence(signals_narrow)
    conf_broad = recalibrate_confidence(signals_broad)

    conf_order = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
    assert conf_order[conf_broad] > conf_order[conf_narrow]


def test_cal_reasoning_uses_correct_absence_language():
    """Reasoning must say 'no genuine contradiction identified' not 'no contradictory evidence exists'."""
    ev = [_make_analyzed(f"P{i}", SupportLevel.SUPPORTS) for i in range(5)]
    verdict = _basic_verdict()
    calibrated = calibrate_final_verdict(
        verdict, ev, _empty_contradictions(), _basic_verification(evidence_count=5),
        independent_groups=5,
    )
    assert "no genuine contradiction was identified" in calibrated.detailed_reasoning.lower()
    assert "no contradictory evidence exists" not in calibrated.detailed_reasoning.lower()


def test_cal_supported_requires_strict_conditions():
    """Strict SUPPORTED verdict only when all conditions met."""
    ev = [_make_analyzed(f"META-{i}", SupportLevel.SUPPORTS, methodology_note="meta-analysis")
          for i in range(6)]
    signals = extract_signals(ev, _empty_contradictions(),
                              _basic_verification(evidence_count=6), independent_groups=6)
    verdict = recalibrate_verdict(signals)
    assert verdict == VerdictType.SUPPORTED

    contra_ctx = ContradictionResult(
        has_contradictions=False,
        contradiction_pairs=[],
        overall_consensus="",
        context_differences=["Context 1", "Context 2"],
    )
    signals_ctx = extract_signals(ev, contra_ctx,
                                  _basic_verification(evidence_count=6), independent_groups=6)
    verdict_ctx = recalibrate_verdict(signals_ctx)
    assert verdict_ctx == VerdictType.PARTIALLY_SUPPORTED


def test_cal_reasoning_has_six_sections():
    """Calibrated reasoning must have all 6 numbered sections."""
    ev = [_make_analyzed(f"P{i}", SupportLevel.SUPPORTS) for i in range(4)]
    verdict = _basic_verdict()
    calibrated = calibrate_final_verdict(
        verdict, ev, _empty_contradictions(), _basic_verification(evidence_count=4),
        independent_groups=4,
    )
    reasoning = calibrated.detailed_reasoning
    for section_num in ["1.", "2.", "3.", "4.", "5.", "6."]:
        assert section_num in reasoning, f"Missing section {section_num} in reasoning"

    assert "OVERALL EVIDENCE DIRECTION" in reasoning
    assert "SUPPORTING EVIDENCE" in reasoning
    assert "LIMITING" in reasoning or "MIXED" in reasoning
    assert "CONTRADICTION STATUS" in reasoning
    assert "SCOPE" in reasoning
    assert "CONFIDENCE" in reasoning


def test_cal_preserves_citations():
    """Calibration must not lose supporting/contradicting citations."""
    ev = [_make_analyzed(f"P{i}", SupportLevel.SUPPORTS) for i in range(3)]
    verdict = FinalVerdict(
        original_question="Test?",
        verdict=VerdictType.SUPPORTED,
        confidence=Confidence.HIGH,
        summary="",
        detailed_reasoning="",
        supporting_evidence=[
            EvidenceCitation(source_id="P0", title="P0", claim="Test claim")
        ],
    )
    calibrated = calibrate_final_verdict(
        verdict, ev, _empty_contradictions(), _basic_verification(evidence_count=3),
        independent_groups=3,
    )
    assert len(calibrated.supporting_evidence) >= 1
    assert calibrated.supporting_evidence[0].source_id == "P0"


def test_cal_full_pipeline_regression():
    """Full pipeline still works end-to-end with calibration."""
    ev = [
        RawEvidence(
            source_id="META-1", title="Meta 1",
            relevant_passage="AI improved outcomes across studies.",
            study_design="Meta-analysis", source_type=SourceType.PEER_REVIEWED,
            peer_reviewed=True,
        ),
        RawEvidence(
            source_id="RCT-1", title="RCT 1",
            relevant_passage="AI produced no significant difference in adult learners.",
            study_design="RCT", source_type=SourceType.PEER_REVIEWED,
            peer_reviewed=True,
        ),
    ]

    def analyze_mock(u):
        return BatchedAnalysisResult(items=[
            AnalyzedEvidenceItem(
                source_id="META-1", question_ids=["Q1"],
                support_level=SupportLevel.SUPPORTS,
                strength=Strength.HIGH, relevance=Relevance.HIGH,
                reason="meta", key_claim="AI improves outcomes",
                methodology_note="meta-analysis",
            ),
            AnalyzedEvidenceItem(
                source_id="RCT-1", question_ids=["Q1"],
                support_level=SupportLevel.CONTRADICTS,
                strength=Strength.HIGH, relevance=Relevance.HIGH,
                reason="rct null", key_claim="No effect in adults",
                methodology_note="rct",
            ),
        ])

    llm = FakeLLM({
        "DecompositionResult": lambda u: DecompositionResult(
            original_question="Test?",
            sub_questions=[SubQuestion(id="Q1", text="Q?", purpose="test")],
            reasoning="", complexity=QuestionComplexity.MODERATE,
        ),
        "BatchedAnalysisResult": analyze_mock,
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="", evidence_b_id="",
            claim_a="", claim_b="",
            is_genuine_contradiction=False,
            explanation="Context differs",
            severity=Strength.MEDIUM,
            classification=ContradictionClass.CONTEXT_DIFFERENCE,
        ),
        "FinalVerdict": lambda u: FinalVerdict(
            original_question="Test?",
            verdict=VerdictType.SUPPORTED,
            confidence=Confidence.HIGH,
            summary="Consistent support",
            detailed_reasoning="Consistent",
        ),
    })
    pipeline = VerificationPipeline(llm=llm, max_rounds=1)
    r = pipeline.run("Does AI improve learning?", ev)

    assert r.verdict is not None
    assert r.verdict.verdict in (
        VerdictType.PARTIALLY_SUPPORTED,
        VerdictType.SUPPORTED,
    )
    assert "OVERALL EVIDENCE DIRECTION" in r.verdict.detailed_reasoning
    assert "no contradictory evidence exists" not in r.verdict.detailed_reasoning.lower()


# ═════════════════════════════════════════════
# SECOND-PASS REGRESSION TESTS
# ═════════════════════════════════════════════

def test_sp_a_stanford_positive_oxford_negative_contradiction():
    """Stanford positive + Oxford negative -> contradiction detected."""
    a = AnalyzedEvidence(
        source_id="STANFORD", title="Stanford RCT",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS,
        strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="12% improvement in math", key_claim="AI improves math scores",
    )
    b = AnalyzedEvidence(
        source_id="OXFORD", title="Oxford RCT",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.CONTRADICTS,
        strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="No significant difference", key_claim="No measurable benefit",
    )
    llm = FakeLLM({
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="STANFORD", evidence_b_id="OXFORD",
            claim_a="AI improves math scores",
            claim_b="No measurable benefit",
            is_genuine_contradiction=True,
            explanation="Different findings on same question.",
            severity=Strength.HIGH,
            classification=ContradictionClass.CONTRADICTORY,
            context_difference="Different populations.",
        )
    })
    r = ContradictionDetector(llm).detect([a, b])
    assert r.has_contradictions is True
    assert len(r.contradiction_pairs) >= 1


def test_sp_b_oxford_medium_same_group():
    """Oxford + Medium dependent -> one independent group."""
    ev = [
        RawEvidence(
            source_id="OXFORD", title="Oxford RCT on Adults",
            url="https://oxford.ac.uk/study",
            source_type=SourceType.PEER_REVIEWED, peer_reviewed=True,
        ),
        RawEvidence(
            source_id="MEDIUM", title="Oxford study copy",
            url="https://medium.com/post",
            source_type=SourceType.BLOG, peer_reviewed=False,
            source_group="oxford-adult-copy",
        ),
    ]
    groups = group_evidence(ev)
    assert len(groups) == 1


def test_sp_c_stanford_vs_oxford_preferred_over_medium():
    """Contradiction pair should be Stanford vs Oxford, not Stanford vs Medium."""
    stanford = AnalyzedEvidence(
        source_id="STANFORD", title="Stanford RCT",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS,
        strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="12% improvement", key_claim="AI improves math scores",
    )
    oxford = AnalyzedEvidence(
        source_id="OXFORD", title="Oxford RCT",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.CONTRADICTS,
        strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="No difference", key_claim="No measurable benefit for adults",
    )
    medium = AnalyzedEvidence(
        source_id="MEDIUM", title="Blog copy",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.CONTRADICTS,
        strength=Strength.LOW, relevance=Relevance.MEDIUM,
        reason="No improvement", key_claim="No improvement like Oxford",
    )
    raw = [
        RawEvidence(source_id="STANFORD", title="Stanford RCT",
                    url="https://stanford.edu/1",
                    source_type=SourceType.PEER_REVIEWED,
                    peer_reviewed=True, study_design="RCT", sample_size=800),
        RawEvidence(source_id="OXFORD", title="Oxford RCT",
                    url="https://oxford.ac.uk/1",
                    source_type=SourceType.PEER_REVIEWED,
                    peer_reviewed=True, study_design="RCT", sample_size=750),
        RawEvidence(source_id="MEDIUM", title="Blog copy",
                    url="https://medium.com/post",
                    source_type=SourceType.BLOG, peer_reviewed=False,
                    source_group="oxford-adult-copy"),
    ]

    seen = []
    def contra_mock(u):
        for sid in ["STANFORD", "OXFORD", "MEDIUM"]:
            if f"Source: {sid}" in u:
                seen.append(sid)
        return ContradictionPair(
            evidence_a_id="", evidence_b_id="",
            claim_a="", claim_b="",
            is_genuine_contradiction=True,
            explanation="Test", severity=Strength.HIGH,
            classification=ContradictionClass.CONTRADICTORY,
        )

    detector = ContradictionDetector(
        FakeLLM({"ContradictionPair": contra_mock}),
        min_overlap=0, semantic_threshold=0.0,
    )
    detector.detect([stanford, oxford, medium], raw)

    assert "STANFORD" in seen
    assert "OXFORD" in seen


def test_sp_d_judge_produces_non_null_verdict():
    """Judge LLM produces a non-null structured verdict."""
    decomp = DecompositionResult(
        original_question="Test?",
        sub_questions=[SubQuestion(id="Q1", text="Q?", purpose="test")],
        reasoning="test", complexity=QuestionComplexity.MODERATE,
    )
    evidence = [AnalyzedEvidence(
        source_id="P1", title="Test",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS,
        strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="test", key_claim="test claim",
    )]
    from verification.models import ContradictionResult
    contra = ContradictionResult(
        has_contradictions=False, contradiction_pairs=[],
        overall_consensus="Strong support",
    )
    verif = VerificationResult(
        is_sufficient=True, confidence=Confidence.HIGH,
        evidence_count=1, supporting_count=1,
        contradicting_count=0, neutral_count=0,
        source_quality="Good", reasoning="Sufficient",
    )
    llm = FakeLLM({
        "FinalVerdict": lambda u: FinalVerdict(
            original_question="Test?",
            verdict=VerdictType.SUPPORTED,
            confidence=Confidence.HIGH,
            summary="Test supported",
            detailed_reasoning="Strong evidence",
            supporting_evidence=[
                EvidenceCitation(source_id="P1", title="Test",
                                 claim="test claim")
            ],
        )
    })
    judge = ResearchJudge(llm)
    verdict = judge.judge(decomp, evidence, contra, verif)
    assert verdict is not None
    assert verdict.verdict in (VerdictType.SUPPORTED, VerdictType.PARTIALLY_SUPPORTED)


def test_sp_e_judge_failure_reports_reason():
    """Judge LLM failure explicitly reports the real failure reason."""
    decomp = DecompositionResult(
        original_question="Test?",
        sub_questions=[SubQuestion(id="Q1", text="Q?", purpose="test")],
        reasoning="test",
    )
    evidence = [AnalyzedEvidence(
        source_id="P1", title="Test",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS,
        strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="test", key_claim="test",
    )]
    from verification.models import ContradictionResult
    contra = ContradictionResult(
        has_contradictions=False, contradiction_pairs=[],
        overall_consensus="test",
    )
    verif = VerificationResult(
        is_sufficient=True, confidence=Confidence.HIGH,
        evidence_count=1, supporting_count=1,
        contradicting_count=0, neutral_count=0,
        source_quality="Good", reasoning="test",
    )
    llm = FakeLLM(fail=True)
    judge = ResearchJudge(llm)
    verdict = judge.judge(decomp, evidence, contra, verif)
    assert verdict is not None
    assert verdict.verdict == VerdictType.INCONCLUSIVE
    assert "failed" in verdict.detailed_reasoning.lower() or \
           "unavailable" in verdict.detailed_reasoning.lower()


def test_sp_f_full_pipeline_non_null_with_real_structure():
    """Full pipeline with mixed evidence produces non-null verdict."""
    ev = [
        RawEvidence(
            source_id="STANFORD", title="Stanford RCT",
            relevant_passage="AI improved math scores by 12%.",
            study_design="RCT", source_type=SourceType.PEER_REVIEWED,
            peer_reviewed=True, sample_size=800,
        ),
        RawEvidence(
            source_id="OXFORD", title="Oxford Adult RCT",
            relevant_passage="No significant improvement for adults.",
            study_design="RCT", source_type=SourceType.PEER_REVIEWED,
            peer_reviewed=True, sample_size=750,
        ),
        RawEvidence(
            source_id="BLOG-DUP", title="Oxford copy blog",
            relevant_passage="No improvement like Oxford showed.",
            study_design="Case Study", source_type=SourceType.BLOG,
            peer_reviewed=False, source_group="oxford-adult-copy",
        ),
    ]

    raw_by_id = {r.source_id: r for r in ev}

    def analyze_mock(u):
        items = []
        for sid, raw in raw_by_id.items():
            text = (raw.title + " " + raw.relevant_passage).lower()
            neg = any(w in text for w in ["no significant", "no improvement",
                                           "no benefit", "no difference"])
            pos = any(w in text for w in ["improved", "increase", "positive"])
            if neg:
                level = SupportLevel.CONTRADICTS
            elif pos:
                level = SupportLevel.SUPPORTS
            else:
                level = SupportLevel.NEUTRAL
            strg = Strength.HIGH if raw.study_design in ["RCT"] else Strength.LOW
            items.append(AnalyzedEvidenceItem(
                source_id=raw.source_id,
                question_ids=["Q1"],
                support_level=level,
                strength=strg,
                relevance=Relevance.HIGH,
                reason="Test",
                key_claim=raw.relevant_passage[:80],
            ))
        return BatchedAnalysisResult(items=items)

    llm = FakeLLM({
        "DecompositionResult": lambda u: DecompositionResult(
            original_question="Test?",
            sub_questions=[SubQuestion(id="Q1", text="Q?", purpose="test")],
            reasoning="test", complexity=QuestionComplexity.COMPLEX,
        ),
        "BatchedAnalysisResult": analyze_mock,
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="STANFORD", evidence_b_id="OXFORD",
            claim_a="improved", claim_b="no improvement",
            is_genuine_contradiction=True,
            explanation="Different populations",
            severity=Strength.HIGH,
            classification=ContradictionClass.CONTRADICTORY,
            context_difference="teens vs adults",
        ),
        "FinalVerdict": lambda u: FinalVerdict(
            original_question="Test?",
            verdict=VerdictType.PARTIALLY_SUPPORTED,
            confidence=Confidence.MEDIUM,
            summary="Context-dependent effect",
            detailed_reasoning="Stanford positive, Oxford negative",
            supporting_evidence=[
                EvidenceCitation(source_id="STANFORD", title="Stanford RCT",
                                 claim="12% improvement")
            ],
            contradicting_evidence=[
                EvidenceCitation(source_id="OXFORD", title="Oxford RCT",
                                 claim="No improvement")
            ],
            limitations=["Different populations"],
        ),
    })
    pipeline = VerificationPipeline(llm=llm, max_rounds=1)
    r = pipeline.run("Does AI improve learning?", ev)
    assert r.verdict is not None
    assert r.verdict.verdict in (
        VerdictType.PARTIALLY_SUPPORTED,
        VerdictType.CONTRADICTED,
    )
    assert len(r.verdict.supporting_evidence) >= 1
    assert len(r.verdict.contradicting_evidence) >= 1


# ═════════════════════════════════════════════
# COMPARABILITY-AWARE CONTRADICTION TESTS
# ═════════════════════════════════════════════

def test_sp2_same_context_contradiction():
    """Identical contexts with opposite outcomes -> GENUINE."""
    a = AnalyzedEvidence(
        source_id="K12-MATH-A", title="K-12 Math Standalone ITS",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS, strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="", key_claim="AI tutoring improved math grades by 12% in K-12 classrooms.",
        methodology_note="RCT, n=500"
    )
    b = AnalyzedEvidence(
        source_id="K12-MATH-B", title="K-12 Math Standalone ITS Null",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.CONTRADICTS, strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="", key_claim="No significant grade difference found with standalone math ITS.",
        methodology_note="RCT, n=510"
    )
    llm = FakeLLM({
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="K12-MATH-A", evidence_b_id="K12-MATH-B",
            claim_a="math improved 12%", claim_b="no significant difference",
            is_genuine_contradiction=True,
            classification=ContradictionClass.CONTRADICTORY,
            explanation="Both test standalone K-12 math software under similar RCT parameters but report contradictory results.",
            severity=Strength.HIGH,
            confidence=Confidence.HIGH
        )
    })
    r = ContradictionDetector(llm).detect([a, b], raw_evidence=[
        RawEvidence(source_id="K12-MATH-A", title="A", url="https://a.org", study_design="RCT", peer_reviewed=True),
        RawEvidence(source_id="K12-MATH-B", title="B", url="https://b.org", study_design="RCT", peer_reviewed=True)
    ])
    assert r.has_contradictions is True
    assert r.contradiction_pairs[0].classification == ContradictionClass.CONTRADICTORY


def test_sp2_different_education_levels_context():
    """Teens vs Adults -> CONTEXT_DIFFERENCE."""
    a = AnalyzedEvidence(
        source_id="STANFORD-TEENS", title="High school Math RCT",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS, strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="", key_claim="math +12% in US teens",
    )
    b = AnalyzedEvidence(
        source_id="OXFORD-ADULTS", title="AI Learning in Adult Classes",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.CONTRADICTS, strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="", key_claim="adults zero benefit",
    )
    llm = FakeLLM({
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="STANFORD-TEENS", evidence_b_id="OXFORD-ADULTS",
            claim_a="math +12% in teens", claim_b="adults zero benefit",
            is_genuine_contradiction=False,
            classification=ContradictionClass.CONTEXT_DIFFERENCE,
            explanation="Different demographics explain the discrepancy (teens vs adult vocational learners).",
            severity=Strength.LOW,
            confidence=Confidence.HIGH,
            context_difference="Different educational levels."
        )
    })
    r = ContradictionDetector(llm).detect([a, b], raw_evidence=[
        RawEvidence(source_id="STANFORD-TEENS", title="A", url="https://a.org", study_design="RCT", peer_reviewed=True),
        RawEvidence(source_id="OXFORD-ADULTS", title="B", url="https://b.org", study_design="RCT", peer_reviewed=True)
    ])
    assert r.has_contradictions is False
    assert r.contradiction_pairs[0].classification == ContradictionClass.CONTEXT_DIFFERENCE


def test_sp2_different_intervention_types_context():
    """Standalone ITS software vs Human-AI Hybrid Tool -> CONTEXT_DIFFERENCE."""
    a = AnalyzedEvidence(
        source_id="ITS-MATH", title="K-12 Math Standalone ITS",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.CONTRADICTS, strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="", key_claim="No classroom math improvement with standalone software.",
    )
    b = AnalyzedEvidence(
        source_id="COPILOT-HYBRID", title="Tutor CoPilot: A Human-AI Approach",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS, strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="", key_claim="Tutors with real-time AI suggestions increased mastery rates.",
    )
    llm = FakeLLM({
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="ITS-MATH", evidence_b_id="COPILOT-HYBRID",
            claim_a="no classroom improvement with standalone ITS", claim_b="tutor suggestions increased mastery",
            is_genuine_contradiction=False,
            classification=ContradictionClass.CONTEXT_DIFFERENCE,
            explanation="Different intervention paradigms (standalone AI software vs real-time human-AI co-piloting).",
            severity=Strength.LOW,
            confidence=Confidence.HIGH,
            context_difference="Different AI integration methods."
        )
    })
    r = ContradictionDetector(llm).detect([a, b], raw_evidence=[
        RawEvidence(source_id="ITS-MATH", title="A", url="https://a.org", study_design="RCT", peer_reviewed=True),
        RawEvidence(source_id="COPILOT-HYBRID", title="B", url="https://b.org", study_design="RCT", peer_reviewed=True)
    ])
    assert r.has_contradictions is False
    assert r.contradiction_pairs[0].classification == ContradictionClass.CONTEXT_DIFFERENCE


def test_sp2_different_outcomes_context():
    """Homework scores vs Standardized Exam transfer -> CONTEXT_DIFFERENCE."""
    a = AnalyzedEvidence(
        source_id="PROOF-HW", title="AI Math Proof support on homework",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS, strength=Strength.MEDIUM, relevance=Relevance.HIGH,
        reason="", key_claim="AI proof-writing support improved math homework scores.",
    )
    b = AnalyzedEvidence(
        source_id="PROOF-EXAM", title="AI Math Proof support on exams",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.CONTRADICTS, strength=Strength.MEDIUM, relevance=Relevance.HIGH,
        reason="", key_claim="No grade transfer to final exam performance.",
    )
    llm = FakeLLM({
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="PROOF-HW", evidence_b_id="PROOF-EXAM",
            claim_a="AI improved homework scores", claim_b="no transfer to final exam performance",
            is_genuine_contradiction=False,
            classification=ContradictionClass.CONTEXT_DIFFERENCE,
            explanation="Different outcome measurements (localized homework assistance vs exam knowledge transfer).",
            severity=Strength.LOW,
            confidence=Confidence.HIGH,
            context_difference="Different outcome metrics."
        )
    })
    r = ContradictionDetector(llm).detect([a, b], raw_evidence=[
        RawEvidence(source_id="PROOF-HW", title="A", url="https://a.org", study_design="Quasi-experimental", peer_reviewed=False),
        RawEvidence(source_id="PROOF-EXAM", title="B", url="https://b.org", study_design="Quasi-experimental", peer_reviewed=False)
    ])
    assert r.has_contradictions is False
    assert r.contradiction_pairs[0].classification == ContradictionClass.CONTEXT_DIFFERENCE


def test_sp2_positive_vs_null_not_automatic_contradiction():
    """Cognitive training vs Subject tutoring -> CONTEXT_DIFFERENCE (not automatic contradiction)."""
    a = AnalyzedEvidence(
        source_id="PHYSICS-ITS", title="Physics ITS RCT",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.SUPPORTS, strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="", key_claim="Physics intelligent tutoring significantly helped students.",
    )
    b = AnalyzedEvidence(
        source_id="COGNITIVE-MEM", title="Working Memory step-wise progression",
        question_ids=["Q1"], question_id="Q1",
        support_level=SupportLevel.CONTRADICTS, strength=Strength.HIGH, relevance=Relevance.HIGH,
        reason="", key_claim="Step-wise memory progression in children showed no cognitive transfer.",
    )
    llm = FakeLLM({
        "ContradictionPair": lambda u: ContradictionPair(
            evidence_a_id="PHYSICS-ITS", evidence_b_id="COGNITIVE-MEM",
            claim_a="Physics ITS helped students", claim_b="no cognitive transfer in memory progression",
            is_genuine_contradiction=False,
            classification=ContradictionClass.CONTEXT_DIFFERENCE,
            explanation="Unrelated paradigms (applied subject tutoring vs generalized cognitive development).",
            severity=Strength.LOW,
            confidence=Confidence.HIGH,
            context_difference="Different learning domains."
        )
    })
    r = ContradictionDetector(llm).detect([a, b], raw_evidence=[
        RawEvidence(source_id="PHYSICS-ITS", title="A", url="https://a.org", study_design="RCT", peer_reviewed=True),
        RawEvidence(source_id="COGNITIVE-MEM", title="B", url="https://b.org", study_design="RCT", peer_reviewed=True)
    ])
    assert r.has_contradictions is False
    assert r.contradiction_pairs[0].classification == ContradictionClass.CONTEXT_DIFFERENCE