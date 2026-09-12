"""
tests/test_providers.py — Provider integration tests.

Cerebras removed. OpenRouter (:free) is the alternative.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from m1.config import CONFIG, get_configured_providers
from m1.gateway import LLMGateway, _OpenRouterProvider, _GroqProvider
from m1.errors import LLMPermanentError, LLMTransientError
from verification.scheduler import RequestScheduler
from verification.task_router import TaskRouter, TIER_PREFERENCES
from verification.models import FinalVerdict, VerdictType, Confidence


def _fresh_scheduler():
    return RequestScheduler(
        max_concurrency=2,
        batch_delay=0.1,
        max_retries=1,
        base_retry_delay=0.05,
        cooldown_seconds=5.0,
    )


class MockProvider:
    def __init__(self, name, model="mock-model", behavior="success"):
        self.name = name
        self.model = model
        self.behavior = behavior
        self.call_count = 0

    def structured(self, system, user, model, timeout=None):
        self.call_count += 1
        if self.behavior == "success":
            return FinalVerdict(
                original_question="Q",
                verdict=VerdictType.SUPPORTED,
                confidence=Confidence.HIGH,
                summary=f"OK from {self.name}",
                detailed_reasoning="test",
            )
        elif self.behavior == "timeout":
            raise TimeoutError(f"Connection timed out on {self.name}")
        elif self.behavior == "rate_limit":
            raise Exception(f"429 rate limit exceeded on {self.name}")
        elif self.behavior == "permanent_402":
            raise Exception(f"402 Payment Required on {self.name}")
        elif self.behavior == "permanent":
            raise Exception(f"401 unauthorized on {self.name}")
        raise Exception(f"generic error on {self.name}")

    def text(self, system, user, timeout=None):
        self.call_count += 1
        if self.behavior == "success":
            return f"OK from {self.name}"
        raise Exception(f"error on {self.name}")


# ── Tests ────────────────────────────────────

def test_1_openrouter_provider_initializes_with_free_model():
    provider = _OpenRouterProvider(
        api_key="test-key",
        model="meta-llama/llama-3.3-70b-instruct:free",
        timeout=10.0,
        site_url="https://example.com",
        app_name="Test App",
    )
    assert provider.name.startswith("openrouter")
    assert provider.model == "meta-llama/llama-3.3-70b-instruct:free"
    assert provider.model.endswith(":free")


def test_2_openrouter_paid_model_logs_warning(caplog):
    """Non-free model should log a warning but still initialize."""
    import logging
    caplog.set_level(logging.WARNING)
    provider = _OpenRouterProvider(
        api_key="test-key",
        model="openai/gpt-4-turbo",  # Not free!
        timeout=10.0,
    )
    assert provider.model == "openai/gpt-4-turbo"
    assert any("does not end with ':free'" in r.message for r in caplog.records)


def test_3_missing_api_keys_disable_providers_gracefully(monkeypatch):
    """When no keys are set, provider chain is empty but gateway doesn't crash."""
    import m1.config
    import m1.gateway
    from m1.config import Config

    # ★ Clean config instance without Cerebras
    empty_config = Config(
        GROQ_API_KEY_1="",
        GROQ_API_KEY_2="",
        GROQ_API_KEY_3="",
        GROQ_API_KEY_4="",
        GEMINI_API_KEY="",
        OPENROUTER_API_KEY="",
        HF_TOKEN="",
    )
    monkeypatch.setattr(m1.config, "CONFIG", empty_config)
    monkeypatch.setattr(m1.gateway, "CONFIG", empty_config)

    gw = m1.gateway.LLMGateway()
    assert gw.has_providers() is False


def test_4_cerebras_no_longer_in_tier_preferences():
    """Cerebras must NOT appear in any tier preference list."""
    for tier, prefs in TIER_PREFERENCES.items():
        assert "cerebras" not in prefs, f"cerebras still in {tier}"


def test_5_openrouter_in_tier_preferences():
    """OpenRouter should appear in all 4 tier preferences."""
    for tier, prefs in TIER_PREFERENCES.items():
        assert "openrouter" in prefs, f"openrouter missing from {tier}"


def test_6_timeout_rotates_to_next_provider():
    scheduler = _fresh_scheduler()
    gw = LLMGateway(scheduler=scheduler)

    openrouter = MockProvider("openrouter(free)", behavior="timeout")
    gemini = MockProvider("gemini(x)", behavior="success")
    gw._providers = [openrouter, gemini]
    gw._provider_map = {p.name: p for p in gw._providers}

    gw._task_router.select_providers = lambda t, avail, cooled_down_providers=None: [
        p for p in ["openrouter(free)", "gemini(x)"] if p in avail
    ]

    result = gw.structured_call(
        system="s", user="u",
        response_model=FinalVerdict,
        task_type="final_verdict",
    )

    assert openrouter.call_count == 1
    assert gemini.call_count == 1
    assert result.summary == "OK from gemini(x)"


