"""Shared constants used by multiple settings pages and engine.py."""

from __future__ import annotations

ATTITUDE_PRESETS = [
    (
        "Professional",
        "You are professional and formal. Use clear, precise language and maintain "
        "a courteous, business-appropriate tone.",
    ),
    (
        "Casual",
        "You are casual and friendly. Use conversational language, contractions, "
        "and a warm, approachable tone.",
    ),
    (
        "Concise",
        "You are extremely concise. Give the shortest possible answers. "
        "Avoid filler words and unnecessary explanation.",
    ),
    (
        "Creative",
        "You are creative and expressive. Use vivid language, metaphors, "
        "and an enthusiastic tone.",
    ),
    (
        "Teacher",
        "You are a patient teacher. Explain concepts step by step, use analogies, "
        "and check for understanding.",
    ),
    (
        "Technical",
        "You are a technical expert. Use precise terminology, cite specifics, "
        "and assume the user has a technical background.",
    ),
]


STT_LANGUAGES = [
    ("Auto-detect", ""),
    ("English", "en"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("German", "de"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Dutch", "nl"),
    ("Japanese", "ja"),
    ("Chinese", "zh"),
    ("Korean", "ko"),
    ("Russian", "ru"),
    ("Arabic", "ar"),
    ("Hindi", "hi"),
]


STT_PROVIDERS = [
    ("OpenAI", "openai"),
    ("Deepgram", "deepgram"),
    ("Local", "local"),
]
