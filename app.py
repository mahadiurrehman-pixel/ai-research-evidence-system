"""
app.py — Reality Checker Streamlit UI.

Unified M4 frontend using:
- m4.database (SQLite source of truth)
- m4.semantic_cache (persistent Chroma cache)
- m4.evidence_store (persistent Chroma evidence)
- m4.engine_integration (real M1 InvestigationEngine)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from m4 import (
    delete_investigation,
    format_verdict_for_display,
    get_evidence_store,
    get_history,
    get_investigation,
    get_semantic_cache,
    init_database,
    run_investigation,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)

# ── Page config ───────────────────────────────

st.set_page_config(
    page_title="Reality Checker",
    page_icon="🔍",
    layout="wide",
)

init_database()


@st.cache_resource
def _init_stores():
    """Warm up shared singletons once."""
    return {
        "cache": get_semantic_cache(),
        "evidence": get_evidence_store(),
    }


stores = _init_stores()

# ── Header ────────────────────────────────────

st.title("🔍 Reality Checker")
st.caption("AI Research Verification Platform (M1 + M3 + M4)")

# ── Sidebar ───────────────────────────────────

page = st.sidebar.radio("Navigation", ["Research", "History", "Evidence Search", "Stats"])

st.sidebar.markdown("---")
st.sidebar.metric("Cached queries", stores["cache"].count())
st.sidebar.metric("Stored evidence", stores["evidence"].count())


# ── Helpers ───────────────────────────────────

def _render_verdict(verdict_data, evidence_count: int, rounds: int, time_taken: str):
    display = format_verdict_for_display(verdict_data)

    color_map = {
        "SUPPORTED": "🟢",
        "PARTIALLY_SUPPORTED": "🟡",
        "CONTRADICTED": "🔴",
        "NOT_SUPPORTED": "🟠",
        "INCONCLUSIVE": "⚪",
    }
    icon = color_map.get(display["verdict"], "🔵")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Verdict", f"{icon} {display['verdict']}")
    col2.metric("Confidence", display["confidence"])
    col3.metric("Rounds", rounds)
    col4.metric("Evidence", evidence_count)

    st.subheader("📝 Summary")
    st.info(display["summary"])

    if display["detailed_reasoning"]:
        with st.expander("🔬 Detailed Reasoning"):
            st.markdown(display["detailed_reasoning"])

    if display["supporting_evidence"]:
        with st.expander(f"✅ Supporting Evidence ({len(display['supporting_evidence'])})"):
            for c in display["supporting_evidence"]:
                sid = c.get("source_id", "?")
                title = c.get("title", "")
                claim = c.get("claim", "")
                st.markdown(f"- **[{sid}]** {title}\n  \n  > {claim}")

    if display["contradicting_evidence"]:
        with st.expander(f"❌ Contradicting Evidence ({len(display['contradicting_evidence'])})"):
            for c in display["contradicting_evidence"]:
                sid = c.get("source_id", "?")
                title = c.get("title", "")
                claim = c.get("claim", "")
                st.markdown(f"- **[{sid}]** {title}\n  \n  > {claim}")

    if display["limitations"]:
        with st.expander(f"⚠️ Limitations ({len(display['limitations'])})"):
            for lim in display["limitations"]:
                st.markdown(f"- {lim}")

    st.caption(f"⏱️ Time taken: {time_taken or 'n/a'}")


# ── RESEARCH PAGE ─────────────────────────────

if page == "Research":
    st.header("🔎 Research Verification")

    question = st.text_area(
        "Research claim or question",
        placeholder="Example: Does AI-assisted learning improve student performance?",
        height=120,
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        max_rounds = st.slider("Max research rounds", 1, 3, 3)
    with col2:
        use_cache = st.checkbox("Use semantic cache", value=True)

    if st.button("Verify Research 🔍", type="primary"):
        if not question.strip():
            st.warning("Please enter a research question first.")
        else:
            with st.spinner("Running investigation…"):
                try:
                    outcome = run_investigation(
                        question=question,
                        max_rounds=max_rounds,
                        use_cache=use_cache,
                    )
                except Exception as e:
                    st.error(f"Investigation failed: {e}")
                    st.stop()

            record = outcome["record"]

            if outcome["from_cache"]:
                freshness = outcome["cache_freshness"]
                distance = outcome["cache_distance"] or 0.0
                if freshness == "FRESH":
                    st.success(f"♻️ Served from cache (distance={distance:.3f})")
                else:
                    st.warning(f"♻️ Cache STALE (distance={distance:.3f}) — consider re-running")
            else:
                st.success("🆕 New investigation completed and saved.")

            st.markdown(f"**Investigation ID:** `{record.investigation_id}`")

            _render_verdict(
                outcome["verdict_dict"],
                evidence_count=record.evidence_count,
                rounds=record.rounds_used,
                time_taken=record.time_taken,
            )


# ── HISTORY PAGE ──────────────────────────────

elif page == "History":
    st.header("📚 Research History")

    history = get_history(limit=50)
    if not history:
        st.info("No research history yet.")
    else:
        st.write(f"Showing {len(history)} recent investigations.")

        for record in history:
            with st.expander(
                f"🔍 {record.question[:80]} — {record.verdict_type} ({record.created_at})"
            ):
                col1, col2, col3 = st.columns(3)
                col1.markdown(f"**Verdict:** {record.verdict_type}")
                col2.markdown(f"**Confidence:** {record.confidence}")
                col3.markdown(f"**Status:** {record.status}")

                st.caption(f"ID: `{record.investigation_id}` | Evidence: {record.evidence_count} | Rounds: {record.rounds_used}")

                if record.summary:
                    st.write(record.summary)

                if st.button("🗑️ Delete", key=f"del_{record.investigation_id}"):
                    delete_investigation(record.investigation_id)
                    st.rerun()

                if st.button("👀 View full verdict", key=f"view_{record.investigation_id}"):
                    _render_verdict(
                        record.verdict_json,
                        evidence_count=record.evidence_count,
                        rounds=record.rounds_used,
                        time_taken=record.time_taken,
                    )


# ── EVIDENCE SEARCH PAGE ──────────────────────

elif page == "Evidence Search":
    st.header("📖 Search Stored Evidence")

    query = st.text_input("Search query", placeholder="e.g. AI tutoring effect on adult learners")
    top_k = st.slider("Results", 1, 20, 5)

    if st.button("Search"):
        results = get_evidence_store().search(query, top_k=top_k)
        if not results:
            st.info("No matching evidence found.")
        else:
            for i, r in enumerate(results, 1):
                meta = r["metadata"]
                title = meta.get("title", "")
                sid = meta.get("source_id", "?")
                inv_id = meta.get("investigation_id", "")
                st.markdown(f"### {i}. [{sid}] {title}")
                st.write(r["text"])
                st.caption(f"Distance: {r['distance']:.3f} | Investigation: {inv_id}")
                st.divider()


# ── STATS PAGE ────────────────────────────────

elif page == "Stats":
    st.header("📊 System Stats")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total investigations", len(get_history(limit=10000)))
    col2.metric("Cached queries", stores["cache"].count())
    col3.metric("Stored evidence", stores["evidence"].count())