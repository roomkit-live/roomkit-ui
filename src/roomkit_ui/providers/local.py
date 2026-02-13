"""Local (vLLM/Ollama) AI provider factory."""

from __future__ import annotations

from typing import Any


def create(settings: dict) -> Any:
    """Create a local vLLM-compatible AI provider from settings."""
    from roomkit.providers.vllm import VLLMConfig, create_vllm_provider

    base_url = settings.get("vc_local_base_url", "http://localhost:11434/v1")
    model_name = settings.get("vc_local_model", "")
    if not model_name:
        raise ValueError("No local model specified. Enter a model name in Settings.")
    api_key = settings.get("vc_local_api_key", "") or "none"
    return create_vllm_provider(VLLMConfig(model=model_name, base_url=base_url, api_key=api_key))
