"""Provider-independent models for the M1 text planning stage."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceLine:
    """Character offsets inside a normalized paragraph, mapped to input line number."""

    start: int
    end: int
    line: int


@dataclass(frozen=True)
class Paragraph:
    index: int
    role: str
    kind: str
    text: str
    line_start: int
    line_end: int
    source_lines: tuple[SourceLine, ...] = field(repr=False)


@dataclass(frozen=True)
class Document:
    mode: str  # 'plain' or 'tagged'
    paragraphs: tuple[Paragraph, ...]


@dataclass(frozen=True)
class PlannedSegment:
    index: int
    role: str
    kind: str
    text: str
    paragraph_index: int
    line_start: int
    line_end: int
    pause_kind: str
    pause_before: float
