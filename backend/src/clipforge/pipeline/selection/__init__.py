"""Moment selection: from scored sentences to a short list of Shorts to render.

    sentences (+heat, tags) -> windows -> candidates -> picks (no-AI or AI) -> validated picks

Everything here is pure (no database, no network) so it is easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Sent:
    """One transcript sentence as selection sees it (full-video seconds)."""

    source_id: str
    idx: int
    start: float
    end: float
    text: str
    heat: float
    tags: tuple[str, ...] = ()  # e.g. ("LOUD", "CHAT")

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Candidate:
    id: int  # 1-based, stable within a run (the AI refers to it)
    source_id: str
    start: float
    end: float
    score: float  # 0..100
    first: int  # sentence indices (inclusive) in the source's list
    last: int
    peak: float  # time of the hottest sentence
    tags: list[str] = field(default_factory=list)
    head: str = ""
    tail: str = ""
    text: str = ""  # full text (deep mode)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Pick:
    source_id: str
    start: float
    end: float
    hook: str
    title: str
    hashtags: list[str]
    keywords: list[str]
    credit: str | None
    score: float
    reason: str
    candidate_id: int | None = None
    issues: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start
