"""M3 reliability regression tests: no TTS network requests required."""

from __future__ import annotations

import asyncio
import json
import shutil
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from voxbraid.audio_validation import AudioValidationError, validate_audio
from voxbraid.parser import parse_text
from voxbraid.planner import plan_segments
from voxbraid.retry import RetryPolicy, is_transient
from voxbraid.synthesis import SynthesisError, synthesize_segments
from voxbraid.tts.base import VoiceProfile
from voxbraid.tts.registry import ProviderRegistry


class FakeAudioProvider:
    audio_extension = ".wav"
    cache_version = "1"

    def __init__(self, failures: int = 0, permanent: Exception | None = None):
        self.calls: list[tuple[str, str]] = []
        self.failures = failures
        self.permanent = permanent

    async def synthesize(self, text: str, profile: VoiceProfile, output: Path):
        self.calls.append((text, profile.voice))
        if self.permanent is not None:
            raise self.permanent
        if self.failures:
            self.failures -= 1
            output.write_bytes(b"partial corrupt bytes")
            raise ConnectionError("socket temporarily closed")
        with wave.open(str(output), "wb") as sink:
            sink.setnchannels(1)
            sink.setsampwidth(2)
            sink.setframerate(16000)
            sink.writeframes(b"\x00\x00" * 3200)


def story(text: str = "Hello. Goodbye."):
    return plan_segments(parse_text(text))


def registry(provider):
    result = ProviderRegistry()
    result.register("fake", provider)
    return result


def go(segments, provider, folder, *, profiles=None, **kwargs):
    mapping = profiles or {"narrator": VoiceProfile("fake", "Brian")}
    # Offline control-flow tests use a deterministic validator; real FFmpeg
    # decoding is covered in test_real_wav_validation_and_corruption.
    kwargs.setdefault("validator", lambda _: 0.2)
    return asyncio.run(synthesize_segments(
        segments, mapping, folder, registry(provider),
        retry_policy=RetryPolicy(retries=2, base_delay=0, jitter=0), **kwargs
    ))


def test_retry_then_succeed_and_rerun_resumes_without_new_calls(tmp_path: Path) -> None:
    provider = FakeAudioProvider(failures=2)
    output = tmp_path / "out"
    first = go(story("Hello."), provider, output)
    assert first.generated == 1
    assert first.retried == 2
    assert len(provider.calls) == 3
    second = go(story("Hello."), provider, output)
    assert second.generated == 0 and second.resumed == 1
    assert len(provider.calls) == 3
    assert (output / "manifest.json").is_file()
    assert not list(output.rglob("*.partial.*"))


def test_mid_run_failure_keeps_checkpoint_and_recovers(tmp_path: Path) -> None:
    class FailSecond(FakeAudioProvider):
        async def synthesize(self, text, profile, output):
            if text == "Second." and self.failures:
                self.failures -= 1
                self.calls.append((text, profile.voice))
                output.write_bytes(b"broken")
                raise ConnectionError("not now")
            remaining = self.failures
            self.failures = 0
            try:
                await super().synthesize(text, profile, output)
            finally:
                self.failures = remaining

    provider = FailSecond(failures=3)
    segments = story("First. Second. Third.")
    folder = tmp_path / "out"
    with pytest.raises(SynthesisError, match="after 3 attempt"):
        go(segments, provider, folder)
    assert (folder / "segment_0001.wav").exists()
    assert (folder / ".voxbraid_state.json").exists()
    assert not (folder / "manifest.json").exists()
    assert not (folder / "segment_0002.wav").exists()
    assert not list(folder.rglob(".voxbraid.partial.*"))
    again = go(segments, provider, folder)
    assert again.resumed == 1 and again.generated == 2
    assert [s["text"] for s in json.loads(again.manifest.read_text())["segments"]] == [
        "First.", "Second.", "Third."
    ]
    assert provider.calls.count(("First.", "Brian")) == 1


def test_reuse_cache_when_output_missing_and_when_shared_across_runs(tmp_path: Path) -> None:
    provider = FakeAudioProvider()
    folder = tmp_path / "a"
    common = tmp_path / "shared"
    first = go(story("Hi!"), provider, folder, cache_dir=common)
    assert first.generated == 1
    (folder / "segment_0001.wav").unlink()
    second = go(story("Hi!"), provider, folder, cache_dir=common)
    assert second.cached == 1 and second.generated == 0
    third = go(story("Hi!"), provider, tmp_path / "b", cache_dir=common)
    assert third.cached == 1 and len(provider.calls) == 1


