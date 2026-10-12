"""The voices Meta Muse tells apart, in a Voice Channel session.

With speaker identification on and Muse as the STT, Muse labels every turn
with its voice (``vc_stt.labels_speakers``): no speaker model, no enrolment,
no pipeline VAD.  The local identification (enrolled voices, sherpa-onnx)
does not run then.  The session keeps a :class:`SpeakerRoster` on the engine
(``engine._speakers``); this module is what the hooks, the chat and each
turn's prompt do with it.

A voice named mid-session keeps its label on the turns said before: the
names reach the assistant as a note at the end of each turn's system prompt
(``with_speaker_note``), which ties labels and names together.

The assistant names voices too (``name_speaker``) when someone says who
they are.  It names from what it hears, which anyone in the room can say,
so a name is a plain name, a voice the user named stays as named, a name
another voice carries stays that voice's ("I'm Sylvain" from a second voice
would otherwise have the assistant read it as Sylvain), and the user's own
name is the user's to give.

The user is whoever carries their name ("Your name", else the primary
speaker profile): the first voice when "The first voice is me" is on, as the
user opens the session, else the voice the user names after themselves.
"Listen only to primary speaker" lets only that voice reach the assistant.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from roomkit_ui.speaker_roster import NAME_MAX, USER_FALLBACK, SpeakerRoster
from roomkit_ui.vc_stt import labels_speakers

logger = logging.getLogger(__name__)

NAMING_NOTICE = "Muse tells the voices apart: click a speaker's name to say who it is."

FIRST_VOICE_NOTICE = "The first voice heard is taken as yours ({name})."

PRIMARY_UNKNOWN_NOTICE = (
    "Listen only to primary speaker is on: nothing reaches the assistant until "
    "you click your voice's name and give yours ({name})."
)

RESTART_NOTICE = (
    "Speaker labels started over: the transcription stream reconnected, and the "
    "voices are told apart afresh. Click a voice's name to name it again."
)

RECLAIM_NOTICE = (
    "Click your voice's name and give yours ({name}) again: until then, nothing "
    "reaches the assistant."
)

_UNATTRIBUTED = "Unknown speaker"  # roomkit's name for words attributed to nobody

NAME_SPEAKER_TOOL: dict = {
    "name": "name_speaker",
    "description": (
        "Put a person's name on one of the voices in this conversation, when "
        'someone says who they are or who another speaker is ("I\'m Julie", '
        '"this is my colleague Marc"). Their turns carry that name from then on. '
        "A voice the user named keeps its name."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "speaker": {
                "type": "string",
                "description": 'The voice, as its turns show it: "Speaker B", or its '
                "current name to correct it.",
            },
            "name": {
                "type": "string",
                "description": "The person's name as they gave it, a first name at least.",
            },
        },
        "required": ["speaker", "name"],
    },
}


def build_roster(settings: dict) -> SpeakerRoster | None:
    """The session's roster when its STT tells the voices apart, else None."""
    if not labels_speakers(settings):
        return None
    return SpeakerRoster(
        user_name=user_name(settings),
        first_voice_is_user=bool(settings.get("speaker_first_voice_is_user", True)),
        primary_only=bool(settings.get("primary_speaker_mode")),
    )


def user_name(settings: dict) -> str:
    """The user's name: "Your name", else the primary speaker profile's."""
    given = " ".join(str(settings.get("user_name") or "").split())[:NAME_MAX].strip()
    if given:
        return given
    from roomkit_ui.speaker_manager import get_primary_speaker

    primary = get_primary_speaker()
    return primary.name if primary is not None else USER_FALLBACK


def start_notices(roster: SpeakerRoster) -> list[str]:
    """What the chat says as the session starts: how the voices get their
    names, and what primary-speaker mode holds back."""
    notices = [NAMING_NOTICE]
    if roster.first_voice_is_user:
        notices.append(FIRST_VOICE_NOTICE.format(name=roster.user_name))
    elif roster.primary_only:
        notices.append(PRIMARY_UNKNOWN_NOTICE.format(name=roster.user_name))
    return notices


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
            if roster.primary_only:
                _notify(engine, RECLAIM_NOTICE.format(name=roster.user_name))
        if heard.new:
            # The chat learns the voice, and that a click can name it.
            _announce(engine, key, roster.display(key))

    if not roster.may_reach_assistant(key):
        try:
            engine.transcription.emit(str(event.text), "other", True, key or _UNATTRIBUTED)
        except Exception:
            pass
        return HookResult.block("non-primary speaker")

    try:
        engine.transcription.emit(str(event.text), "user", True, key or _UNATTRIBUTED)
    except Exception:
        pass
    name = roster.display(key) if key is not None else None
    if name is None or name == event.sender_name:
        return HookResult.allow()
    return HookResult.modify(dataclasses.replace(event, sender_name=name))


