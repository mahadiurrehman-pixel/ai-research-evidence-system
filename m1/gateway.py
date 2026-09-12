"""
m1/gateway.py — Shared LLM Gateway with task-aware model routing and 4 Groq Keys.

Task routing:
    - Fast tasks      → Groq (groq-1, groq-2, groq-3, groq-4)
    - Reasoning      → Gemini
    - Strong tasks    → HuggingFace/Qwen
    - Automatic fallback on 429, timeout, unavailable model,
      connection errors, and transient errors.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Callable, Optional, Type, TypeVar

from pydantic import BaseModel

from verification.scheduler import (
    RequestScheduler,
    get_default_scheduler,
    is_rate_limit_error,
    is_timeout_error,
    is_connection_error,
    _extract_retry_after,
)

from verification.task_router import (
    TaskRouter,
    get_default_task_router,
)

from .config import CONFIG
from .errors import (
    LLMPermanentError,
    LLMProviderError,
    LLMTransientError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ============================================================
# Error Classification
# ============================================================

_PERMANENT_TOKENS = (
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
    "401",
    "forbidden",
    "403",
    "invalid_request",
    "billing",
    "insufficient_quota",
    "permission denied",
)

_MODEL_UNAVAILABLE_TOKENS = (
    "not found",
    "404",
    "model_not_found",
    "does not exist",
    "not supported",
    "unknown model",
    "model unavailable",
    "model is not available",
)


def _error_message(err: Exception) -> str:
    return str(err).lower()


def _classify(err: Exception) -> LLMProviderError:
    """
    Convert arbitrary provider exceptions into project-level errors.
    """
    if isinstance(err, LLMProviderError):
        return err

    message = _error_message(err)

    if any(token in message for token in _PERMANENT_TOKENS):
        return LLMPermanentError(str(err))

    return LLMTransientError(str(err))


def _is_model_unavailable(err: Exception) -> bool:
    """
    Detect errors indicating that selected model is unavailable.
    """
    message = _error_message(err)
    return any(
        token in message
        for token in _MODEL_UNAVAILABLE_TOKENS
    )


def _get_timeout_for_task(task_type: str) -> float:
    """Select the exact configured timeout limit for a specific task safely."""
    if task_type in ("query_generation", "decomposition", "search_planning", "classification"):
        return getattr(CONFIG, "TIMEOUT_QUERY_GENERATION", 30.0)
    elif task_type in ("evidence_analysis", "evidence_extraction"):
        return getattr(CONFIG, "TIMEOUT_EVIDENCE_ANALYSIS", 45.0)
    elif task_type in ("contradiction_detection", "contradiction_pairs"):
        return getattr(CONFIG, "TIMEOUT_CONTRADICTION_PAIRS", 45.0)
    elif task_type in ("final_verdict", "final_synthesis"):
        return getattr(CONFIG, "TIMEOUT_FINAL_VERDICT", 90.0)
    return getattr(CONFIG, "LLM_TIMEOUT", 30.0)

# ============================================================
# Provider Interface
# ============================================================

class _Provider:
    name: str = "base"

    def structured(
        self,
        system: str,
        user: str,
        model: Type[T],
        timeout: Optional[float] = None,
    ) -> T:
        raise NotImplementedError

    def text(
        self,
        system: str,
        user: str,
        timeout: Optional[float] = None,
    ) -> str:
        raise NotImplementedError


# ============================================================
# Groq Provider
# ============================================================

class _GroqProvider(_Provider):
    """
    OpenAI-compatible Groq provider.
    """

    def __init__(
        self,
        api_key: str,
        label: str,
        model: str,
        timeout: float,
    ):
        from openai import OpenAI

        self.name = label
        self._model = model
        self._default_timeout = timeout

        self._client = OpenAI(
            api_key=api_key,
            base_url=CONFIG.GROQ_BASE_URL,
            timeout=timeout,
            max_retries=0,
        )

    def structured(
        self,
        system: str,
        user: str,
        model: Type[T],
        timeout: Optional[float] = None,
    ) -> T:
        t = timeout if timeout is not None else self._default_timeout
        try:
            completion = self._client.beta.chat.completions.parse(
                model=self._model,
                temperature=CONFIG.LLM_TEMPERATURE,
                messages=[
                    {
                        "role": "system",
                        "content": system,
                    },
                    {
                        "role": "user",
                        "content": user,
                    },
                ],
                response_format=model,
                timeout=t,
            )

            parsed = getattr(
                completion.choices[0].message,
                "parsed",
                None,
            )

            if parsed is not None:
                return parsed

        except Exception as error:
            logger.debug(
                "[%s] Native structured output failed: %s",
                self.name,
                error,
            )

        schema_hint = (
            "\n\nRespond with ONLY valid JSON matching this schema:\n"
            f"{json.dumps(model.model_json_schema(), indent=2)}"
        )

        completion = self._client.chat.completions.create(
            model=self._model,
            temperature=CONFIG.LLM_TEMPERATURE,
            response_format={
                "type": "json_object",
            },
            messages=[
                {
                    "role": "system",
                    "content": system + schema_hint,
                },
                {
                    "role": "user",
                    "content": user,
                },
            ],
            timeout=t,
        )

        content = (
            completion.choices[0].message.content or ""
        ).strip()

        if not content:
            raise LLMTransientError(
                f"{self.name}: empty structured response"
            )

        try:
            payload = json.loads(content)
            return model.model_validate(payload)

        except Exception as error:
            raise LLMTransientError(
                f"{self.name}: invalid structured JSON: {error}"
            ) from error

    def text(
        self,
        system: str,
        user: str,
        timeout: Optional[float] = None,
    ) -> str:
        t = timeout if timeout is not None else self._default_timeout
        completion = self._client.chat.completions.create(
            model=self._model,
            temperature=CONFIG.LLM_TEMPERATURE,
            messages=[
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": user,
                },
            ],
            timeout=t,
        )

        content = (
            completion.choices[0].message.content or ""
        ).strip()

        if not content:
            raise LLMTransientError(
                f"{self.name}: empty text response"
            )

        return content


# ============================================================
# Gemini Provider
# ============================================================

class _GeminiProvider(_Provider):
    """
    Google Gemini provider using the currently installed
    google-generativeai compatibility package.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str,
        timeout: float,
    ):
        import google.generativeai as genai

        self._model_name = model_name
        self.name = f"gemini({model_name})"
        self._default_timeout = timeout

        genai.configure(api_key=api_key)

        self._model = genai.GenerativeModel(
            model_name=model_name,
        )

    def structured(
        self,
        system: str,
        user: str,
        model: Type[T],
        timeout: Optional[float] = None,
    ) -> T:
        t = timeout if timeout is not None else self._default_timeout
        schema_hint = (
            "\n\nRespond with ONLY valid JSON matching this schema:\n"
            f"{json.dumps(model.model_json_schema(), indent=2)}"
        )

        response = self._model.generate_content(
            f"{system}\n"
            f"{schema_hint}\n\n"
            f"USER:\n{user}",
            generation_config={
                "response_mime_type": "application/json",
                "temperature": CONFIG.LLM_TEMPERATURE,
            },
            request_options={"timeout": t},
        )

        content = (
            getattr(response, "text", "") or ""
        ).strip()

        if not content:
            raise LLMTransientError(
                f"{self.name}: empty structured response"
            )

        try:
            payload = json.loads(content)
            return model.model_validate(payload)

        except Exception as error:
            raise LLMTransientError(
                f"{self.name}: invalid structured JSON: {error}"
            ) from error

    def text(
        self,
        system: str,
        user: str,
        timeout: Optional[float] = None,
    ) -> str:
        t = timeout if timeout is not None else self._default_timeout
        response = self._model.generate_content(
            f"{system}\n\nUSER:\n{user}",
            request_options={"timeout": t},
        )

        content = (
            getattr(response, "text", "") or ""
        ).strip()

        if not content:
            raise LLMTransientError(
                f"{self.name}: empty text response"
            )

        return content


