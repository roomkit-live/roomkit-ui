"""OpenAI AI provider factory."""

from __future__ import annotations

from typing import Any


def create(settings: dict) -> Any:
    """Create an OpenAI AI provider from settings."""
    from roomkit.providers.openai.ai import OpenAIAIProvider
    from roomkit.providers.openai.config import OpenAIConfig

    api_key = settings.get("openai_api_key", "")
    if not api_key:
        raise ValueError("OpenAI API key is required. Open Settings to enter it.")
    return OpenAIAIProvider(
        OpenAIConfig(
            api_key=api_key,
            model=settings.get("vc_openai_model", "gpt-4o"),
        )
    )
