"""Audio tags: the cues a Voice Channel TTS performs instead of reading them.

ElevenLabs v3/v4 and Gemini TTS act out a tag written inline in the text
(``[laughs]``, ``[whispers]``) rather than saying it.  Whatever the setting,
such a TTS gets brackets through its filter (``build_tts_filter``).  With
``vc_tts_audio_tags`` on, the system prompt also lists the tags this TTS
performs, so the model uses them to vary its delivery.  A TTS that performs
none never gets the list: it would read the tags out.
"""

from __future__ import annotations

# ElevenLabs v3's tags are roomkit's EXPRESSIVE_TAGS; v4 documents [pause]
# too, and stacked tags.
_ELEVENLABS_V3_TAGS = ("[laughs]", "[sighs]", "[whispers]", "[excited]", "[slow]")
_ELEVENLABS_V4_TAGS = ("[laughs]", "[sighs]", "[whispers]", "[excited]", "[pause]")

# Google documents [laughs] and [whispers] for Gemini 3.1 TTS, <laugh> and
# <sigh> for 3.8, and the 3.8 models perform both spellings (roomkit,
# measured 2026-09-27).  Brackets only: the chat renders a reply as Markdown,
# where <laugh> would be an HTML tag.
_GEMINI_TAGS = (
    "[laughs]",
    "[sighs]",
    "[whispers]",
    "[excitedly]",
    "[slowly]",
    "[short pause]",
)


def performed_tags(settings: dict) -> tuple[str, ...]:
    """The audio tags the session's TTS performs; empty when it would read them out."""
    provider = settings.get("vc_tts_provider")
    if provider == "gemini":
        return _GEMINI_TAGS
    if provider == "elevenlabs":
        from roomkit_ui.tts.elevenlabs import model_id

        model = model_id(settings)
        if model.startswith("eleven_v4"):
            return _ELEVENLABS_V4_TAGS
        if model.startswith("eleven_v3"):
            return _ELEVENLABS_V3_TAGS
    return ()


def audio_tags_prompt(tags: tuple[str, ...]) -> str:
    """The system prompt section that hands the model *tags*."""
    return (
        "Your voice performs audio tags. Put one inline, right where the sound or "
        "the change of delivery belongs, when the moment calls for it, not in every "
        f"reply: {' '.join(tags)}. Write the tags in English, exactly as listed, "
        "whatever language you answer in. Never explain or announce them. "
        'Example: "Oh, that one got me [laughs] Okay, [whispers] here is the secret."'
    )


def audio_tags_note(settings: dict) -> str:
    """The prompt section for this session: empty when off or the TTS performs none."""
    if not settings.get("vc_tts_audio_tags"):
        return ""
    tags = performed_tags(settings)
    return audio_tags_prompt(tags) if tags else ""