# ============================================================
# HuggingFace Provider
# ============================================================

class _HuggingFaceProvider(_Provider):
    """
    OpenAI-compatible HuggingFace Router provider.
    """

    def __init__(
        self,
        token: str,
        primary_model: str,
        fallback_model: Optional[str],
        base_url: str,
        timeout: float,
    ):
        from openai import OpenAI

        self._OpenAI = OpenAI
        self._token = token
        self._default_timeout = timeout

        self._base_url = self._normalize_base_url(base_url)

        self._primary = primary_model
        self._fallback = fallback_model

        self._current = primary_model
        self._switched = False

        self._client = self._make_client()
        self.name = f"hf({self._current})"

        logger.info(
            "HF endpoint normalized to: %s",
            self._base_url,
        )

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        url = (base_url or "").strip().rstrip("/")

        if not url:
            return "https://router.huggingface.co/v1"

        if "api-inference.huggingface.co" in url:
            logger.warning(
                "Deprecated HuggingFace endpoint detected. "
                "Switching to router.huggingface.co/v1"
            )
            return "https://router.huggingface.co/v1"

        if url == "https://router.huggingface.co":
            return "https://router.huggingface.co/v1"

        if not url.endswith("/v1"):
            url = f"{url}/v1"

        return url

    def _make_client(self):
        return self._OpenAI(
            api_key=self._token,
            base_url=self._base_url,
            timeout=self._default_timeout,
            max_retries=0,
        )

    def _try_switch(self) -> bool:
        if self._switched:
            return False

        if not self._fallback:
            return False

        logger.warning(
            "HF model '%s' unavailable → switching to '%s'",
            self._current,
            self._fallback,
        )

        self._current = self._fallback
        self._client = self._make_client()
        self.name = f"hf({self._current})"
        self._switched = True

        return True

    def _do_structured(
        self,
        system: str,
        user: str,
        model: Type[T],
        timeout: Optional[float] = None,
    ) -> T:
        t = timeout if timeout is not None else self._default_timeout
        schema_hint = (
            "\n\nRespond with ONLY valid JSON matching this schema:\n"
            f"{json.dumps(model.model_json_schema(), indent=2)}"
        )

        messages = [
            {
                "role": "system",
                "content": system + schema_hint,
            },
            {
                "role": "user",
                "content": user,
            },
        ]

        try:
            completion = self._client.chat.completions.create(
                model=self._current,
                temperature=CONFIG.LLM_TEMPERATURE,
                response_format={
                    "type": "json_object",
                },
                messages=messages,
                timeout=t,
            )

        except Exception as first_error:
            if is_connection_error(first_error):
                raise

            if is_timeout_error(first_error):
                raise

            logger.debug(
                "[%s] JSON response_format failed: %s",
                self.name,
                first_error,
            )

            completion = self._client.chat.completions.create(
                model=self._current,
                temperature=CONFIG.LLM_TEMPERATURE,
                messages=messages,
                timeout=t,
            )

        content = (
            completion.choices[0].message.content or ""
        ).strip()

        if not content:
            raise LLMTransientError(
                f"{self.name}: empty structured response"
            )

        try:
            payload = json.loads(content)
            return model.model_validate(payload)

        except Exception as error:
            raise LLMTransientError(
                f"{self.name}: invalid structured JSON: {error}"
            ) from error

    def structured(
        self,
        system: str,
        user: str,
        model: Type[T],
        timeout: Optional[float] = None,
    ) -> T:
        try:
            return self._do_structured(
                system,
                user,
                model,
                timeout=timeout,
            )

        except Exception as error:
            if (
                _is_model_unavailable(error)
                and self._try_switch()
            ):
                return self._do_structured(
                    system,
                    user,
                    model,
                    timeout=timeout,
                )

            raise

    def _do_text(
        self,
        system: str,
        user: str,
        timeout: Optional[float] = None,
    ) -> str:
        t = timeout if timeout is not None else self._default_timeout
        completion = self._client.chat.completions.create(
            model=self._current,
            temperature=CONFIG.LLM_TEMPERATURE,
            messages=[
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": user,
                },
            ],
            timeout=t,
        )

        content = (
            completion.choices[0].message.content or ""
        ).strip()

        if not content:
            raise LLMTransientError(
                f"{self.name}: empty text response"
            )

        return content

    def text(
        self,
        system: str,
        user: str,
        timeout: Optional[float] = None,
    ) -> str:
        try:
            return self._do_text(
                system,
                user,
                timeout=timeout,
            )

        except Exception as error:
            if (
                _is_model_unavailable(error)
                and self._try_switch()
            ):
                return self._do_text(
                    system,
                    user,
                    timeout=timeout,
                )

            raise


