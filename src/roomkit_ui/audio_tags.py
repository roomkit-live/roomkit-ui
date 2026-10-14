"""Audio tags: the cues a Voice Channel TTS performs instead of reading them.

ElevenLabs v3/v4 and Gemini TTS act out a tag written inline in the text
(``[laughs]``, ``[whispers]``) rather than saying it.  Whatever the setting,
such a TTS gets brackets through its filter (``build_tts_filter``): all of
them, as their tags are open-ended, or only its own when they form a closed
list (Vui, :func:`closed_tags`).  With ``vc_tts_audio_tags`` on, the system
prompt also lists the tags this TTS performs, so the model uses them to vary
its delivery.  A TTS that performs none never gets the list: it would read
the tags out.
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


# roomkit's VUI_TAGS, the sounds Vui renders: any other bracketed word is
# read or garbled (tests/test_tts_vui.py keeps the two the same set).
_VUI_TAGS = ("[laugh]", "[sigh]", "[breath]", "[gasp]", "[cough]", "[hesitate]")


def performed_tags(settings: dict) -> tuple[str, ...]:
    """The audio tags the session's TTS performs; empty when it would read them out."""
    provider = settings.get("vc_tts_provider")
    if provider == "gemini":
        return _GEMINI_TAGS
    if provider == "vui":
        return _VUI_TAGS
    if provider == "elevenlabs":
        from roomkit_ui.tts.elevenlabs import model_id

        model = model_id(settings)
        if model.startswith("eleven_v4"):
            return _ELEVENLABS_V4_TAGS
        if model.startswith("eleven_v3"):
            return _ELEVENLABS_V3_TAGS
    return ()


def closed_tags(settings: dict) -> tuple[str, ...]:
    """The only tags the TTS performs, without brackets, when they form a closed list.

    Empty for a TTS with open-ended tags (any cue is interpreted) or none.
    """
    if settings.get("vc_tts_provider") == "vui":
        return tuple(tag.strip("[]") for tag in _VUI_TAGS)
    return ()


def audio_tags_prompt(tags: tuple[str, ...]) -> str:
    """The system prompt section that hands the model *tags*.

    The example uses the list's own tags (each list opens with its laugh): a
    tag shown but not listed would be stripped, or read out.
    """
    whisper = "[whispers] " if "[whispers]" in tags else ""
    return (
        "Your voice performs audio tags. Put one inline, right where the sound or "
        "the change of delivery belongs, when the moment calls for it, not in every "
        f"reply: {' '.join(tags)}. Write the tags in English, exactly as listed, "
        "whatever language you answer in. Never explain or announce them. "
        f'Example: "Oh, that one got me {tags[0]} Okay, {whisper}here is the secret."'
    )


def audio_tags_note(settings: dict) -> str:
    """The prompt section for this session: empty when off or the TTS performs none."""
    if not settings.get("vc_tts_audio_tags"):
        return ""
    tags = performed_tags(settings)
    return audio_tags_prompt(tags) if tags else ""
