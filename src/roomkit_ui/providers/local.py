"""Local (vLLM/Ollama) AI provider factory."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# Ollama's port: its OpenAI-compatible /v1 is this app's default local server.
_OLLAMA_PORT = 11434


def create(settings: dict) -> Any:
    """Create a local vLLM-compatible AI provider from settings."""
    from pydantic import SecretStr
    from roomkit.providers.vllm import VLLMConfig, create_vllm_provider

    base_url = settings.get("vc_local_base_url", "http://localhost:11434/v1")
    model_name = settings.get("vc_local_model", "")
    if not model_name:
        raise ValueError("No local model specified. Enter a model name in Settings.")
    api_key = settings.get("vc_local_api_key", "") or "none"
    thinking = bool(settings.get("vc_local_thinking", False))
    return create_vllm_provider(
        VLLMConfig(
            model=model_name,
            base_url=base_url,
            api_key=SecretStr(api_key),
            **thinking_fields(base_url, thinking=thinking),
        )
    )


def thinking_fields(base_url: str, *, thinking: bool) -> dict[str, Any]:
    """The VLLMConfig fields that keep a reasoning model from reasoning.

    On, nothing is sent: the model's own default, as before.  Off:

    - vLLM renders the chat template itself and reads
      ``chat_template_kwargs.enable_thinking`` — VLLMConfig's enable_thinking.
    - Ollama's /v1 ignores those kwargs (qwen3:8b on Ollama 0.17.5 reasoned
      154 tokens with them, 12 without) but takes the OpenAI field
      ``reasoning_effort: "none"`` as its ``think=false``, and accepts it for a
      model that cannot reason.  Sent to Ollama only: vLLM's request schema
      may refuse an effort of "none".
    """
    if thinking:
        return {}
    fields: dict[str, Any] = {"enable_thinking": False}
    if _is_ollama(base_url):
        fields["extra_body"] = {"reasoning_effort": "none"}
    return fields


def _is_ollama(base_url: str) -> bool:
    try:
        return urlparse(base_url).port == _OLLAMA_PORT
    except ValueError:  # a port that is not a number
        return False
