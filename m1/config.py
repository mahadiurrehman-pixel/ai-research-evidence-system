"""
m1/config.py — Configuration + environment loading.

Providers: Groq (4 keys) + Gemini + OpenRouter (free model) + HuggingFace.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv()
from dataclasses import dataclass


def _get_openrouter_model() -> str:
    raw = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    # Remap deprecated/paid slugs automatically
    if raw in ("openai/gpt-oss-120b:free", "openai/gpt-oss-120b", ""):
        return "meta-llama/llama-3.3-70b-instruct:free"
    return raw


@dataclass(frozen=True)
class Config:
    # ── Groq (4 keys for high-throughput fast tier) ──
    GROQ_API_KEY_1: str = os.getenv("GROQ_API_KEY_1", "") or os.getenv("GROQ_API_KEY", "")
    GROQ_API_KEY_2: str = os.getenv("GROQ_API_KEY_2", "")
    GROQ_API_KEY_3: str = os.getenv("GROQ_API_KEY_3", "")
    GROQ_API_KEY_4: str = os.getenv("GROQ_API_KEY_4", "")
    GROQ_BASE_URL: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    # ── Gemini ──
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # ── OpenRouter (FREE MODEL ONLY) ──
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = _get_openrouter_model()
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OPENROUTER_SITE_URL: str = os.getenv("OPENROUTER_SITE_URL", "")
    OPENROUTER_APP_NAME: str = os.getenv(
        "OPENROUTER_APP_NAME",
        "AI Research Evidence Verification System",
    )

    # ── HuggingFace (optional fallback) ──
    HF_TOKEN: str = os.getenv("HF_TOKEN", "")
    HF_MODEL: str = os.getenv("HF_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    HF_MODEL_FALLBACK: str = os.getenv("HF_MODEL_FALLBACK", "Qwen/Qwen2.5-32B-Instruct")
    HF_BASE_URL: str = os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1")

    LLM_TEMPERATURE: float = 0.2

    # ── Scheduler tuning ──
    SCHEDULER_MAX_CONCURRENCY: int = int(os.getenv("SCHEDULER_MAX_CONCURRENCY", "6"))
    SCHEDULER_BATCH_SIZE: int = int(os.getenv("SCHEDULER_BATCH_SIZE", "8"))
    SCHEDULER_INTER_BATCH_DELAY: float = float(os.getenv("SCHEDULER_INTER_BATCH_DELAY", "0.3"))
    SCHEDULER_PROVIDER_COOLDOWN: float = float(os.getenv("SCHEDULER_PROVIDER_COOLDOWN", "30"))

    # ── Task-specific timeouts ──
    TIMEOUT_QUERY_GENERATION: float = float(os.getenv("TIMEOUT_QUERY_GENERATION", "15.0"))
    TIMEOUT_EVIDENCE_ANALYSIS: float = float(os.getenv("TIMEOUT_EVIDENCE_ANALYSIS", "30.0"))
    TIMEOUT_CONTRADICTION_PAIRS: float = float(os.getenv("TIMEOUT_CONTRADICTION_PAIRS", "30.0"))
    TIMEOUT_FINAL_VERDICT: float = float(os.getenv("TIMEOUT_FINAL_VERDICT", "45.0"))

    # ── Standard timeouts ──
    LLM_TIMEOUT: float = 30.0
    M2_TIMEOUT: float = 20.0
    M3_TIMEOUT: float = 60.0
    ROUND_TIMEOUT: float = 90.0
    TOTAL_TIMEOUT: float = 180.0

    # ── Rounds ──
    DEFAULT_MAX_ROUNDS: int = 3
    SIMPLE_MAX_ROUNDS: int = 1
    MODERATE_MAX_ROUNDS: int = 2
    COMPLEX_MAX_ROUNDS: int = 3

    # ── M2 ──
    M2_MAX_RESULTS_PER_QUERY: int = 8
    M2_MAX_QUERIES_PER_ROUND: int = 5
    M2_RETRY_ATTEMPTS: int = 2
    M2_RETRY_DELAY: float = 3.0

    # ── Cache ──
    CACHE_FRESH_HOURS: int = 24
    CACHE_STALE_HOURS: int = 72


CONFIG = Config()


def has_llm_available() -> bool:
    """True if at least one LLM provider is configured."""
    return bool(
        CONFIG.GROQ_API_KEY_1
        or CONFIG.GROQ_API_KEY_2
        or CONFIG.GROQ_API_KEY_3
        or CONFIG.GROQ_API_KEY_4
        or CONFIG.GEMINI_API_KEY
        or CONFIG.OPENROUTER_API_KEY
        or CONFIG.HF_TOKEN
    )


def get_configured_providers() -> list[str]:
    """Return list of provider names with keys configured."""
    providers = []
    for i, key in enumerate([
        CONFIG.GROQ_API_KEY_1, CONFIG.GROQ_API_KEY_2,
        CONFIG.GROQ_API_KEY_3, CONFIG.GROQ_API_KEY_4,
    ], start=1):
        if key:
            providers.append(f"groq-{i}")
    if CONFIG.GEMINI_API_KEY:
        providers.append(f"gemini({CONFIG.GEMINI_MODEL})")
    if CONFIG.OPENROUTER_API_KEY:
        providers.append(f"openrouter({CONFIG.OPENROUTER_MODEL})")
    if CONFIG.HF_TOKEN:
        providers.append(f"hf({CONFIG.HF_MODEL})")
    return providers


def validate_openrouter_free_model() -> bool:
    """Ensures the configured OpenRouter model uses the ':free' variant."""
    if not CONFIG.OPENROUTER_API_KEY:
        return True
    return CONFIG.OPENROUTER_MODEL.endswith(":free")