def test_corrupt_cache_is_detected_and_resynthesized(tmp_path: Path) -> None:
    provider = FakeAudioProvider()
    folder = tmp_path / "a"
    go(story("Hi."), provider, folder)
    cache_clip = next((folder / ".voxbraid_cache").rglob("*.wav"))
    cache_clip.write_bytes(b"corrupted cache longer than original")
    (folder / "segment_0001.wav").unlink()
    second = go(story("Hi."), provider, folder)
    assert second.generated == 1
    assert len(provider.calls) == 2


def test_corrupt_output_is_restored_from_cache(tmp_path: Path) -> None:
    provider = FakeAudioProvider()
    folder = tmp_path / "out"
    go(story("Hi."), provider, folder)
    (folder / "segment_0001.wav").write_bytes(b"bad")
    second = go(story("Hi."), provider, folder)
    assert second.cached == 1
    assert len(provider.calls) == 1
    assert (folder / "segment_0001.wav").stat().st_size > 300


def test_changes_to_voice_only_resynth_that_role(tmp_path: Path) -> None:
    segments = story("[narrator]\nWelcome.\n\n[fox]\nHello.\n\n[narrator]\nGoodbye.")
    provider = FakeAudioProvider()
    folder = tmp_path / "out"
    profiles = {
        "narrator": VoiceProfile("fake", "Brian"),
        "fox": VoiceProfile("fake", "Andrew"),
    }
    go(segments, provider, folder, profiles=profiles)
    assert len(provider.calls) == 3
    new_profiles = {**profiles, "fox": VoiceProfile("fake", "Ava")}
    again = go(segments, provider, folder, profiles=new_profiles)
    assert again.generated == 1 and again.resumed == 2
    assert len(provider.calls) == 4
    assert provider.calls[-1] == ("Hello.", "Ava")


def test_change_only_pause_updates_manifest_without_retts(tmp_path: Path) -> None:
    segments = story("Hello. Goodbye.")
    provider = FakeAudioProvider()
    folder = tmp_path / "out"
    go(segments, provider, folder)
    changed = tuple(replace(s, pause_before=9.0) for s in segments)
    again = go(changed, provider, folder)
    assert again.resumed == 2
    assert len(provider.calls) == 2
    manifest_segments = json.loads(again.manifest.read_text())["segments"]
    assert all(seg["pause_before"] == 9 for seg in manifest_segments)


def test_overwrite_forces_new_synthesis(tmp_path: Path) -> None:
    segments = story("Hi.")
    provider = FakeAudioProvider()
    folder = tmp_path / "out"
    go(segments, provider, folder)
    again = go(segments, provider, folder, overwrite=True)
    assert again.generated == 1 and again.resumed == 0 and len(provider.calls) == 2


def test_legacy_untracked_output_requires_overwrite(tmp_path: Path) -> None:
    folder = tmp_path / "old"
    folder.mkdir()
    (folder / "segment_0001.wav").write_bytes(b"untracked")
    provider = FakeAudioProvider()
    with pytest.raises(FileExistsError, match="--overwrite"):
        go(story("Hi."), provider, folder)
    assert not provider.calls
    result = go(story("Hi."), provider, folder, overwrite=True)
    assert result.generated == 1


def test_do_not_retry_nontransient_config_errors(tmp_path: Path) -> None:
    provider = FakeAudioProvider(permanent=ValueError("bad voice"))
    with pytest.raises(SynthesisError, match="after 1 attempt"):
        go(story("Hi."), provider, tmp_path / "x")
    assert len(provider.calls) == 1


def test_no_audio_received_class_name_is_retryable() -> None:
    NoAudioReceived = type("NoAudioReceived", (Exception,), {})
    assert is_transient(NoAudioReceived())
    assert not is_transient(ValueError("invalid voice"))
    assert is_transient(ConnectionError("socket"))


def test_http_retry_status_check() -> None:
    class HttpError(Exception):
        def __init__(self, status):
            self.status = status

    assert is_transient(HttpError(429))
    assert is_transient(HttpError(503))
    assert not is_transient(HttpError(401))
    assert not is_transient(HttpError(403))


