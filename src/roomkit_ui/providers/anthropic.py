"""Anthropic AI provider factory."""

from __future__ import annotations

from typing import Any


def create(settings: dict) -> Any:
    """Create an Anthropic AI provider from settings."""
    from roomkit.providers.anthropic.ai import AnthropicAIProvider
    from roomkit.providers.anthropic.config import AnthropicConfig

    api_key = settings.get("anthropic_api_key", "")
    if not api_key:
        raise ValueError("Anthropic API key is required. Open Settings to enter it.")
    return AnthropicAIProvider(
        AnthropicConfig(
            api_key=api_key,
            model=settings.get("vc_anthropic_model", "claude-sonnet-4-20250514"),
        )
    )
