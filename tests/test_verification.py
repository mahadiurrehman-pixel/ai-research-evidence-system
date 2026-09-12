"""
verification/task_router.py — Task-Aware Model Routing.

Cerebras removed due to HTTP 402 payment errors.
OpenRouter (free model) added to appropriate tiers.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


TASK_POLICY: Dict[str, str] = {
    "decomposition": "fast",
    "search_planning": "fast",
    "classification": "fast",
    "normalization": "fast",
    "query_generation": "fast",
    "formatting": "fast",
    "metadata_extraction": "fast",
    "evidence_extraction": "balanced",
    "evidence_summarization": "balanced",
    "deduplication": "balanced",
    "contradiction_candidate": "balanced",
    "evidence_grouping": "balanced",
    "contradiction_detection": "reasoning",
    "evidence_comparison": "reasoning",
    "evidence_weighting": "reasoning",
    "context_comparison": "reasoning",
    "reliability_analysis": "reasoning",
    "contradiction_verification": "strong",
    "cross_source_reasoning": "strong",
    "final_synthesis": "strong",
    "final_verdict": "strong",
}


# ── Tier → Provider Preference ────────────────
# Cerebras removed. OpenRouter (:free) added to appropriate positions.

TIER_PREFERENCES: Dict[str, List[str]] = {
    "fast": [
        "groq",         # Fastest, highest throughput
        "openrouter",   # Free tier — good backup
        "gemini",       # Google fallback
        "hf-32b",
        "hf-72b",
    ],
    "balanced": [
        "groq",         # Fast + high throughput
        "gemini",       # Good reasoning
        "openrouter",   # Free tier fallback
        "hf-72b",
        "hf-32b",
    ],
    "reasoning": [
        "gemini",       # Best reasoning/price ratio
        "groq",         # Fast alternative
        "openrouter",   # Free tier — variable quality
        "hf-72b",
        "hf-32b",
    ],
    "strong": [
        "gemini",       # ★ Gemini first for final verdict
        "groq",         # ★ Groq second (fast + capable)
        "openrouter",   # ★ OpenRouter free tier
        "hf-72b",       # ★ HF as fallback
        "hf-32b",
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
    elif prefix == "openrouter":
        return name.startswith("openrouter")
    elif prefix == "hf-72b":
        return "hf" in name and "72b" in name
    elif prefix == "hf-32b":
        return "hf" in name and "32b" in name
    elif prefix == "hf":
        return name.startswith("hf")
    else:
        return prefix in name


class TaskRouter:
    def __init__(self):
        self._stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "fallbacks": 0, "cooldowns": 0}
        )
        self._task_counts: Dict[str, int] = defaultdict(int)

    def get_tier(self, task_type: str) -> str:
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

        def _score(provider_name: str) -> Tuple[int, int]:
            pref_score = len(preferences)
            for i, prefix in enumerate(preferences):
                if _provider_matches_prefix(provider_name, prefix):
                    pref_score = i
                    break
            cooldown_penalty = 1 if provider_name in cooled else 0
            return (cooldown_penalty, pref_score)

        ordered = sorted(available_providers, key=_score)
        active = [p for p in ordered if p not in cooled]
        primary = active[0] if active else ordered[0]
        self._task_counts[task_type] += 1

        logger.info(
            "[TASK ROUTER] task=%-28s tier=%-8s provider=%-30s",
            task_type, tier, primary,
        )
        return ordered

    def record_call(self, task_type: str, provider: str,
                    was_fallback: bool = False) -> None:
        self._stats[provider]["calls"] += 1
        if was_fallback:
            self._stats[provider]["fallbacks"] += 1

    def record_cooldown(self, provider: str) -> None:
        self._stats[provider]["cooldowns"] += 1

    def get_usage_summary(self) -> Dict[str, dict]:
        return {
            "providers": dict(self._stats),
            "tasks": dict(self._task_counts),
        }

    def print_usage_summary(self) -> None:
        logger.info("=" * 60)
        logger.info("  📊 PROVIDER USAGE SUMMARY")
        logger.info("=" * 60)
        if not self._stats:
            logger.info("  No calls recorded.")
            return

        logger.info("  %-30s %6s %10s %10s", "Provider", "Calls", "Fallbacks", "Cooldowns")
        logger.info("  " + "-" * 60)
        for provider, stats in sorted(self._stats.items()):
            logger.info(
                "  %-30s %6d %10d %10d",
                provider, stats["calls"], stats["fallbacks"], stats["cooldowns"],
            )

        logger.info("")
        logger.info("  Task distribution:")
        for task, count in sorted(self._task_counts.items(), key=lambda x: -x[1]):
            tier = self.get_tier(task)
            logger.info("    %-30s tier=%-8s calls=%d", task, tier, count)
        logger.info("=" * 60)


_default_router: Optional[TaskRouter] = None


def get_default_task_router() -> TaskRouter:
    global _default_router
    if _default_router is None:
        _default_router = TaskRouter()
    return _default_router