def test_retry_policy_validation() -> None:
    with pytest.raises(ValueError, match="retries"):
        RetryPolicy(retries=-1)
    with pytest.raises(ValueError, match="Retry delay"):
        RetryPolicy(base_delay=-1)
    assert RetryPolicy(base_delay=0).delay(1) == 0


@pytest.mark.skipif(shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None,
                    reason="FFmpeg + FFprobe required for real audio validation")
def test_real_wav_validation_and_corruption(tmp_path: Path) -> None:
    provider = FakeAudioProvider()
    result = go(story("Hello."), provider, tmp_path / "real", validator=validate_audio)
    audio = result.clips[0]
    assert 0.19 <= validate_audio(audio) <= 0.21
    bad = tmp_path / "broken.wav"
    bad.write_bytes(b"RIFFwhatevercorrupted")
    with pytest.raises(AudioValidationError):
        validate_audio(bad)


def test_identical_segments_reuse_speech_in_one_run(tmp_path: Path) -> None:
    provider = FakeAudioProvider()
    result = go(story("Hello. Hello."), provider, tmp_path / "out")
    assert result.generated == 1 and result.cached == 1
    assert len(provider.calls) == 1
    assert len(result.clips) == 2


def test_adopt_verified_clip_after_interruption_before_checkpoint(tmp_path: Path) -> None:
    provider = FakeAudioProvider()
    folder = tmp_path / "out"
    go(story("Hi."), provider, folder)
    (folder / ".voxbraid_state.json").unlink()
    second = go(story("Hi."), provider, folder)
    assert second.cached == 1
    assert len(provider.calls) == 1


def test_cache_invalidates_on_provider_implementation_version(tmp_path: Path) -> None:
    provider = FakeAudioProvider()
    folder = tmp_path / "out"
    first = go(story("Hi."), provider, folder)
    assert first.generated == 1
    provider.cache_version = "2"
    again = go(story("Hi."), provider, folder)
    assert again.generated == 1 and len(provider.calls) == 2


def test_missing_audio_tool_detected_before_any_request(tmp_path: Path, monkeypatch) -> None:
    import voxbraid.audio_validation as audio_validation

    monkeypatch.setattr(audio_validation.shutil, "which", lambda _: None)
    provider = FakeAudioProvider()
    with pytest.raises(ValueError, match="FFmpeg/FFprobe"):
        asyncio.run(synthesize_segments(
            story("Hi."), {"narrator": VoiceProfile("fake", "Brian")},
            tmp_path / "out", registry(provider)
        ))
    assert not provider.calls


def test_invalid_synthesis_duration_is_retried(tmp_path: Path) -> None:
    provider = FakeAudioProvider()
    with pytest.raises(SynthesisError, match="no valid audio duration"):
        go(story("Hi."), provider, tmp_path / "out", validator=lambda _: float("nan"))
    assert len(provider.calls) == 3


@pytest.mark.skipif(shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None,
                    reason="FFmpeg + FFprobe required for audio validation")
def test_fake_large_mp3_bytes_are_not_valid_audio(tmp_path: Path) -> None:
    class FakeBrokenMP3:
        audio_extension = ".mp3"

        async def synthesize(self, text, profile, output):
            output.write_bytes(b"not a real mp3" * 1000)

    provider = FakeBrokenMP3()
    folder = tmp_path / "out"
    with pytest.raises(SynthesisError, match="after 1 attempt"):
        asyncio.run(synthesize_segments(
            story("Hello."), {"narrator": VoiceProfile("fake", "Brian")},
            folder, registry(provider), retry_policy=RetryPolicy(retries=0)
        ))
    assert not (folder / "manifest.json").exists()
    assert not (folder / "segment_0001.mp3").exists()
    assert not list(folder.rglob(".voxbraid.partial.*"))


def test_stale_manifest_removed_before_retry_exhaustion(tmp_path: Path) -> None:
    provider = FakeAudioProvider()
    folder = tmp_path / "out"
    go(story("First."), provider, folder)
    assert (folder / "manifest.json").exists()
    provider.permanent = ValueError("bad voice")
    with pytest.raises(SynthesisError, match="bad voice"):
        go(story("Changed text."), provider, folder)
    assert not (folder / "manifest.json").exists()
