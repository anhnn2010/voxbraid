"""Validate provider audio before accepting it into the persistent cache.

FFprobe identifies the audio stream and duration; FFmpeg actually decodes it.
Keeping both checks catches truncated clips that have a plausible header.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path


class AudioValidationError(RuntimeError):
    """The provider returned empty, corrupt, or undecodable audio."""


def check_audio_tools() -> None:
    """Fail before online synthesis when audio verification cannot be done."""
    missing = [tool for tool in ("ffprobe", "ffmpeg") if shutil.which(tool) is None]
    if missing:
        raise ValueError(
            "M3 requires FFmpeg/FFprobe to validate clips. Missing: "
            + ", ".join(missing)
            + ". On Arch: sudo pacman -S ffmpeg"
        )


def validate_audio(path: Path) -> float:
    """Fully decode a clip and return its positive duration in seconds."""
    if not path.is_file() or path.stat().st_size == 0:
        raise AudioValidationError("Provider returned no audio (empty or missing file)")
    try:
        probed = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_name", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, check=False, timeout=30,
        )
        if probed.returncode:
            raise AudioValidationError("FFprobe cannot read audio: " + probed.stderr.strip()[:300])
        info = json.loads(probed.stdout)
        if not info.get("streams"):
            raise AudioValidationError("Clip has no audio stream")
        duration = float(info.get("format", {}).get("duration", 0))
        if not math.isfinite(duration) or duration <= 0:
            raise AudioValidationError("Clip has no positive audio duration")
        decoded = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
             "-map", "0:a:0", "-f", "null", "-"],
            capture_output=True, text=True, check=False, timeout=120,
        )
        if decoded.returncode:
            raise AudioValidationError(
                "FFmpeg cannot decode audio: " + decoded.stderr.strip()[:300]
            )
        return duration
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise AudioValidationError(f"Cannot validate audio: {exc}") from exc
