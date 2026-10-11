"""The voices Meta Muse tells apart, in a Voice Channel session.

With speaker identification on and Muse as the STT, Muse labels every turn
with its voice (``vc_stt.labels_speakers``): no speaker model, no enrolment,
no pipeline VAD.  The local identification (enrolled voices, sherpa-onnx)
does not run then.  The session keeps a :class:`SpeakerRoster` on the engine
(``engine._speakers``); this module is what the hooks do with it.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from roomkit_ui.speaker_roster import SpeakerRoster
from roomkit_ui.vc_stt import labels_speakers

logger = logging.getLogger(__name__)

PRIMARY_UNKNOWN_NOTICE = (
    "Listen only to primary speaker is on, and no voice is known to be yours: "
    "what is said is shown, but nothing reaches the assistant."
)

RESTART_NOTICE = (
    "Speaker labels started over: the transcription stream reconnected, and the "
    "voices are told apart afresh."
)

_UNATTRIBUTED = "Unknown speaker"  # roomkit's name for words attributed to nobody


def build_roster(settings: dict) -> SpeakerRoster | None:
    """The session's roster when its STT tells the voices apart, else None."""
    if not labels_speakers(settings):
        return None
    return SpeakerRoster(primary_only=bool(settings.get("primary_speaker_mode")))


def labelled_turn(engine: Any, event: Any) -> Any:
    """ON_TRANSCRIPTION for a session whose STT labels the voices.

    The chat gets the voice's key ("Speaker A"), which names it until the
    user or the assistant gives it a name; the room message, what the
    assistant reads and the stored conversation get its current name.  A
    turn primary-speaker mode holds back shows as someone else's and goes
    no further.
    """
    from roomkit import HookResult

    roster: SpeakerRoster = engine._speakers
    key = None
    if event.speaker is not None:
        heard = roster.observe(str(event.speaker), event.speaker_epoch)
        key = heard.key
        if heard.restarted:
            _notify(engine, RESTART_NOTICE)

    if not roster.may_reach_assistant(key):
        try:
            engine.transcription.emit(str(event.text), "other", True, key or _UNATTRIBUTED)
        except Exception:
            pass
        return HookResult.block("non-primary speaker")

    engine._partial_buffers.pop("assistant", None)
    try:
        engine.transcription.emit(str(event.text), "user", True, key or _UNATTRIBUTED)
    except Exception:
        pass
    name = roster.display(key) if key is not None else None
    if name is None or name == event.sender_name:
        return HookResult.allow()
    return HookResult.modify(dataclasses.replace(event, sender_name=name))


def _notify(engine: Any, notice: str) -> None:
    try:
        engine.session_notice.emit(notice)
    except Exception:
        pass
