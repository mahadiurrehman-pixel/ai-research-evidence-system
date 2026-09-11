"""
source_identity.py — Robust source-group resolution.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable
from urllib.parse import urlparse

from .models import RawEvidence


_WORD_RE = re.compile(r"[a-z0-9]+")
_SUBDOMAIN_PREFIXES = ("www.", "m.", "amp.", "en.", "old.")


def normalize_title(title: str) -> str:
    if not title:
        return ""
    tokens = _WORD_RE.findall(title.lower())
    return " ".join(t for t in tokens if len(t) > 2)


def normalize_domain(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = (parsed.netloc or parsed.path or "").lower()
    except Exception:
        return ""
    for prefix in _SUBDOMAIN_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.split(":", 1)[0]
    return host


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ta = set(_WORD_RE.findall(a.lower()))
    tb = set(_WORD_RE.findall(b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def get_source_group(ev: RawEvidence) -> str:
    if ev.source_group:
        return f"group:{ev.source_group.strip().lower()}"

    domain = normalize_domain(ev.url)
    if domain:
        norm_title = normalize_title(ev.title)
        if norm_title:
            return f"domain+title:{domain}|{norm_title[:120]}"
        return f"domain:{domain}"

    if ev.publisher:
        norm_title = normalize_title(ev.title)
        if norm_title:
            return f"pub+title:{ev.publisher.strip().lower()}|{norm_title[:120]}"
        return f"pub:{ev.publisher.strip().lower()}"

    return f"id:{ev.source_id}"


def _extract_source_group_tokens(ev: RawEvidence) -> set[str]:
    """Extract meaningful tokens from explicit source_group for partial matching."""
    if not ev.source_group:
        return set()
    raw = ev.source_group.strip().lower()
    tokens = _WORD_RE.findall(raw)
    return {t for t in tokens if t not in {"copy", "duplicate", "syndicate",
                                           "syndicated", "group", "source",
                                           "dependent", "related"} and len(t) > 2}


def group_evidence(
    items: Iterable[RawEvidence],
    title_similarity_threshold: float = 0.85,
) -> dict[str, list[RawEvidence]]:
    groups: dict[str, list[RawEvidence]] = defaultdict(list)
    for ev in items:
        groups[get_source_group(ev)].append(ev)

    keys = list(groups.keys())
    merged: dict[str, str] = {k: k for k in keys}

    def _find(k: str) -> str:
        while merged[k] != k:
            merged[k] = merged[merged[k]]
            k = merged[k]
        return k

    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            if _find(k1) == _find(k2):
                continue
            g1 = groups[k1][0]
            g2 = groups[k2][0]

            same_domain = (
                normalize_domain(g1.url)
                and normalize_domain(g1.url) == normalize_domain(g2.url)
            )
            same_pub = (
                g1.publisher and g2.publisher
                and g1.publisher.strip().lower() == g2.publisher.strip().lower()
            )
            if (same_domain or same_pub) and \
               _title_similarity(g1.title, g2.title) >= title_similarity_threshold:
                merged[_find(k2)] = _find(k1)
                continue

            tokens1 = _extract_source_group_tokens(g1)
            tokens2 = _extract_source_group_tokens(g2)

            def _tokens_match_source(tokens: set[str], other: RawEvidence) -> bool:
                if not tokens:
                    return False
                other_domain = normalize_domain(other.url)
                other_pub = (other.publisher or "").strip().lower()
                other_title_tokens = set(_WORD_RE.findall(other.title.lower()))
                for t in tokens:
                    if t in other_domain:
                        return True
                    if t in other_pub:
                        return True
                    if t in other_title_tokens:
                        return True
                return False

            if _tokens_match_source(tokens1, g2) or _tokens_match_source(tokens2, g1):
                merged[_find(k2)] = _find(k1)

    final: dict[str, list[RawEvidence]] = defaultdict(list)
    for k, items_ in groups.items():
        final[_find(k)].extend(items_)
    return dict(final)


def independence_factor(group_size: int) -> float:
    if group_size <= 1:
        return 1.0
    return 1.0 + sum(1.0 / (i * i) for i in range(2, group_size + 1))