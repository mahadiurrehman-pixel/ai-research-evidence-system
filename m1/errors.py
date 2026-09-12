"""
m1/errors.py — Custom error types.
"""


class M1Error(Exception):
    """Base M1 error."""


class ValidationError(M1Error):
    """Request validation failed."""


class RoutingError(M1Error):
    """Question routing failed."""


class PlanningError(M1Error):
    """Research planning failed."""


class M2Error(M1Error):
    """M2 retrieval failed."""


class M3IntegrationError(M1Error):
    """M3 invocation failed."""


class LLMProviderError(M1Error):
    """LLM provider failed."""


class LLMPermanentError(LLMProviderError):
    """Do not retry — auth, quota, invalid request."""


class LLMTransientError(LLMProviderError):
    """Safe to retry / try next provider."""


class M1TimeoutError(M1Error):
    """Investigation timed out."""