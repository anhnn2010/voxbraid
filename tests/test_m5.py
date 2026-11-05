"""M5 config and single-command render tests, all offline."""

from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path

import pytest

from voxbraid.cli import main
from voxbraid.settings import SettingsError, load_render_settings
from voxbraid.tts.registry import ProviderRegistry
from voxbraid.voices import VoiceConfigError, load_voices

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def test_bedtime_preset_and_builtin_defaults() -> None:
    defaults = load_render_settings()
    bedtime = load_render_settings(preset="bedtime")
    assert bedtime.pauses.intro == defaults.pauses.intro == 3.0
    assert bedtime.pauses.paragraph == 3
    assert bedtime.music.volume == 0.04
    assert bedtime.music.source is None
    assert bedtime.voices["narrator"].voice == "en-US-BrianNeural"


def test_config_layers_preset_book_and_cli(tmp_path: Path) -> None:
    folder = tmp_path / "book"
    folder.mkdir()
    (folder / "tracks").mkdir()
    custom_preset = folder / "my_preset.yaml"
    custom_preset.write_text("version: 1\npauses:\n  intro: 1\n  sentence: 2\nmusic:\n  volume: 0.2\n")
    book = folder / "book.yaml"
    book.write_text("""version: 1
voices:
  narrator: {provider: edge, voice: en-US-EmmaNeural}
pauses: {sentence: 2.5, paragraph: 4}
music: {source: tracks, volume: 0.05, seed: 11}
retry: {retries: 2}
""")
    cfg = load_render_settings(
        preset=str(custom_preset), config=book,
        overrides={"sentence": 1.25, "music_volume": 0.08, "retries": 3},
    )
    assert cfg.pauses.intro == 1
    assert cfg.pauses.sentence == 1.25
    assert cfg.pauses.paragraph == 4
    assert cfg.music.source == folder / "tracks"
    assert cfg.music.seed == 11
    assert cfg.music.volume == 0.08
    assert cfg.voices["narrator"].voice == "en-US-EmmaNeural"
    assert cfg.retry.retries == 3
    no_music = load_render_settings(config=book, overrides={"no_music": True})
    assert no_music.music.source is None and no_music.music.seed is None


def test_voice_file_yaml_and_json_backward_compatible(tmp_path: Path) -> None:
    mapping = {"narrator": {"provider": "edge", "voice": "en-US-BrianNeural",
                             "options": {"rate": "-10%"}}}
    yml = tmp_path / "voices.yaml"
    yml.write_text("narrator:\n  provider: edge\n  voice: en-US-BrianNeural\n"
                   "  options:\n    rate: '-10%'\n")
    js = tmp_path / "voices.json"
    js.write_text(json.dumps(mapping))
    assert load_voices(js)["narrator"] == load_voices(yml)["narrator"]
    error = tmp_path / "broken.yml"
    error.write_text("narrator: [unterminated")
    with pytest.raises(VoiceConfigError, match="Invalid YAML"):
        load_voices(error)


def test_external_voices_override_book_mapping(tmp_path: Path) -> None:
    conf = tmp_path / "book.yaml"
    conf.write_text("voices:\n  witch: {provider: edge, voice: en-US-EmmaNeural}\n")
    custom = tmp_path / "voice.json"
    custom.write_text(json.dumps({"narrator": {
        "provider": "edge", "voice": "en-US-AvaNeural"
    }}))
    profiles = load_render_settings(config=conf, voices=custom).voices
    assert list(profiles) == ["narrator"]
    assert profiles["narrator"].voice == "en-US-AvaNeural"


@pytest.mark.parametrize("configuration, match", [
    ("version: 2", "version"),
    ("pauses: {unknown: 3}", "unknown"),
    ("pauses: {intro: -1}", "nonnegative"),
    ("pauses: {intro: true}", "number"),
    ("music: {volume: 5}", "between 0 and 1"),
    ("retry: {retries: 'four'}", "integer"),
    ("voices: {narrator: [bad]}", "Voice profile"),
    ("unsafe: option", "unknown"),
])
def test_invalid_book_config_rejected(tmp_path: Path, configuration: str, match: str) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(configuration)
    with pytest.raises(SettingsError, match=match):
        load_render_settings(config=path)


