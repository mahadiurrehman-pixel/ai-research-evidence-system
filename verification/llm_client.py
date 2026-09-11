"""
llm_client.py — Provider-isolated LLM client with Groq-specific 429 handling.

Updates:
- Catches 429 rate limits.
- Parses 'Retry-After' and 'x-ratelimit-reset' headers.
- Regex-parses error body text (e.g., "try again in 15.34s") to get precise sleep times.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from enum import Enum
from typing import Any, Callable, Protocol, Type, TypeVar

from pydantic import BaseModel, ValidationError

from .errors import (
    LLMError,
    LLMParseError,
    PermanentLLMError,
    TransientLLMError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_WAIT_TIME_RE = re.compile(r"(?:try again in|wait|retry after)\s*([0-9.]+)\s*s?", re.IGNORECASE)


class LLMClient(Protocol):
    def structured_call(
        self, system: str, user: str, response_model: Type[T]
    ) -> T: ...

    def text_call(self, system: str, user: str) -> str: ...


# ── Rate Limit Helper ────────────────────────

def _extract_retry_delay(err: Exception) -> float | None:
    """Inspect headers and error message to extract the required backoff delay."""
    # 1. Check HTTP headers (OpenAI SDK structures this under e.headers)
    headers = getattr(err, "headers", None)
    if not headers and hasattr(err, "response"):
        headers = getattr(err.response, "headers", None)

    if headers:
        for hkey in ("retry-after", "x-ratelimit-reset", "x-ratelimit-reset-tokens"):
            val = headers.get(hkey)
            if val:
                try:
                    return max(1.0, float(val))
                except ValueError:
                    pass

    # 2. Check string message for Groq-style backoff instructions (e.g. "try again in 15.3s")
    msg = str(err)
    match = _WAIT_TIME_RE.search(msg)
    if match:
        try:
            return max(1.0, float(match.group(1)))
        except ValueError:
            pass

    return None


def _classify_provider_error(e: Exception) -> LLMError:
    if isinstance(e, LLMError):
        return e
    
    status_code = getattr(e, "status_code", None)
    if status_code == 429:
        return TransientLLMError(str(e))
        
    name = type(e).__name__.lower()
    msg = str(e).lower()
    
    if any(x in name for x in ("timeout", "connection", "apiconnection", "ratelimit")):
        return TransientLLMError(str(e))
    if any(x in name for x in ("authentication", "permission", "notfound", "badrequest")):
        return PermanentLLMError(str(e))
    if any(k in msg for k in _PERMANENT_KEYWORDS):
        return PermanentLLMError(str(e))
    if any(k in msg for k in _TRANSIENT_KEYWORDS):
        return TransientLLMError(str(e))
    return TransientLLMError(str(e))


_TRANSIENT_KEYWORDS = (
    "timeout", "timed out", "temporarily", "temporary",
    "rate limit", "429", "503", "502", "504", "gateway",
    "connection", "reset", "overloaded",
)
_PERMANENT_KEYWORDS = (
    "invalid api key", "unauthorized", "401", "forbidden", "403",
    "not found", "404", "invalid request", "invalid_request_error",
    "model_not_found", "quota", "billing", "insufficient_quota",
)


SleepFn = Callable[[float], None]


def _with_retry(
    fn: Callable[[], T],
    max_retries: int,
    base_delay: float,
    sleep_fn: SleepFn,
    label: str,
) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except PermanentLLMError:
            raise
        except LLMParseError:
            raise
        except Exception as raw_e:
            err = _classify_provider_error(raw_e)
            if isinstance(err, PermanentLLMError):
                logger.error("%s permanent LLM error: %s", label, err)
                raise err
            
            attempt += 1
            if attempt > max_retries:
                logger.error("%s retry exhausted (%s attempts): %s", label, attempt, err)
                raise err

            # ★ Rate limit handling: prioritize server instructions
            delay = _extract_retry_delay(raw_e)
            if delay is None:
                delay = base_delay * (2 ** (attempt - 1))
                delay = delay * (1 + random.uniform(-0.1, 0.1))  # Jitter
            else:
                logger.warning("Rate-limit match! Waiting %.2fs as instructed by Groq server.", delay)
                delay += 0.5  # Safety buffer

            logger.warning(
                "%s transient failure (attempt %d/%d): %s — sleeping %.2fs",
                label, attempt, max_retries, err, delay,
            )
            sleep_fn(delay)


# ── JSON Coercion ────────────────────────────

def _coerce_to_schema(data: dict, model: Type[T]) -> dict:
    if not isinstance(data, dict):
        return data

    schema = model.model_json_schema()
    properties = schema.get("properties", {})
    defs = schema.get("$defs", {}) or schema.get("definitions", {})

    coerced = {}
    for key, value in data.items():
        if key not in properties:
            continue
        prop = properties[key]
        coerced[key] = _coerce_value(value, prop, defs)

    for field_name, field_info in model.model_fields.items():
        if field_name not in coerced:
            if field_info.default is not None and field_info.default is not ...:
                try:
                    coerced[field_name] = field_info.default
                except Exception:
                    pass
            elif field_info.default_factory is not None:
                try:
                    coerced[field_name] = field_info.default_factory()
                except Exception:
                    pass
    return coerced


def _resolve_ref(prop_schema: dict, defs: dict) -> dict:
    if "$ref" in prop_schema:
        ref = prop_schema["$ref"]
        parts = ref.split("/")
        name = parts[-1]
        if name in defs:
            return defs[name]
    return prop_schema


def _coerce_value(value: Any, prop_schema: dict, defs: dict) -> Any:
    resolved = _resolve_ref(prop_schema, defs)

    if "enum" in resolved:
        valid = resolved["enum"]
        if value in valid:
            return value
        upper_val = str(value).upper().strip().replace("-", "_").replace(" ", "_")
        for v in valid:
            if str(v).upper() == upper_val:
                return v
        synonym_map = {
            "MIXED": "PARTIALLY_SUPPORTED",
            "CONTEXT_DEPENDENT": "PARTIALLY_SUPPORTED",
            "PARTIAL": "PARTIALLY_SUPPORTED",
            "PARTIALLY": "PARTIALLY_SUPPORTED",
            "YES": "SUPPORTED",
            "TRUE": "SUPPORTED",
            "NO": "NOT_SUPPORTED",
            "FALSE": "NOT_SUPPORTED",
            "POSITIVE": "SUPPORTED",
            "NEGATIVE": "CONTRADICTED",
            "INSUFFICIENT": "INCONCLUSIVE",
            "INSUFFICIENT_EVIDENCE": "INCONCLUSIVE",
            "UNKNOWN": "INCONCLUSIVE",
            "UNCLEAR": "INCONCLUSIVE",
            "STRONG": "HIGH",
            "WEAK": "LOW",
            "MODERATE": "MEDIUM",
            "MED": "MEDIUM",
        }
        mapped = synonym_map.get(upper_val)
        if mapped and mapped in valid:
            return mapped
        return valid[0]

    if resolved.get("type") == "object" and isinstance(value, dict):
        return value

    if resolved.get("type") == "array" and isinstance(value, list):
        item_schema = resolved.get("items", {})
        return [_coerce_value(v, item_schema, defs) for v in value]

    return value


# ── OpenAI Client ─────────────────────────────

class OpenAICompatibleLLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
        timeout: float = 60.0,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        sleep_fn: SleepFn | None = None,
    ):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise PermanentLLMError("openai package is required") from e

        self._client = OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
            timeout=timeout,
            max_retries=0,
        )
        self.model = model
        self.temperature = temperature
        self.max_retries = max(0, max_retries)
        self.retry_base_delay = max(0.0, retry_base_delay)
        self.sleep_fn: SleepFn = sleep_fn or time.sleep

    def structured_call(
        self, system: str, user: str, response_model: Type[T]
    ) -> T:
        def _do() -> T:
            try:
                completion = self._client.beta.chat.completions.parse(
                    model=self.model,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format=response_model,
                )
                msg = completion.choices[0].message
                parsed = getattr(msg, "parsed", None)
                if parsed is not None:
                    return parsed
                raw = getattr(msg, "content", None)
                if raw:
                    try:
                        return response_model.model_validate_json(raw)
                    except ValidationError:
                        pass
            except Exception as e:
                logger.debug("Native structured output failed: %s", e)

            data = self._json_call(system, user, response_model)
            coerced = _coerce_to_schema(data, response_model)
            try:
                return response_model.model_validate(coerced)
            except ValidationError as ve:
                errors = ve.errors()
                error_summary = "; ".join(
                    f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}"
                    for e in errors[:5]
                )
                logger.error(
                    "Schema validation failed for %s: %s",
                    response_model.__name__, error_summary,
                )
                raise LLMParseError(f"Validation failed for {response_model.__name__}: {error_summary}") from ve

        return _with_retry(
            _do,
            max_retries=self.max_retries,
            base_delay=self.retry_base_delay,
            sleep_fn=self.sleep_fn,
            label="structured_call",
        )

    def text_call(self, system: str, user: str) -> str:
        def _do() -> str:
            completion = self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = completion.choices[0].message.content
            if not content:
                raise LLMParseError("Empty LLM response")
            return content.strip()

        return _with_retry(
            _do,
            max_retries=self.max_retries,
            base_delay=self.retry_base_delay,
            sleep_fn=self.sleep_fn,
            label="text_call",
        )

    def _json_call(
        self, system: str, user: str, response_model: Type[T]
    ) -> dict:
        schema_hint = (
            "\n\nRespond with ONLY a valid JSON object matching this schema:\n"
            f"{json.dumps(response_model.model_json_schema(), indent=2)}"
        )
        completion = self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system + schema_hint},
                {"role": "user", "content": user},
            ],
        )
        content = completion.choices[0].message.content
        if not content:
            raise LLMParseError("Empty LLM JSON response")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMParseError(f"Invalid JSON from LLM: {e}") from e


def default_llm_client() -> LLMClient:
    return OpenAICompatibleLLMClient()