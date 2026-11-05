"""M5 configuration layering for the TXT -> MP3 render command.

Configuration precedence (lowest to highest): library defaults, preset,
per-book config, and explicitly supplied CLI flags. Voice mappings are
replaced as a *whole* rather than silently merging per-character assignments.
No TTS/model initialization or audio work happens during settings loading.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from voxbraid.planner import PauseOptions
from voxbraid.retry import RetryPolicy
from voxbraid.tts.base import VoiceProfile
from voxbraid.voices import DEFAULT_NARRATOR, VoiceConfigError, parse_voice_mapping


class SettingsError(ValueError):
    """Invalid VoxBraid YAML/JSON book configuration or preset."""


@dataclass(frozen=True)
class MusicSettings:
    source: Path | None = None
    seed: int | None = None
    volume: float = 0.04
    fade_in: float = 2.0
    fade_out: float = 5.0


@dataclass(frozen=True)
class RenderSettings:
    voices: dict[str, VoiceProfile]
    pauses: PauseOptions
    retry: RetryPolicy
    music: MusicSettings


_PAUSE_KEYS = frozenset({"intro", "sentence", "paragraph", "speaker", "attribution", "lead"})
_MUSIC_KEYS = frozenset({"source", "seed", "volume", "fade_in", "fade_out"})
_RETRY_KEYS = frozenset({"retries", "base_delay", "max_delay"})
_ROOT_KEYS = frozenset({"version", "voices", "pauses", "music", "retry"})


def _read_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SettingsError(f"Configuration file not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        raise SettingsError(f"Expected .yaml, .yml or .json configuration: {path}")
    try:
        contents = path.read_text(encoding="utf-8-sig")
        obj = json.loads(contents) if suffix == ".json" else yaml.safe_load(contents)
    except (OSError, UnicodeError, yaml.YAMLError, json.JSONDecodeError) as exc:
        raise SettingsError(f"Invalid configuration {path}: {exc}") from exc
    if not isinstance(obj, dict):
        raise SettingsError(f"Configuration must be a mapping: {path}")
    _unknown_keys(obj, _ROOT_KEYS, f"Configuration {path}")
    if "version" in obj and (type(obj["version"]) is not int or obj["version"] != 1):
        raise SettingsError(f"Unsupported configuration version in {path} (expected 1)")
    return obj


def _unknown_keys(mapping: Mapping[Any, Any], allowed: frozenset[str], label: str) -> None:
    if any(not isinstance(key, str) for key in mapping):
        raise SettingsError(f"{label} keys must be strings")
    unknown = set(mapping) - allowed
    if unknown:
        raise SettingsError(f"{label}: unknown keys: {', '.join(sorted(unknown))}")


def _section(value: Any, allowed: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SettingsError(f"{label} must be a mapping")
    _unknown_keys(value, allowed, label)
    return value


def _seconds(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise SettingsError(f"{label} must be a nonnegative number")
    num = float(value)
    if not math.isfinite(num) or num < 0:
        raise SettingsError(f"{label} must be finite and nonnegative")
    return num


def _int_or_none(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise SettingsError(f"{label} must be an integer or null")
    return value


def _music_path(value: Any, *, basedir: Path | None) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SettingsError("music.source must be a nonempty file/directory path or null")
    path = Path(value).expanduser()
    if not path.is_absolute() and basedir is not None:
        path = basedir / path
    return path


def _read_preset(name: str) -> tuple[dict[str, Any], Path | None]:
    if name == "bedtime":
        # Installed wheel contains this resource; no dependency on cwd or repo checkout.
        with resources.as_file(
            resources.files("voxbraid").joinpath("presets", "bedtime.yaml")
        ) as packaged:
            return _read_document(packaged), None
    path = Path(name).expanduser()
    return _read_document(path), path.resolve().parent


def load_render_settings(
    *,
    preset: str | None = None,
    config: Path | None = None,
    voices: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> RenderSettings:
    """Resolve settings without performing network calls or writing files.

    CLI override keys: intro/sentence/paragraph/speaker/attribution/lead,
    music_source/no_music/music_seed/music_volume/fade_in/fade_out,
    retries/retry_base_delay/retry_max_delay.
    """
    pause_data: dict[str, Any] = {}
    music_data: dict[str, Any] = {}
    retry_data: dict[str, Any] = {}
    voice_data: dict[str, Any] | None = None
    override = dict(overrides or {})
    allowed_override = _PAUSE_KEYS | {
        "music_source", "no_music", "music_seed", "music_volume", "fade_in", "fade_out",
        "retries", "retry_base_delay", "retry_max_delay",
    }
    _unknown_keys(override, allowed_override, "CLI overrides")

    layers: list[tuple[dict[str, Any], Path | None]] = []
    if preset is not None:
        layers.append(_read_preset(preset))
    if config is not None:
        layers.append((_read_document(config), config.resolve().parent))
    for data, basedir in layers:
        if "voices" in data:
            if not isinstance(data["voices"], dict):
                raise SettingsError("voices must be a mapping of roles to voice profiles")
            voice_data = data["voices"]
        if "pauses" in data:
            pause_data.update(_section(data["pauses"], _PAUSE_KEYS, "pauses"))
        if "retry" in data:
            retry_data.update(_section(data["retry"], _RETRY_KEYS, "retry"))
        if "music" in data:
            music = _section(data["music"], _MUSIC_KEYS, "music")
            for key, value in music.items():
                music_data[key] = _music_path(value, basedir=basedir) if key == "source" else value

    for key in _PAUSE_KEYS:
        if override.get(key) is not None:
            pause_data[key] = override[key]
    for cli_key, setting_key in (
        ("music_source", "source"), ("music_seed", "seed"),
        ("music_volume", "volume"), ("fade_in", "fade_in"), ("fade_out", "fade_out"),
    ):
        if override.get(cli_key) is not None:
            music_data[setting_key] = override[cli_key]
    if override.get("no_music"):
        if override.get("music_source") is not None:
            raise SettingsError("--music and --no-music cannot be used together")
        music_data["source"] = None
        music_data["seed"] = None
    for cli_key, setting_key in (
        ("retries", "retries"), ("retry_base_delay", "base_delay"),
        ("retry_max_delay", "max_delay"),
    ):
        if override.get(cli_key) is not None:
            retry_data[setting_key] = override[cli_key]

    for name, value in pause_data.items():
        pause_data[name] = _seconds(value, f"pauses.{name}")
    pause_options = PauseOptions(**pause_data)

    for name in ("volume", "fade_in", "fade_out"):
        if name in music_data:
            music_data[name] = _seconds(music_data[name], f"music.{name}")
    if music_data.get("volume", 0.04) > 1:
        raise SettingsError("music.volume must be between 0 and 1")
    if "seed" in music_data:
        music_data["seed"] = _int_or_none(music_data["seed"], "music.seed")
    if "source" in music_data and isinstance(music_data["source"], str):
        music_data["source"] = _music_path(music_data["source"], basedir=None)
    music_settings = MusicSettings(**music_data)
    if music_settings.seed is not None and music_settings.source is None:
        raise SettingsError("music.seed requires a music directory")
    if music_settings.seed is not None and music_settings.source is not None:
        # A seed with a specific file is an error; fail before synthesis.
        if music_settings.source.is_file():
            raise SettingsError("music.seed only applies to a directory, not a file")

    for name, value in retry_data.items():
        if name == "retries":
            if type(value) is not int:
                raise SettingsError("retry.retries must be an integer")
        else:
            retry_data[name] = _seconds(value, f"retry.{name}")
    retry_policy = RetryPolicy(**retry_data)

    if voices is not None:
        from voxbraid.voices import load_voices  # noqa: PLC0415

        profiles = load_voices(voices)
    elif voice_data is not None:
        try:
            profiles = parse_voice_mapping(voice_data)
        except VoiceConfigError as exc:
            raise SettingsError(str(exc)) from exc
    else:
        profiles = {"narrator": DEFAULT_NARRATOR}
    return RenderSettings(profiles, pause_options, retry_policy, music_settings)
