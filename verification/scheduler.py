"""
verification/scheduler.py — High-Throughput Request Scheduler.

Fixes:
- Rate limit (429) cooldown capped to min(15.0, retry_after or 10.0)s. NEVER 3600s!
- Permanent errors fast-fail immediately without local retries.
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel

from .errors import LLMError, LLMParseError, PermanentLLMError, TransientLLMError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ── Configuration from environment ───────────

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


DEFAULT_MAX_CONCURRENCY = _env_int("SCHEDULER_MAX_CONCURRENCY", 6)
DEFAULT_BATCH_SIZE = _env_int("SCHEDULER_BATCH_SIZE", 8)
DEFAULT_INTER_BATCH_DELAY = _env_float("SCHEDULER_INTER_BATCH_DELAY", 0.3)
DEFAULT_PROVIDER_COOLDOWN = _env_float("SCHEDULER_PROVIDER_COOLDOWN", 10.0)
DEFAULT_MAX_RETRIES = _env_int("SCHEDULER_MAX_RETRIES", 2)
DEFAULT_BASE_RETRY_DELAY = _env_float("SCHEDULER_BASE_RETRY_DELAY", 1.0)


# ── Error Detection Helpers ───────────────────

_RATE_LIMIT_TOKENS = (
    "429", "rate_limit", "rate limit", "rate-limit",
    "too many requests", "tpm limit", "rpm limit",
    "requests per minute", "tokens per minute",
    "resource_exhausted", "quota exceeded", "quotaexceeded",
)

_CONNECTION_ERROR_TOKENS = (
    "connection error", "connection refused", "connection reset", "connection aborted",
    "connecterror", "network is unreachable", "name or service not known",
    "temporary failure in name resolution", "remote disconnected", "remote end closed connection",
    "connection closed", "failed to establish a new connection", "max retries exceeded with url",
    "dns failure", "unexpected_eof_while_reading", "eof occurred in violation of protocol",
)

_PERMANENT_TOKENS = (
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
    "401",
    "402",
    "payment required",
    "payment_required",
    "forbidden",
    "403",
    "404",
    "invalid_request",
    "permission denied",
    "authentication",
    "api key",
    "no auth credentials",
    "additionalproperties",
    "unsupported parameter",
    "unsupported_parameter",
    "invalid parameter",
    "extra inputs are not permitted",
    "response_format",
    "unknown model",
    "model not found",
    "model_not_found",
    "does not exist",
    "unsupported model",
)


def is_rate_limit_error(err: Exception) -> bool:
    status = getattr(err, "status_code", None)
    if status == 429:
        return True
    response = getattr(err, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return True
    msg = str(err).lower()
    return any(tok in msg for tok in _RATE_LIMIT_TOKENS)


def is_connection_error(err: Exception) -> bool:
    msg = str(err).lower()
    return any(tok in msg for tok in _CONNECTION_ERROR_TOKENS)


def is_timeout_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "timeout" in msg or "timed out" in msg or "read timeout" in msg or "connect timeout" in msg


def is_permanent_error(err: Exception) -> bool:
    # 429 is NEVER permanent!
    if is_rate_limit_error(err):
        return False
    status = getattr(err, "status_code", None)
    if status in (401, 402, 403, 404):
        return True
    response = getattr(err, "response", None)
    if response is not None and getattr(response, "status_code", None) in (401, 402, 403, 404):
        return True
    msg = str(err).lower()
    return any(tok in msg for tok in _PERMANENT_TOKENS)


def _extract_retry_after(err: Exception) -> Optional[float]:
    msg = str(err)
    m = re.search(r"(?:try again in|wait|retry after|retry in|retrydelay': ')\s*([0-9.]+)\s*s?", msg, re.I)
    if m:
        try:
            return max(1.0, float(m.group(1)))
        except ValueError:
            pass
    headers = getattr(err, "headers", None)
    if not headers and hasattr(err, "response"):
        headers = getattr(err.response, "headers", None)
    if headers:
        for key in ("retry-after", "x-ratelimit-reset"):
            val = headers.get(key)
            if val:
                try:
                    return max(1.0, float(val))
                except ValueError:
                    pass
    return None


# ── Per-Provider Rate Limiter ────────────────

class _ProviderLimiter:
    def __init__(self, name: str, max_concurrent: int, cooldown_seconds: float):
        self.name = name
        self.semaphore = threading.Semaphore(max_concurrent)
        self.cooldown_seconds = cooldown_seconds
        self._cooldown_until: float = 0.0
        self._lock = threading.Lock()

    @property
    def in_cooldown(self) -> bool:
        with self._lock:
            return time.time() < self._cooldown_until

    @property
    def cooldown_remaining(self) -> float:
        with self._lock:
            return max(0.0, self._cooldown_until - time.time())

    def set_cooldown(self, seconds: Optional[float] = None) -> None:
        duration = seconds or self.cooldown_seconds
        with self._lock:
            self._cooldown_until = time.time() + duration
        logger.warning("🧊 COOLDOWN: '%s' paused for %.1fs", self.name, duration)


# ── Request Scheduler ────────────────────────

class RequestScheduler:
    def __init__(
        self,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        batch_size: int = DEFAULT_BATCH_SIZE,
        batch_delay: float = DEFAULT_INTER_BATCH_DELAY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_retry_delay: float = DEFAULT_BASE_RETRY_DELAY,
        cooldown_seconds: float = DEFAULT_PROVIDER_COOLDOWN,
    ):
        self.max_concurrency = max_concurrency
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        self.cooldown_seconds = cooldown_seconds

        self._pool = ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="m3-sched",
        )
        self._limiters: Dict[str, _ProviderLimiter] = {}
        self._limiters_lock = threading.Lock()
        self._counter = 0
        self._counter_lock = threading.Lock()

        logger.info(
            "🔧 Scheduler created: concurrency=%d, batch_size=%d, batch_delay=%.2fs, cooldown=%.0fs",
            max_concurrency, batch_size, batch_delay, cooldown_seconds,
        )

    def _get_limiter(self, provider: str) -> _ProviderLimiter:
        with self._limiters_lock:
            if provider not in self._limiters:
                per_provider = max(2, self.max_concurrency // 2)
                self._limiters[provider] = _ProviderLimiter(
                    name=provider,
                    max_concurrent=per_provider,
                    cooldown_seconds=self.cooldown_seconds,
                )
            return self._limiters[provider]

    def _next_req_id(self) -> int:
        with self._counter_lock:
            self._counter += 1
            return self._counter

    def is_in_cooldown(self, provider: str) -> bool:
        return self._get_limiter(provider).in_cooldown

    def get_cooldown_remaining(self, provider: str) -> float:
        return self._get_limiter(provider).cooldown_remaining

    def set_cooldown(self, provider: str, seconds: Optional[float] = None) -> None:
        self._get_limiter(provider).set_cooldown(seconds)

    # ── Single Request Execution ──────────

    def execute(
        self,
        fn: Callable[[], T],
        provider_name: str = "default",
        request_label: str = "",
    ) -> T:
        label = request_label or "request"
        limiter = self._get_limiter(provider_name)
        req_id = self._next_req_id()
        last_error: Optional[Exception] = None

        # ★ If provider is in cooldown, fail fast! Do NOT sleep inside worker thread!
        remaining = limiter.cooldown_remaining
        if remaining > 0:
            logger.info("⏭️ [req #%d] '%s' in cooldown (%.1fs). Failing fast.", req_id, provider_name, remaining)
            raise TransientLLMError(f"Provider '{provider_name}' in cooldown ({remaining:.1f}s)")

        for attempt in range(1, self.max_retries + 2):
            with limiter.semaphore:
                logger.info("📤 [req #%d] %s via '%s' (attempt %d/%d)", req_id, label, provider_name, attempt, self.max_retries + 1)
                try:
                    result = fn()
                    logger.info("✅ [req #%d] %s via '%s' OK (attempt %d)", req_id, label, provider_name, attempt)
                    return result

                except LLMParseError:
                    logger.error("❌ [req #%d] %s PARSE ERROR", req_id, label)
                    raise

                except PermanentLLMError:
                    logger.error("❌ [req #%d] %s PERMANENT ERROR", req_id, label)
                    raise

                except Exception as raw_e:
                    last_error = raw_e

                    if is_permanent_error(raw_e):
                        logger.warning("🚫 [req #%d] %s PERMANENT ERROR on '%s': %s. Failing fast.", req_id, label, provider_name, raw_e)
                        raise PermanentLLMError(str(raw_e)) from raw_e

                    if is_rate_limit_error(raw_e):
                        retry_after = _extract_retry_after(raw_e)
                        # ★ Cap 429 cooldown to 10s max (NEVER 3600s!)
                        cooldown = min(15.0, retry_after or 10.0)
                        limiter.set_cooldown(cooldown)
                        logger.warning("🚫 [req #%d] %s RATE LIMITED by '%s'. Cooldown %.1fs. Failing fast.", req_id, label, provider_name, cooldown)
                        raise TransientLLMError(f"Rate limited by {provider_name}: {raw_e}") from raw_e

                    if is_timeout_error(raw_e) or is_connection_error(raw_e):
                        logger.warning("⏱️ [req #%d] %s TIMEOUT/CONN ERROR on '%s'. Failing fast.", req_id, label, provider_name)
                        raise TransientLLMError(f"Network error on {provider_name}: {raw_e}") from raw_e

                    logger.warning("⚠️  [req #%d] %s FAILED via '%s': %s (%d/%d)", req_id, label, provider_name, raw_e, attempt, self.max_retries + 1)

                    if attempt > self.max_retries:
                        break

                    delay = self.base_retry_delay * (2 ** (attempt - 1))
                    delay *= 1 + random.uniform(-0.15, 0.15)
                    time.sleep(max(0.5, delay))

        raise last_error or TransientLLMError(f"All {self.max_retries + 1} attempts failed for {label}")

    # ── Batch Processing ──────────────────

    def process_batch(
        self,
        items: Sequence[Any],
        fn: Callable[[Any], Any],
        batch_size: Optional[int] = None,
        batch_delay: Optional[float] = None,
        provider_name: str = "default",
        label: str = "batch",
    ) -> List[Any]:
        if not items:
            return []

        bs = batch_size or self.batch_size
        delay = batch_delay if batch_delay is not None else self.batch_delay
        batches = [items[i:i + bs] for i in range(0, len(items), bs)]
        total_batches = len(batches)
        all_results: List[Any] = [None] * len(items)

        logger.info("📦 BATCH START: %s — %d items, %d batches (size=%d, delay=%.2fs, concurrency=%d)", label, len(items), total_batches, bs, delay, self.max_concurrency)

        for batch_idx, batch in enumerate(batches):
            batch_offset = batch_idx * bs
            logger.info("📦 Batch %d/%d: %d items [%s]", batch_idx + 1, total_batches, len(batch), label)

            future_to_idx = {}
            for local_idx, item in enumerate(batch):
                global_idx = batch_offset + local_idx
                item_label = f"{label}[{global_idx}]"
                future = self._pool.submit(
                    self._execute_batch_item,
                    fn=fn,
                    item=item,
                    provider_name=provider_name,
                    request_label=item_label,
                )
                future_to_idx[future] = global_idx

            for future in as_completed(future_to_idx):
                global_idx = future_to_idx[future]
                try:
                    all_results[global_idx] = future.result()
                except Exception as e:
                    logger.error("❌ %s[%d] FAILED: %s", label, global_idx, e)
                    all_results[global_idx] = None

            if batch_idx < total_batches - 1 and delay > 0:
                time.sleep(delay)

        succeeded = sum(1 for r in all_results if r is not None)
        failed = len(all_results) - succeeded
        logger.info("📦 BATCH DONE: %s — %d/%d succeeded, %d failed", label, succeeded, len(all_results), failed)
        return all_results

    def _execute_batch_item(self, fn: Callable[[Any], Any], item: Any, provider_name: str, request_label: str) -> Any:
        return self.execute(fn=lambda: fn(item), provider_name=provider_name, request_label=request_label)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


class ScheduledLLMClient:
    def __init__(self, inner: Any, scheduler: RequestScheduler, provider_name: str = "default", task_type: str = "default"):
        self._inner = inner
        self._scheduler = scheduler
        self._provider = provider_name
        self._task_type = task_type

    def structured_call(self, system: str, user: str, response_model: Type[T], **kwargs) -> T:
        task = kwargs.pop("task_type", self._task_type)
        return self._call_inner("structured_call", system, user, response_model, task_type=task)

    def text_call(self, system, user, **kwargs) -> str:
        task = kwargs.pop("task_type", self._task_type)
        return self._call_inner("text_call", system, user, task_type=task)

    def _call_inner(self, method: str, *args, **kwargs):
        fn = getattr(self._inner, method)
        try:
            return fn(*args, **kwargs)
        except TypeError:
            kwargs.pop("task_type", None)
            return fn(*args, **kwargs)


_default_scheduler: Optional[RequestScheduler] = None
_default_lock = threading.Lock()


def get_default_scheduler() -> RequestScheduler:
    global _default_scheduler
    with _default_lock:
        if _default_scheduler is None:
            _default_scheduler = RequestScheduler()
        return _default_scheduler