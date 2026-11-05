"""M4 integration/regression tests, entirely offline (no Edge/other TTS calls)."""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from voxbraid.audio_validation import validate_audio
from voxbraid.cli import main
from voxbraid.composer import (
    ComposeError,
    PauseOverrides,
    choose_music,
    compose_audiobook,
    load_manifest,
)

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _voice_wav(path: Path, *, duration: float = 0.2, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = round(duration * rate)
        values = [int(2500 * math.sin(2 * math.pi * 220 * i / rate))
                  for i in range(samples)]
        output.writeframes(struct.pack(f"<{samples}h", *values))


def _manifest(folder: Path, *, pauses: tuple[float, ...] = (0.3, 0.2)) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, (seconds, kind) in enumerate(
        zip(pauses, ("intro", "sentence"), strict=True), 1
    ):
        filename = f"segment_{index:04d}.wav"
        _voice_wav(folder / filename)
        entries.append({"index": index, "role": "narrator", "file": filename,
                        "pause_kind": kind, "pause_before": seconds})
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps({"format": "voxbraid-synthesis-v1", "composed": False,
                                    "segments": entries}), encoding="utf-8")
    return manifest


def _music(path: Path, *, duration: float = 0.3) -> None:
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=16000", "-t", str(duration),
        "-c:a", "libmp3lame", "-q:a", "5", "-y", str(path),
    ], check=True, capture_output=True)


def test_pause_overrides_and_manifest_validation(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    clips = load_manifest(manifest)
    assert [clip.pause_before for clip in clips] == [0.3, 0.2]
    clips = load_manifest(manifest, PauseOverrides(sentence=0.6, intro=0))
    assert [clip.pause_before for clip in clips] == [0, 0.6]
    assert [clip.path.name for clip in clips] == ["segment_0001.wav", "segment_0002.wav"]


@pytest.mark.parametrize("invalid", [float("nan"), -0.1, float("inf")])
def test_override_non_finite_or_negative(invalid: float) -> None:
    with pytest.raises(ComposeError):
        PauseOverrides(sentence=invalid)


@pytest.mark.parametrize("edit", [
    lambda x: x.update(format="nope"),
    lambda x: x.update(composed=True),
    lambda x: x.update(segments=[]),
    lambda x: x["segments"][1].update(index=7),
    lambda x: x["segments"][0].update(pause_kind="unknown"),
    lambda x: x["segments"][0].update(pause_before=-1),
    lambda x: x["segments"][0].update(pause_before="0.3"),
    lambda x: x["segments"][0].update(file="../outside.wav"),
    lambda x: x["segments"][0].update(file="not_here.wav"),
])
def test_refuse_incomplete_or_unsafe_manifest(tmp_path: Path, edit) -> None:
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text())
    edit(data)
    manifest.write_text(json.dumps(data))
    with pytest.raises(ComposeError):
        load_manifest(manifest)


