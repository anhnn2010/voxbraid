from __future__ import annotations

import json
from pathlib import Path

import pytest

from voxbraid.tts.base import VoiceProfile
from voxbraid.voices import VoiceConfigError, load_voices


def test_default_narrator_brian() -> None:
    assert load_voices(None) == {
        "narrator": VoiceProfile("edge", "en-US-BrianNeural", {"rate": "-10%"})
    }


def test_profiles_allow_different_providers_for_one_book(tmp_path: Path) -> None:
    config = tmp_path / "voices.json"
    config.write_text(json.dumps({
        "narrator": {"provider": "edge", "voice": "en-US-BrianNeural"},
        "bird": {"provider": "mock-local", "voice": "bird-voice", "options": {"speed": "1.2"}},
    }))
    profiles = load_voices(config)
    assert profiles["narrator"].provider == "edge"
    assert profiles["bird"].provider == "mock-local"
    assert profiles["bird"].options == {"speed": "1.2"}


@pytest.mark.parametrize("content", [
    "[]", "{}", '[{"provider":"edge"}]',
    '{"bird":{"voice":"ok"}}',
    '{"bird":{"provider":"edge","voice":""}}',
    '{"Bird":{"provider":"edge","voice":"x"}}',
    '{"bird":{"provider":"edge","voice":"x","options":{"rate":3}}}',
    '{"bird":{"provider":"edge","voice":"x","oops":2}}',
])
def test_invalid_voice_config_has_clear_errors(tmp_path: Path, content: str) -> None:
    config = tmp_path / "voices.json"
    config.write_text(content)
    with pytest.raises(VoiceConfigError):
        load_voices(config)


def test_bad_json_fails(tmp_path: Path) -> None:
    config = tmp_path / "voices.json"
    config.write_text("{")
    with pytest.raises(VoiceConfigError, match="Invalid JSON"):
        load_voices(config)
