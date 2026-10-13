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

# (label, provider) — every LLM a role can run on, in the order Settings offers them.
LLM_PROVIDERS: list[tuple[str, str]] = [
    ("Anthropic", "anthropic"),
    ("OpenAI", "openai"),
    ("Google Gemini", "gemini"),
    ("Local (vLLM / Ollama)", "local"),
    ("llama.cpp (local GGUF)", "llamacpp"),
]

# What a provider's factory and its reasoning read beside its API key, named
# without the "vc_" of Think · LLM's keys: a role prefixes them with its own.
MODEL_FIELDS: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic_model", "anthropic_thinking", "anthropic_effort"),
    "openai": ("openai_model",),
    "gemini": ("gemini_model", "gemini_thinking"),
    "local": ("local_base_url", "local_model", "local_tools", "local_thinking"),
    "llamacpp": ("llamacpp_model", "llamacpp_context", "llamacpp_thinking"),
}

# Think · LLM's reasoning (engine_vc_helpers.reasoning_options), set for a
# spoken reply someone waits on: a role on a model of its own reasons as its
# own fields say, its model's default where they are empty.
_REPLY_REASONING = ("vc_anthropic_thinking", "vc_anthropic_effort", "vc_gemini_thinking")

# role → (the settings key naming its provider, the prefix of its model
# fields).  The conversation is Think · LLM; the others run on it while their
# provider key is empty.
LLM_ROLES: dict[str, tuple[str, str]] = {
    "conversation": ("vc_llm_provider", "vc_"),
    "background": ("vc_background_model", "vc_background_"),
    "text": ("text_llm_provider", "text_"),
}


def create_ai_provider(name: str, settings: dict, *, role: str = "conversation") -> Any:
    """Create an AI provider by name, lazily importing the backing module.

    *role* matters to llama.cpp only: it keeps one server per role.
    """
    module_path = _REGISTRY.get(name)
    if module_path is None:
        raise ValueError(f"Unknown AI provider: {name!r}")
    # Check before importing: the factory would fail on the provider SDK
    # import with a message that names a roomkit module, not an install.
    feature = AI_PROVIDER_FEATURES.get(name)
    if feature is not None:
        require(feature)
    module = importlib.import_module(module_path)
    if name == "llamacpp":
        return module.create(settings, role=role)
    return module.create(settings)


def has_own_llm(settings: dict, role: str) -> bool:
    """Whether *role* runs on a model of its own rather than Think · LLM's."""
    provider_key, _prefix = LLM_ROLES[role]
    return role != "conversation" and bool(settings.get(provider_key))


def llm_settings(settings: dict, role: str) -> dict:
    """*settings* as *role*'s model reads them: ``vc_llm_provider`` names its
    provider and Think · LLM's model fields hold its own.  A field left empty
    takes Think · LLM's, save its reasoning: empty, the model's default.  A
    role on Think · LLM's model gets *settings* as is."""
    if not has_own_llm(settings, role):
        return settings
    provider_key, prefix = LLM_ROLES[role]
    provider = str(settings[provider_key])
    merged = {**settings, **dict.fromkeys(_REPLY_REASONING, ""), "vc_llm_provider": provider}
    for name in MODEL_FIELDS.get(provider, ()):
        value = settings.get(prefix + name)
        if isinstance(value, bool) or value not in (None, ""):
            merged["vc_" + name] = value
    return merged
