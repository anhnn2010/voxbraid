from __future__ import annotations

import json
from pathlib import Path

import pytest

from voxbraid.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_plain_preview_offline(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["preview", str(FIXTURES / "plain_story.txt")]) == 0
    output = capsys.readouterr().out
    assert "Mode: plain" in output
    assert "sentence" in output
    assert "paragraph" in output
    assert "no TTS request" in output


def test_tagged_preview_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["preview", str(FIXTURES / "multivoice_story.txt"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "tagged"
    assert data["segments_total"] == 5
    assert [s["role"] for s in data["segments"]] == [
        "narrator", "fox", "narrator", "bird", "narrator"
    ]
    assert data["segments"][2]["pause_kind"] == "attribution"


def test_custom_pause_and_limit(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["preview", str(FIXTURES / "plain_story.txt"),
                 "--intro", "7", "--sentence-gap", "2", "--limit", "2", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["segments"]) == 2
    assert data["segments"][0]["pause_before"] == 7
    assert data["segments"][1]["pause_before"] == 2
    assert data["segments_total"] > 2


@pytest.mark.parametrize("extra", [["--limit", "0"], ["--intro", "-1"],
                                  ["--speaker-gap", "nan"]])
def test_invalid_preview_options_raise_clean_error(extra: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["preview", str(FIXTURES / "plain_story.txt"), *extra])
    assert exc.value.code == 2


def test_missing_file_error_is_clear(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["preview", "no_such_file_here.txt"])
    assert exc.value.code == 2
    assert "no_such_file_here.txt" in capsys.readouterr().err
