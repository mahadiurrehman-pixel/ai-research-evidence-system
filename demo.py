# demo.py — M3 Verification Module Demo
import json
from datetime import date
from verification import (
    VerificationPipeline,
    RawEvidence,
    SourceType,
    Strength,
    QuestionComplexity,
)

# --- 1. Fake LLM Client Banao (Taake bina API Key ke turant chale) ---
# Agar tumhare paas real OpenAI Key hai, to tum "use_real_llm = True" kar sakte ho!
use_real_llm = False 

if use_real_llm:
    from verification import OpenAICompatibleLLMClient
    # Ensure OPENAI_API_KEY is set in your terminal: export OPENAI_API_KEY="your-key"
    llm = OpenAICompatibleLLMClient(model="gpt-4o-mini")
else:
    # Simulated responses returned by our FakeLLM for this specific demo
    from tests.test_verification import FakeLLM
    from verification import (
        DecompositionResult, SubQuestion, AnalyzedEvidence,
        Relevance, SupportLevel, ContradictionResult, ContradictionPair,
        ContradictionClass, VerificationResult, FinalVerdict, EvidenceCitation, Confidence, VerdictType
    )

    demo_routes = {
        "DecompositionResult": lambda u: DecompositionResult(
            original_question="Does AI-assisted learning improve student performance?",
            sub_questions=[
                SubQuestion(id="Q1", text="What is AI-assisted learning?", purpose="Definition"),
                SubQuestion(id="Q2", text="What studies measure its effect on grades?", purpose="Evidence"),
                SubQuestion(id="Q3", text="Are there studies showing no improvement?", purpose="Counter-Evidence")
            ],
            reasoning="Split into definition, core evidence, and counter-studies.",
            complexity=QuestionComplexity.MODERATE
        ),
        "VerificationResult": lambda u: VerificationResult(
            is_sufficient=True,
            confidence=Confidence.HIGH,
            evidence_count=3,
            supporting_count=2,
            contradicting_count=1,
            neutral_count=0,
            source_quality="Excellent (High-quality RCT and Systematic Review)",
            reasoning="We have independent high-strength studies from Harvard and MIT, outweighing a low-quality blog.",
            additional_research_needed=False
        ),
        "FinalVerdict": lambda u: FinalVerdict(
            original_question="Does AI-assisted learning improve student performance?",
            verdict=VerdictType.PARTIALLY_SUPPORTED,
            confidence=Confidence.HIGH,
            summary="AI-assisted learning is highly supported by tier-1 studies (12% math score increase), though minor implementation issues exist in smaller contexts.",
            detailed_reasoning="Strong RCT evidence from Harvard and MIT systematic reviews support gains. One minor blog reported no benefit but suffers from low sample size.",
            supporting_evidence=[
                EvidenceCitation(source_id="HARVARD-2023", title="Impact of AI-assisted Tutoring", claim="12% score increase in Math RCT", reason="High quality RCT"),
                EvidenceCitation(source_id="MIT-2024", title="Meta-analysis of AI tools", claim="Positive effect d=0.25 on performance", reason="Systematic review")
            ],
            contradicting_evidence=[
                EvidenceCitation(source_id="BLOG-1", title="AI tutor review", claim="No significant difference in grades", reason="Small sample blog post")
            ],
            limitations=[
                "Most positive studies focus on Mathematics",
                "Smaller studies struggle with implementation quality"
            ],
            sub_question_answers={
                "Q1": "AI-assisted learning refers to personalized software/tutors adapting to student needs.",
                "Q2": "Harvard RCT (n=1200) and MIT meta-analysis (n=15000) measure positive grade effects.",
                "Q3": "Some small blogs/surveys report no improvement due to poor software usage."
            },
            recommendations=[
                "Deploy adaptive AI systems specifically for mathematics.",
                "Focus on teacher-training during software deployment."
            ]
        )
    }
    llm = FakeLLM(routes=demo_routes)


