"""TTS provider factory with lazy-loading registry."""

from __future__ import annotations

import importlib
from typing import Any

_REGISTRY: dict[str, str] = {
    "qwen3": "roomkit_ui.tts.qwen3",
    "neutts": "roomkit_ui.tts.neutts",
    "piper": "roomkit_ui.tts.piper",
    "gradium": "roomkit_ui.tts.gradium",
}


def create_tts_provider(name: str, settings: dict) -> tuple[Any, int]:
    """Create a TTS provider by name. Returns (provider, sample_rate)."""
    module_path = _REGISTRY.get(name)
    if module_path is None:
        raise ValueError(f"Unknown TTS provider: {name!r}")
    module = importlib.import_module(module_path)
    result: tuple[Any, int] = module.create(settings)
    return result
