"""Gemini AI provider factory."""

from __future__ import annotations

from typing import Any


def create(settings: dict) -> Any:
    """Create a Gemini AI provider from settings."""
    from roomkit.providers.gemini.ai import GeminiAIProvider
    from roomkit.providers.gemini.config import GeminiConfig

    api_key = settings.get("api_key", "")
    if not api_key:
        raise ValueError("Google API key is required. Open Settings to enter it.")
    return GeminiAIProvider(
        GeminiConfig(
            api_key=api_key,
            model=settings.get("vc_gemini_model", "gemini-2.0-flash"),
        )
    )
