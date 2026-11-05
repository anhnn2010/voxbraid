"""Microsoft Edge online TTS adapter, intentionally installed only on demand."""

from __future__ import annotations

from pathlib import Path

from voxbraid.tts.base import VoiceProfile

_EDGE_OPTIONS = frozenset({"rate", "volume", "pitch"})


class EdgeTTSProvider:
    """Edge's online voices through the third-party `edge-tts` package."""

    audio_extension = ".mp3"

    def validate(self, profile: VoiceProfile) -> None:
        unsupported = set(profile.options) - _EDGE_OPTIONS
        if unsupported:
            raise ValueError(
                "Edge TTS unsupported option(s): " + ", ".join(sorted(unsupported))
            )
        for key, value in profile.options.items():
            if not isinstance(value, str):
                raise ValueError(f"Edge TTS option {key!r} must be a string")

    async def synthesize(self, text: str, profile: VoiceProfile, output: Path) -> None:
        self.validate(profile)
        try:
            import edge_tts  # noqa: PLC0415 - lazy provider-only dependency
        except ImportError as exc:
            raise RuntimeError(
                'Edge TTS is not installed. Run: python -m pip install -e ".[edge]"'
            ) from exc
        communicate = edge_tts.Communicate(text, voice=profile.voice, **profile.options)
        await communicate.save(str(output))
