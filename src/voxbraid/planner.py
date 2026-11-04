"""Convert parsed paragraphs into voice-ready segments and pause decisions."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from voxbraid.models import Document, Paragraph, PlannedSegment

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "etc", "no",
}
_CLOSERS = '\u201d\u2019"\'\u00bb)]}'
_OPENERS = '\u201c"\'\u00ab([{'
_ATTRIBUTION_VERBS = {
    "said", "says", "asked", "asks", "cried", "cries", "shouted", "shouts",
    "whispered", "whispers", "replied", "replies", "called", "calls",
    "murmured", "murmurs", "yelled", "yells", "answered", "answers",
}


@dataclass(frozen=True)
class PauseOptions:
    intro: float = 3.0
    sentence: float = 1.5
    paragraph: float = 3.0
    speaker: float = 1.0
    attribution: float = 0.4
    lead: float = 0.6

    def __post_init__(self) -> None:
        for name in ("intro", "sentence", "paragraph", "speaker", "attribution", "lead"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} pause must be a finite, non-negative number")


def _is_abbreviation(text: str, index: int) -> bool:
    if 0 < index < len(text) - 1 and text[index - 1].isdigit() and text[index + 1].isdigit():
        return True  # 3.14
    found = re.search(r"([A-Za-z]+)$", text[:index])
    if not found:
        return False
    word = found.group(1)
    if word.lower() in _ABBREVIATIONS:
        return True
    # A. B. Smith; J. R. R. Tolkien. Only suppress an initial before another capital.
    if len(word) == 1 and re.match(r"\s+[A-Z]", text[index + 1 :]):
        return True
    return False


def sentence_slices(text: str) -> list[tuple[int, int]]:
    """Return offsets of English sentence-like spans, without losing punctuation.

    The rule-based splitter deliberately does not infer speakers. A closing quote
    followed by a speech-attribution phrase remains in the same sentence.
    """
    output: list[tuple[int, int]] = []
    start = 0
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char not in ".?!\u2026":
            pos += 1
            continue
        if char == "." and _is_abbreviation(text, pos):
            pos += 1
            continue
        punct_end = pos + 1
        while punct_end < len(text) and text[punct_end] in ".?!\u2026":
            punct_end += 1
        after_closers = punct_end
        while after_closers < len(text) and text[after_closers] in _CLOSERS:
            after_closers += 1
        if after_closers < len(text) and not text[after_closers].isspace():
            pos = punct_end
            continue
        remainder = text[after_closers:].lstrip()
        next_word = re.match(r"[A-Za-z]+", remainder.lstrip(_OPENERS))
        quoted = after_closers > punct_end
        if quoted and next_word:
            word = next_word.group(0).lower()
            # "Hello!" she said. / "Stop!" whispered the witch.
            # Do not merge independent narration like "Hello!" She walked away.
            pronoun_and_verb = re.match(r"(?i)(he|she|they|i|we|it)\s+([a-z]+)\b", remainder)
            is_attribution = word in _ATTRIBUTION_VERBS or (
                pronoun_and_verb is not None
                and pronoun_and_verb.group(2).lower() in _ATTRIBUTION_VERBS
            )
            if is_attribution:
                pos = after_closers
                continue
        chunk = text[start:after_closers]
        if chunk.strip():
            offset = len(chunk) - len(chunk.lstrip())
            output.append((start + offset, after_closers))
        start = after_closers
        while start < len(text) and text[start].isspace():
            start += 1
        pos = start
    if text[start:].strip():
        output.append((start, len(text.rstrip())))
    return output


def _source_lines(paragraph: Paragraph, start: int, end: int) -> tuple[int, int]:
    overlapping = [
        item.line for item in paragraph.source_lines
        if item.start < end and item.end > start
    ]
    if not overlapping:
        return paragraph.line_start, paragraph.line_end
    return min(overlapping), max(overlapping)


def _spoken_text(
    text: str, paragraph: Paragraph, first: bool, last: bool
) -> str:
    """Strip balanced quotation marks wrapping a character's whole paragraph.

    A quoted character paragraph can span several sentences, so the opener and
    closer may belong to *different* planned segments.
    """
    if paragraph.role != "narrator" and paragraph.kind == "normal":
        whole = paragraph.text
        if len(whole) >= 2 and (whole[0], whole[-1]) in {
            ('"', '"'), ('\u201c', '\u201d'), ("'", "'")
        }:
            if first:
                text = text[1:].lstrip()
            if last:
                text = text[:-1].rstrip()
    return text


def plan_segments(
    document: Document, options: PauseOptions | None = None
) -> tuple[PlannedSegment, ...]:
    """Plan deterministic, provider-independent speech chunks with one pause each."""
    options = options or PauseOptions()
    planned: list[PlannedSegment] = []
    last_paragraph: Paragraph | None = None
    for paragraph in document.paragraphs:
        slices = (
            [(0, len(paragraph.text))]
            if paragraph.kind != "normal"
            else sentence_slices(paragraph.text)
        )
        for sentence_no, (start, end) in enumerate(slices):
            raw = paragraph.text[start:end].strip()
            if not raw:
                continue
            if not planned:
                pause_kind = "intro"
            elif sentence_no > 0:
                pause_kind = "sentence"
            elif paragraph.kind == "tag" and last_paragraph and last_paragraph.role != "narrator":
                pause_kind = "attribution"
            elif last_paragraph and last_paragraph.kind == "tag" and paragraph.role != "narrator":
                pause_kind = "attribution"
            elif last_paragraph and last_paragraph.kind == "lead" and paragraph.role != "narrator":
                pause_kind = "lead"
            elif last_paragraph and paragraph.role != last_paragraph.role:
                pause_kind = "speaker"
            else:
                pause_kind = "paragraph"
            line_start, line_end = _source_lines(paragraph, start, end)
            planned.append(
                PlannedSegment(
                    index=len(planned) + 1,
                    role=paragraph.role,
                    kind=paragraph.kind,
                    text=_spoken_text(raw, paragraph, sentence_no == 0,
                                      sentence_no == len(slices) - 1),
                    paragraph_index=paragraph.index,
                    line_start=line_start,
                    line_end=line_end,
                    pause_kind=pause_kind,
                    pause_before=getattr(options, pause_kind),
                )
            )
        last_paragraph = paragraph
    return tuple(planned)