# --- 2. Input Evidence (M2 se laayi hui kachchi research) ---
mock_evidence = [
    # 1. Harvard RCT (Super High Quality)
    RawEvidence(
        source_id="HARVARD-2023",
        title="Impact of AI-assisted Tutoring: A Randomized Controlled Trial",
        authors=["Doe, J.", "Smith, A."],
        year=2023,
        url="https://harvard.edu/papers/ai-tutoring",
        relevant_passage="Students using adaptive AI tutors showed a 12% math score increase over the control group.",
        study_design="RCT",
        sample_size=1200,
        source_type=SourceType.PEER_REVIEWED,
        peer_reviewed=True
    ),
    # 2. MIT Meta-analysis (Very High Quality)
    RawEvidence(
        source_id="MIT-2024",
        title="Meta-analysis of AI tools in Secondary Education",
        authors=["Chen, L."],
        year=2024,
        url="https://mit.edu/secondary-education-ai",
        relevant_passage="Systematic review of 40 studies found positive performance effects across diverse demographics.",
        study_design="Systematic Review",
        sample_size=15000,
        source_type=SourceType.PEER_REVIEWED,
        peer_reviewed=True
    ),
    # 3. Blog Post (Duplicate Copy 1 - Low Quality)
    RawEvidence(
        source_id="BLOG-1",
        title="Why AI Tutors Didn't Work in My Classroom",
        publisher="Medium Education",
        year=2024,
        url="https://medium.com/edu-tales/ai-tutors-fail",
        relevant_passage="Our small class of 15 students saw no significant difference in grades after 3 weeks.",
        study_design="Case Study",
        sample_size=15,
        source_type=SourceType.BLOG,
        peer_reviewed=False,
        source_group="medium-blog-syndicate"  # Grouping check!
    )
]

# --- 3. Pipeline Run Karo ---
print("🚀 M3 Pipeline Start Kar Rahein Hain...\n")

# Hum 3 rounds max research set kar rahe hain
pipeline = VerificationPipeline(llm=llm, max_rounds=3)

# M1 ne request di (Hum manual complexity bhi de rahe hain 'MODERATE')
result = pipeline.run(
    question="Does AI-assisted learning improve student performance?",
    evidence=mock_evidence,
    complexity=QuestionComplexity.MODERATE
)

# --- 4. Beautifully Outputs Print Karo ---
state = result.state

print("=" * 60)
print("1. DECOMPOSER (Sawaal Toda Gaya)")
print("=" * 60)
print(f"Auto Complexity: {state.decomposition.complexity.value}")
for sq in state.decomposition.sub_questions:
    print(f"  [{sq.id}] {sq.text} ({sq.purpose})")

print("\n" + "=" * 60)
print("2. SOURCE GROUPING (Duplicates Check)")
print("=" * 60)
from verification.source_identity import group_evidence, get_source_group
groups = group_evidence(mock_evidence)
print(f"Total Raw Papers: {len(mock_evidence)}")
print(f"Unique Independent Groups Found: {len(groups)}")
for gkey, items in groups.items():
    print(f"  Group Key: '{gkey}' -> contains {[i.source_id for i in items]}")

print("\n" + "=" * 60)
print("3. EVIDENCE WEIGHTS (Quality vs Quantity)")
print("=" * 60)
from verification.weighting import calculate_evidence_weight
# Analyzer ne analyze kiya pehle
for ae in state.analyzed_evidence:
    raw = next((r for r in mock_evidence if r.source_id == ae.source_id), None)
    weight_breakdown = calculate_evidence_weight(ae, raw)
    print(f"  Paper {ae.source_id}:")
    print(f"    Support Level: {ae.support_level.value}")
    print(f"    Calculated Weight Score: {weight_breakdown.total:.3f}")
    print(f"    Explanation: {weight_breakdown.explain()}")

print("\n" + "=" * 60)
print("4. CONTRADICTIONS DETECTION (Jhagda Classifier)")
print("=" * 60)
print(f"Has Genuine Contradictions: {state.contradictions.has_contradictions}")
print(f"Overall Weighted Consensus: {state.contradictions.overall_consensus}")

print("\n" + "=" * 60)
print("5. VERIFIER & FINAL JUDGE REPORT")
print("=" * 60)
verdict = result.verdict
print(f"VERDICT: {verdict.verdict.value}")
print(f"CONFIDENCE: {verdict.confidence.value}")
print(f"\nSUMMARY:\n{verdict.summary}")
print(f"\nDETAILED REASONING:\n{verdict.detailed_reasoning}")

print("\nCITATIONS FOR M4 (Traceable Links):")
print("  Supporting:")
for citation in verdict.supporting_evidence:
    print(f"    - [{citation.source_id}] {citation.title}: {citation.claim}")
print("  Contradicting:")
for citation in verdict.contradicting_evidence:
    print(f"    - [{citation.source_id}] {citation.title}: {citation.claim}")

print("\nLIMITATIONS:")
for lim in verdict.limitations:
    print(f"  • {lim}")

print("\nRECOMMENDATIONS:")
for rec in verdict.recommendations:
    print(f"  • {rec}")
print("=" * 60)