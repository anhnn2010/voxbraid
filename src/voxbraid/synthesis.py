"""Resumable per-segment TTS synthesis. Composition remains a separate M4 stage."""

from __future__ import annotations

import asyncio
import math
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from voxbraid.audio_validation import AudioValidationError, check_audio_tools, validate_audio
from voxbraid.cache import ClipCache, RunState, clip_key, file_sha256, write_json_atomic
from voxbraid.models import PlannedSegment
from voxbraid.retry import RetryPolicy, is_transient
from voxbraid.tts.base import VoiceProfile
from voxbraid.tts.registry import ProviderRegistry


@dataclass(frozen=True)
class SynthesisResult:
    """Completed clips, success manifest, and synthesis/cache counters."""

    output_dir: Path
    manifest: Path
    clips: tuple[Path, ...]
    generated: int = 0
    cached: int = 0
    resumed: int = 0
    retried: int = 0


class SynthesisError(RuntimeError):
    """A specific segment's provider synthesis failed; original error is chained."""


@dataclass(frozen=True)
class _Job:
    segment: PlannedSegment
    profile: VoiceProfile
    destination: Path
    key: str
    extension: str


def _prepare(
    segments: tuple[PlannedSegment, ...],
    profiles: Mapping[str, VoiceProfile],
    output_dir: Path,
    registry: ProviderRegistry,
) -> list[_Job]:
    if not segments:
        raise ValueError("Nothing to synthesize: no planned segments")
    jobs: list[_Job] = []
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
        version = str(getattr(provider, "cache_version", "1"))
        key = clip_key(segment.text, profile, extension, version)
        destination = output_dir / f"segment_{segment.index:04d}{extension}"
        jobs.append(_Job(segment, profile, destination, key, extension))
    return jobs


def _tempfile(folder: Path, extension: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".voxbraid.partial.", suffix=extension, dir=folder)
    os.close(fd)
    return Path(name)


def _copy_atomic(source: Path, destination: Path) -> None:
    temporary = _tempfile(destination.parent, destination.suffix)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_existing_outputs(jobs: list[_Job], state: RunState, cache: ClipCache) -> None:
    """Refuse overwriting untracked legacy/user files without --overwrite."""
    for job in jobs:
        if not job.destination.exists() or job.destination.name in state.clips:
            continue
        verified = cache.find(job.key, job.extension)
        # A crash can occur after clip-copy but before checkpoint commit. If the
        # file matches a verified cache entry, we can safely adopt it on resume.
        if verified is not None and job.destination.is_file() and (
            job.destination.stat().st_size == verified[1]["size"]
        ):
            if file_sha256(job.destination) == verified[1]["sha256"]:
                continue
        raise FileExistsError(
            f"Untracked output exists: {job.destination}. "
            "Use another --out-dir or --overwrite once to replace old M2 output."
        )


async def _make_clip(
    job: _Job,
    registry: ProviderRegistry,
    cache: ClipCache,
    policy: RetryPolicy,
    validator: Callable[[Path], float],
    number: int,
    total: int,
) -> tuple[dict[str, object], int]:
    provider = registry.get(job.profile.provider)
    attempts = 0
    while True:
        attempts += 1
        temp = _tempfile(cache.path(job.key, job.extension).parent, job.extension)
        try:
            await provider.synthesize(job.segment.text, job.profile, temp)
            if not temp.is_file() or temp.stat().st_size == 0:
                raise AudioValidationError("Provider returned no audio (empty or missing file)")
            duration = validator(temp)
            if (
                not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or duration <= 0
            ):
                raise AudioValidationError("Provider returned no valid audio duration")
        except Exception as exc:
            temp.unlink(missing_ok=True)
            retriable = isinstance(exc, AudioValidationError) or is_transient(exc)
            if not retriable or attempts > policy.retries:
                raise SynthesisError(
                    f"Segment {job.segment.index}/{total} [{job.segment.role}] "
                    f"({job.profile.provider}:{job.profile.voice}) failed after "
                    f"{attempts} attempt(s): {type(exc).__name__}: {exc}"
                ) from exc
            delay = policy.delay(attempts)
            print(f"[{number}/{total}] [{job.segment.role}] "
                  f"{type(exc).__name__}: retry {attempts}/{policy.retries} "
                  f"in {delay:.1f}s")
            await asyncio.sleep(delay)
            continue
        else:
            try:
                return cache.save_verified(job.key, job.extension, temp, duration), attempts - 1
            finally:
                temp.unlink(missing_ok=True)


async def synthesize_segments(
    segments: tuple[PlannedSegment, ...],
    profiles: Mapping[str, VoiceProfile],
    output_dir: Path,
    registry: ProviderRegistry,
    *,
    overwrite: bool = False,
    cache_dir: Path | None = None,
    retry_policy: RetryPolicy | None = None,
    validator: Callable[[Path], float] | None = None,
) -> SynthesisResult:
    """Create/reuse clips while writing a checkpoint after each completed segment.

    The success manifest only exists when every requested clip is finished.
    --overwrite forces fresh synthesis; normally reruns resume or hit the cache.
    """
    jobs = _prepare(segments, profiles, output_dir, registry)
    policy = retry_policy if retry_policy is not None else RetryPolicy()
    if validator is None:
        check_audio_tools()
        validator = validate_audio
    cache = ClipCache(cache_dir if cache_dir is not None else output_dir / ".voxbraid_cache")
    state = RunState(output_dir / ".voxbraid_state.json")
    if not overwrite:
        _safe_existing_outputs(jobs, state, cache)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / "manifest.json"
    # A failed/interrupted new run cannot leave a stale 'complete' manifest.
    manifest.unlink(missing_ok=True)
    generated = cached = resumed = retried = 0
    entries: list[dict[str, object]] = []
    for pos, job in enumerate(jobs, 1):
        if not overwrite and state.matching(job.destination.name, job.key, job.destination):
            resumed += 1
            print(f"[{pos}/{len(jobs)}] [{job.segment.role}] RESUME {job.destination.name}")
        else:
            cached_copy = None if overwrite else cache.find(job.key, job.extension)
            if cached_copy is None:
                _metadata, retries_used = await _make_clip(
                    job, registry, cache, policy, validator, pos, len(jobs)
                )
                retried += retries_used
                generated += 1
                print(f"[{pos}/{len(jobs)}] [{job.segment.role}] "
                      f"{job.profile.provider}:{job.profile.voice} "
                      f"-> {job.destination.name} (new)")
            else:
                cached += 1
                print(f"[{pos}/{len(jobs)}] [{job.segment.role}] "
                      f"CACHE HIT {job.destination.name}")
            _copy_atomic(cache.path(job.key, job.extension), job.destination)
            state.commit(job.destination.name, job.key, job.destination)
        entry = {
            **asdict(job.segment),
            "file": job.destination.name,
            "provider": job.profile.provider,
            "voice": job.profile.voice,
            "options": dict(job.profile.options),
            "cache_key": job.key,
        }
        entries.append(entry)
    write_json_atomic(manifest, {
        "format": "voxbraid-synthesis-v1",
        "composed": False,
        "segments": entries,
    })
    return SynthesisResult(
        output_dir=output_dir, manifest=manifest,
        clips=tuple(job.destination for job in jobs),
        generated=generated, cached=cached, resumed=resumed, retried=retried,
    )
