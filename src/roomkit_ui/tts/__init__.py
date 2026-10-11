"""TTS provider factory with lazy-loading registry."""

from __future__ import annotations

import importlib
from typing import Any

from roomkit_ui.features import TTS_PROVIDER_FEATURES, require

_REGISTRY: dict[str, str] = {
    "qwen3": "roomkit_ui.tts.qwen3",
    "neutts": "roomkit_ui.tts.neutts",
    "piper": "roomkit_ui.tts.piper",
    "gradium": "roomkit_ui.tts.gradium",
    "elevenlabs": "roomkit_ui.tts.elevenlabs",
    "pocket": "roomkit_ui.tts.pocket",
}

# Local models, expensive to load: the engine keeps the last one built for
# the next session while nothing it was built from changes.  Cloud TTS is a
# connection, closed with its session.
_CACHED: frozenset[str] = frozenset({"piper", "qwen3", "neutts", "pocket"})


def create_tts_provider(name: str, settings: dict) -> tuple[Any, int]:
    """Create a TTS provider by name. Returns (provider, sample_rate)."""
    module_path = _REGISTRY.get(name)
    if module_path is None:
        raise ValueError(f"Unknown TTS provider: {name!r}")
    feature = TTS_PROVIDER_FEATURES.get(name)
    if feature is not None:
        require(feature)
    module = importlib.import_module(module_path)
    result: tuple[Any, int] = module.create(settings)
    return result


def is_cached_tts(name: str) -> bool:
    """Whether the engine keeps this provider's TTS across sessions."""
    return name in _CACHED


def tts_cache_fields(name: str, settings: dict) -> tuple:
    """What a provider's TTS is built from beyond the engine's own cache key.

    A factory module may define ``cache_fields(settings)``; its settings then
    rebuild a cached instance when they change.
    """
    module_path = _REGISTRY.get(name)
    if module_path is None:
        return ()
    fields = getattr(importlib.import_module(module_path), "cache_fields", None)
    return tuple(fields(settings)) if fields is not None else ()
