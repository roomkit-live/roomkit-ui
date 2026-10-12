"""Local readiness check for the conversation LLM; no API call or model load."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from urllib.parse import urlparse

from roomkit_ui.features import AI_PROVIDER_FEATURES, is_available

_CLOUD = {
    "anthropic": ("Anthropic", "anthropic_api_key", "vc_anthropic_model"),
    "openai": ("OpenAI", "openai_api_key", "vc_openai_model"),
    "gemini": ("Gemini", "api_key", "vc_gemini_model"),
}
CONFIGURATION_HINT = "Settings → Conversation → Voice Channel → Reason · LLM"


def text_chat_unavailable(settings: dict) -> str:
    """A reason for the disabled input, or empty when its AI channel is configured."""
    provider = settings.get("vc_llm_provider", "anthropic")
    if provider in _CLOUD:
        name, key, model_key = _CLOUD[provider]
        if not str(settings.get(key) or "").strip():
            return f"Add your {name} key in Settings…"
        # Omitted means the factory's default; a saved blank is not a model.
        if model_key in settings and not str(settings[model_key] or "").strip():
            return "Choose a chat model in Settings…"
    elif provider == "local":
        if not str(settings.get("vc_local_model") or "").strip():
            return "Choose a local chat model in Settings…"
        try:
            url = urlparse(str(settings.get("vc_local_base_url", "http://localhost:11434/v1")))
            valid_url = url.scheme in ("http", "https") and bool(url.hostname)
            _ = url.port  # reject malformed ports as well as malformed host names
        except ValueError:
            valid_url = False
        if not valid_url:
            return "Configure your local server in Settings…"
    elif provider == "llamacpp":
        model = str(settings.get("vc_llamacpp_model") or "").strip()
        if model.lower().endswith(".gguf") and not Path(model).expanduser().is_file():
            return "Choose an available GGUF model in Settings…"
    else:
        return "Configure a chat model in Settings…"
    feature = AI_PROVIDER_FEATURES.get(provider)
    if feature and not is_available(feature):
        return "Install the chat provider in Settings…"
    return ""


def image_chat_unavailable(settings: dict) -> str:
    """Use RoomKit's model metadata without opening a provider or making a request."""
    if reason := text_chat_unavailable(settings):
        return reason
    name = settings.get("vc_llm_provider", "anthropic")
    classes = {
        "anthropic": "AnthropicAIProvider",
        "openai": "OpenAIAIProvider",
        "gemini": "GeminiAIProvider",
    }
    if name not in classes:
        return ""  # Local endpoints report unsupported images in their response.
    model = settings.get(_CLOUD[name][2], "")
    try:
        provider = getattr(import_module(f"roomkit.providers.{name}.ai"), classes[name])
        entry = next((m for m in provider.available_models() if m.id == model), None)
    except ImportError:
        return "Install the chat provider in Settings…"
    if entry is not None and entry.supports_vision is False:
        return "This model does not accept images. Choose a vision model in Settings."
    return ""
