"""AI provider factory with lazy-loading registry."""

from __future__ import annotations

import importlib
from typing import Any

_REGISTRY: dict[str, str] = {
    "anthropic": "roomkit_ui.providers.anthropic",
    "openai": "roomkit_ui.providers.openai",
    "gemini": "roomkit_ui.providers.gemini",
    "local": "roomkit_ui.providers.local",
}


def create_ai_provider(name: str, settings: dict) -> Any:
    """Create an AI provider by name, lazily importing the backing module."""
    module_path = _REGISTRY.get(name)
    if module_path is None:
        raise ValueError(f"Unknown AI provider: {name!r}")
    module = importlib.import_module(module_path)
    return module.create(settings)
