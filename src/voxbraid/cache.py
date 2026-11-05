"""Content-addressed, integrity-checked audio cache with atomic JSON metadata."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from voxbraid.tts.base import VoiceProfile

CACHE_FORMAT = "voxbraid-clip-v1"
STATE_FORMAT = "voxbraid-state-v1"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clip_key(text: str, profile: VoiceProfile, extension: str, engine_version: str) -> str:
    """Ignore book position, pauses and music: only synthesis inputs affect the key."""
    payload = {
        "format": CACHE_FORMAT,
        "text": text,
        "provider": profile.provider,
        "voice": profile.voice,
        "options": profile.options,
        "extension": extension,
        "adapter_version": engine_version,
    }
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".partial.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


class ClipCache:
    """Store verified clips in a shard keyed by text+provider+voice+options."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, key: str, extension: str) -> Path:
        return self.root / key[:2] / f"{key}{extension}"

    def metadata_path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def find(self, key: str, extension: str) -> tuple[Path, dict[str, Any]] | None:
        audio = self.path(key, extension)
        meta = read_json(self.metadata_path(key))
        if not meta or meta.get("format") != CACHE_FORMAT or meta.get("key") != key:
            return None
        if not audio.is_file() or audio.stat().st_size <= 0:
            return None
        if meta.get("size") != audio.stat().st_size:
            return None
        if file_sha256(audio) != meta.get("sha256"):
            return None
        if not isinstance(meta.get("duration"), (float, int)) or meta["duration"] <= 0:
            return None
        return audio, meta

    def save_verified(
        self, key: str, extension: str, source: Path, duration: float
    ) -> dict[str, Any]:
        """Called only after the temporary source has passed full decode validation."""
        destination = self.path(key, extension)
        destination.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "format": CACHE_FORMAT,
            "key": key,
            "sha256": file_sha256(source),
            "size": source.stat().st_size,
            "duration": duration,
            "extension": extension,
        }
        os.replace(source, destination)
        write_json_atomic(self.metadata_path(key), metadata)
        return metadata


class RunState:
    """Checkpoint per completed output clip (not a success manifest)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        existing = read_json(path)
        self.known = bool(existing and existing.get("format") == STATE_FORMAT
                          and isinstance(existing.get("clips"), dict))
        self.clips: dict[str, Any] = dict(existing["clips"]) if self.known else {}

    def matching(self, name: str, key: str, destination: Path) -> bool:
        item = self.clips.get(name)
        if not isinstance(item, dict) or item.get("key") != key:
            return False
        if not destination.is_file() or destination.stat().st_size != item.get("size"):
            return False
        return file_sha256(destination) == item.get("sha256")

    def commit(self, name: str, key: str, destination: Path) -> dict[str, Any]:
        item = {"key": key, "sha256": file_sha256(destination),
                "size": destination.stat().st_size}
        self.clips[name] = item
        write_json_atomic(self.path, {"format": STATE_FORMAT, "clips": self.clips})
        self.known = True
        return item
