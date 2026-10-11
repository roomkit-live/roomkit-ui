"""AI provider factory with lazy-loading registry."""

from __future__ import annotations

import importlib
from typing import Any

from roomkit_ui.features import AI_PROVIDER_FEATURES, require

_REGISTRY: dict[str, str] = {
    "anthropic": "roomkit_ui.providers.anthropic",
    "openai": "roomkit_ui.providers.openai",
    "gemini": "roomkit_ui.providers.gemini",
    "local": "roomkit_ui.providers.local",
    "llamacpp": "roomkit_ui.providers.llamacpp",
}


def create_ai_provider(name: str, settings: dict) -> Any:
    """Create an AI provider by name, lazily importing the backing module."""
    module_path = _REGISTRY.get(name)
    if module_path is None:
        raise ValueError(f"Unknown AI provider: {name!r}")
    # Check before importing: the factory would fail on the provider SDK
    # import with a message that names a roomkit module, not an install.
    feature = AI_PROVIDER_FEATURES.get(name)
    if feature is not None:
        require(feature)
    module = importlib.import_module(module_path)
    return module.create(settings)
