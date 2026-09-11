# test_scenarios.py — Realistic Scenario Tester for M3
import sys
from verification import (
    VerificationPipeline,
    RawEvidence,
    SourceType,
    Strength,
    QuestionComplexity,
    SupportLevel,
    Relevance,
    DecompositionResult,
    SubQuestion,
    AnalyzedEvidence,
    ContradictionPair,
    ContradictionClass,
    VerificationResult,
    FinalVerdict,
    EvidenceCitation,
    Confidence,
    VerdictType
)
from tests.test_verification import FakeLLM

# --- SMART DYNAMIC SIMULATOR (Bina API key ke dimaag lagane wala Fake LLM) ---
def create_smart_simulator(raw_evidence_list):
    raw_by_id = {r.source_id: r for r in raw_evidence_list}
    def analyze_evidence_mock(user_prompt):
        source_id = None
        for sid in raw_by_id:
            if sid in user_prompt:
                source_id = sid
                break
        
        if not source_id:
            return _minimal_fallback(AnalyzedEvidence)
            
        raw = raw_by_id[source_id]
        text = (raw.title + " " + raw.relevant_passage).lower()
        
        # 🔥 FIX: Pehle NEGATIVE check karo (kyunki "no improvement" mein bhi "improvement" hota hai!)
        negative_keywords = ["no academic", "no significant", "no measurable", 
                            "no benefit", "no improvement", "no difference",
                            "did not", "not work", "failed", "no grade"]
        positive_keywords = ["improved", "positive", "increase", "benefit", 
                            "gain", "significant improvement", "better outcomes"]
        
        # NEGATIVE pehle check kiya jaayega
        is_negative = any(w in text for w in negative_keywords)
        is_positive = any(w in text for w in positive_keywords)
        
        if is_negative:
            # Agar negative signal hai to CONTRADICTS (chahe positive word bhi ho)
            level = SupportLevel.CONTRADICTS
            claim = f"AI tools showed no significant academic benefits ({raw.title})"
            reason = "Study measured outcomes and found no statistical difference."
        elif is_positive:
            level = SupportLevel.SUPPORTS
            claim = f"AI tutoring significantly improves performance ({raw.title})"
            reason = "Study directly reports measurable positive outcomes."
        else:
            level = SupportLevel.NEUTRAL
            claim = f"Neutral evaluation of AI tools ({raw.title})"
            reason = "Descriptive study with no direct positive or negative claim."

        # Strength based on methodology
        strg = Strength.LOW
        if raw.study_design in ["RCT", "Systematic Review"]:
            strg = Strength.HIGH
        elif raw.study_design in ["Survey", "Cohort"]:
            strg = Strength.MEDIUM

        return AnalyzedEvidence(
            source_id=raw.source_id,
            title=raw.title,
            question_ids=["Q2"],
            question_id="Q2",
            support_level=level,
            strength=strg,
            relevance=Relevance.HIGH,
            reason=reason,
            key_claim=claim,
            methodology_note=raw.methodology or raw.study_design or "Unknown"
        )
    def contradiction_mock(user_prompt):
        # Check matching ids
        id_a, id_b = None, None
        for sid in raw_by_id:
            if f"Source: {sid}" in user_prompt:
                if not id_a:
                    id_a = sid
                else:
                    id_b = sid
        
        if id_a and id_b:
            raw_a = raw_by_id[id_a]
            raw_b = raw_by_id[id_b]
            # Agar dono alag country ya alag population ke hain
            if ("us" in raw_a.title.lower() and "adult" in raw_b.title.lower()) or \
               ("high school" in raw_a.title.lower() and "primary" in raw_b.title.lower()):
                return ContradictionPair(
                    evidence_a_id=id_a, evidence_b_id=id_b,
                    claim_a=raw_a.title, claim_b=raw_b.title,
                    is_genuine_contradiction=False,
                    classification=ContradictionClass.CONTEXT_DIFFERENCE,
                    explanation=f"Context difference: {id_a} is focused on US high schoolers, while {id_b} studies adult learners.",
                    severity=Strength.LOW,
                    confidence=Confidence.HIGH,
                    context_difference="Different target populations and age groups."
                )
            # Agar bilkul same question par ulta bol rahe hain
            return ContradictionPair(
                evidence_a_id=id_a, evidence_b_id=id_b,
                claim_a=raw_a.title, claim_b=raw_b.title,
                is_genuine_contradiction=True,
                classification=ContradictionClass.CONTRADICTORY,
                explanation="Direct collision! Both measure math grades using RCT but report opposite outcomes.",
                severity=Strength.HIGH,
                confidence=Confidence.HIGH
            )
        return _minimal_fallback(ContradictionPair)

    def verifier_mock(user_prompt):
        # FIX: Matches "support=SUPPORTS" in prompt format
        supports_count = user_prompt.count("support=SUPPORTS")
        contradicts_count = user_prompt.count("support=CONTRADICTS")
        total_count = supports_count + contradicts_count
        
        is_sufficient = total_count >= 2 and (supports_count >= 2 or contradicts_count >= 2)
        if contradicts_count > 0 and supports_count > 0:
            # If there's a conflict, we need at least 3 sources to be sufficient
            is_sufficient = total_count >= 3

        return VerificationResult(
            is_sufficient=is_sufficient,
            confidence=Confidence.HIGH if is_sufficient else Confidence.LOW,
            evidence_count=total_count,
            supporting_count=supports_count,
            contradicting_count=contradicts_count,
            neutral_count=0,
            source_quality="Good" if is_sufficient else "Insufficient Data",
            reasoning=f"Dynamic verification: support={supports_count}, contradicts={contradicts_count}, total={total_count}.",
            additional_research_needed=not is_sufficient,
            research_focus="Find more independent studies to resolve the contradictions" if not is_sufficient else ""
        )

    def judge_mock(user_prompt):
        # Read stats from context
        has_contra = "YES — Genuine contradictions detected" in user_prompt
        sup_count = 0
        con_count = 0
        for line in user_prompt.split("\n"):
            if "Supporting:" in line or "supports:" in line:
                try: sup_count = int(line.split("supports:")[1].split("%")[0].strip())
                except: pass
            if "Contradicting:" in line or "contradicts:" in line:
                try: con_count = int(line.split("contradicts:")[1].split("%")[0].strip())
                except: pass

        if has_contra:
            verdict = VerdictType.PARTIALLY_SUPPORTED
            summary = "AI-assisted learning shows positive outcomes, but direct contradictions exist in some studies."
            detailed = "While Harvard reports a 12% increase, other studies contradict this. This indicates high dependency on implementation context."
        elif sup_count > 70:
            verdict = VerdictType.SUPPORTED
            summary = "AI-assisted learning strongly improves academic outcomes."
            detailed = "Consensus is clear across high-quality peer-reviewed studies showing significant grade improvements."
        elif con_count > 70:
            verdict = VerdictType.CONTRADICTED
            summary = "Evidence suggests AI-assisted learning does NOT improve performance."
            detailed = "The high-strength RCTs consistently show no statistically significant improvement."
        else:
            verdict = VerdictType.INCONCLUSIVE
            summary = "Evidence is too mixed or insufficient to draw a solid conclusion."
            detailed = "The current evidence base has severe gaps or is evenly split between success and failure."

        return FinalVerdict(
            original_question="Does AI-assisted learning improve student performance?",
            verdict=verdict,
            confidence=Confidence.HIGH,
            summary=summary,
            detailed_reasoning=detailed,
            supporting_evidence=[
                EvidenceCitation(source_id=sid, title=r.title, claim=r.relevant_passage)
                for sid, r in raw_by_id.items() if "improve" in r.relevant_passage.lower() or "positive" in r.relevant_passage.lower()
            ],
            contradicting_evidence=[
                EvidenceCitation(source_id=sid, title=r.title, claim=r.relevant_passage)
                for sid, r in raw_by_id.items() if "no" in r.relevant_passage.lower() or "fail" in r.relevant_passage.lower()
            ],
            limitations=["Context-dependency is extremely high.", "Sample size in negative studies is low."],
            sub_question_answers={"Q1": "Personalized adaptive software.", "Q2": "Positive RCTs exist.", "Q3": "Yes, some failures reported."}
        )

    routes = {
        "DecompositionResult": lambda u: DecompositionResult(
            original_question="Does AI-assisted learning improve student performance?",
            sub_questions=[
                SubQuestion(id="Q1", text="What is AI-assisted learning?", purpose="Definition"),
                SubQuestion(id="Q2", text="What studies measure its effect on grades?", purpose="Evidence"),
                SubQuestion(id="Q3", text="Are there studies showing no improvement?", purpose="Counter-Evidence")
            ],
            reasoning="Broken down logically.",
            complexity=QuestionComplexity.MODERATE
        ),
        "AnalyzedEvidence": analyze_evidence_mock,
        "ContradictionPair": contradiction_mock,
        "VerificationResult": verifier_mock,
        "FinalVerdict": judge_mock
    }
    return FakeLLM(routes=routes)

