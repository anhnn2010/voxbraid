"""Provider routing; simple registry without discovery, plugins, or side effects."""

from __future__ import annotations

from voxbraid.tts.base import TTSProvider
from voxbraid.tts.edge import EdgeTTSProvider


class ProviderRegistry:
    """Supply provider implementations by ID; tests can inject a fake provider."""

    def __init__(self) -> None:
        self._providers: dict[str, TTSProvider] = {}

    def register(self, name: str, provider: TTSProvider) -> None:
        if not name or name != name.lower():
            raise ValueError("Provider name must be a nonempty lowercase string")
        if name in self._providers:
            raise ValueError(f"Provider already registered: {name}")
        self._providers[name] = provider

    def get(self, name: str) -> TTSProvider:
        if name not in self._providers:
            choices = ", ".join(sorted(self._providers)) or "(none)"
            raise ValueError(f"Unknown TTS provider {name!r}; available: {choices}")
        return self._providers[name]


def default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("edge", EdgeTTSProvider())
    return registry
