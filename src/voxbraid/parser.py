"""Parse prepared UTF-8 TXT with optional role headings; no NLP or audio work."""

from __future__ import annotations

import re
from pathlib import Path

from voxbraid.models import Document, Paragraph, SourceLine

_ROLE_TAG = re.compile(r"\[([a-z][a-z0-9_-]*)(?::([a-z][a-z0-9_-]*))?\]", re.I)


class TextFormatError(ValueError):
    """Input TXT is not a valid VoxBraid document."""


def _role_marker(line: str, line_no: int) -> tuple[str, str] | None:
    """Return (role, kind) for a heading; reject suspicious standalone markup."""
    match = _ROLE_TAG.fullmatch(line)
    if match:
        role = match.group(1).lower()
        kind = (match.group(2) or "normal").lower()
        if kind not in {"normal", "tag", "lead"}:
            raise TextFormatError(f"Line {line_no}: unknown role modifier :{kind}")
        if kind in {"tag", "lead"} and role != "narrator":
            raise TextFormatError(
                f"Line {line_no}: :{kind} is reserved for [narrator:{kind}]"
            )
        return role, kind
    if line.startswith("[") and line.endswith("]"):
        raise TextFormatError(f"Line {line_no}: invalid role heading {line!r}")
    return None


def parse_text(text: str) -> Document:
    """Read plain TXT or tagged TXT, retaining paragraphs and source line provenance.

    A blank line ends a paragraph. Wrapped lines join with a single space. Each new
    role heading starts a new paragraph; arbitrary role names are valid. In tagged
    mode, leading #-comments are ignored (legacy demo compatibility).
    """
    lines = text.lstrip("\ufeff").splitlines()
    markers = [_role_marker(line.strip(), number) for number, line in enumerate(lines, 1)]
    tagged = any(marker is not None for marker in markers)
    role: str | None = None if tagged else "narrator"
    kind = "normal"
    pending_label: int | None = None
    has_text_after_label = False
    collected: list[tuple[int, str]] = []
    paragraphs: list[Paragraph] = []

    def flush() -> None:
        if not collected:
            return
        normalized: list[str] = []
        provenance: list[SourceLine] = []
        offset = 0
        for line_number, raw in collected:
            fragment = raw.strip()
            if normalized:
                offset += 1  # joining space
            provenance.append(SourceLine(offset, offset + len(fragment), line_number))
            normalized.append(fragment)
            offset += len(fragment)
        paragraphs.append(
            Paragraph(
                index=len(paragraphs) + 1,
                role=role or "narrator",
                kind=kind,
                text=" ".join(normalized),
                line_start=collected[0][0],
                line_end=collected[-1][0],
                source_lines=tuple(provenance),
            )
        )
        collected.clear()

    # for line_no, (raw, marker) in enumerate(zip(lines, markers), 1):
    for line_no, (raw, marker) in enumerate(
        zip(lines, markers, strict=True), 1
    ):
        line = raw.strip()
        if marker is not None:
            flush()
            if pending_label is not None and not has_text_after_label:
                raise TextFormatError(f"Line {pending_label}: role heading has no text")
            role, kind = marker
            pending_label = line_no
            has_text_after_label = False
            continue
        if not line:
            flush()
            continue
        if tagged and line.startswith("#"):
            continue
        if tagged and role is None:
            raise TextFormatError(
                f"Line {line_no}: text before first [role] heading: {line[:70]!r}"
            )
        collected.append((line_no, line))
        has_text_after_label = True

    flush()
    if tagged and pending_label is not None and not has_text_after_label:
        raise TextFormatError(f"Line {pending_label}: role heading has no text")
    if not paragraphs:
        raise TextFormatError("No readable text found in TXT")
    return Document("tagged" if tagged else "plain", tuple(paragraphs))


def parse_file(path: Path) -> Document:
    """Decode with strict UTF-8 to avoid silently mangling book contents."""
    return parse_text(path.read_text(encoding="utf-8-sig"))
