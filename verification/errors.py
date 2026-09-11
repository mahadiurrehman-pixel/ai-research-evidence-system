"""
errors.py — Typed exceptions for the verification module.
"""

from __future__ import annotations


class VerificationError(Exception):
    """Base class for all verification-module errors."""


class LLMError(VerificationError):
    """Base class for LLM failures."""


class TransientLLMError(LLMError):
    """
    Temporary LLM failure that is safe to retry:
    timeouts, rate limits, 5xx, transient network errors.
    """


class PermanentLLMError(LLMError):
    """
    Permanent LLM failure — do NOT retry:
    auth failure, invalid request, model-not-found, quota exceeded.
    """


class LLMParseError(LLMError):
    """Raised when the LLM returns malformed / unparseable output."""


class PipelineStateError(VerificationError):
    """Raised when the pipeline is used in an invalid order/state."""