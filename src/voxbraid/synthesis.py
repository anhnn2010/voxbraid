"""Turn a planned book into native speech clips; audio composition is M4."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from voxbraid.models import PlannedSegment
from voxbraid.tts.base import VoiceProfile
from voxbraid.tts.registry import ProviderRegistry


@dataclass(frozen=True)
class SynthesisResult:
    """Paths of generated clips plus their sequence/voice metadata."""

    output_dir: Path
    manifest: Path
    clips: tuple[Path, ...]


class SynthesisError(RuntimeError):
    """A specific segment's provider synthesis failed; original error is chained."""


def _prepare(
    segments: tuple[PlannedSegment, ...],
    profiles: Mapping[str, VoiceProfile],
    output_dir: Path,
    registry: ProviderRegistry,
    *,
    overwrite: bool,
) -> tuple[list[tuple[PlannedSegment, VoiceProfile, Path]], Path]:
    if not segments:
        raise ValueError("Nothing to synthesize: no planned segments")
    jobs = []
    for segment in segments:
        if segment.role not in profiles:
            raise ValueError(
                f"No voice mapping for [{segment.role}]. Add it to --voices JSON."
            )
        profile = profiles[segment.role]
        provider = registry.get(profile.provider)
        validate = getattr(provider, "validate", None)
        if validate is not None:
            validate(profile)
        extension = provider.audio_extension
        if not re.fullmatch(r"\.[a-z0-9]{2,8}", extension):
            raise ValueError(
                f"Provider {profile.provider!r} has unsafe audio extension {extension!r}"
            )
        destination = output_dir / f"segment_{segment.index:04d}{extension}"
        jobs.append((segment, profile, destination))
    manifest = output_dir / "manifest.json"
    collision = next((path for _, _, path in jobs if path.exists()), None)
    if not overwrite and (collision is not None or manifest.exists()):
        raise FileExistsError(
            f"Output already exists: {collision or manifest}. "
            "Choose another --out-dir or use --overwrite. "
            "Automatic resume starts in M3."
        )
    return jobs, manifest


async def synthesize_segments(
    segments: tuple[PlannedSegment, ...],
    profiles: Mapping[str, VoiceProfile],
    output_dir: Path,
    registry: ProviderRegistry,
    *,
    overwrite: bool = False,
) -> SynthesisResult:
    """Produce audio clips in order and write a manifest when all clips succeed.

    M2 intentionally has no retry/cache/resume. Every run writes new clips. A
    partial failed request never replaces its destination file.
    """
    jobs, manifest = _prepare(segments, profiles, output_dir, registry, overwrite=overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)
    # In overwrite mode, do not leave an old success manifest beside partial
    # replacements if the new generation fails midway.
    if overwrite:
        manifest.unlink(missing_ok=True)
    manifest_segments: list[dict[str, object]] = []
    generated: list[Path] = []
    for segment, profile, destination in jobs:
        temp = destination.with_name(destination.name + ".partial")
        try:
            temp.unlink(missing_ok=True)
            await registry.get(profile.provider).synthesize(segment.text, profile, temp)
            if not temp.is_file() or temp.stat().st_size == 0:
                raise RuntimeError(
                    f"Provider {profile.provider!r} returned no audio for segment {segment.index}"
                )
            temp.replace(destination)
        except Exception as exc:
            temp.unlink(missing_ok=True)
            raise SynthesisError(
                f"Segment {segment.index}/{len(jobs)} [{segment.role}] "
                f"({profile.provider}:{profile.voice}) failed: "
                f"{type(exc).__name__}: {exc}. "
                "M2 has no automatic retry/resume; retry with --overwrite "
                "or a new --out-dir."
            ) from exc
        generated.append(destination)
        manifest_segments.append({
            **asdict(segment),
            "file": destination.name,
            "provider": profile.provider,
            "voice": profile.voice,
            "options": dict(profile.options),
        })
        print(f"[{len(generated)}/{len(jobs)}] [{segment.role}] "
              f"{profile.provider}:{profile.voice} -> {destination.name}")
    payload = {
        "format": "voxbraid-synthesis-v1",
        "composed": False,
        "segments": manifest_segments,
    }
    temporary_manifest = manifest.with_suffix(".json.partial")
    try:
        temporary_manifest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary_manifest.replace(manifest)
    finally:
        temporary_manifest.unlink(missing_ok=True)
    return SynthesisResult(output_dir=output_dir, manifest=manifest, clips=tuple(generated))
