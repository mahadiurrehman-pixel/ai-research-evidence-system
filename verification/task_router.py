"""
verification/task_router.py — Centralized Task-Aware Model Routing.

Maps task types to provider tiers and reorders the provider chain
so each task uses the most suitable available model.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Task → Tier Mapping ──────────────────────

TASK_POLICY: Dict[str, str] = {
    # FAST — simple, high-volume, low-complexity
    "decomposition": "fast",
    "search_planning": "fast",
    "classification": "fast",
    "normalization": "fast",
    "query_generation": "fast",
    "formatting": "fast",
    "metadata_extraction": "fast",

    # BALANCED — moderate complexity
    "evidence_extraction": "balanced",
    "evidence_summarization": "balanced",
    "deduplication": "balanced",
    "contradiction_candidate": "balanced",
    "evidence_grouping": "balanced",

    # REASONING — requires careful analysis
    "contradiction_detection": "reasoning",
    "evidence_comparison": "reasoning",
    "evidence_weighting": "reasoning",
    "context_comparison": "reasoning",
    "reliability_analysis": "reasoning",

    # STRONG — critical, complex reasoning
    "contradiction_verification": "strong",
    "cross_source_reasoning": "strong",
    "final_synthesis": "strong",
    "final_verdict": "strong",
}

# ── Tier → Provider Preference Order ─────────

TIER_PREFERENCES: Dict[str, List[str]] = {
    "fast": [
        "groq",          # Fastest, cheapest
        "gemini",        # Good fallback
        "hf-32b",        # Lighter HF model
        "hf-72b",        # Heavier but available
    ],
    "balanced": [
        "groq",          # Still fast enough
        "gemini",        # Good reasoning
        "hf-72b",        # Strong if needed
        "hf-32b",
    ],
    "reasoning": [
        "gemini",        # Best reasoning/price ratio
        "hf-72b",        # Strong reasoning
        "groq",          # Fallback
        "hf-32b",
    ],
    "strong": [
        "gemini",        # ★ Gemini first for final verdict & strong tasks
        "groq",          # ★ Then Groq keys
        "hf-32b",        # ★ Then HuggingFace fallback
        "hf-72b",        # ★ Last resort fallback
    ],
}


def _provider_matches_prefix(provider_name: str, prefix: str) -> bool:
    """Check if a provider name matches a tier preference prefix."""
    name = provider_name.lower()
    prefix = prefix.lower()

    if prefix == "groq":
        return name.startswith("groq")
    elif prefix == "gemini":
        return name.startswith("gemini")
    elif prefix == "hf-72b":
        return "hf" in name and "72b" in name
    elif prefix == "hf-32b":
        return "hf" in name and "32b" in name
    elif prefix == "hf":
        return name.startswith("hf")
    else:
        return prefix in name


class TaskRouter:
    """
    Centralized task-aware provider router.
    """

    def __init__(self):
        self._stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "fallbacks": 0, "cooldowns": 0}
        )
        self._task_counts: Dict[str, int] = defaultdict(int)

    def get_tier(self, task_type: str) -> str:
        """Get the tier for a task type. Defaults to 'balanced' for unknown tasks."""
        return TASK_POLICY.get(task_type, "balanced")

    def select_providers(
        self,
        task_type: str,
        available_providers: List[str],
        cooled_down_providers: Optional[set] = None,
    ) -> List[str]:
        if not available_providers:
            return []

        cooled = cooled_down_providers or set()
        tier = self.get_tier(task_type)
        preferences = TIER_PREFERENCES.get(tier, TIER_PREFERENCES["balanced"])

        # Score each provider (lower = better)
        def _score(provider_name: str) -> Tuple[int, int]:
            # First sort key: position in preference list
            pref_score = len(preferences)  # default: worst
            for i, prefix in enumerate(preferences):
                if _provider_matches_prefix(provider_name, prefix):
                    pref_score = i
                    break

            # Second sort key: cooldown status (cooled providers go last)
            cooldown_penalty = 1 if provider_name in cooled else 0

            return (cooldown_penalty, pref_score)

        ordered = sorted(available_providers, key=_score)

        # Log routing decision
        active = [p for p in ordered if p not in cooled]
        primary = active[0] if active else ordered[0]
        self._task_counts[task_type] += 1

        logger.info(
            "[TASK ROUTER] task=%-28s tier=%-8s provider=%-12s (available: %s)",
            task_type, tier, primary, ", ".join(ordered),
        )

        return ordered

    def record_call(
        self,
        task_type: str,
        provider: str,
        was_fallback: bool = False,
    ) -> None:
        """Record a completed call for usage statistics."""
        self._stats[provider]["calls"] += 1
        if was_fallback:
            self._stats[provider]["fallbacks"] += 1

    def record_cooldown(self, provider: str) -> None:
        """Record a 429 cooldown event."""
        self._stats[provider]["cooldowns"] += 1

    def get_usage_summary(self) -> Dict[str, dict]:
        """Return provider usage statistics."""
        return {
            "providers": dict(self._stats),
            "tasks": dict(self._task_counts),
        }

    def print_usage_summary(self) -> None:
        """Print a formatted usage summary to the logger."""
        logger.info("=" * 60)
        logger.info("  📊 PROVIDER USAGE SUMMARY")
        logger.info("=" * 60)

        if not self._stats:
            logger.info("  No calls recorded.")
            return

        logger.info("  %-15s %6s %10s %10s", "Provider", "Calls", "Fallbacks", "Cooldowns")
        logger.info("  " + "-" * 45)
        for provider, stats in sorted(self._stats.items()):
            logger.info(
                "  %-15s %6d %10d %10d",
                provider,
                stats["calls"],
                stats["fallbacks"],
                stats["cooldowns"],
            )

        logger.info("")
        logger.info("  Task distribution:")
        for task, count in sorted(self._task_counts.items(), key=lambda x: -x[1]):
            tier = self.get_tier(task)
            logger.info("    %-30s tier=%-8s calls=%d", task, tier, count)
        logger.info("=" * 60)


# ── Global Default Router ────────────────────

_default_router: Optional[TaskRouter] = None


def get_default_task_router() -> TaskRouter:
    """Get or create the global TaskRouter singleton."""
    global _default_router
    if _default_router is None:
        _default_router = TaskRouter()
    return _default_router