# ============================================================
# Public LLM Gateway
# ============================================================

class LLMGateway:
    """
    Central LLM gateway with task-aware provider routing.
    """

    def __init__(
        self,
        max_retries_per_provider: int = 2,
        base_delay: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        scheduler: Optional[RequestScheduler] = None,
        task_router: Optional[TaskRouter] = None,
    ):
        self._providers: list[_Provider] = []
        self._provider_map: dict[str, _Provider] = {}

        self.max_retries = max_retries_per_provider
        self.base_delay = base_delay
        self._sleep = sleep_fn

        self._scheduler = (
            scheduler
            or get_default_scheduler()
        )

        self._task_router = (
            task_router
            or get_default_task_router()
        )

        self._build_provider_chain()

        if not self._providers:
            logger.warning(
                "No LLM providers configured."
            )

    # --------------------------------------------------------
    # Provider Chain (UPDATED FOR 4 GROQ KEYS)
    # --------------------------------------------------------

    def _build_provider_chain(self) -> None:
        def add_provider(provider: _Provider) -> None:
            self._providers.append(provider)
            self._provider_map[provider.name] = provider

        groq_slots = [
            (CONFIG.GROQ_API_KEY_1, "groq-1"),
            (CONFIG.GROQ_API_KEY_2, "groq-2"),
            (CONFIG.GROQ_API_KEY_3, "groq-3"),
            (CONFIG.GROQ_API_KEY_4, "groq-4"),
        ]

        for api_key, label in groq_slots:
            if api_key:
                try:
                    add_provider(
                        _GroqProvider(
                            api_key=api_key,
                            label=label,
                            model=CONFIG.GROQ_MODEL,
                            timeout=CONFIG.LLM_TIMEOUT,
                        )
                    )
                except Exception as error:
                    logger.warning(
                        "Failed to initialize %s: %s",
                        label,
                        error,
                    )

        # Gemini
        if CONFIG.GEMINI_API_KEY:
            try:
                add_provider(
                    _GeminiProvider(
                        api_key=CONFIG.GEMINI_API_KEY,
                        model_name=CONFIG.GEMINI_MODEL,
                        timeout=CONFIG.LLM_TIMEOUT,
                    )
                )
            except Exception as error:
                logger.warning(
                    "Failed to initialize Gemini: %s",
                    error,
                )

        # HuggingFace
        if CONFIG.HF_TOKEN:
            try:
                add_provider(
                    _HuggingFaceProvider(
                        token=CONFIG.HF_TOKEN,
                        primary_model=CONFIG.HF_MODEL,
                        fallback_model=CONFIG.HF_MODEL_FALLBACK,
                        base_url=CONFIG.HF_BASE_URL,
                        timeout=CONFIG.LLM_TIMEOUT,
                    )
                )
            except Exception as error:
                logger.warning(
                    "Failed to initialize HuggingFace: %s",
                    error,
                )

        provider_names = [
            provider.name
            for provider in self._providers
        ]

        logger.info(
            "Provider chain: %s",
            " → ".join(provider_names)
            if provider_names
            else "(none)",
        )

    def has_providers(self) -> bool:
        return bool(self._providers)

    # --------------------------------------------------------
    # Public M3 / LLMClient Protocol
    # --------------------------------------------------------

    def structured_call(
        self,
        system: str,
        user: str,
        response_model: Type[T],
        **kwargs: Any,
    ) -> T:
        task_type = kwargs.get(
            "task_type",
            "default",
        )

        return self._call_with_fallback(
            fn=lambda provider, t_out: provider.structured(
                system,
                user,
                response_model,
                timeout=t_out,
            ),
            label=f"structured<{response_model.__name__}>",
            task_type=task_type,
        )

    def text_call(
        self,
        system: str,
        user: str,
        **kwargs: Any,
    ) -> str:
        task_type = kwargs.get(
            "task_type",
            "default",
        )

        return self._call_with_fallback(
            fn=lambda provider, t_out: provider.text(
                system,
                user,
                timeout=t_out,
            ),
            label="text_call",
            task_type=task_type,
        )

    # --------------------------------------------------------
    # Task-Aware Fallback Execution
    # --------------------------------------------------------

    def _call_with_fallback(
        self,
        fn: Callable[[_Provider, float], Any],
        label: str,
        task_type: str = "default",
    ) -> Any:
        if not self._providers:
            raise LLMPermanentError(
                "No LLM providers configured"
            )

        # Match exact timeout config based on task type
        task_timeout = _get_timeout_for_task(task_type)

        available_names = [
            provider.name
            for provider in self._providers
        ]

        cooled = {
            name
            for name in available_names
            if self._scheduler.is_in_cooldown(name)
        }

        ordered_names = self._task_router.select_providers(
            task_type,
            available_names,
            cooled_down_providers=cooled,
        )

        ordered_providers = [
            self._provider_map[name]
            for name in ordered_names
            if name in self._provider_map
        ]

        last_error: Optional[Exception] = None
        is_first_provider = True

        for provider in ordered_providers:
            if self._scheduler.is_in_cooldown(provider.name):
                remaining = (
                    self._scheduler.get_cooldown_remaining(
                        provider.name
                    )
                )

                logger.info(
                    "⏭️ Skip '%s' (cooldown %.1fs)",
                    provider.name,
                    remaining,
                )
                is_first_provider = False
                continue

            logger.info(
                "Trying provider '%s' for task='%s'",
                provider.name,
                task_type,
            )

            for attempt in range(
                1,
                self.max_retries + 2,
            ):
                try:
                    result = self._scheduler.execute(
                        fn=lambda p=provider: fn(p, task_timeout),
                        provider_name=provider.name,
                        request_label=(
                            f"{task_type}:{label}"
                        ),
                    )

                    self._task_router.record_call(
                        task_type,
                        provider.name,
                        was_fallback=not is_first_provider,
                    )

                    return result

                except Exception as raw_error:
                    err = _classify(raw_error)
                    last_error = err

                    # ----------------------------------------
                    # Rate limit: immediately move provider
                    # ----------------------------------------
                    if is_rate_limit_error(raw_error):
                        retry_after = _extract_retry_after(
                            raw_error
                        )

                        cooldown = (
                            retry_after
                            or self._scheduler.cooldown_seconds
                        )

                        self._scheduler.set_cooldown(
                            provider.name,
                            cooldown,
                        )

                        self._task_router.record_cooldown(
                            provider.name
                        )

                        logger.warning(
                            "🚫 429 from '%s'. Cooldown %.1fs "
                            "→ next provider.",
                            provider.name,
                            cooldown,
                        )
                        break

                    # ----------------------------------------
                    # Connection error: no repeated retry
                    # ----------------------------------------
                    if is_connection_error(raw_error):
                        logger.warning(
                            "🌐 Connection failure on '%s': %s "
                            "→ next provider immediately",
                            provider.name,
                            raw_error,
                        )
                        break

                    # ----------------------------------------
                    # Timeout: immediately failover
                    # ----------------------------------------
                    if is_timeout_error(raw_error):
                        # Apply local 15-second soft cooldown to prevent immediately hammering it
                        self._scheduler.set_cooldown(provider.name, 15.0)
                        logger.warning(
                            "⏱️ Timeout on '%s' for task='%s'. "
                            "Switching to next provider.",
                            provider.name,
                            task_type,
                        )
                        break

                    # ----------------------------------------
                    # Permanent provider error
                    # ----------------------------------------
                    if isinstance(err, LLMPermanentError):
                        logger.warning(
                            "Permanent error on '%s': %s",
                            provider.name,
                            err,
                        )
                        break

                    # ----------------------------------------
                    # Model unavailable
                    # ----------------------------------------
                    if _is_model_unavailable(raw_error):
                        logger.warning(
                            "Model unavailable on '%s': %s "
                            "→ next provider",
                            provider.name,
                            raw_error,
                        )
                        break

                    # ----------------------------------------
                    # Normal transient retry
                    # ----------------------------------------
                    if attempt > self.max_retries:
                        logger.warning(
                            "'%s' retries exhausted",
                            provider.name,
                        )
                        break

                    delay = (
                        self.base_delay
                        * (2 ** (attempt - 1))
                    )

                    delay *= 1 + random.uniform(
                        -0.1,
                        0.1,
                    )

                    self._sleep(
                        max(0.5, delay)
                    )

            is_first_provider = False

        raise last_error or LLMProviderError(
            "All providers failed or are in cooldown"
        )


# ============================================================
# Optional Convenience Singleton
# ============================================================

_default_gateway: Optional[LLMGateway] = None


def get_default_gateway() -> LLMGateway:
    """
    Return a lazily initialized shared gateway instance.
    """
    global _default_gateway

    if _default_gateway is None:
        _default_gateway = LLMGateway()

    return _default_gateway