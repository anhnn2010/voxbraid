from __future__ import annotations

import pytest

from voxbraid.parser import parse_text
from voxbraid.planner import PauseOptions, plan_segments, sentence_slices


def parts(text: str) -> list[str]:
    return [text[start:end] for start, end in sentence_slices(text)]


@pytest.mark.parametrize(("text", "expected"), [
    ("Mr. Elephant is kind. Hello!", ["Mr. Elephant is kind.", "Hello!"]),
    ("Dr. Smith arrived. He waved.", ["Dr. Smith arrived.", "He waved."]),
    ("J. R. R. Tolkien wrote books. He did.", [
        "J. R. R. Tolkien wrote books.", "He did."
    ]),
    ("The price is 3.14 dollars. Great!", [
        "The price is 3.14 dollars.", "Great!"
    ]),
    ('"Hello!" she said. "Come in!"', ['"Hello!" she said.', '"Come in!"']),
    ('“Who are you?” asked Emma. “I am Ava.”', [
        '“Who are you?” asked Emma.', '“I am Ava.”'
    ]),
    ('"Hello!" "Goodbye!"', ['"Hello!"', '"Goodbye!"']),
    ("Wait... What is that?", ["Wait...", "What is that?"]),
    ("Well?! That was close.", ["Well?!", "That was close."]),
    ("No punctuation here", ["No punctuation here"]),
    ("Hi! how are you?", ["Hi!", "how are you?"]),
])
def test_sentence_boundaries(text: str, expected: list[str]) -> None:
    assert parts(text) == expected


def test_sentence_and_paragraph_pauses() -> None:
    doc = parse_text("One. Two.\nThree.\n\nFour.")
    segments = plan_segments(doc)
    assert [s.text for s in segments] == ["One.", "Two.", "Three.", "Four."]
    assert [s.pause_kind for s in segments] == [
        "intro", "sentence", "sentence", "paragraph"
    ]
    assert [s.pause_before for s in segments] == [3, 1.5, 1.5, 3]
    assert [(s.line_start, s.line_end) for s in segments] == [
        (1, 1), (1, 1), (2, 2), (4, 4)
    ]


def test_legacy_speaker_attribution_lead_and_outer_quotes() -> None:
    doc = parse_text("""[narrator:lead]
Then she called:
[witch]
“Rapunzel, let down your hair!”
[narrator:tag]
she said.
[rapunzel]
“The prince,”
[narrator:tag]
says Rapunzel.
""")
    segments = plan_segments(doc)
    assert [s.role for s in segments] == [
        "narrator", "witch", "narrator", "rapunzel", "narrator"
    ]
    assert [s.text for s in segments] == [
        "Then she called:", "Rapunzel, let down your hair!", "she said.",
        "The prince,", "says Rapunzel."
    ]
    assert [s.pause_kind for s in segments] == [
        "intro", "lead", "attribution", "attribution", "attribution"
    ]
    assert [s.pause_before for s in segments] == [3, 0.6, 0.4, 0.4, 0.4]


def test_speaker_pause_is_distinct_from_paragraph() -> None:
    segments = plan_segments(parse_text("[fox]\nHi.\n[bird]\nHello.\n[narrator]\nAll was well."))
    assert [s.pause_kind for s in segments] == ["intro", "speaker", "speaker"]


def test_custom_pauses_are_respected() -> None:
    options = PauseOptions(intro=2, sentence=0, paragraph=4, speaker=1.2)
    segments = plan_segments(parse_text("One. Two.\n\nThree."), options)
    assert [s.pause_before for s in segments] == [2, 0, 4]


@pytest.mark.parametrize("bad", [-1, float("inf"), float("nan")])
def test_nonfinite_and_negative_pauses_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="finite, non-negative"):
        PauseOptions(sentence=bad)


def test_repeated_paragraphs_keep_source_provenance() -> None:
    segs = plan_segments(parse_text("[narrator]\nOne sentence\nends here. Next one.\n"))
    assert segs[0].text == "One sentence ends here."
    assert (segs[0].line_start, segs[0].line_end) == (2, 3)
    assert segs[1].text == "Next one."
    assert (segs[1].line_start, segs[1].line_end) == (3, 3)


def test_legacy_rapunzel_can_be_previewed_without_network() -> None:
    # Fixture only contains original synthetic content, not the full book.
    doc = parse_text("[witch]\n“Who gave you this?”\n[narrator:tag]\nshouts the witch.")
    segs = plan_segments(doc)
    assert len(segs) == 2
    assert segs[1].pause_kind == "attribution"


def test_quoted_character_paragraph_spanning_multiple_sentences() -> None:
    doc = parse_text('[witch]\n“You took my food. Now I will take your baby!”')
    segments = plan_segments(doc)
    assert [s.text for s in segments] == [
        "You took my food.", "Now I will take your baby!"
    ]
    assert [s.pause_kind for s in segments] == ["intro", "sentence"]


def test_quoted_speech_followed_by_independent_narration_splits() -> None:
    assert parts('“Hello!” She walked away.') == ['“Hello!”', 'She walked away.']