def test_7_http_402_fails_fast_no_retries():
    """HTTP 402 Payment Required = permanent, no retries on same provider."""
    scheduler = _fresh_scheduler()
    gw = LLMGateway(scheduler=scheduler)

    openrouter = MockProvider("openrouter(paid)", behavior="permanent_402")
    groq = MockProvider("groq-1", behavior="success")
    gw._providers = [openrouter, groq]
    gw._provider_map = {p.name: p for p in gw._providers}

    gw._task_router.select_providers = lambda t, avail, cooled_down_providers=None: [
        p for p in ["openrouter(paid)", "groq-1"] if p in avail
    ]

    result = gw.structured_call(
        system="s", user="u",
        response_model=FinalVerdict,
        task_type="final_verdict",
    )

    assert openrouter.call_count == 1, f"Expected 1 call, got {openrouter.call_count}"
    assert groq.call_count == 1
    assert result.summary == "OK from groq-1"


def test_8_http_401_fails_fast_no_retries():
    """HTTP 401 = permanent, no retries."""
    scheduler = _fresh_scheduler()
    gw = LLMGateway(scheduler=scheduler)

    bad = MockProvider("openrouter(bad)", behavior="permanent")
    good = MockProvider("groq-1", behavior="success")
    gw._providers = [bad, good]
    gw._provider_map = {p.name: p for p in gw._providers}

    gw._task_router.select_providers = lambda t, avail, cooled_down_providers=None: [
        p for p in ["openrouter(bad)", "groq-1"] if p in avail
    ]

    gw.structured_call(
        system="s", user="u",
        response_model=FinalVerdict,
        task_type="final_verdict",
    )

    assert bad.call_count == 1
    assert good.call_count == 1


def test_9_openrouter_final_verdict_success():
    scheduler = _fresh_scheduler()
    gw = LLMGateway(scheduler=scheduler)

    openrouter = MockProvider(
        "openrouter(meta-llama/llama-3.3-70b-instruct:free)",
        model="meta-llama/llama-3.3-70b-instruct:free",
        behavior="success",
    )
    gw._providers = [openrouter]
    gw._provider_map = {openrouter.name: openrouter}
    gw._task_router.select_providers = (
        lambda t, avail, cooled_down_providers=None: [openrouter.name]
    )

    result = gw.structured_call(
        system="s", user="u",
        response_model=FinalVerdict,
        task_type="final_verdict",
    )
    assert result.summary == f"OK from {openrouter.name}"


def test_10_metadata_recorded_after_openrouter_402_fallback():
    """Metadata should reflect fallback from OpenRouter (402) to Groq."""
    scheduler = _fresh_scheduler()
    gw = LLMGateway(scheduler=scheduler)

    openrouter = MockProvider("openrouter(free)", behavior="permanent_402")
    groq = MockProvider("groq-1", behavior="success")
    gw._providers = [openrouter, groq]
    gw._provider_map = {p.name: p for p in gw._providers}
    gw._task_router.select_providers = lambda t, avail, cooled_down_providers=None: [
        p for p in ["openrouter(free)", "groq-1"] if p in avail
    ]

    gw.structured_call(
        system="s", user="u",
        response_model=FinalVerdict,
        task_type="final_verdict",
    )

    meta = gw.get_last_call_metadata()
    assert meta["provider"] == "groq-1"
    assert meta["fallback_used"] is True
    assert meta["fallback_from"] == "openrouter(free)"


def test_11_existing_groq_behavior_preserved():
    scheduler = _fresh_scheduler()
    gw = LLMGateway(scheduler=scheduler)

    groq = MockProvider("groq-1", behavior="success")
    gw._providers = [groq]
    gw._provider_map = {"groq-1": groq}
    gw._task_router.select_providers = (
        lambda t, avail, cooled_down_providers=None: ["groq-1"]
    )

    result = gw.structured_call(
        system="s", user="u",
        response_model=FinalVerdict,
        task_type="classification",
    )
    assert result.summary == "OK from groq-1"
    assert groq.call_count == 1


def test_12_no_infinite_retry_on_permanent_error():
    """Permanent errors should never cause infinite loops."""
    scheduler = _fresh_scheduler()
    gw = LLMGateway(scheduler=scheduler, max_retries_per_provider=3)

    p1 = MockProvider("p1", behavior="permanent_402")
    p2 = MockProvider("p2", behavior="permanent_402")
    gw._providers = [p1, p2]
    gw._provider_map = {p.name: p for p in gw._providers}
    gw._task_router.select_providers = (
        lambda t, avail, cooled_down_providers=None: ["p1", "p2"]
    )

    with pytest.raises((LLMPermanentError, LLMTransientError, Exception)):
        gw.structured_call(
            system="s", user="u",
            response_model=FinalVerdict,
            task_type="final_verdict",
        )

    assert p1.call_count == 1
    assert p2.call_count == 1