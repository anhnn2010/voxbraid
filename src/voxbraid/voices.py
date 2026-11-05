"""Read provider-independent speaker-to-voice mappings from JSON or YAML."""

from __future__ import annotations

import json

import yaml
from pathlib import Path
from typing import Any

from voxbraid.tts.base import VoiceProfile

DEFAULT_NARRATOR = VoiceProfile(
    provider="edge",
    voice="en-US-BrianNeural",
    options={"rate": "-10%"},
)


class VoiceConfigError(ValueError):
    """Invalid or missing speaker voice configuration."""


def _parse_profile(role: str, obj: Any) -> VoiceProfile:
    if not isinstance(obj, dict):
        raise VoiceConfigError(f"Voice profile for [{role}] must be a JSON object")
    unexpected = set(obj) - {"provider", "voice", "options"}
    if unexpected:
        raise VoiceConfigError(
            f"Voice profile for [{role}] has unknown fields: {', '.join(sorted(unexpected))}"
        )
    provider = obj.get("provider")
    voice = obj.get("voice")
    options = obj.get("options", {})
    if not isinstance(provider, str) or not provider.strip():
        raise VoiceConfigError(f"[{role}]: provider must be a nonempty string")
    if not isinstance(voice, str) or not voice.strip():
        raise VoiceConfigError(f"[{role}]: voice must be a nonempty string")
    if not isinstance(options, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in options.items()
    ):
        raise VoiceConfigError(f"[{role}]: options must map string keys to string values")
    return VoiceProfile(provider=provider.strip(), voice=voice.strip(), options=options)


def parse_voice_mapping(data: Any) -> dict[str, VoiceProfile]:
    """Validate a role-to-profile mapping, shared by JSON/YAML and book config."""
    if not isinstance(data, dict) or not data:
        raise VoiceConfigError("Voice config must be a nonempty role-to-profile mapping")
    profiles: dict[str, VoiceProfile] = {}
    for role, definition in data.items():
        if not isinstance(role, str) or not role or role.lower() != role:
            raise VoiceConfigError("Voice role keys must be nonempty lowercase strings")
        profiles[role] = _parse_profile(role, definition)
    return profiles


def load_voices(path: Path | None) -> dict[str, VoiceProfile]:
    """Return explicit mapping; without a file only narrator receives a default.

    No implicit fallback for named characters: synthesizing a witch with the
    narrator's voice by accident is worse than stopping with a clear error.
    """
    if path is None:
        return {"narrator": DEFAULT_NARRATOR}
    if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
        raise VoiceConfigError(f"Voice config must end in .json, .yaml or .yml: {path}")
    try:
        contents = path.read_text(encoding="utf-8-sig")
        data = (json.loads(contents) if path.suffix.lower() == ".json"
                else yaml.safe_load(contents))
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        format_label = "JSON" if path.suffix.lower() == ".json" else "YAML"
        raise VoiceConfigError(f"Invalid {format_label} voice config {path}: {exc}") from exc
    return parse_voice_mapping(data)
