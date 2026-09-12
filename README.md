<div align="center">

# 🔍 Reality Checker

### AI Research Evidence Verification System

*An autonomous multi-agent pipeline for claim verification, evidence synthesis, and calibrated verdict generation.*

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Tests](https://img.shields.io/badge/Tests-60%2B%20passing-2EA44F)](#testing)
[![License](https://img.shields.io/badge/License-MIT-F5C518)](#license)

[**GitHub Repository**](https://github.com/mahadiurrehman-pixel/ai-research-evidence-system)

</div>

---

## 📖 Overview

**Reality Checker** is a production-oriented, multi-agent AI system for investigating research claims. It retrieves empirical evidence, evaluates source quality, identifies contextual differences and genuine contradictions, and produces calibrated, evidence-grounded verdicts.

Unlike a conventional search-and-summarize tool, Reality Checker follows a **Plan → Execute → Verify → Re-plan** architecture. Its safeguards are designed to reduce confirmation bias, avoid duplicate sources, handle provider rate limits, and make uncertainty explicit.

> **Core question:** Given a research claim, what does the totality of available evidence actually say—and how confident should we be?

## ✨ Highlights

- **Balanced evidence retrieval** with supporting, opposing, null, and mixed-finding queries.
- **Context-aware contradiction detection** that separates genuine contradictions from differences caused by population, intervention, outcome, or study context.
- **Calibrated verdicts** such as `SUPPORTED_WITH_LIMITATIONS` instead of oversimplified yes/no answers.
- **Traceable reasoning** with source-linked citations, explicit limitations, and structured confidence.
- **Task-aware model routing** across fast, balanced, reasoning, and strong synthesis tiers.
- **High-throughput scheduling** with concurrent requests, provider rotation, cooldowns, and failover.
- **Deterministic sufficiency checks** based on study design, sample size, peer-review status, and independent evidence groups.
- **Persistent storage** backed by SQLite and ChromaDB for investigations, semantic caching, and evidence indexing.

---

## 🏗️ Architecture

```text
┌──────────────────┐
│    Researcher    │
└────────┬─────────┘
         │
┌────────▼─────────┐
│ M4 Frontend      │  Streamlit UI · SQLite · ChromaDB
│ Cache & Storage   │  Persistent semantic cache and evidence index
└────────┬─────────┘
         │
┌────────▼─────────┐
│ M1 Orchestrator  │  Intent classification
│ Investigation     │  Balanced query planning
│ Controller        │  Adaptive round management
└──────┬───────┬────┘
       │       │
┌──────▼─────┐ ┌▼──────────────┐
│ M2          │ │ M3            │
│ Retrieval   │ │ Verification  │
│             │ │               │
│ arXiv       │ │ Deduplication │
│ Semantic    │ │ Weighting     │
│ Scholar     │ │ Contradiction │
│ Tavily      │ │ Calibration   │
│ PubMed      │ │ Verdict       │
└─────────────┘ └───────────────┘
```

### Agent responsibilities

| Agent | Role | Primary responsibilities |
|---|---|---|
| **M1** | Orchestrator | Classifies questions, plans balanced searches, and manages adaptive research loops. |
| **M2** | Retrieval | Discovers and extracts evidence from academic databases and web sources. |
| **M3** | Verification | Deduplicates, weighs, and compares evidence before generating a calibrated verdict. |
| **M4** | Frontend & persistence | Renders results, manages cache and storage, and maintains investigation history. |

---

## 🔬 Key technical capabilities

### 1. Balanced retrieval to reduce confirmation bias

The orchestrator generates more than supportive searches. It deliberately includes opposing, null-result, and mixed-finding queries so that the system actively looks for evidence that could weaken the initial claim.

### 2. Context-aware contradiction classification

The verification pipeline distinguishes between:

- **Genuine contradictions:** incompatible findings under sufficiently comparable conditions.
- **Contextual differences:** divergent findings that can be explained by differences in population, intervention, comparator, outcome metric, implementation, or study design.

For example, a positive RCT involving high-school mathematics tutoring and a null RCT involving adult vocational training should not automatically be treated as a contradiction: the populations and contexts differ substantially.

### 3. Task-aware model routing

LLM calls are routed according to task complexity and expected reasoning requirements:

| Task tier | Preferred provider(s) | Example use cases |
|---|---|---|
| **Fast** | Groq | Query planning, classification, and decomposition |
| **Balanced** | Groq / Gemini | Evidence extraction and grouping |
| **Reasoning** | Gemini | Contradiction detection and context comparison |
| **Strong** | Gemini → Groq → Qwen-72B | Final verdict synthesis |

### 4. High-throughput scheduling with failover

- `ThreadPoolExecutor` parallelism with configurable concurrency.
- Per-provider cooldowns when a key receives an HTTP 429 response.
- Fail-fast timeouts that move to the next provider.
- Round-robin rotation across up to four Groq API keys.

### 5. Deterministic evidence sufficiency

Sufficiency is checked with pure-Python heuristics rather than an additional LLM call. The checks consider study design, sample size, peer-review status, and the number of independent evidence groups.

### 6. Three-layer persistent storage

| Layer | Technology | Purpose |
|---|---|---|
| Source of truth | SQLite | Investigation records and structured verdict JSON |
| Semantic cache | Persistent ChromaDB | Similarity-based query deduplication with configurable TTLs |
| Evidence index | Persistent ChromaDB | Vector search over retrieved evidence passages |

### 7. Calibrated verdicts

Final verdicts include:

- Overall direction of the evidence.
- Degree of support and its main limitations.
- Contradiction status and contextual interpretation.
- Scope of applicability.
- Calibrated confidence.
- Traceable citations linked to source identifiers.

---

## 🛠️ Technology stack

| Component | Technology |
|---|---|
| Language | Python 3.10+; developed with Python 3.12 |
| UI framework | Streamlit |
| Data validation | Pydantic v2 |
| LLM providers | Groq, Google Gemini, Hugging Face |
| Strong-model options | Qwen 72B / 32B Instruct |
| Vector database | ChromaDB |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Relational database | SQLite |
| Testing | pytest |
| Package management | uv or pip |

---

## ⚡ Quick start

### Prerequisites

- Python 3.10 or newer.
- At least one supported LLM API key; Groq is recommended for the fast and balanced tiers.
- API access for the retrieval providers enabled in your environment, if those connectors are used.

### Installation

```bash
# Clone the repository
git clone https://github.com/mahadiurrehman-pixel/ai-research-evidence-system.git
cd ai-research-evidence-system

# Create and activate a virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt
```

With standard `pip`, the equivalent setup is:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Environment configuration

Create a `.env` file in the project root. Add only the providers and keys available to you.

```dotenv
# ── Groq: primary fast/balanced tier ──
GROQ_API_KEY_1=gsk_your_key_1
GROQ_API_KEY_2=gsk_your_key_2
GROQ_API_KEY_3=gsk_your_key_3
GROQ_API_KEY_4=gsk_your_key_4
GROQ_MODEL=openai/gpt-oss-120b

# ── Google Gemini: reasoning tier ──
GEMINI_API_KEY=AIzaSy_your_gemini_key
GEMINI_MODEL=gemini-3.1-flash-lite

# ── Hugging Face: strong/final-verdict tier ──
HF_TOKEN=hf_your_token
HF_MODEL=Qwen/Qwen2.5-72B-Instruct
HF_MODEL_FALLBACK=Qwen/Qwen2.5-32B-Instruct
HF_BASE_URL=https://router.huggingface.co/v1

# ── Scheduler tuning ──
SCHEDULER_MAX_CONCURRENCY=6
SCHEDULER_BATCH_SIZE=8
SCHEDULER_INTER_BATCH_DELAY=0.3
SCHEDULER_PROVIDER_COOLDOWN=30
```

> **Security:** Never commit `.env` or live API keys to source control. Use `.env.example` as a template for new environments.

---

## 🚀 Running the application

### Interactive web UI

```bash
streamlit run app.py
```

Then open the local URL printed by Streamlit, normally:

```text
http://localhost:8501
```

### Command-line demo

```bash
python run_m1_demo.py
```

---

## 🧪 Testing

Run the complete test suite:

```bash
python -m pytest -v
```

Run individual areas:

```bash
# M3 verification tests
python -m pytest tests/test_verification.py -v

# M1 orchestrator tests
python -m pytest m1/tests/ -v

# M4 frontend and storage tests
python -m pytest m4/tests/test_m4.py -v
```

The project currently documents **60+ tests** across the M1, M3, and M4 components.

---

## 📊 Example verdict

```text
========================================================================
  FINAL VERDICT
========================================================================

  Verdict:    PARTIALLY_SUPPORTED (SUPPORTED_WITH_LIMITATIONS)
  Confidence: HIGH

  Summary:
  The analyzed evidence generally supports the claim that AI-assisted
  learning improves student performance, but effect magnitude varies
  significantly by educational level, subject area, and implementation
  context. The conclusion should not be interpreted as universally
  applicable across all settings.

  Detailed reasoning:
  1. OVERALL EVIDENCE DIRECTION: Strongly leans toward supporting the
     claim (9 supporting, 0 contradicting, 1 neutral across 10
     independent groups).
  2. MAIN SUPPORTING EVIDENCE: 8 meta-analyses/systematic reviews.
     10 sources classified as high-quality.
  3. LIMITING EVIDENCE: 1 contextual variation pair; 1 neutral finding.
  4. CONTRADICTION STATUS: No genuine contradiction identified among
     comparable evidence contexts.
  5. SCOPE: Broad enough for general conclusions; effect sizes vary.
  6. CALIBRATED CONFIDENCE: HIGH (8 meta-analyses).
```

---

## 🔌 Programmatic API

### M1 investigation engine

```python
from m1 import InvestigationEngine, InvestigationRequest

engine = InvestigationEngine()

result = engine.run(
    InvestigationRequest(
        question="Does AI-assisted learning improve student performance?",
        max_rounds=3,
    )
)

print(result.status)         # COMPLETED
print(result.verdict)        # FinalVerdict Pydantic object
print(result.evidence_count) # Number of retrieved evidence items
print(result.time_taken)     # Example: 12.4s
```

### M2 search contract

M2 retrieval agents return a list of `RawEvidence` objects:

```python
from verification import RawEvidence, SourceType

evidence = [
    RawEvidence(
        source_id="ARXIV-2025-001",
        title="Adaptive AI Tutoring in Secondary Mathematics",
        relevant_passage="Students showed 12% improvement...",
        url="https://arxiv.org/abs/2025.001",
        study_design="RCT",
        sample_size=800,
        source_type=SourceType.PEER_REVIEWED,
        peer_reviewed=True,
        year=2025,
    )
]
```

---

## 📁 Project structure

```text
ai-research-evidence-system/
├── verification/                 # M3 — Evidence Verification Pipeline
│   ├── models.py                 # Pydantic schemas
│   ├── pipeline.py               # Main verification orchestrator
│   ├── decomposer.py             # Question decomposition
│   ├── evidence_analyzer.py      # Batched evidence analysis
│   ├── contradiction.py          # Context-aware contradiction detection
│   ├── verifier.py               # Deterministic sufficiency checks
│   ├── judge.py                  # Calibrated verdict generation
│   ├── scheduler.py              # High-throughput request scheduler
│   ├── task_router.py            # Task-aware model routing
│   ├── source_identity.py        # Deduplication and source grouping
│   ├── weighting.py               # Evidence quality scoring
│   ├── llm_client.py              # LLM provider abstraction
│   └── calibration.py             # Verdict calibration layer
│
├── m1/                           # M1 — Research Investigation Orchestrator
│   ├── engine.py                  # Main investigation engine
│   ├── router.py                  # Intent and complexity classification
│   ├── planner.py                 # Balanced query planning
│   ├── gateway.py                 # Multi-provider LLM gateway
│   ├── cache.py                   # Investigation cache
│   ├── state.py                   # State management
│   ├── config.py                  # Configuration and environment
│   └── mock_m2.py                 # Mock M2 for testing
│
├── m4/                           # M4 — Frontend, Database, and Cache
│   ├── database.py                # SQLite source of truth
│   ├── semantic_cache.py          # Persistent semantic cache
│   ├── evidence_store.py          # Evidence vector store
│   ├── embeddings.py              # Shared embedding-model singleton
│   ├── verdict_formatter.py       # Verdict display formatting
│   ├── engine_integration.py      # M1 ↔ M4 bridge
│   └── config.py                  # Storage paths and thresholds
│
├── app.py                         # Streamlit web application
├── run_m1_demo.py                 # CLI demo script
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment-variable template
└── tests/                         # Test suites
    ├── test_verification.py       # M3 tests
    └── m4/tests/test_m4.py        # M4 tests
```

---

## 👥 Team

| Member | Role | Responsibility | LinkedIn |
|---|---|---|---|
| [Mahadi Ur Rehman Siddiqui](https://www.linkedin.com/in/mahadi-ur-rehman-siddiqui-139b93386/) | M3 Lead & Architect | Evidence verification, contradiction detection, and verdict calibration | [Profile](https://www.linkedin.com/in/mahadi-ur-rehman-siddiqui-139b93386/) |
| [Abdul Rafay](https://www.linkedin.com/in/abdul-rafay19/) | M1 Orchestrator | Investigation planning, adaptive research loops, and LLM gateway | [Profile](https://www.linkedin.com/in/abdul-rafay19/) |
| [Maria Parveen](https://www.linkedin.com/in/maria-parveen-53678b401) | M2 Retrieval | Academic search APIs, evidence extraction, and source discovery | [Profile](https://www.linkedin.com/in/maria-parveen-53678b401) |
| [Ayesha Masood](https://www.linkedin.com/in/ayesha-maqsood-9074592aa/) | M4 Frontend | Streamlit UI, SQLite database, and semantic caching | [Profile](https://www.linkedin.com/in/ayesha-maqsood-9074592aa/) |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

<div align="center">

Built for the AI Research Verification Hackathon

</div>
