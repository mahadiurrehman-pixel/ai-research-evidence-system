"""
m1/schema_utils.py — Provider-specific JSON Schema Builders.

FIX: If an object has NO 'properties' field (e.g. dictionary objects like dict[str, str]),
we explicitly pop the 'required' array. This prevents Groq 400 Bad Request errors.
"""

from __future__ import annotations

import copy
from typing import Any, Type
from pydantic import BaseModel


def build_canonical_schema(model: Type[BaseModel]) -> dict[str, Any]:
    """Generate pristine, untouched canonical JSON schema from Pydantic model."""
    return copy.deepcopy(model.model_json_schema())


def build_groq_schema(model: Type[BaseModel]) -> dict[str, Any]:
    """
    Groq / OpenAI Strict Mode requires:
    1. additionalProperties: false recursively on EVERY object.
    2. 'required' array MUST exist ONLY on objects with properties and list ALL keys.
    3. Free-form dictionaries without 'properties' must NOT have a 'required' field.
    """
    schema = build_canonical_schema(model)
    return _sanitize_groq_strict_schema(schema)


def build_openrouter_schema(model: Type[BaseModel]) -> dict[str, Any]:
    return build_groq_schema(model)


def build_huggingface_schema(model: Type[BaseModel]) -> dict[str, Any]:
    return build_canonical_schema(model)


def build_gemini_schema(model: Type[BaseModel]) -> dict[str, Any]:
    canonical = build_canonical_schema(model)
    defs = canonical.get("$defs", {}) or canonical.get("definitions", {})
    dereferenced = _dereference_schema(canonical, defs)
    return _clean_gemini_schema(dereferenced)


# ── Internal Helpers ──────────────────────────────────────────

def _sanitize_groq_strict_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema

    cleaned = dict(schema)

    # If it is an object schema with properties
    if "properties" in cleaned and isinstance(cleaned["properties"], dict):
        cleaned["type"] = "object"
        cleaned["additionalProperties"] = False
        # List all property keys in required
        cleaned["required"] = list(cleaned["properties"].keys())

        # Recurse properties
        cleaned["properties"] = {
            k: _sanitize_groq_strict_schema(v)
            for k, v in cleaned["properties"].items()
        }

    else:
        # ★ CRITICAL FIX: If there are NO properties (e.g. dict[str, str]),
        # we MUST remove the 'required' array to comply with strict parser.
        cleaned.pop("required", None)
        if cleaned.get("type") == "object" or "additionalProperties" in cleaned:
            cleaned["type"] = "object"
            cleaned["additionalProperties"] = False

    # Recurse array items
    if "items" in cleaned:
        cleaned["items"] = _sanitize_groq_strict_schema(cleaned["items"])

    # Recurse definitions ($defs and definitions)
    for def_key in ("$defs", "definitions"):
        if def_key in cleaned and isinstance(cleaned[def_key], dict):
            cleaned[def_key] = {
                k: _sanitize_groq_strict_schema(v)
                for k, v in cleaned[def_key].items()
            }

    # Recurse combinators
    for comb_key in ("anyOf", "allOf", "oneOf"):
        if comb_key in cleaned and isinstance(cleaned[comb_key], list):
            cleaned[comb_key] = [
                _sanitize_groq_strict_schema(x) for x in cleaned[comb_key]
            ]

    return cleaned


def _dereference_schema(schema: Any, defs: dict[str, Any]) -> Any:
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        ref_path = schema["$ref"]
        ref_name = ref_path.split("/")[-1]
        if ref_name in defs:
            resolved = copy.deepcopy(defs[ref_name])
            return _dereference_schema(resolved, defs)
        return schema

    deref = dict(schema)

    if "properties" in deref and isinstance(deref["properties"], dict):
        deref["properties"] = {
            k: _dereference_schema(v, defs) for k, v in deref["properties"].items()
        }

    if "items" in deref:
        deref["items"] = _dereference_schema(deref["items"], defs)

    for comb_key in ("anyOf", "allOf", "oneOf"):
        if comb_key in deref and isinstance(deref[comb_key], list):
            deref[comb_key] = [
                _dereference_schema(x, defs) for x in deref[comb_key]
            ]

    return deref


_GEMINI_STRIP_KEYS = {
    "$schema",
    "$defs",
    "definitions",
    "title",
    "additionalProperties",
    "additional_properties",
}


def _clean_gemini_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema

    cleaned = {
        k: _clean_gemini_schema(v)
        for k, v in schema.items()
        if k not in _GEMINI_STRIP_KEYS
    }

    if "properties" in cleaned and isinstance(cleaned["properties"], dict):
        cleaned["properties"] = {
            k: _clean_gemini_schema(v)
            for k, v in cleaned["properties"].items()
        }

    if "items" in cleaned:
        cleaned["items"] = _clean_gemini_schema(cleaned["items"])

    for comb_key in ("anyOf", "allOf", "oneOf"):
        if comb_key in cleaned and isinstance(cleaned[comb_key], list):
            cleaned[comb_key] = [
                _clean_gemini_schema(x) for x in cleaned[comb_key]
            ]

    return cleaned