def _minimal_fallback(model):
    from tests.test_verification import _minimal
    return _minimal(model)

# --- SCENARIOS DEFINITIONS ---

SCENARIO_1_POSITIVE = [
    RawEvidence(source_id="HARVARD-2023", title="Impact of AI-assisted Tutoring: Math RCT", url="https://harvard.edu/1",
                relevant_passage="Adaptive AI tutors improved math scores by 12% over control group.",
                study_design="RCT", source_type=SourceType.PEER_REVIEWED, peer_reviewed=True, sample_size=1200),
    RawEvidence(source_id="MIT-2024", title="Meta-analysis of AI tools", url="https://mit.edu/1",
                relevant_passage="Systematic review of 40 studies found positive performance benefits across schools.",
                study_design="Systematic Review", source_type=SourceType.PEER_REVIEWED, peer_reviewed=True, sample_size=15000),
]

SCENARIO_2_CONFLICT = [
    RawEvidence(source_id="STANFORD-YES", title="Math RCT in US High Schools", url="https://stanford.edu/1",
                relevant_passage="AI software improved student exam results significantly.",
                study_design="RCT", source_type=SourceType.PEER_REVIEWED, peer_reviewed=True, sample_size=800),
    RawEvidence(source_id="OXFORD-NO", title="AI Learning in Adult Classes", url="https://oxford.ac.uk/2",
                relevant_passage="Adult students using AI software showed no academic benefit or grade improvement.",
                study_design="RCT", source_type=SourceType.PEER_REVIEWED, peer_reviewed=True, sample_size=750),
    RawEvidence(source_id="DUPLICATE-BLOG", title="Why AI software did not work", url="https://medium.com/blog-copy",
                publisher="Medium", relevant_passage="We saw no academic benefit in adult students using AI.",
                study_design="Survey", source_type=SourceType.BLOG, peer_reviewed=False, source_group="oxford-adult-copy")
]

