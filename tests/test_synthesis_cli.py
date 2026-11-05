from __future__ import annotations

import json
from pathlib import Path

import pytest

from voxbraid.cli import main


@pytest.mark.parametrize("args", [
    ["--max-segments", "0"],
    ["--max-segments", "-4"],
    ["--intro", "-1"],
])
def test_synthesis_rejects_invalid_arguments(args, tmp_path: Path) -> None:
    story = tmp_path / "story.txt"
    story.write_text("Hello there.")
    with pytest.raises(SystemExit) as exc:
        main(["synthesize", str(story), "--out-dir", str(tmp_path / "out"), *args])
    assert exc.value.code == 2


def test_synthesis_missing_voice_config_is_clear(tmp_path: Path, capsys) -> None:
    story = tmp_path / "story.txt"
    story.write_text("[narrator]\nHello!\n\n[witch]\nNo!")
    with pytest.raises(SystemExit) as exc:
        main(["synthesize", str(story), "--out-dir", str(tmp_path / "out")])
    assert exc.value.code == 2
    assert "No voice mapping for [witch]" in capsys.readouterr().err


def test_synthesis_with_invalid_edge_options_stops_offline(tmp_path: Path, capsys) -> None:
    story = tmp_path / "story.txt"
    story.write_text("Hi!")
    config = tmp_path / "voices.json"
    config.write_text(json.dumps({
        "narrator": {"provider": "edge", "voice": "Brian", "options": {"speed": "1"}}
    }))
    with pytest.raises(SystemExit) as exc:
        main(["synthesize", str(story), "--voices", str(config),
              "--out-dir", str(tmp_path / "out")])
    assert exc.value.code == 2
    assert "unsupported" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_cli_synthesize_mock_provider_and_max_segments(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    from voxbraid.tts.registry import ProviderRegistry

    class FakeProvider:
        audio_extension = ".mp3"

        def validate(self, profile):
            assert profile.voice == "en-US-BrianNeural"

        async def synthesize(self, text, profile, output):
            output.write_bytes(b"fake mp3 bytes")

    registry = ProviderRegistry()
    registry.register("edge", FakeProvider())
    monkeypatch.setattr("voxbraid.cli.default_registry", lambda: registry)
    monkeypatch.setattr("voxbraid.synthesis.check_audio_tools", lambda: None)
    monkeypatch.setattr("voxbraid.synthesis.validate_audio", lambda path: 1.0)
    story = tmp_path / "story.txt"
    story.write_text("One day a fox arrived.\nThe bird looked up.")
    output_dir = tmp_path / "speech"
    assert main([
        "synthesize", str(story), "--out-dir", str(output_dir), "--max-segments", "1"
    ]) == 0
    assert (output_dir / "segment_0001.mp3").is_file()
    assert not (output_dir / "segment_0002.mp3").exists()
    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert len(manifest["segments"]) == 1
    assert manifest["segments"][0]["voice"] == "en-US-BrianNeural"
    assert "Completed 1 speech clips" in capsys.readouterr().out