def test_refuse_symlinked_audio_outside_manifest(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    manifest = _manifest(folder)
    target = tmp_path / "private.wav"
    _voice_wav(target)
    (folder / "segment_0001.wav").unlink()
    (folder / "segment_0001.wav").symlink_to(target)
    with pytest.raises(ComposeError, match="unsafe"):
        load_manifest(manifest)


def test_choose_music_file_and_folder_seed(tmp_path: Path) -> None:
    folder = tmp_path / "music"
    folder.mkdir()
    (folder / "A.mp3").write_bytes(b"x")
    (folder / "b.MP3").write_bytes(b"x")
    (folder / "other.wav").write_bytes(b"x")
    inner = folder / "subfolder"
    inner.mkdir()
    (inner / "c.mp3").write_bytes(b"x")
    assert choose_music(folder / "A.mp3") == (folder / "A.mp3").resolve()
    chosen = choose_music(folder, seed=42)
    assert chosen.name in {"A.mp3", "b.MP3"}
    assert choose_music(folder, seed=42) == chosen
    with pytest.raises(ComposeError, match="directory"):
        choose_music(folder / "A.mp3", seed=42)
    with pytest.raises(ComposeError, match="requires"):
        choose_music(None, seed=42)
    with pytest.raises(ComposeError, match="MP3"):
        choose_music(folder / "other.wav")
    with pytest.raises(ComposeError, match="no MP3"):
        choose_music(tmp_path)


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requires FFmpeg/FFprobe")
def test_real_speech_composition_pcm_pauses_and_mp3(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "clips")
    output = tmp_path / "story.mp3"
    result = compose_audiobook(manifest, output)
    assert output.exists() and result.music is None
    # 0.3 intro + 0.2 + 0.2 sentence gap + 0.2 speech = 0.9s
    assert result.speech_duration == pytest.approx(0.9, abs=0.015)
    assert validate_audio(output) == pytest.approx(0.9, abs=0.09)
    metadata = json.loads(result.metadata.read_text())
    assert metadata["pauses"] == [0.3, 0.2]
    assert metadata["music"] is None
    assert not list(tmp_path.glob(".voxbraid-compose-*"))

    # Change only the M4 timeline; speech clips remain exactly unchanged.
    original_data = [(p.name, p.read_bytes()) for p in (tmp_path / "clips").glob("*.wav")]
    new_result = compose_audiobook(manifest, output,
                                    pauses=PauseOverrides(intro=0, sentence=0.6))
    assert new_result.speech_duration == pytest.approx(1.0, abs=0.015)
    assert [(p.name, p.read_bytes()) for p in (tmp_path / "clips").glob("*.wav")] == original_data


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requires FFmpeg/FFprobe")
def test_music_directory_loop_fades_and_speech_export(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "clips", pauses=(0.3, 0.2))
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    _music(music_dir / "bach.mp3", duration=0.17)  # Shorter than audiobook -> loop
    _music(music_dir / "vivaldi.mp3", duration=0.18)
    result = compose_audiobook(
        manifest, tmp_path / "mix.mp3", music_source=music_dir,
        music_seed=12, fade_in=0.12, fade_out=0.12,
        speech_output=tmp_path / "speech.mp3",
    )
    assert result.music in (music_dir / "bach.mp3", music_dir / "vivaldi.mp3")
    assert result.speech_output is not None and result.speech_output.exists()
    assert validate_audio(result.output) == pytest.approx(result.speech_duration, abs=0.12)
    assert validate_audio(result.speech_output) == pytest.approx(result.speech_duration, abs=0.12)
    report = json.loads(result.metadata.read_text())
    assert report["music"] == str(result.music)
    assert report["music_seed"] == 12

    again = compose_audiobook(manifest, tmp_path / "mix2.mp3",
                              music_source=music_dir, music_seed=12)
    assert again.music == result.music


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requires FFmpeg/FFprobe")
def test_music_explicit_file_and_atomic_failure(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "clips")
    song = tmp_path / "music.mp3"
    _music(song)
    final = tmp_path / "final.mp3"
    result = compose_audiobook(manifest, final, music_source=song)
    assert result.music == song.resolve()
    previous = final.read_bytes()
    (tmp_path / "clips" / "segment_0002.wav").write_bytes(b"broken")
    with pytest.raises(ComposeError):
        compose_audiobook(manifest, final, music_source=song)
    assert final.read_bytes() == previous
    assert not list(tmp_path.glob(".voxbraid-compose-*"))


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requires FFmpeg/FFprobe")
def test_input_collision_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "clips")
    mp3_clip = tmp_path / "clips" / "segment_0001.mp3"
    _music(mp3_clip)
    data = json.loads(manifest.read_text())
    data["segments"][0]["file"] = mp3_clip.name
    manifest.write_text(json.dumps(data))
    with pytest.raises(ComposeError, match="overwrite an input"):
        compose_audiobook(manifest, mp3_clip)

    song = tmp_path / "music.mp3"
    _music(song)
    with pytest.raises(ComposeError, match="overwrite an input"):
        compose_audiobook(manifest, song, music_source=song)


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requires FFmpeg/FFprobe")
def test_cli_compose_and_invalid_file(tmp_path: Path, capsys) -> None:
    manifest = _manifest(tmp_path / "clips")
    target = tmp_path / "book.mp3"
    assert main(["compose", str(manifest), "--output", str(target),
                 "--intro", "0", "--sentence-gap", "0.1"]) == 0
    assert "Composed 2 speech clips" in capsys.readouterr().out
    assert target.is_file()
    with pytest.raises(SystemExit) as error:
        main(["compose", str(manifest), "-o", str(tmp_path / "book.wav")])
    assert error.value.code == 2


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requires FFmpeg/FFprobe")
def test_mix_native_wav_and_mp3_clips(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "clips")
    source = tmp_path / "clips" / "segment_0002.wav"
    encoded = tmp_path / "clips" / "segment_0002.mp3"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(source),
        "-codec:a", "libmp3lame", "-q:a", "4", "-y", str(encoded),
    ], check=True, capture_output=True)
    source.unlink()
    data = json.loads(manifest.read_text())
    data["segments"][1]["file"] = encoded.name
    data["segments"][1]["provider"] = "second-provider"
    manifest.write_text(json.dumps(data))
    result = compose_audiobook(manifest, tmp_path / "mixed.mp3")
    assert result.segments == 2
    assert result.speech_duration == pytest.approx(0.9, abs=0.06)


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requires FFmpeg/FFprobe")
def test_real_m3_manifest_then_m4_compose_without_tts(tmp_path: Path) -> None:
    import asyncio

    from voxbraid.parser import parse_text
    from voxbraid.planner import plan_segments
    from voxbraid.retry import RetryPolicy
    from voxbraid.synthesis import synthesize_segments
    from voxbraid.tts.base import VoiceProfile
    from voxbraid.tts.registry import ProviderRegistry

    class SpeechProvider:
        audio_extension = ".wav"
        cache_version = "1"

        def __init__(self) -> None:
            self.calls = 0

        async def synthesize(self, text, profile, output):
            self.calls += 1
            _voice_wav(output)

    speech = SpeechProvider()
    registry = ProviderRegistry()
    registry.register("fake", speech)
    segments = plan_segments(parse_text("First sentence. Second sentence."))
    result = asyncio.run(synthesize_segments(
        segments, {"narrator": VoiceProfile("fake", "Brian")},
        tmp_path / "clips", registry,
        retry_policy=RetryPolicy(retries=0),
    ))
    assert speech.calls == 2
    composition = compose_audiobook(result.manifest, tmp_path / "complete.mp3")
    assert composition.output.is_file()
    assert composition.segments == 2
    assert speech.calls == 2  # Compose must not call any provider


def test_non_mp3_output_rejected_without_changes(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "clips")
    with pytest.raises(ComposeError, match=".mp3"):
        compose_audiobook(manifest, tmp_path / "out.wav")
    assert not (tmp_path / "out.wav").exists()
