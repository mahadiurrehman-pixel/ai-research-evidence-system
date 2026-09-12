"""
m1/gateway.py — Shared LLM Gateway with task-aware model routing and 4 Groq Keys.

FIXES:
- Prevents 429 rate limits from being misclassified as permanent errors due to
  billing URLs in the error body.
- Rate limits now apply a short 10-15s soft cooldown, NEVER 3600s.
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
from .schema_utils import (
    build_canonical_schema,
    build_gemini_schema,
    build_groq_schema,
    build_huggingface_schema,
    build_openrouter_schema,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ============================================================
# Error Classification
# ============================================================

# Strictly permanent auth/billing tokens (excluding generic substrings like "billing"
# which appear in Groq 429 response URLs).
_PERMANENT_TOKENS = (
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
    "401",
    "402",
    "payment required",
    "payment_required",
    "403",
    "invalid_request_error",
    "insufficient_quota",
    "insufficient credits",
    "permission denied",
    "account deactivated",
)

_MODEL_UNAVAILABLE_TOKENS = (
    "model not found",
    "model_not_found",
    "model unavailable",
    "model is not available",
    "does not exist",
    "unknown model",
    "not supported",
    "unsupported model",
    "404",
)


def _error_message(error: Exception) -> str:
    return str(error).lower()


def _classify(error: Exception) -> LLMProviderError:
    """
    Convert arbitrary exceptions into project-level errors.
    Rate limits (429) are ALWAYS transient.
    """
    if isinstance(error, LLMProviderError):
        return error

    if is_rate_limit_error(error):
        return LLMTransientError(str(error))

    if type(error).__name__ in ("PermanentLLMError", "LLMPermanentError"):
        return LLMPermanentError(str(error))

    message = _error_message(error)
    status_code = getattr(error, "status_code", None)

    if status_code in (401, 402, 403, 404):
        return LLMPermanentError(str(error))

    if any(token in message for token in _PERMANENT_TOKENS):
        return LLMPermanentError(str(error))

    if any(token in message for token in _MODEL_UNAVAILABLE_TOKENS):
        return LLMPermanentError(str(error))

    return LLMTransientError(str(error))


def _is_model_unavailable(error: Exception) -> bool:
    message = _error_message(error)
    return any(token in message for token in _MODEL_UNAVAILABLE_TOKENS)


def _is_unsupported_parameter(error: Exception) -> bool:
    message = _error_message(error)
    tokens = (
        "unsupported parameter",
        "unsupported_parameter",
        "unknown parameter",
        "unrecognized request argument",
        "temperature is not supported",
        "temperature not supported",
        "response_format is not supported",
        "json_schema is not supported",
        "extra inputs are not permitted",
        "invalid parameter",
    )
    return any(token in message for token in tokens)


def _get_timeout_for_task(task_type: str) -> float:
    if task_type in ("query_generation", "decomposition", "search_planning", "classification"):
        return getattr(CONFIG, "TIMEOUT_QUERY_GENERATION", 15.0)
    if task_type in ("evidence_analysis", "evidence_extraction"):
        return getattr(CONFIG, "TIMEOUT_EVIDENCE_ANALYSIS", 25.0)
    if task_type in ("contradiction_detection", "contradiction_pairs"):
        return getattr(CONFIG, "TIMEOUT_CONTRADICTION_PAIRS", 20.0)
    if task_type in ("final_verdict", "final_synthesis"):
        return getattr(CONFIG, "TIMEOUT_FINAL_VERDICT", 25.0)
    return getattr(CONFIG, "LLM_TIMEOUT", 25.0)


# ============================================================
# Provider Interface
# ============================================================

class _Provider:
    name: str = "base"
    model: str = "unknown"

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
# OpenAI-Compatible Base Provider
# ============================================================

class _OpenAICompatibleProvider(_Provider):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        label: str,
        timeout: float,
        default_headers: Optional[dict[str, str]] = None,
        schema_builder: Optional[Callable[[Type[BaseModel]], dict[str, Any]]] = None,
    ):
        from openai import OpenAI

        self.name = label
        self.model = model
        self._default_timeout = timeout
        self._schema_builder = schema_builder or build_canonical_schema

        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "timeout": timeout,
            "max_retries": 0,
        }
        if default_headers:
            client_kwargs["default_headers"] = default_headers

        self._client = OpenAI(**client_kwargs)

    def _create_completion(
        self,
        *,
        messages: list[dict[str, str]],
        timeout: float,
        response_format: Optional[dict[str, Any]] = None,
        include_temperature: bool = True,
    ):
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "timeout": timeout,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        if include_temperature:
            kwargs["temperature"] = CONFIG.LLM_TEMPERATURE

        try:
            return self._client.chat.completions.create(**kwargs)
        except Exception as error:
            if include_temperature and _is_unsupported_parameter(error):
                logger.debug(
                    "[%s] Request parameter unsupported; retrying without temperature: %s",
                    self.name,
                    error,
                )
                kwargs.pop("temperature", None)
                return self._client.chat.completions.create(**kwargs)
            raise

    @staticmethod
    def _extract_content(completion: Any) -> str:
        try:
            content = completion.choices[0].message.content
        except Exception as error:
            raise LLMTransientError(f"Invalid completion response: {error}") from error
        return (content or "").strip()

    def structured(
        self,
        system: str,
        user: str,
        model: Type[T],
        timeout: Optional[float] = None,
    ) -> T:
        t = timeout if timeout is not None else self._default_timeout
        provider_schema = self._schema_builder(model)

        schema_hint = (
            "\n\nRespond with ONLY valid JSON matching this schema:\n"
            f"{json.dumps(provider_schema, indent=2)}"
        )
        messages = [
            {"role": "system", "content": system + schema_hint},
            {"role": "user", "content": user},
        ]

        # Attempt 1: JSON Schema mode
        try:
            completion = self._create_completion(
                messages=messages,
                timeout=t,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": model.__name__,
                        "strict": True,
                        "schema": provider_schema,
                    },
                },
            )
            content = self._extract_content(completion)
            if content:
                return model.model_validate_json(content)
        except Exception as error:
            logger.debug("[%s] JSON schema mode failed (%s) -> trying json_object", self.name, error)
            if (
                _is_model_unavailable(error)
                or is_connection_error(error)
                or is_timeout_error(error)
                or is_rate_limit_error(error)
            ):
                raise

        # Attempt 2: JSON Object mode
        try:
            completion = self._create_completion(
                messages=messages,
                timeout=t,
                response_format={"type": "json_object"},
            )
            content = self._extract_content(completion)
            if content:
                return model.model_validate_json(content)
        except Exception as error:
            logger.debug("[%s] JSON object mode failed: %s", self.name, error)
            if (
                _is_model_unavailable(error)
                or is_connection_error(error)
                or is_timeout_error(error)
                or is_rate_limit_error(error)
            ):
                raise

        # Attempt 3: Plain completion
        completion = self._create_completion(
            messages=messages,
            timeout=t,
            response_format=None,
        )
        content = self._extract_content(completion)
        if not content:
            raise LLMTransientError(f"{self.name}: empty structured response")

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
        completion = self._create_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            timeout=t,
            response_format=None,
        )
        content = self._extract_content(completion)
        if not content:
            raise LLMTransientError(f"{self.name}: empty text response")
        return content


# ============================================================
# Groq Provider
# ============================================================

class _GroqProvider(_OpenAICompatibleProvider):
    def __init__(self, api_key: str, label: str, model: str, timeout: float):
        super().__init__(
            api_key=api_key,
            base_url=getattr(CONFIG, "GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            model=model,
            label=label,
            timeout=timeout,
            schema_builder=build_groq_schema,
        )


# ============================================================
# OpenRouter Provider
# ============================================================

class _OpenRouterProvider(_OpenAICompatibleProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float,
        site_url: str = "",
        app_name: str = "",
    ):
        if not model.endswith(":free"):
            logger.warning(
                "OpenRouter model '%s' does not end with ':free'.",
                model,
            )

        headers: dict[str, str] = {}
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name

        super().__init__(
            api_key=api_key,
            base_url=getattr(CONFIG, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            model=model,
            label="openrouter",
            timeout=timeout,
            default_headers=headers or None,
            schema_builder=build_openrouter_schema,
        )


# ============================================================
# Gemini Provider
# ============================================================

class _GeminiProvider(_Provider):
    def __init__(self, api_key: str, model_name: str, timeout: float):
        try:
            from google import genai
            self._client = genai.Client(api_key=api_key)
            self._use_new_sdk = True
        except ImportError:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._model_obj = genai.GenerativeModel(model_name=model_name)
            self._use_new_sdk = False

        self.name = f"gemini({model_name})"
        self.model = model_name
        self._default_timeout = timeout

    def structured(
        self,
        system: str,
        user: str,
        model: Type[T],
        timeout: Optional[float] = None,
    ) -> T:
        schema = build_gemini_schema(model)
        prompt = f"{system}\n\nUSER:\n{user}"

        if self._use_new_sdk:
            from google.genai import types
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=CONFIG.LLM_TEMPERATURE,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        else:
            schema_hint = (
                "\n\nRespond with ONLY valid JSON matching this schema:\n"
                f"{json.dumps(schema, indent=2)}"
            )
            response = self._model_obj.generate_content(
                f"{system}\n{schema_hint}\n\nUSER:\n{user}",
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": CONFIG.LLM_TEMPERATURE,
                },
            )

        content = (getattr(response, "text", "") or "").strip()
        if not content:
            raise LLMTransientError(f"{self.name}: empty structured response")

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
        prompt = f"{system}\n\nUSER:\n{user}"
        if self._use_new_sdk:
            response = self._client.models.generate_content(
                model=self.model, contents=prompt,
            )
        else:
            response = self._model_obj.generate_content(prompt)

        content = (getattr(response, "text", "") or "").strip()
        if not content:
            raise LLMTransientError(f"{self.name}: empty text response")
        return content


# ============================================================
# HuggingFace Provider
# ============================================================

class _HuggingFaceProvider(_Provider):
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
        self.model = self._current

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        url = (base_url or "").strip().rstrip("/")
        if not url:
            return "https://router.huggingface.co/v1"
        if "api-inference.huggingface.co" in url:
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
        if self._switched or not self._fallback:
            return False
        logger.warning("HF model '%s' unavailable -> switching to '%s'", self._current, self._fallback)
        self._current = self._fallback
        self._client = self._make_client()
        self.name = f"hf({self._current})"
        self.model = self._current
        self._switched = True
        return True

    def _do_structured(
        self,
        system: str,
        user: str,
        model: Type[T],
        timeout: Optional[float] = None,
    ) -> T:
        provider = _OpenAICompatibleProvider.__new__(_OpenAICompatibleProvider)
        provider.name = self.name
        provider.model = self._current
        provider._default_timeout = self._default_timeout
        provider._client = self._client
        provider._schema_builder = build_huggingface_schema

        return provider.structured(
            system=system, user=user, model=model, timeout=timeout,
        )

    def structured(
        self,
        system: str,
        user: str,
        model: Type[T],
        timeout: Optional[float] = None,
    ) -> T:
        try:
            return self._do_structured(system, user, model, timeout=timeout)
        except Exception as error:
            if _is_model_unavailable(error) and self._try_switch():
                return self._do_structured(system, user, model, timeout=timeout)
            raise

    def _do_text(
        self,
        system: str,
        user: str,
        timeout: Optional[float] = None,
    ) -> str:
        t = timeout if timeout is not None else self._default_timeout
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs: dict[str, Any] = {
            "model": self._current,
            "messages": messages,
            "timeout": t,
            "temperature": CONFIG.LLM_TEMPERATURE,
        }
        try:
            completion = self._client.chat.completions.create(**kwargs)
        except Exception as error:
            if _is_unsupported_parameter(error):
                kwargs.pop("temperature", None)
                completion = self._client.chat.completions.create(**kwargs)
            else:
                raise

        content = (completion.choices[0].message.content or "").strip()
        if not content:
            raise LLMTransientError(f"{self.name}: empty text response")
        return content

    def text(
        self,
        system: str,
        user: str,
        timeout: Optional[float] = None,
    ) -> str:
        try:
            return self._do_text(system, user, timeout=timeout)
        except Exception as error:
            if _is_model_unavailable(error) and self._try_switch():
                return self._do_text(system, user, timeout=timeout)
            raise


# ============================================================
# Public LLM Gateway
# ============================================================

class LLMGateway:
    """
    Central gateway for all LLM requests.
    """

    def __init__(
        self,
        max_retries_per_provider: int = 1,
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

        self._scheduler = scheduler or get_default_scheduler()
        self._task_router = task_router or get_default_task_router()
        self._last_call_metadata: dict[str, Any] = {}

        self._build_provider_chain()

        if not self._providers:
            logger.warning("No LLM providers configured.")

    def get_last_call_metadata(self) -> dict:
        return dict(self._last_call_metadata)

    def _build_provider_chain(self) -> None:
        def add_provider(provider: _Provider) -> None:
            self._providers.append(provider)
            self._provider_map[provider.name] = provider

        groq_slots = [
            (getattr(CONFIG, "GROQ_API_KEY_1", ""), "groq-1"),
            (getattr(CONFIG, "GROQ_API_KEY_2", ""), "groq-2"),
            (getattr(CONFIG, "GROQ_API_KEY_3", ""), "groq-3"),
            (getattr(CONFIG, "GROQ_API_KEY_4", ""), "groq-4"),
        ]

        for api_key, label in groq_slots:
            if not api_key:
                continue
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
                logger.warning("Failed to initialize %s: %s", label, error)

        gemini_key = getattr(CONFIG, "GEMINI_API_KEY", "")
        if gemini_key:
            try:
                add_provider(
                    _GeminiProvider(
                        api_key=gemini_key,
                        model_name=CONFIG.GEMINI_MODEL,
                        timeout=CONFIG.LLM_TIMEOUT,
                    )
                )
            except Exception as error:
                logger.warning("Failed to initialize Gemini: %s", error)

        openrouter_key = getattr(CONFIG, "OPENROUTER_API_KEY", "")
        if openrouter_key:
            try:
                add_provider(
                    _OpenRouterProvider(
                        api_key=openrouter_key,
                        model=CONFIG.OPENROUTER_MODEL,
                        timeout=CONFIG.LLM_TIMEOUT,
                        site_url=getattr(CONFIG, "OPENROUTER_SITE_URL", ""),
                        app_name=getattr(CONFIG, "OPENROUTER_APP_NAME", ""),
                    )
                )
            except Exception as error:
                logger.warning("Failed to initialize OpenRouter: %s", error)

        hf_token = getattr(CONFIG, "HF_TOKEN", "")
        if hf_token:
            try:
                add_provider(
                    _HuggingFaceProvider(
                        token=hf_token,
                        primary_model=CONFIG.HF_MODEL,
                        fallback_model=getattr(CONFIG, "HF_MODEL_FALLBACK", None),
                        base_url=CONFIG.HF_BASE_URL,
                        timeout=CONFIG.LLM_TIMEOUT,
                    )
                )
            except Exception as error:
                logger.warning("Failed to initialize HuggingFace: %s", error)

        logger.info(
            "Provider chain: %s",
            " → ".join(p.name for p in self._providers) if self._providers else "(none)",
        )

    def has_providers(self) -> bool:
        return bool(self._providers)

    def structured_call(
        self,
        system: str,
        user: str,
        response_model: Type[T],
        **kwargs: Any,
    ) -> T:
        task_type = kwargs.get("task_type", "default")
        return self._call_with_fallback(
            fn=lambda provider, timeout: provider.structured(
                system=system,
                user=user,
                model=response_model,
                timeout=timeout,
            ),
            label=f"structured<{response_model.__name__}>",
            task_type=task_type,
            operation="structured",
        )

    def text_call(
        self,
        system: str,
        user: str,
        **kwargs: Any,
    ) -> str:
        task_type = kwargs.get("task_type", "default")
        return self._call_with_fallback(
            fn=lambda provider, timeout: provider.text(
                system=system,
                user=user,
                timeout=timeout,
            ),
            label="text_call",
            task_type=task_type,
            operation="text",
        )

    def _call_with_fallback(
        self,
        fn: Callable[[_Provider, float], Any],
        label: str,
        task_type: str = "default",
        operation: str = "structured",
    ) -> Any:
        if not self._providers:
            raise LLMPermanentError("No LLM providers configured")

        task_timeout = _get_timeout_for_task(task_type)

        available_names = [p.name for p in self._providers]
        cooled = {n for n in available_names if self._scheduler.is_in_cooldown(n)}

        routed_names = self._task_router.select_providers(
            task_type,
            available_names,
            cooled_down_providers=cooled,
        )

        ordered_names: list[str] = []
        for name in routed_names:
            if name in self._provider_map and name not in ordered_names:
                ordered_names.append(name)
        for name in available_names:
            if name not in ordered_names and name not in cooled:
                ordered_names.append(name)
        if not ordered_names:
            ordered_names = list(routed_names)

        ordered_providers = [
            self._provider_map[name]
            for name in ordered_names
            if name in self._provider_map
        ]

        last_error: Optional[Exception] = None
        provider_attempt_number = 0
        first_provider_tried: Optional[str] = None

        for provider in ordered_providers:
            if self._scheduler.is_in_cooldown(provider.name):
                remaining = self._scheduler.get_cooldown_remaining(provider.name)
                logger.info("⏭️ Skip '%s' (cooldown %.1fs)", provider.name, remaining)
                continue

            provider_attempt_number += 1
            is_fallback = provider_attempt_number > 1
            provider_model = getattr(provider, "model", "unknown-model")

            if first_provider_tried is None:
                first_provider_tried = provider.name

            logger.info(
                "[LLM] task=%s provider=%s model=%s attempt=%d",
                task_type,
                provider.name,
                provider_model,
                provider_attempt_number,
            )

            for retry_attempt in range(1, self.max_retries + 2):
                started_at = time.time()
                try:
                    result = self._scheduler.execute(
                        fn=lambda p=provider: fn(p, task_timeout),
                        provider_name=provider.name,
                        request_label=f"{task_type}:{label}",
                    )

                    latency_ms = int((time.time() - started_at) * 1000)

                    self._last_call_metadata = {
                        "provider": provider.name,
                        "model": provider_model,
                        "task_type": task_type,
                        "operation": operation,
                        "status": "success",
                        "error": None,
                        "attempt": provider_attempt_number,
                        "retry_attempt": retry_attempt,
                        "latency_ms": latency_ms,
                        "fallback_used": is_fallback,
                        "fallback_from": first_provider_tried if is_fallback else None,
                        "timestamp": time.time(),
                    }

                    self._task_router.record_call(
                        task_type,
                        provider.name,
                        was_fallback=is_fallback,
                    )

                    return result

                except Exception as raw_error:
                    latency_ms = int((time.time() - started_at) * 1000)
                    err = _classify(raw_error)
                    last_error = err

                    self._last_call_metadata = {
                        "provider": provider.name,
                        "model": provider_model,
                        "task_type": task_type,
                        "operation": operation,
                        "status": "failed",
                        "error": str(raw_error),
                        "attempt": provider_attempt_number,
                        "retry_attempt": retry_attempt,
                        "latency_ms": latency_ms,
                        "fallback_used": is_fallback,
                        "fallback_from": first_provider_tried if is_fallback else None,
                        "timestamp": time.time(),
                    }

                    # ★ Fast failover for rate limit: 10s soft cooldown (NOT 3600s!)
                    if is_rate_limit_error(raw_error):
                        retry_after = _extract_retry_after(raw_error)
                        cooldown = min(15.0, retry_after or 10.0)
                        self._scheduler.set_cooldown(provider.name, cooldown)
                        self._task_router.record_cooldown(provider.name)
                        logger.warning(
                            "🚫 Rate limit '%s'. Cooldown %.1fs → next provider",
                            provider.name,
                            cooldown,
                        )
                        break

                    # ★ Fast failover for permanent errors (401/402/403/404)
                    if isinstance(err, LLMPermanentError):
                        self._scheduler.set_cooldown(provider.name, 300.0)
                        logger.warning(
                            "🚫 Permanent error on '%s': %s → failing over to next provider",
                            provider.name,
                            err,
                        )
                        break

                    if is_connection_error(raw_error):
                        logger.warning(
                            "🌐 Connection failure on '%s': %s → next provider",
                            provider.name,
                            raw_error,
                        )
                        break

                    if is_timeout_error(raw_error):
                        self._scheduler.set_cooldown(provider.name, 15.0)
                        logger.warning(
                            "⏱️ Timeout on '%s' task='%s' → next provider",
                            provider.name,
                            task_type,
                        )
                        break

                    if _is_model_unavailable(raw_error):
                        logger.warning(
                            "Model unavailable on '%s': %s → next provider",
                            provider.name,
                            raw_error,
                        )
                        break

                    if retry_attempt > self.max_retries:
                        logger.warning("'%s' retries exhausted", provider.name)
                        break

                    delay = self.base_delay * (2 ** (retry_attempt - 1))
                    delay *= 1 + random.uniform(-0.1, 0.1)
                    self._sleep(max(0.5, delay))

        raise last_error or LLMProviderError("All providers failed or are in cooldown")


# ============================================================
# Singleton
# ============================================================

_default_gateway: Optional[LLMGateway] = None


def get_default_gateway() -> LLMGateway:
    global _default_gateway
    if _default_gateway is None:
        _default_gateway = LLMGateway()
    return _default_gateway