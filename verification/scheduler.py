"""
verification/scheduler.py — High-Throughput Request Scheduler.

Optimized for speed while preventing 429 rate-limit errors.
Immediately raises rate-limit, timeout, and connection errors to allow instant cross-key failover.
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
DEFAULT_PROVIDER_COOLDOWN = _env_float("SCHEDULER_PROVIDER_COOLDOWN", 30.0)
DEFAULT_MAX_RETRIES = _env_int("SCHEDULER_MAX_RETRIES", 3)
DEFAULT_BASE_RETRY_DELAY = _env_float("SCHEDULER_BASE_RETRY_DELAY", 1.5)


# ── Error Detection Helpers ───────────────────

_RATE_LIMIT_TOKENS = (
    "429", "rate_limit", "rate limit", "rate-limit",
    "too many requests", "quota exceeded", "tpm limit",
    "requests per minute", "tokens per minute",
)

_CONNECTION_ERROR_TOKENS = (
    "connection error", "connection refused", "connection reset", "connection aborted",
    "connecterror", "network is unreachable", "name or service not known",
    "temporary failure in name resolution", "remote disconnected", "remote end closed connection",
    "connection closed", "failed to establish a new connection", "max retries exceeded with url",
    "dns failure",
)


def is_rate_limit_error(err: Exception) -> bool:
    """Detect HTTP 429 or rate-limit errors from any provider."""
    status = getattr(err, "status_code", None)
    if status == 429:
        return True
    response = getattr(err, "response", None)
    if response is not None:
        if getattr(response, "status_code", None) == 429:
            return True
    msg = str(err).lower()
    return any(tok in msg for tok in _RATE_LIMIT_TOKENS)


def is_connection_error(err: Exception) -> bool:
    """Detect connection and network-level errors."""
    msg = str(err).lower()
    return any(tok in msg for tok in _CONNECTION_ERROR_TOKENS)


def is_timeout_error(err: Exception) -> bool:
    """Detect timeout errors."""
    msg = str(err).lower()
    return "timeout" in msg or "timed out" in msg or "read timeout" in msg or "connect timeout" in msg


def _extract_retry_after(err: Exception) -> Optional[float]:
    """Extract Retry-After seconds from error headers or message."""
    msg = str(err)
    m = re.search(r"(?:try again in|wait|retry after)\s*([0-9.]+)\s*s?", msg, re.I)
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
    """Thread-safe per-provider cooldown and concurrency tracker."""

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
        logger.warning(
            "🧊 COOLDOWN: '%s' paused for %.1fs", self.name, duration
        )


# ── Request Scheduler ────────────────────────

class RequestScheduler:
    """
    High-throughput request scheduler with real parallelism.

    Uses ThreadPoolExecutor for actual concurrent execution.
    Per-provider cooldowns ensure one provider's 429 doesn't block others.
    """

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
            "🔧 Scheduler created: concurrency=%d, batch_size=%d, "
            "batch_delay=%.2fs, cooldown=%.0fs",
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
        """
        Execute a single LLM request with retry and per-provider cooldown.

        NO inter-request delay — single calls (like FinalVerdict) run instantly.
        """
        label = request_label or "request"
        limiter = self._get_limiter(provider_name)
        req_id = self._next_req_id()
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 2):
            # Wait if provider is in cooldown
            remaining = limiter.cooldown_remaining
            if remaining > 0:
                logger.info(
                    "⏳ [req #%d] '%s' cooldown (%.1fs). Waiting...",
                    req_id, provider_name, remaining,
                )
                time.sleep(remaining + 0.2)

            # Acquire per-provider slot
            with limiter.semaphore:
                logger.info(
                    "📤 [req #%d] %s via '%s' (attempt %d/%d)",
                    req_id, label, provider_name,
                    attempt, self.max_retries + 1,
                )
                try:
                    result = fn()
                    logger.info(
                        "✅ [req #%d] %s via '%s' OK (attempt %d)",
                        req_id, label, provider_name, attempt,
                    )
                    return result

                except LLMParseError:
                    logger.error("❌ [req #%d] %s PARSE ERROR", req_id, label)
                    raise

                except PermanentLLMError:
                    logger.error("❌ [req #%d] %s PERMANENT ERROR", req_id, label)
                    raise

                except Exception as raw_e:
                    last_error = raw_e

                    if is_rate_limit_error(raw_e):
                        retry_after = _extract_retry_after(raw_e)
                        cooldown = retry_after or self.cooldown_seconds
                        limiter.set_cooldown(cooldown)
                        logger.warning(
                            "🚫 [req #%d] %s RATE LIMITED by '%s'. "
                            "Cooldown %.1fs. Failing fast to allow failover.",
                            req_id, label, provider_name, cooldown
                        )
                        # Immediately raise TransientLLMError to trigger instant failover in gateway
                        raise TransientLLMError(
                            f"Rate limited by {provider_name}: {raw_e}"
                        ) from raw_e

                    if is_timeout_error(raw_e):
                        logger.warning(
                            "⏱️ [req #%d] %s TIMEOUT on '%s'. "
                            "Failing fast to allow immediate provider failover.",
                            req_id, label, provider_name
                        )
                        # Immediately raise TransientLLMError to switch provider without local retry loop
                        raise TransientLLMError(
                            f"Timeout on {provider_name}: {raw_e}"
                        ) from raw_e

                    if is_connection_error(raw_e):
                        logger.warning(
                            "🌐 [req #%d] %s CONNECTION ERROR on '%s'. "
                            "Failing fast to allow immediate provider failover.",
                            req_id, label, provider_name
                        )
                        raise TransientLLMError(
                            f"Connection error on {provider_name}: {raw_e}"
                        ) from raw_e

                    logger.warning(
                        "⚠️  [req #%d] %s FAILED via '%s': %s (%d/%d)",
                        req_id, label, provider_name, raw_e,
                        attempt, self.max_retries + 1,
                    )

                    if attempt > self.max_retries:
                        break

                    delay = self.base_retry_delay * (2 ** (attempt - 1))
                    delay *= 1 + random.uniform(-0.15, 0.15)
                    delay = max(0.5, delay)
                    time.sleep(delay)

        raise last_error or TransientLLMError(
            f"All {self.max_retries + 1} attempts failed for {label}"
        )

    # ── Batch Processing (Parallel) ───────

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

        logger.info(
            "📦 BATCH START: %s — %d items, %d batches (size=%d, delay=%.2fs, concurrency=%d)",
            label, len(items), total_batches, bs, delay, self.max_concurrency,
        )

        for batch_idx, batch in enumerate(batches):
            batch_offset = batch_idx * bs
            logger.info(
                "📦 Batch %d/%d: %d items [%s]",
                batch_idx + 1, total_batches, len(batch), label,
            )

            # Submit all items in this batch to thread pool concurrently
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

            # Collect results as they complete
            for future in as_completed(future_to_idx):
                global_idx = future_to_idx[future]
                try:
                    all_results[global_idx] = future.result()
                except Exception as e:
                    logger.error("❌ %s[%d] FAILED: %s", label, global_idx, e)
                    all_results[global_idx] = None

            # Small inter-batch delay (not after last batch)
            if batch_idx < total_batches - 1 and delay > 0:
                logger.debug(
                    "⏳ Inter-batch delay: %.2fs", delay,
                )
                time.sleep(delay)

        succeeded = sum(1 for r in all_results if r is not None)
        failed = len(all_results) - succeeded
        logger.info(
            "📦 BATCH DONE: %s — %d/%d succeeded, %d failed",
            label, succeeded, len(all_results), failed,
        )
        return all_results

    def _execute_batch_item(
        self,
        fn: Callable[[Any], Any],
        item: Any,
        provider_name: str,
        request_label: str,
    ) -> Any:
        """Execute a single batch item with retry (runs inside thread pool)."""
        return self.execute(
            fn=lambda: fn(item),
            provider_name=provider_name,
            request_label=request_label,
        )

    # ── Multi-Provider Distribution ───────

    def process_batch_distributed(
        self,
        items: Sequence[Any],
        fn: Callable[[Any, str], Any],
        providers: List[str],
        batch_size: Optional[int] = None,
        batch_delay: Optional[float] = None,
        label: str = "batch",
    ) -> List[Any]:
        if not items:
            return []
        if not providers:
            return self.process_batch(items, lambda x: fn(x, "default"),
                                      batch_size, batch_delay, "default", label)

        bs = batch_size or self.batch_size
        delay = batch_delay if batch_delay is not None else self.batch_delay
        all_results: List[Any] = [None] * len(items)

        logger.info(
            "📦 DISTRIBUTED BATCH: %s — %d items across %d providers (%s)",
            label, len(items), len(providers), ", ".join(providers),
        )

        assignments: Dict[str, List[tuple[int, Any]]] = {p: [] for p in providers}
        provider_idx = 0

        for global_idx, item in enumerate(items):
            tried = 0
            while tried < len(providers):
                p = providers[provider_idx % len(providers)]
                provider_idx += 1
                if not self.is_in_cooldown(p):
                    assignments[p].append((global_idx, item))
                    break
                tried += 1
            else:
                p = providers[0]
                assignments[p].append((global_idx, item))

        futures = {}
        for provider, provider_items in assignments.items():
            if not provider_items:
                continue
            batches = [
                provider_items[i:i + bs]
                for i in range(0, len(provider_items), bs)
            ]
            for batch_idx, batch in enumerate(batches):
                for local_idx, (global_idx, item) in enumerate(batch):
                    item_label = f"{label}[{global_idx}]@{provider}"
                    future = self._pool.submit(
                        self._execute_distributed_item,
                        fn=fn,
                        item=item,
                        provider_name=provider,
                        request_label=item_label,
                    )
                    futures[future] = global_idx

                if batch_idx < len(batches) - 1 and delay > 0:
                    time.sleep(delay)

        for future in as_completed(futures):
            global_idx = futures[future]
            try:
                all_results[global_idx] = future.result()
            except Exception as e:
                logger.error("❌ %s[%d] FAILED: %s", label, global_idx, e)
                all_results[global_idx] = None

        succeeded = sum(1 for r in all_results if r is not None)
        logger.info(
            "📦 DISTRIBUTED DONE: %s — %d/%d succeeded",
            label, succeeded, len(all_results),
        )
        return all_results

    def _execute_distributed_item(
        self,
        fn: Callable[[Any, str], Any],
        item: Any,
        provider_name: str,
        request_label: str,
    ) -> Any:
        return self.execute(
            fn=lambda: fn(item, provider_name),
            provider_name=provider_name,
            request_label=request_label,
        )

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


# ── Scheduled LLM Client Wrapper ─────────────

class ScheduledLLMClient:
    """
    Drop-in wrapper that adds scheduling to any LLMClient.

    Implements the same protocol (structured_call, text_call).
    """

    def __init__(
        self,
        inner: Any,
        scheduler: RequestScheduler,
        provider_name: str = "default",
        task_type: str = "default",
    ):
        self._inner = inner
        self._scheduler = scheduler
        self._provider = provider_name
        self._task_type = task_type

    def structured_call(self, system: str, user: str, response_model: Type[T], **kwargs) -> T:
        task = kwargs.pop("task_type", self._task_type)
        return self._scheduler.execute(
            fn=lambda: self._call_inner(
                "structured_call", system, user, response_model, task_type=task
            ),
            provider_name=self._provider,
            request_label=f"{task}:structured<{response_model.__name__}>",
        )

    def text_call(self, system: str, user: str, **kwargs) -> str:
        task = kwargs.pop("task_type", self._task_type)
        return self._scheduler.execute(
            fn=lambda: self._call_inner("text_call", system, user, task_type=task),
            provider_name=self._provider,
            request_label=f"{task}:text_call",
        )

    def _call_inner(self, method: str, *args, **kwargs):
        fn = getattr(self._inner, method)
        try:
            return fn(*args, **kwargs)
        except TypeError:
            kwargs.pop("task_type", None)
            return fn(*args, **kwargs)


# ── Global Default Scheduler ─────────────────

_default_scheduler: Optional[RequestScheduler] = None
_default_lock = threading.Lock()


def get_default_scheduler() -> RequestScheduler:
    global _default_scheduler
    with _default_lock:
        if _default_scheduler is None:
            _default_scheduler = RequestScheduler()
        return _default_scheduler