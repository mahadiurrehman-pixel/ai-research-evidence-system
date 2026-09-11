"""
weighting.py — Isolated evidence-weight scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .models import (
    AnalyzedEvidence,
    RawEvidence,
    Relevance,
    SourceType,
    Strength,
)


_STRENGTH_W = {Strength.HIGH: 3.0, Strength.MEDIUM: 2.0, Strength.LOW: 1.0}
_RELEVANCE_W = {
    Relevance.HIGH: 1.0,
    Relevance.MEDIUM: 0.7,
    Relevance.LOW: 0.4,
    Relevance.NONE: 0.0,
}
_SOURCE_TYPE_W = {
    SourceType.PEER_REVIEWED: 1.25,
    SourceType.GOVERNMENT: 1.15,
    SourceType.ENCYCLOPEDIA: 1.05,
    SourceType.BOOK: 1.05,
    SourceType.PREPRINT: 0.9,
    SourceType.NEWS: 0.8,
    SourceType.BLOG: 0.6,
    SourceType.OTHER: 0.85,
}
_METHOD_W = {
    "meta-analysis": 1.35,
    "systematic review": 1.30,
    "rct": 1.25,
    "randomized controlled": 1.25,
    "cohort": 1.10,
    "case-control": 1.05,
    "cross-sectional": 0.95,
    "survey": 0.85,
    "case study": 0.75,
    "opinion": 0.5,
    "editorial": 0.5,
}


@dataclass
class WeightBreakdown:
    base: float = 0.0
    relevance: float = 0.0
    source_type: float = 1.0
    methodology: float = 1.0
    peer_review: float = 1.0
    recency: float = 1.0
    quality_hint: float = 1.0
    independence: float = 1.0
    total: float = 0.0
    notes: list[str] = field(default_factory=list)

    def explain(self) -> str:
        return (
            f"base={self.base:.2f}, rel={self.relevance:.2f}, "
            f"src={self.source_type:.2f}, method={self.methodology:.2f}, "
            f"peer={self.peer_review:.2f}, recency={self.recency:.2f}, "
            f"quality={self.quality_hint:.2f}, indep={self.independence:.2f} "
            f"=> total={self.total:.3f}"
        )


def _method_multiplier(text: str) -> tuple[float, str | None]:
    if not text:
        return 1.0, None
    t = text.lower()
    for key, mult in _METHOD_W.items():
        if key in t:
            return mult, key
    return 1.0, None


def _recency_multiplier(
    year: Optional[int],
    publication_date: Optional[date],
    today: Optional[date] = None,
) -> float:
    year_val: Optional[int] = None
    if publication_date is not None:
        year_val = publication_date.year
    elif year is not None:
        year_val = year
    if year_val is None:
        return 1.0
    cur = (today or date.today()).year
    age = max(0, cur - year_val)
    if age <= 2:
        return 1.10
    if age <= 5:
        return 1.00
    if age <= 10:
        return 0.90
    if age <= 20:
        return 0.80
    return 0.70


def calculate_evidence_weight(
    analyzed: AnalyzedEvidence,
    raw: Optional[RawEvidence] = None,
    independence_factor: float = 1.0,
    today: Optional[date] = None,
) -> WeightBreakdown:
    b = WeightBreakdown()

    b.base = _STRENGTH_W.get(analyzed.strength, 1.0)
    b.relevance = _RELEVANCE_W.get(analyzed.relevance, 0.5)

    if raw is not None:
        if raw.source_type is not None:
            b.source_type = _SOURCE_TYPE_W.get(raw.source_type, 1.0)

        method_text = " ".join(filter(None, [
            raw.study_design or "",
            raw.methodology or "",
            analyzed.methodology_note or "",
        ]))
        m_mult, m_key = _method_multiplier(method_text)
        b.methodology = m_mult
        if m_key:
            b.notes.append(f"method:{m_key}")

        if raw.peer_reviewed is True:
            b.peer_review = 1.20
        elif raw.peer_reviewed is False:
            b.peer_review = 0.95

        b.recency = _recency_multiplier(raw.year, raw.publication_date, today)

        if raw.source_quality == Strength.HIGH:
            b.quality_hint = 1.15
        elif raw.source_quality == Strength.LOW:
            b.quality_hint = 0.85

    b.independence = max(0.25, min(2.0, independence_factor))

    total = (
        b.base
        * max(b.relevance, 0.05)
        * b.source_type
        * b.methodology
        * b.peer_review
        * b.recency
        * b.quality_hint
        * b.independence
    )
    if analyzed.relevance == Relevance.NONE:
        total = 0.0
    b.total = float(max(total, 0.0))
    return b