def name_voice(engine: Any, key: str, name: str) -> None:
    """Put *name* on a voice of the session; the chat relabels its turns.

    The turns already said keep the name they were said under: the note in
    the next turn's prompt tells the assistant who they were.
    """
    roster: SpeakerRoster | None = engine._speakers
    if roster is None or key not in roster.heard():
        return
    roster.name(key, name)
    logger.info("Voice %s named %r", key, roster.display(key))
    _announce(engine, key, roster.display(key))


def name_speaker_tool(engine: Any, arguments: dict[str, Any]) -> str:
    """``name_speaker``: the assistant names a voice it heard introduced.

    Refused (``ToolRefusedError``, nothing named) for a voice nobody heard,
    a voice the user named, or something that is not a plain name.
    """
    from roomkit import ToolRefusedError

    roster: SpeakerRoster | None = engine._speakers
    if roster is None:
        raise ToolRefusedError("This session does not tell the voices apart.")
    key = roster.resolve(str(arguments.get("speaker") or ""))
    if key is None:
        voices = ", ".join(_listed(roster, k) for k in roster.heard()) or "none yet"
        raise ToolRefusedError(f"No voice is called that. The voices: {voices}.")
    if roster.named_by_user(key):
        raise ToolRefusedError(
            f"The user named {key} {roster.display(key)}; only the user renames it."
        )
    if roster.is_user_name(str(arguments.get("name") or "")):
        # Whoever carries the user's name is the user (primary-speaker mode
        # lets only that voice through): a voice saying it is the user does
        # not make it so.
        raise ToolRefusedError("Only the user says which voice is theirs.")
    given = str(arguments.get("name") or "").strip()
    if not _plain_name(given):
        raise ToolRefusedError(
            f"A name is letters, with spaces, hyphens or apostrophes: {_NAME_WORDS} "
            f"words and {NAME_MAX} characters at most."
        )
    name = " ".join(given.split())
    if roster.carried_by_another(key, name):
        # Two voices under one name read as one person: a second voice saying
        # it is someone already here must not pass for them.  The user can
        # still join two voices Muse split, with a click.
        raise ToolRefusedError(
            f"Another voice is already called {name}; only the user can give "
            "two voices the same name."
        )
    roster.name(key, name, by="assistant")
    logger.info("Voice %s named %r by the assistant", key, name)
    _announce(engine, key, name)
    _notify(engine, f"{key} → {name}")
    return f"{key} is now {name}."


_NAME_WORDS = 4  # "Dr. Ana María López"; a sentence is not a name


def _plain_name(name: str) -> bool:
    """A person's name: letters, spaces, hyphens, apostrophes, dots; one
    line, a few words.  What the assistant heard ends up in every turn's
    prompt, so anything that reads like a sentence is refused."""
    return (
        0 < len(name) <= NAME_MAX
        and len(name.split()) <= _NAME_WORDS
        and any(ch.isalpha() for ch in name)
        and all(ch.isalpha() or ch in " -'’." for ch in name)
    )


def _listed(roster: SpeakerRoster, key: str) -> str:
    name = roster.named(key)
    return f"{key} ({name})" if name else key


TurnConfig = Callable[[Any, Any], Awaitable[Any]]


def with_speaker_note(provide: TurnConfig, engine: Any) -> TurnConfig:
    """Wrap a turn's config: the AI channel's prompt, then who is who.

    The prompt is read from the channel each turn, so an attitude set
    mid-session (``AIChannel.set_system_prompt``) still holds.
    """

    async def provide_with_note(binding: Any, context: Any) -> Any:
        config = await provide(binding, context)
        roster: SpeakerRoster | None = engine._speakers
        note = roster.prompt_note() if roster is not None else None
        channel = engine._ai_channel
        if note is None or channel is None:
            return config
        prompt = channel.system_prompt or ""
        return dataclasses.replace(config, system_prompt=f"{prompt}\n\n{note}".strip())

    return provide_with_note


def _announce(engine: Any, key: str, name: str) -> None:
    try:
        engine.speaker_named.emit(key, name)
    except Exception:
        pass


def _notify(engine: Any, notice: str) -> None:
    try:
        engine.session_notice.emit(notice)
    except Exception:
        pass
