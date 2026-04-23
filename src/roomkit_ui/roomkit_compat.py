"""Single point of contact for every reach-into-roomkit-internals.

Each helper here documents **what** private attribute it touches, **why**
a public API is not available, and guards access with ``hasattr`` so a
future roomkit refactor degrades gracefully instead of crashing.

The rest of the package is forbidden from touching ``roomkit`` private
attributes directly — if a new hook is needed, add it here so regressions
show up in one file.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VoiceChannel / RealtimeVoiceChannel teardown
# ---------------------------------------------------------------------------
#
# The session-cleanup sequence in ``Engine._cleanup`` needs to:
#   1. detach STT / TTS from the channel so ``VoiceChannel.close()`` does
#      not attempt to close them a second time (ElevenLabs's httpx client
#      hangs on a second ``aclose``),
#   2. keep the backend attached across ``kit.close()`` so in-flight
#      streaming tasks can still reach it, then
#   3. detach the backend once those tasks are cancelled.
#
# ``VoiceChannel`` exposes no public "detach provider" API — it assumes
# the channel owns STT/TTS for its whole lifetime.  Until upstream adds
# one, mutate the attributes directly but keep the damage local to these
# three helpers.


def detach_channel_providers(channel: Any) -> None:
    """Unbind the STT and TTS providers from a VoiceChannel.

    Call **before** ``kit.close()`` so the channel's own close path sees
    ``None`` and skips closing the providers.  Ignored on channels that
    don't expose these slots (e.g. RealtimeVoiceChannel).
    """
    if channel is None:
        return
    for attr in ("_stt", "_tts"):
        if hasattr(channel, attr):
            try:
                setattr(channel, attr, None)
            except Exception:
                logger.debug("detach_channel_providers: failed to clear %s", attr, exc_info=True)


def detach_channel_backend(channel: Any) -> None:
    """Unbind the backend from a VoiceChannel.

    Call **after** ``kit.close()`` has cancelled any in-flight streaming
    tasks so dangling references to the backend aren't reused across
    sessions.  No-op on channels without a ``_backend`` slot.
    """
    if channel is None or not hasattr(channel, "_backend"):
        return
    try:
        channel._backend = None
    except Exception:
        logger.debug("detach_channel_backend: failed to clear _backend", exc_info=True)


# ---------------------------------------------------------------------------
# AIChannel live system-prompt update
# ---------------------------------------------------------------------------
#
# ``AIChannel`` takes ``system_prompt`` as a constructor argument and
# caches it on ``_system_prompt``.  No public setter — constructing a new
# channel mid-session would drop memory and tool state.  The attitude
# feature needs to swap prompts on the fly; mutating the private slot is
# the least-bad option until a public ``set_system_prompt`` lands.

_ATTITUDE_MARKER = "\n\n# Attitude\n"


def compose_attitude_prompt(base_prompt: str, attitude_description: str) -> str:
    """Build a full system prompt by appending an ``# Attitude`` section.

    * ``attitude_description`` non-empty → append the section to ``base_prompt``.
    * ``attitude_description`` empty → return ``base_prompt`` verbatim.

    Pure function (no side-effects); used by both the VoiceChannel path
    (which writes to ``AIChannel._system_prompt``) and the realtime path
    (which pushes the result into ``RealtimeVoiceChannel.reconfigure_session``).
    """
    base = base_prompt or ""
    if attitude_description:
        return f"{base}{_ATTITUDE_MARKER}{attitude_description}"
    return base


def set_ai_system_prompt(ai_channel: Any, new_prompt: str) -> None:
    """Replace the ``AIChannel`` system prompt for subsequent turns.

    ``AIChannel`` has no public live-update API — it rebuilds context from
    ``self._system_prompt`` each turn, so writing the slot is functionally
    equivalent to the hypothetical ``set_system_prompt`` method.  Silently
    no-ops when the channel doesn't expose the attribute.
    """
    if ai_channel is None or not hasattr(ai_channel, "_system_prompt"):
        return
    try:
        ai_channel._system_prompt = new_prompt
    except Exception:
        logger.debug("set_ai_system_prompt: failed to write _system_prompt", exc_info=True)


# ---------------------------------------------------------------------------
# SherpaOnnxDiarizationProvider enrollment reset
# ---------------------------------------------------------------------------
#
# ``SherpaOnnxDiarizationProvider.reset()`` clears clustering state but
# not the enrollment dictionary maintained inside the provider's private
# ``_manager`` / ``_enrolled_embeddings`` members.  Reusing a cached
# provider across sessions leaves stale enrollments behind, which mixes
# speakers from previous conversations into the new one.  Reach into the
# private state until a ``clear_speakers()`` method is added upstream.


def clear_diarization_enrollment(diarization: Any) -> None:
    """Reset a diarization provider *and* forget every enrolled speaker."""
    if diarization is None:
        return
    try:
        diarization.reset()
    except Exception:
        logger.debug("clear_diarization_enrollment: reset() failed", exc_info=True)

    mgr = getattr(diarization, "_manager", None)
    if mgr is not None:
        for name in list(getattr(mgr, "all_speakers", []) or []):
            try:
                diarization.remove_speaker(name)
            except Exception:
                logger.debug(
                    "clear_diarization_enrollment: remove_speaker(%r) failed", name, exc_info=True
                )

    enrolled = getattr(diarization, "_enrolled_embeddings", None)
    if enrolled is not None:
        try:
            enrolled.clear()
        except Exception:
            logger.debug(
                "clear_diarization_enrollment: _enrolled_embeddings.clear() failed", exc_info=True
            )
