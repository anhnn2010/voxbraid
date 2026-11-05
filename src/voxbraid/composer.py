"""M4: offline, provider-agnostic assembly of speech clips and background music.

No TTS provider is imported or invoked here. Native clip formats are decoded
into a streaming PCM WAV intermediate; a single MP3 encoding pass produces
an atomic output. A selected track can be looped, mixed and faded by FFmpeg.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from voxbraid.audio_validation import AudioValidationError, check_audio_tools, validate_audio
from voxbraid.cache import write_json_atomic

_SAMPLE_RATE = 48000
_CHANNELS = 2
_SAMPLE_WIDTH = 2
_BYTES_PER_FRAME = _CHANNELS * _SAMPLE_WIDTH
_KINDS = frozenset({"intro", "sentence", "paragraph", "speaker", "attribution", "lead"})


class ComposeError(ValueError):
    """Invalid manifest, missing audio or failed FFmpeg operation."""


@dataclass(frozen=True)
class PauseOverrides:
    intro: float | None = None
    sentence: float | None = None
    paragraph: float | None = None
    speaker: float | None = None
    attribution: float | None = None
    lead: float | None = None

    def __post_init__(self) -> None:
        for kind in _KINDS:
            duration = getattr(self, kind)
            if duration is not None and (not math.isfinite(duration) or duration < 0):
                raise ComposeError(f"{kind} gap must be finite and non-negative")

    def for_kind(self, kind: str, fallback: float) -> float:
        chosen = getattr(self, kind)
        return fallback if chosen is None else chosen


@dataclass(frozen=True)
class Clip:
    index: int
    role: str
    path: Path
    pause_kind: str
    pause_before: float


@dataclass(frozen=True)
class ComposeResult:
    output: Path
    duration: float
    speech_duration: float
    music: Path | None
    segments: int
    metadata: Path
    speech_output: Path | None = None


def _nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ComposeError(f"{label} must be a non-negative number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ComposeError(f"{label} must be finite and non-negative")
    return number


def load_manifest(manifest: Path, overrides: PauseOverrides | None = None) -> tuple[Clip, ...]:
    """Read a *complete* M3 manifest; reject unsafe paths and invalid data."""
    if not manifest.is_file():
        raise ComposeError(f"Manifest not found: {manifest}")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ComposeError(f"Cannot read manifest {manifest}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != "voxbraid-synthesis-v1":
        raise ComposeError("Unsupported manifest format (expected voxbraid-synthesis-v1)")
    if payload.get("composed") is not False:
        raise ComposeError("Expected complete synthesis manifest (composed must be false)")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ComposeError("Synthesis manifest contains no segments")
    options = overrides if overrides is not None else PauseOverrides()
    base = manifest.parent.resolve()
    clips: list[Clip] = []
    for expected_index, item in enumerate(raw_segments, 1):
        if not isinstance(item, dict) or type(item.get("index")) is not int:
            raise ComposeError(f"Segment {expected_index} missing integer index")
        if item["index"] != expected_index:
            raise ComposeError(
                f"Segments must be ordered consecutively (expected {expected_index})"
            )
        filename = item.get("file")
        if (
            not isinstance(filename, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.[A-Za-z0-9]{2,8}", filename)
            or filename in {".", ".."}
        ):
            raise ComposeError(f"Segment {expected_index}: unsafe audio file name")
        path = base / filename
        if not path.is_file() or path.resolve() != base / filename:
            raise ComposeError(f"Segment {expected_index}: missing/unsafe audio clip {filename}")
        role = item.get("role")
        if not isinstance(role, str) or not role.strip():
            raise ComposeError(f"Segment {expected_index}: missing speaker role")
        kind = item.get("pause_kind")
        if kind not in _KINDS:
            raise ComposeError(f"Segment {expected_index}: unknown pause_kind {kind!r}")
        original_gap = _nonnegative(item.get("pause_before"), f"Segment {expected_index} gap")
        clips.append(Clip(expected_index, role, path, kind,
                          options.for_kind(kind, original_gap)))
    return tuple(clips)


def choose_music(source: Path | None, seed: int | None = None) -> Path | None:
    """Use an explicit MP3, or choose one MP3 from the direct children of a folder."""
    if source is None:
        if seed is not None:
            raise ComposeError("--music-seed requires --music DIRECTORY")
        return None
    if source.is_file():
        if seed is not None:
            raise ComposeError("--music-seed only applies to a music directory")
        if source.suffix.lower() != ".mp3":
            raise ComposeError(f"Music file must be an MP3: {source}")
        return source.resolve()
    if source.is_dir():
        available = sorted(
            (p for p in source.iterdir() if p.is_file() and p.suffix.lower() == ".mp3"),
            key=lambda p: (p.name.casefold(), p.name),
        )
        if not available:
            raise ComposeError(f"Music directory has no MP3 files: {source}")
        rng = random.Random(seed) if seed is not None else random.SystemRandom()
        return rng.choice(available).resolve()
    raise ComposeError(f"Music source not found: {source}")


def _silence(output: wave.Wave_write, seconds: float) -> int:
    frames = round(seconds * _SAMPLE_RATE)
    # At most 192 KiB of zeroes in memory, regardless of pause length.
    zero_chunk = b"\0" * (_SAMPLE_RATE * _BYTES_PER_FRAME)
    remaining = frames
    while remaining:
        size = min(remaining, _SAMPLE_RATE)
        output.writeframesraw(zero_chunk[:size * _BYTES_PER_FRAME])
        remaining -= size
    return frames


def _decode_to_wav(source: Path, output: wave.Wave_write) -> int:
    """Stream FFmpeg PCM into a WAV writer without loading the book into RAM."""
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror",
        "-i", str(source), "-map", "0:a:0", "-ac", str(_CHANNELS),
        "-ar", str(_SAMPLE_RATE), "-f", "s16le", "pipe:1",
    ]
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE) as process:
            assert process.stdout is not None
            assert process.stderr is not None
            total = 0
            while chunk := process.stdout.read(262144):
                output.writeframesraw(chunk)
                total += len(chunk)
            error = process.stderr.read().decode("utf-8", errors="replace")
            if process.wait() != 0:
                raise ComposeError(f"Cannot decode {source.name}: {error.strip()[:500]}")
    except OSError as exc:
        raise ComposeError(f"Cannot launch FFmpeg for {source}: {exc}") from exc
    if total == 0 or total % _BYTES_PER_FRAME:
        raise ComposeError(f"Invalid decoded PCM from {source.name}")
    return total // _BYTES_PER_FRAME


def _make_speech_wav(clips: tuple[Clip, ...], destination: Path) -> float:
    samples = 0
    with wave.open(str(destination), "wb") as writer:
        writer.setnchannels(_CHANNELS)
        writer.setsampwidth(_SAMPLE_WIDTH)
        writer.setframerate(_SAMPLE_RATE)
        for clip in clips:
            samples += _silence(writer, clip.pause_before)
            samples += _decode_to_wav(clip.path, writer)
    return samples / _SAMPLE_RATE


def _encode_mp3(source_wav: Path, destination: Path, *, music: Path | None,
                music_volume: float, fade_in: float, fade_out: float,
                duration: float) -> None:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
               "-xerror", "-i", str(source_wav)]
    if music is not None:
        command.extend(["-stream_loop", "-1", "-i", str(music)])
        fade_in = min(fade_in, duration)
        fade_out = min(fade_out, duration)
        filters = [f"[1:a]volume={music_volume:.12g}"]
        if fade_in > 0:
            filters.append(f"afade=t=in:st=0:d={fade_in:.9f}")
        if fade_out > 0:
            filters.append(f"afade=t=out:st={max(0, duration - fade_out):.9f}:d={fade_out:.9f}")
        music_filter = ",".join(filters) + "[bg]"
        filter_graph = (
            music_filter + ";"
            "[0:a][bg]amix=inputs=2:duration=first:normalize=0:"
            "dropout_transition=0,alimiter=limit=0.95[out]"
        )
        command.extend(["-filter_complex", filter_graph, "-map", "[out]"])
    else:
        command.extend(["-map", "0:a:0"])
    command.extend(["-vn", "-c:a", "libmp3lame", "-q:a", "3", "-y", str(destination)])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ComposeError(f"FFmpeg MP3 encoding failed: {result.stderr.strip()[-800:]}")


def compose_audiobook(
    manifest: Path,
    output: Path,
    *,
    pauses: PauseOverrides | None = None,
    music_source: Path | None = None,
    music_seed: int | None = None,
    music_volume: float = 0.04,
    fade_in: float = 2.0,
    fade_out: float = 5.0,
    speech_output: Path | None = None,
) -> ComposeResult:
    """Compose an M3 manifest into final MP3(s), without any TTS calls.

    Errors never replace an existing final MP3. Temporary WAV/MP3 files are
    cleaned automatically. A .compose.json sidecar records chosen music.
    """
    if output.suffix.lower() != ".mp3":
        raise ComposeError("Output must have .mp3 extension")
    if speech_output is not None and speech_output.suffix.lower() != ".mp3":
        raise ComposeError("--speech-output must have .mp3 extension")
    if speech_output is not None and music_source is None:
        raise ComposeError("--speech-output is only useful with --music")
    if speech_output is not None and output.resolve() == speech_output.resolve():
        raise ComposeError("--speech-output must be different from --output")
    music_volume = _nonnegative(music_volume, "Music volume")
    if music_volume > 1:
        raise ComposeError("Music volume must be between 0 and 1")
    fade_in = _nonnegative(fade_in, "Music fade-in")
    fade_out = _nonnegative(fade_out, "Music fade-out")
    check_audio_tools()
    clips = load_manifest(manifest, pauses)
    chosen_music = choose_music(music_source, music_seed)
    # Refuse any output path that would overwrite a source segment or music file.
    inputs = {clip.path.resolve() for clip in clips}
    if chosen_music is not None:
        inputs.add(chosen_music)
    for target in (output, speech_output):
        if target is not None and target.resolve() in inputs:
            raise ComposeError(f"Output would overwrite an input audio file: {target}")
    for clip in clips:
        try:
            validate_audio(clip.path)
        except AudioValidationError as exc:
            raise ComposeError(f"Segment {clip.index} ({clip.path.name}): {exc}") from exc
    if chosen_music is not None:
        try:
            validate_audio(chosen_music)
        except AudioValidationError as exc:
            raise ComposeError(f"Invalid music {chosen_music.name}: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    if speech_output is not None:
        speech_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".voxbraid-compose-", dir=output.parent) as tmp:
        work = Path(tmp)
        speech_wav = work / "speech.wav"
        speech_duration = _make_speech_wav(clips, speech_wav)
        temporary_mp3 = work / "composed.mp3"
        _encode_mp3(speech_wav, temporary_mp3, music=chosen_music,
                    music_volume=music_volume, fade_in=fade_in, fade_out=fade_out,
                    duration=speech_duration)
        try:
            final_duration = validate_audio(temporary_mp3)
        except AudioValidationError as exc:
            raise ComposeError(f"Rendered MP3 is invalid: {exc}") from exc
        if speech_output is not None:
            speech_temp = work / "speech_only.mp3"
            _encode_mp3(speech_wav, speech_temp, music=None, music_volume=0,
                        fade_in=0, fade_out=0, duration=speech_duration)
            try:
                validate_audio(speech_temp)
            except AudioValidationError as exc:
                raise ComposeError(f"Speech-only MP3 is invalid: {exc}") from exc
            os.replace(speech_temp, speech_output)
        os.replace(temporary_mp3, output)
    metadata = output.with_suffix(".compose.json")
    write_json_atomic(metadata, {
        "format": "voxbraid-compose-v1",
        "manifest": str(manifest.resolve()),
        "output": str(output.resolve()),
        "segments": len(clips),
        "music": str(chosen_music) if chosen_music is not None else None,
        "music_source": str(music_source.resolve()) if music_source is not None else None,
        "music_seed": music_seed,
        "music_volume": music_volume if chosen_music is not None else None,
        "fade_in": fade_in if chosen_music is not None else None,
        "fade_out": fade_out if chosen_music is not None else None,
        "speech_seconds": round(speech_duration, 6),
        "output_seconds": round(final_duration, 6),
        "pauses": [round(clip.pause_before, 6) for clip in clips],
    })
    return ComposeResult(output, final_duration, speech_duration,
                         chosen_music, len(clips), metadata, speech_output)
