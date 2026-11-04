from __future__ import annotations

import pytest

from voxbraid.parser import TextFormatError, parse_text


def test_plain_text_paragraphs_and_wrapped_lines() -> None:
    document = parse_text("First sentence.\nAnother sentence.\n\nA new paragraph.\n")
    assert document.mode == "plain"
    assert [p.text for p in document.paragraphs] == [
        "First sentence. Another sentence.", "A new paragraph."
    ]
    assert [(p.line_start, p.line_end) for p in document.paragraphs] == [(1, 2), (4, 4)]
    assert all(p.role == "narrator" for p in document.paragraphs)


def test_role_markers_and_legacy_tags() -> None:
    document = parse_text("""# Title
[narrator]
Hello there.

[bad_witch]
“Stop!”
[narrator:tag]
she cried.
[narrator:lead]
Then she called:
""")
    assert document.mode == "tagged"
    assert [(p.role, p.kind) for p in document.paragraphs] == [
        ("narrator", "normal"), ("bad_witch", "normal"),
        ("narrator", "tag"), ("narrator", "lead"),
    ]
    assert [p.line_start for p in document.paragraphs] == [3, 6, 8, 10]


def test_role_case_insensitive_and_utf8_bom() -> None:
    doc = parse_text("\ufeff[NaRrAtOr]\nOnce upon a time.\n[QUEEN]\nHello!\n")
    assert [p.role for p in doc.paragraphs] == ["narrator", "queen"]


def test_comments_only_ignored_in_tagged_mode() -> None:
    plain = parse_text("# Chapter One\nThis is narrated.")
    assert plain.paragraphs[0].text.startswith("# Chapter One")
    tagged = parse_text("[narrator]\n# Chapter One\nThis is narrated.")
    assert tagged.paragraphs[0].text == "This is narrated."


@pytest.mark.parametrize("text,message", [
    ("", "No readable text"),
    (" \n\n", "No readable text"),
    ("Foreword.\n[narrator]\nHello.", "Line 1: text before"),
    ("[witch:tag]\nHello!", "reserved for"),
    ("[narrator:unknown]\nHello!", "unknown role modifier"),
    ("[narrator]\nHi\n[witch]\n", "Line 3: role heading has no text"),
    ("[narrator]\n[witch]\nHello!", "Line 1: role heading has no text"),
    ("[not a role]\nHello!", "invalid role heading"),
    ("[narrator]\n#comment\n", "role heading has no text"),
])
def test_invalid_text_is_rejected(text: str, message: str) -> None:
    with pytest.raises(TextFormatError, match=message):
        parse_text(text)


def test_paragraph_separation_inside_role() -> None:
    document = parse_text("[narrator]\nFirst.\n\nSecond.\n")
    assert len(document.paragraphs) == 2
    assert document.paragraphs[0].text == "First."
    assert document.paragraphs[1].text == "Second."


def test_no_markers_required_for_plain_text() -> None:
    doc = parse_text("The quick brown fox.")
    assert doc.mode == "plain"
    assert doc.paragraphs[0].role == "narrator"
