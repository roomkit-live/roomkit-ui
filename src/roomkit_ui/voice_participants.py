"""Each voice of a Voice Channel session told apart, as a participant of its room.

roomkit counts a conversation's speakers by source since 0.112 (RMK-1221): a
name proves nothing, so every turn of one microphone stream read as one
person's, whatever name its voice carried, and the assistant no longer read
who said what.  A voice is a speaker of its own once an ``ON_TRANSCRIPTION``
hook matches it to a room participant (``TranscriptionEvent.participant_id``,
RMK-904): its turns are then that participant's, labelled with their name
(``Alice: "…"``), the assistant is told who takes part, and a turn detector
never joins two of them into one turn.

One participant per name a voice goes by in the session: an enrolled name,
"Speaker A" until someone names it, the name given.  Two voices the user gave
one name read as one person, as the user meant; a name no voice goes by any
more (a voice renamed) leaves the room, so the people the assistant is told
take part are those still there.  The ids carry the voice session's, and
every one still in a room when a session opens on it leaves first
(:func:`release_voices`): the voices are those of this session.

Leaf module: the hooks and ``memory.ensure_room`` call in.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import Any

logger = logging.getLogger(__name__)

PREFIX = "voice:"
"""What every participant id of a voice starts with: no other member has it."""

VOICE_CHANNEL = "voice"


def participant_id(session_id: str, name: str) -> str:
    """The id of the participant *name* is, in voice session *session_id*.

    Names compare as the roster compares them, case aside: "julie" and
    "Julie" are one person.
    """
    return f"{PREFIX}{session_id}:{' '.join(name.split()).casefold()}"


class VoiceParticipants:
    """The voices one session's hooks matched to participants of its room."""

    def __init__(self, kit: Any) -> None:
        self._kit = kit
        self._joined: dict[str, str] = {}  # participant id → room

    async def match(
        self, room_id: str, session_id: str, name: str, *, names: Collection[str] = ()
    ) -> str:
        """The participant *name* is, a member of *room_id* from now on.

        *names* are those the session's voices go by now: a participant none
        of them is any more leaves the room.  Empty, none leaves.
        """
        pid = participant_id(session_id, name)
        if pid not in self._joined:
            await self._kit.add_member(room_id, VOICE_CHANNEL, pid, display_name=name)
            self._joined[pid] = room_id
        if names:
            current = {participant_id(session_id, held) for held in names}
            for other, room in list(self._joined.items()):
                if other not in current:
                    await self._leave(room, other)
        return pid

    async def _leave(self, room_id: str, pid: str) -> None:
        self._joined.pop(pid, None)
        try:
            await self._kit.remove_member(room_id, pid)
        except Exception:
            logger.debug("A renamed voice's participant could not leave", exc_info=True)


async def release_voices(kit: Any, room_id: str) -> None:
    """Every voice an earlier session matched in *room_id* leaves it.

    A session's own voices stay members until the next one opens: leaving at
    the end would take the room's lock while the teardown cuts its turns.
    """
    from roomkit.models.enums import ParticipantStatus

    for member in await kit.store.list_participants(room_id):
        if member.id.startswith(PREFIX) and member.status == ParticipantStatus.ACTIVE:
            await kit.remove_member(room_id, member.id)
