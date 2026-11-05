from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from voxbraid.parser import parse_text
from voxbraid.planner import plan_segments
from voxbraid.synthesis import SynthesisError, synthesize_segments
from voxbraid.tts.base import VoiceProfile
from voxbraid.tts.edge import EdgeTTSProvider
from voxbraid.tts.registry import ProviderRegistry, default_registry


class FakeProvider:
    audio_extension = ".mp3"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def validate(self, _profile: VoiceProfile) -> None:
        return

    async def synthesize(self, text: str, profile: VoiceProfile, output: Path) -> None:
        self.calls.append((text, profile.voice))
        output.write_bytes(b"mock mp3 data (not a real codec)")


class FailingProvider:
    audio_extension = ".mp3"

    async def synthesize(self, _text: str, _profile: VoiceProfile, output: Path) -> None:
        output.write_bytes(b"partial audio")
        raise ConnectionError("socket closed")


@pytest.fixture
def story():
    return plan_segments(parse_text(
        "[narrator]\nOnce upon a time.\n\n[fox]\nHello!\n\n[bird]\nGoodbye."
    ))


def test_registry_can_mix_providers_and_keeps_order(tmp_path: Path, story) -> None:
    edge = FakeProvider()
    local = FakeProvider()
    registry = ProviderRegistry()
    registry.register("edge", edge)
    registry.register("local", local)
    profiles = {
        "narrator": VoiceProfile("edge", "Brian"),
        "fox": VoiceProfile("local", "Fox"),
        "bird": VoiceProfile("edge", "Ava"),
    }
    result = asyncio.run(synthesize_segments(story, profiles, tmp_path / "audio", registry))
    assert len(result.clips) == 3
    assert edge.calls == [("Once upon a time.", "Brian"), ("Goodbye.", "Ava")]
    assert local.calls == [("Hello!", "Fox")]
    info = json.loads(result.manifest.read_text())
    assert info["composed"] is False
    assert [s["role"] for s in info["segments"]] == ["narrator", "fox", "bird"]
    assert [s["pause_kind"] for s in info["segments"]] == [
        "intro", "speaker", "speaker"
    ]
    assert [p.name for p in result.clips] == [
        "segment_0001.mp3", "segment_0002.mp3", "segment_0003.mp3"
    ]


def test_preflight_missing_mapping_does_not_make_files(tmp_path: Path, story) -> None:
    provider = FakeProvider()
    registry = ProviderRegistry()
    registry.register("edge", provider)
    folder = tmp_path / "speech"
    with pytest.raises(ValueError, match="No voice mapping for \\[fox\\]"):
        asyncio.run(synthesize_segments(story, {
            "narrator": VoiceProfile("edge", "Brian")
        }, folder, registry))
    assert not folder.exists()
    assert provider.calls == []


def test_preflight_unknown_provider_stops_before_network(tmp_path: Path, story) -> None:
    registry = default_registry()
    profiles = {
        role: VoiceProfile("not-installed", "test") for role in ("narrator", "fox", "bird")
    }
    with pytest.raises(ValueError, match="Unknown TTS provider"):
        asyncio.run(synthesize_segments(story, profiles, tmp_path / "out", registry))
    assert not (tmp_path / "out").exists()


def test_preflight_output_collision_requires_explicit_overwrite(tmp_path: Path, story) -> None:
    provider = FakeProvider()
    registry = ProviderRegistry()
    registry.register("fake", provider)
    profiles = {r: VoiceProfile("fake", r) for r in ("narrator", "fox", "bird")}
    output = tmp_path / "a"
    asyncio.run(synthesize_segments(story, profiles, output, registry))
    with pytest.raises(FileExistsError, match="--overwrite"):
        asyncio.run(synthesize_segments(story, profiles, output, registry))
    assert len(provider.calls) == 3
    asyncio.run(synthesize_segments(story[:1], profiles, output, registry, overwrite=True))
    assert len(provider.calls) == 4


def test_failed_provider_cleans_partial_and_no_manifest(tmp_path: Path, story) -> None:
    registry = ProviderRegistry()
    registry.register("broken", FailingProvider())
    output = tmp_path / "out"
    with pytest.raises(SynthesisError, match="socket closed"):
        asyncio.run(synthesize_segments(story[:1], {
            "narrator": VoiceProfile("broken", "test")
        }, output, registry))
    assert not (output / "segment_0001.mp3").exists()
    assert not (output / "segment_0001.mp3.partial").exists()
    assert not (output / "manifest.json").exists()


def test_empty_provider_output_is_rejected(tmp_path: Path, story) -> None:
    class EmptyProvider:
        audio_extension = ".mp3"

        async def synthesize(self, text, profile, output):
            output.write_bytes(b"")

    registry = ProviderRegistry()
    registry.register("empty", EmptyProvider())
    with pytest.raises(SynthesisError, match="returned no audio"):
        asyncio.run(synthesize_segments(story[:1], {
            "narrator": VoiceProfile("empty", "anything")
        }, tmp_path / "empty", registry))


def test_edge_adapter_uses_api_directly_without_live_network(tmp_path: Path, monkeypatch) -> None:
    calls = []

    class FakeCommunicate:
        def __init__(self, text, *, voice, **kwargs):
            calls.append((text, voice, kwargs))

        async def save(self, path):
            Path(path).write_bytes(b"some audio")

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=FakeCommunicate))
    provider = EdgeTTSProvider()
    output = tmp_path / "one.mp3"
    asyncio.run(provider.synthesize(
        "Hello!", VoiceProfile("edge", "en-US-AvaNeural", {"rate": "-10%"}), output
    ))
    assert calls == [("Hello!", "en-US-AvaNeural", {"rate": "-10%"})]
    assert output.read_bytes() == b"some audio"


def test_edge_adapter_rejects_invalid_options_before_import() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        EdgeTTSProvider().validate(VoiceProfile("edge", "Brian", {"speed": "slow"}))


def test_registry_disallows_duplicates() -> None:
    registry = default_registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register("edge", EdgeTTSProvider())


def test_registry_allows_native_wav_for_future_providers(tmp_path: Path, story) -> None:
    class LocalWavProvider(FakeProvider):
        audio_extension = ".wav"

    registry = ProviderRegistry()
    registry.register("local", LocalWavProvider())
    profiles = {r: VoiceProfile("local", r) for r in ("narrator", "fox", "bird")}
    result = asyncio.run(synthesize_segments(story[:2], profiles, tmp_path / "wav", registry))
    assert [path.suffix for path in result.clips] == [".wav", ".wav"]
    assert result.clips[0].name == "segment_0001.wav"


def test_bad_provider_extension_rejected_before_writing(tmp_path: Path, story) -> None:
    class BadProvider(FakeProvider):
        audio_extension = ".\\evil"

    registry = ProviderRegistry()
    registry.register("bad", BadProvider())
    with pytest.raises(ValueError, match="unsafe audio extension"):
        asyncio.run(synthesize_segments(story[:1], {
            "narrator": VoiceProfile("bad", "X")
        }, tmp_path / "bad", registry))
    assert not (tmp_path / "bad").exists()
