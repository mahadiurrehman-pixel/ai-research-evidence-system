"""
tests/test_schema.py — Unit tests verifying provider-specific schema normalization
and fail-fast error behaviors.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest
from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from m1.schema_utils import (
    build_canonical_schema,
    build_gemini_schema,
    build_groq_schema,
    build_huggingface_schema,
    build_openrouter_schema,
)
from m1.config import CONFIG, validate_openrouter_free_model
from m1.gateway import LLMGateway
from m1.models import RouterOutput
from verification.models import FinalVerdict, VerdictType, Confidence


class NestedChild(BaseModel):
    id: str
    description: str = "default_desc"


class ParentModel(BaseModel):
    name: str
    children: list[NestedChild]
    metadata: dict[str, str] = {}


# ── Test 1: Groq Schema has additionalProperties: False and all required fields ──

def test_1_groq_schema_has_recursive_additional_properties_and_required():
    schema = build_groq_schema(ParentModel)
    
    # Root object validation
    assert schema["additionalProperties"] is False
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"name", "children", "metadata"}
    
    # Nested definition in $defs validation
    if "$defs" in schema:
        assert "NestedChild" in schema["$defs"]
        child_def = schema["$defs"]["NestedChild"]
        assert child_def["additionalProperties"] is False
        assert set(child_def["required"]) == {"id", "description"}

    # Validation on actual RouterOutput model (dynamically checks all model fields)
    router_schema = build_groq_schema(RouterOutput)
    assert router_schema["additionalProperties"] is False
    assert set(router_schema["required"]) == set(RouterOutput.model_fields.keys())


# ── Test 2: Gemini Schema has NO additionalProperties or $defs ──

def test_2_gemini_schema_is_clean_and_inlined():
    schema = build_gemini_schema(ParentModel)
    
    # Must NOT contain forbidden keys
    schema_str = str(schema)
    assert "additionalProperties" not in schema_str
    assert "additional_properties" not in schema_str
    assert "$defs" not in schema
    assert "definitions" not in schema
    assert "$schema" not in schema
    assert "title" not in schema

    # Child should be inlined into items
    items = schema["properties"]["children"]["items"]
    assert items["type"] == "object"
    assert "id" in items["properties"]
    assert "description" in items["properties"]


# ── Test 3: Canonical schema remains unchanged ──

def test_3_canonical_schema_is_immutable():
    canonical_before = build_canonical_schema(ParentModel)
    
    _ = build_groq_schema(ParentModel)
    _ = build_gemini_schema(ParentModel)
    _ = build_openrouter_schema(ParentModel)
    _ = build_huggingface_schema(ParentModel)
    
    canonical_after = build_canonical_schema(ParentModel)
    assert canonical_before == canonical_after


# ── Test 4: OpenRouter model explicitly ends with :free ──

def test_4_openrouter_model_is_genuinely_free():
    assert CONFIG.OPENROUTER_MODEL.endswith(":free")
    assert validate_openrouter_free_model() is True


# ── Test 5: HTTP 400 schema error fails fast ──

def test_5_http_400_schema_error_fails_fast():
    class FailingSchemaProvider:
        name = "groq-1"
        model = "mock"
        calls = 0
        def structured(self, system, user, model, timeout=None):
            FailingSchemaProvider.calls += 1
            raise Exception("400 Invalid parameter: additional_properties is not supported")

    class SuccessFallbackProvider:
        name = "gemini(gemini-2.0-flash)"
        model = "gemini-2.0-flash"
        calls = 0
        def structured(self, system, user, model, timeout=None):
            SuccessFallbackProvider.calls += 1
            return FinalVerdict(
                original_question="Q",
                verdict=VerdictType.SUPPORTED,
                confidence=Confidence.HIGH,
                summary="OK",
                detailed_reasoning="OK",
            )

    FailingSchemaProvider.calls = 0
    SuccessFallbackProvider.calls = 0

    from verification.scheduler import RequestScheduler
    scheduler = RequestScheduler(max_retries=3, base_retry_delay=0.01)
    gw = LLMGateway(scheduler=scheduler)
    gw._providers = [FailingSchemaProvider(), SuccessFallbackProvider()]
    gw._provider_map = {p.name: p for p in gw._providers}
    gw._task_router.select_providers = lambda t, avail, cooled_down_providers=None: [
        "groq-1", "gemini(gemini-2.0-flash)"
    ]

    res = gw.structured_call(
        system="s", user="u", response_model=FinalVerdict
    )

    # Failing provider should fail fast in 1 attempt (NOT 4 retries)
    assert FailingSchemaProvider.calls == 1
    # Fallback provider should be called and succeed
    assert SuccessFallbackProvider.calls == 1
    assert res.summary == "OK"