SCENARIO_3_INSUFFICIENT = [
    RawEvidence(source_id="BLOG-1", title="My thoughts on AI classes", url="https://blogger.com/my-thoughts",
                relevant_passage="I think AI is cool and maybe improves grades.",
                study_design="Opinion", source_type=SourceType.BLOG, peer_reviewed=False)
]


# --- RUN SCENARIO FUNCTION ---
def run_scenario(scenario_name, evidence_list):
    print("\n" + "="*80)
    print(f"🔥 RUNNING SCENARIO: {scenario_name}")
    print("="*80)
    
    llm = create_smart_simulator(evidence_list)
    pipeline = VerificationPipeline(llm=llm, max_rounds=3)
    
    result = pipeline.run(
        question="Does AI-assisted learning improve student performance?",
        evidence=evidence_list,
        complexity=QuestionComplexity.MODERATE
    )
    
    state = result.state
    
    # 1. Groups & Weights
    print("\n[SOURCE GROUPS & WEIGHTS]")
    from verification.source_identity import group_evidence
    groups = group_evidence(evidence_list)
    print(f"  Raw Papers: {len(evidence_list)} | Unique Groups: {len(groups)}")
    
    from verification.weighting import calculate_evidence_weight
    for ae in state.analyzed_evidence:
        raw = next((r for r in evidence_list if r.source_id == ae.source_id), None)
        w = calculate_evidence_weight(ae, raw)
        print(f"  • {ae.source_id} -> Support: {ae.support_level.value} | Weight: {w.total:.3f} | Claim: {ae.key_claim}")
        
    # 2. Consensus & Contradiction
    print("\n[CONTRADICTIONS & CONSENSUS]")
    print(f"  Has Genuine Contradictions: {state.contradictions.has_contradictions}")
    print(f"  Weighted Consensus: {state.contradictions.overall_consensus}")
    for pair in state.contradictions.contradiction_pairs:
        status = "GENUINE" if pair.is_genuine_contradiction else "CONTEXT DIFFERENCE"
        print(f"    - {pair.evidence_a_id} vs {pair.evidence_b_id} ({status}): {pair.explanation}")

    # 3. Sufficiency & Verdict
    print("\n[VERIFICATION & FINAL VERDICT]")
    print(f"  Is Sufficient: {state.verification.is_sufficient} (Reason: {state.verification.reasoning})")
    
    verdict = result.verdict
    # FIX: Guard print with Null check
    if verdict:
        print(f"  FINAL VERDICT: {verdict.verdict.value} (Confidence: {verdict.confidence.value})")
        print(f"  Summary: {verdict.summary}")
        print(f"\n  Detailed Reasoning: {verdict.detailed_reasoning}")
        
        print("\n  CITATIONS FOR M4:")
        print("    Supporting:")
        for citation in verdict.supporting_evidence:
            print(f"      - [{citation.source_id}] {citation.title}: {citation.claim}")
        print("    Contradicting:")
        for citation in verdict.contradicting_evidence:
            print(f"      - [{citation.source_id}] {citation.title}: {citation.claim}")
    else:
        print("  FINAL VERDICT: None (Evidence is insufficient, pipeline needs more research!)")
    
    if result.needs_more_research:
        print(f"\n  ⚠️ Orchestrator (M1) is instructed to run MORE research focusing on: '{result.research_focus}'")


# --- MAIN CHOOSE SCENARIO ---
if __name__ == "__main__":
    print("🤖 Welcome to M3 Scenario Tester!")
    print("1: Positive Consensus (AI wins, no conflict)")
    print("2: Contradiction / Population Context Difference (Stanford vs Oxford)")
    print("3: Insufficient Evidence (Only 1 weak blog, pipeline needs more research)")
    print("4: Run ALL Scenarios")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        run_scenario("Strong Support (AI Wins)", SCENARIO_1_POSITIVE)
    elif choice == "2":
        run_scenario("Contradiction / Population Context", SCENARIO_2_CONFLICT)
    elif choice == "3":
        run_scenario("Insufficient Evidence", SCENARIO_3_INSUFFICIENT)
    elif choice == "4":
        run_scenario("Strong Support (AI Wins)", SCENARIO_1_POSITIVE)
        run_scenario("Contradiction / Population Context", SCENARIO_2_CONFLICT)
        run_scenario("Insufficient Evidence", SCENARIO_3_INSUFFICIENT)
    else:
        print("Invalid choice!")