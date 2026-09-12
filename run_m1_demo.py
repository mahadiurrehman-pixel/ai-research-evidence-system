#!/usr/bin/env python3
"""
run_m1_demo.py — Full M1 → MockM2 → M3 pipeline demo.

Prerequisites:
  - verification/ module built (M3)
  - real_dataset.py at project root
  - Either GROQ_API_KEY_1 set for real LLM, or runs in deterministic fallback mode
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Logging ───────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-14s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)

from m1 import InvestigationEngine, InvestigationRequest, InvestigationStatus


def _print_banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def _print_verdict(v) -> None:
    if v is None:
        print("  (no verdict — investigation was direct/inconclusive)")
        return

    def _safe(attr, default="n/a"):
        val = getattr(v, attr, None)
        if val is None:
            return default
        if hasattr(val, "value"):
            return val.value
        return val

    print(f"  Verdict:    {_safe('verdict')}")
    print(f"  Confidence: {_safe('confidence')}")
    print(f"\n  Summary:\n    {_safe('summary', '(none)')}")

    reasoning = _safe("detailed_reasoning", "")
    if reasoning:
        print("\n  Detailed Reasoning:")
        for line in str(reasoning).splitlines():
            print(f"    {line}")

    supp = getattr(v, "supporting_evidence", []) or []
    if supp:
        print("\n  Supporting evidence:")
        for c in supp:
            sid = getattr(c, "source_id", "?")
            claim = str(getattr(c, "claim", ""))[:80]
            print(f"    ✅ [{sid}] {claim}")

    contra = getattr(v, "contradicting_evidence", []) or []
    if contra:
        print("\n  Contradicting evidence:")
        for c in contra:
            sid = getattr(c, "source_id", "?")
            claim = str(getattr(c, "claim", ""))[:80]
            print(f"    ❌ [{sid}] {claim}")

    lims = getattr(v, "limitations", []) or []
    if lims:
        print("\n  Limitations:")
        for lim in lims:
            print(f"    ⚠️  {lim}")


def main() -> None:
    _print_banner("🧠 M1 Research Investigation Orchestrator — Demo")

    # Environment check
    has_groq = bool(os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    print(f"  LLM providers: groq={has_groq} gemini={has_gemini}")
    if not (has_groq or has_gemini):
        print("  ⚠️  No LLM providers configured — using deterministic fallbacks.")

    engine = InvestigationEngine()

    question = "Does AI-assisted learning improve student performance"
    print(f"\n  Question: {question}")

    request = InvestigationRequest(question=question, max_rounds=3)
    result = engine.run(request)

    _print_banner("📊 Result")
    print(f"  Investigation ID : {result.investigation_id}")
    print(f"  Status           : {result.status.value}")
    print(f"  From cache       : {result.from_cache}")
    print(f"  Rounds used      : {result.rounds_used}")
    print(f"  Evidence count   : {result.evidence_count}")
    print(f"  Time taken       : {result.time_taken}")

    if result.route_metadata:
        rm = result.route_metadata
        print("\n  Route metadata:")
        print(f"    intent               : {rm.intent.value}")
        print(f"    domain               : {rm.domain}")
        print(f"    complexity           : {rm.complexity.value}")
        print(f"    investigation_level  : {rm.investigation_level.value}")
        print(f"    reason               : {rm.reason}")

    _print_banner("🏛️  Final Verdict")
    if result.status == InvestigationStatus.COMPLETED:
        _print_verdict(result.verdict)
    elif result.status == InvestigationStatus.NO_RESEARCH_NEEDED:
        print("  Direct answer regime — no research performed.")
    elif result.status == InvestigationStatus.INCONCLUSIVE:
        print("  Insufficient evidence to draw a conclusion.")
    elif result.status == InvestigationStatus.FAILED:
        print("  Investigation failed.")
        for err in result.errors:
            print(f"    error: {err}")

    _print_banner("📋 Trace")
    for i, event in enumerate(result.trace_summary, 1):
        print(f"  {i:2d}. {event}")


if __name__ == "__main__":
    main()
    # Print provider usage summary
    from verification.task_router import get_default_task_router
    task_router = get_default_task_router()
    task_router.print_usage_summary()