"""M6: required offline end-to-end acceptance tests with actual encoded audio.

No mock skips or external TTS API access: FFmpeg/FFprobe are required to run
these tests. Providers are deterministic, and all outputs live under tmp_path.
"""

from __future__ import annotations

import json
import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from voxbraid.audio_validation import validate_audio
from voxbraid.cli import main
from voxbraid.composer import choose_music
from voxbraid.tts.registry import ProviderRegistry


def _tone_wav(path: Path, *, rate: int, hz: int) -> None:
    """Write real PCM audio to exercise FFmpeg conversion."""
    samples = round(rate * 0.18)
    values = [round(1200 * math.sin(2 * math.pi * hz * i / rate))
              for i in range(samples)]
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(struct.pack(f"<{samples}h", *values))


class MockLocalWav:
    audio_extension = ".wav"
    cache_version = "m6-mock-wav"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text, profile, output) -> None:
        self.calls.append((text, profile.voice))
        _tone_wav(output, rate=16000, hz=330)


class MockRemoteMp3:
    audio_extension = ".mp3"
    cache_version = "m6-mock-mp3"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text, profile, output) -> None:
        self.calls.append((text, profile.voice))
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=24000",
             "-t", "0.23", "-c:a", "libmp3lame", "-q:a", "5",
             "-y", str(output)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)


def _music(path: Path, frequency: int) -> None:
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=24000",
         "-t", "0.21", "-c:a", "libmp3lame", "-q:a", "6", "-y", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path, MockLocalWav, MockRemoteMp3]:
    local = MockLocalWav()
    remote = MockRemoteMp3()
    providers = ProviderRegistry()
    providers.register("local-wav", local)
    providers.register("remote-mp3", remote)
    monkeypatch.setattr("voxbraid.cli.default_registry", lambda: providers)
    story = tmp_path / "story.txt"
    story.write_text(
        "[narrator]\nOnce upon a time. The bird sang.\n\n"
        "[fox]\nHello, little bird!\n\n"
        "[narrator:tag]\nsaid the fox.\n\n"
        "[bird]\nHello, fox!\n", encoding="utf-8"
    )
    cfg = tmp_path / "book.yaml"
    cfg.write_text(
        "version: 1\nvoices:\n"
        "  narrator: {provider: local-wav, voice: Brian}\n"
        "  fox: {provider: remote-mp3, voice: Andrew}\n"
        "  bird: {provider: local-wav, voice: Ava}\n"
        "pauses: {intro: 0.1, sentence: 0.12, paragraph: 0.18,"
        " speaker: 0.2, attribution: 0.05, lead: 0.06}\n",
        encoding="utf-8",
    )
    return story, cfg, local, remote


def test_m6_cli_mixed_provider_music_and_recomposition(tmp_path: Path, monkeypatch) -> None:
    """Run real TXT -> WAV/MP3 clips -> 48k PCM -> mixed MP3, then rerender."""
    story, cfg, local, remote = _setup(tmp_path, monkeypatch)
    playlist = tmp_path / "baroque"
    playlist.mkdir()
    _music(playlist / "bach.mp3", 440)
    _music(playlist / "handel.mp3", 660)
    output = tmp_path / "audiobook.mp3"
    speech = tmp_path / "speech.mp3"
    command = ["render", str(story), "--config", str(cfg),
               "--music", str(playlist), "--music-seed", "11",
               "--speech-output", str(speech), "-o", str(output)]
    assert main(command) == 0
    assert output.exists() and speech.exists()
    assert len(local.calls) == 4 and len(remote.calls) == 1
    assert validate_audio(output) > 1
    assert validate_audio(speech) > 1
    work = tmp_path / "audiobook.voxbraid"
    payload = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    assert len(payload["segments"]) == 5
    assert payload["segments"][2]["provider"] == "remote-mp3"
    assert {Path(s["file"]).suffix for s in payload["segments"]} == {".wav", ".mp3"}
    metadata = json.loads(output.with_suffix(".compose.json").read_text(encoding="utf-8"))
    assert Path(metadata["music"]) == choose_music(playlist, seed=11)
    assert metadata["music_volume"] == 0.04
    assert len(metadata["pauses"]) == 5

    # Rendering again with a different pause only rewrites the mix, not speech.
    previous_calls = (len(local.calls), len(remote.calls))
    assert main([*command, "--sentence-gap", "0.4"]) == 0
    assert (len(local.calls), len(remote.calls)) == previous_calls
    revised = json.loads(output.with_suffix(".compose.json").read_text(encoding="utf-8"))
    assert revised["pauses"][1] == pytest.approx(0.4)
    assert revised["music"] == metadata["music"]

    # Change only fox's voice: only the fox segment should be synthesized again.
    cfg.write_text(cfg.read_text().replace("voice: Andrew", "voice: Andrew2"))
    assert main(command) == 0
    assert len(local.calls) == previous_calls[0]
    assert len(remote.calls) == previous_calls[1] + 1


def test_m6_cli_render_without_music_then_offline_compose(tmp_path: Path, monkeypatch) -> None:
    story, cfg, local, remote = _setup(tmp_path, monkeypatch)
    output = tmp_path / "plain.mp3"
    assert main(["render", str(story), "--config", str(cfg),
                 "-o", str(output)]) == 0
    assert validate_audio(output) > 1
    expected_calls = (len(local.calls), len(remote.calls))
    assert main(["compose", str(tmp_path / "plain.voxbraid" / "manifest.json"),
                 "--sentence-gap", "0.02", "-o", str(tmp_path / "short.mp3")]) == 0
    assert validate_audio(tmp_path / "short.mp3") > 0
    assert (len(local.calls), len(remote.calls)) == expected_calls


def test_m6_failed_audio_composition_keeps_previous_good_mp3(
    tmp_path: Path, monkeypatch,
) -> None:
    story, cfg, _, _ = _setup(tmp_path, monkeypatch)
    final = tmp_path / "good.mp3"
    assert main(["render", str(story), "--config", str(cfg), "-o", str(final)]) == 0
    before = final.read_bytes()
    music = tmp_path / "broken.mp3"
    music.write_bytes(b"this is not a usable mp3")
    with pytest.raises(SystemExit) as error:
        main(["compose", str(tmp_path / "good.voxbraid" / "manifest.json"),
              "--music", str(music), "-o", str(final)])
    assert error.value.code == 2
    assert final.read_bytes() == before
