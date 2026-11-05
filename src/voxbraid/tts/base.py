"""Small provider contract shared by cloud and future local synthesizers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class VoiceProfile:
    """A voice selection for one role, including provider-specific options."""

    provider: str
    voice: str
    options: dict[str, str] = field(default_factory=dict)


class TTSProvider(Protocol):
    """Synthesize a single text segment into an audio file.

    Providers may have different native codecs; the future composer will decode
    all inputs to a common lossless format. They must not silently fall back to
    a different provider or voice.
    """

    audio_extension: str  # e.g. ".mp3" (Edge) or ".wav" (future local provider)

    async def synthesize(self, text: str, profile: VoiceProfile, output: Path) -> None:
        """Write speech bytes for exactly one segment to ``output``."""