def test_missing_music_seed_rejected() -> None:
    with pytest.raises(SettingsError, match="directory"):
        load_render_settings(overrides={"music_seed": 4})


def test_render_dry_run_creates_nothing_and_checks_roles(tmp_path: Path, capsys) -> None:
    story = tmp_path / "story.txt"
    story.write_text("[narrator]\nHello!\n\n[fox]\nWho is there?\n")
    voice = tmp_path / "voices.yaml"
    voice.write_text("narrator: {provider: edge, voice: en-US-BrianNeural}\n"
                     "fox: {provider: edge, voice: en-US-AndrewNeural}\n")
    output = tmp_path / "story.mp3"
    assert main(["render", str(story), "--voices", str(voice),
                 "--preset", "bedtime", "--dry-run", "-o", str(output)]) == 0
    assert "[fox] edge:en-US-AndrewNeural" in capsys.readouterr().out
    assert not output.exists()
    assert not output.with_suffix(".voxbraid").exists()
    voice.write_text("narrator: {provider: edge, voice: en-US-BrianNeural}\n")
    with pytest.raises(SystemExit) as exc:
        main(["render", str(story), "--voices", str(voice),
              "--dry-run", "-o", str(output)])
    assert exc.value.code == 2
    assert not output.with_suffix(".voxbraid").exists()


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg/FFprobe unavailable")
def test_render_full_pipeline_offline_resumes_and_recomposes(tmp_path: Path, monkeypatch) -> None:
    class FakeWAV:
        audio_extension = ".wav"
        cache_version = "m5-mock"

        def __init__(self) -> None:
            self.calls = 0

        def validate(self, profile) -> None:
            if profile.voice != "fake-voice":
                raise ValueError("voice invalid")

        async def synthesize(self, text, profile, output):
            self.calls += 1
            with wave.open(str(output), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(16000)
                writer.writeframes(b"\x00\x00" * 3200)

    fake = FakeWAV()
    registry = ProviderRegistry()
    registry.register("fake", fake)
    monkeypatch.setattr("voxbraid.cli.default_registry", lambda: registry)
    story = tmp_path / "test.txt"
    story.write_text("Hello. Goodbye.\n\nThe end!", encoding="utf-8")
    voices = tmp_path / "book.yaml"
    voices.write_text("voices:\n  narrator: {provider: fake, voice: fake-voice}\n")
    output = tmp_path / "test.mp3"
    command = ["render", str(story), "--config", str(voices),
               "--preset", "bedtime", "-o", str(output)]
    assert main(command) == 0
    assert fake.calls == 3
    assert output.exists()
    assert (tmp_path / "test.voxbraid" / "manifest.json").exists()
    # Composing again with a different pause never calls TTS again.
    assert main([*command, "--sentence-gap", "0.1", "--paragraph-gap", "0.2"]) == 0
    assert fake.calls == 3
    metadata = json.loads(output.with_suffix(".compose.json").read_text())
    assert metadata["pauses"] == [3.0, 0.1, 0.2]
    # Changing a line re-synthesizes only the changed chunk.
    story.write_text("Hello. Another goodbye.\n\nThe end!")
    assert main(command) == 0
    assert fake.calls == 4


def test_invalid_render_option_fails_before_files(tmp_path: Path, capsys) -> None:
    story = tmp_path / "hello.txt"
    story.write_text("Hello.")
    for option in (["--music-seed", "2"], ["--music-volume", "1.5"],
                   ["--max-segments", "0"], ["--speech-output", str(tmp_path / "x.mp3")]):
        with pytest.raises(SystemExit) as error:
            main(["render", str(story), "-o", str(tmp_path / "out.mp3"), *option])
        assert error.value.code == 2
        assert not (tmp_path / "out.voxbraid").exists()
        capsys.readouterr()
