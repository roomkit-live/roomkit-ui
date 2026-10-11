"""The voices a diarizing STT tells apart, and the names put on them, for one session.

Meta Muse labels each turn with the voice it heard: "A", "B"… in the order
the voices first speak, within one stream.  roomkit names a label "Speaker A"
and numbers a stream that starts over ("Speaker A#1"), so the same letter
from two streams never reads as one person.  A label is nobody in particular
until someone names it: the user, with a click on the speaker in the chat.

Pure logic: the hooks and the chat call in (``speaker_naming``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

NAME_MAX = 40
"""Longest name a voice takes: a name goes into every turn's system prompt."""


def label_key(label: str | None, epoch: int | None) -> str | None:
    """How roomkit names an unnamed label: "Speaker A", "Speaker A#1" in a later
    stream.  ``None`` for words the STT attributed to nobody."""
    return None if label is None else _key(label, epoch or 0)


def _key(label: str, epoch: int) -> str:
    return f"Speaker {label}" if epoch == 0 else f"Speaker {label}#{epoch}"


@dataclass(frozen=True)
class Heard:
    """One labelled turn, as the roster saw it."""

    key: str
    new: bool  # the first turn of this voice
    restarted: bool  # the first turn of a new stream: earlier labels no longer hold


@dataclass
class SpeakerRoster:
    """The session's voices, keyed by their "Speaker A" name, and their names."""

    # "Listen only to primary speaker": only the user's turns reach the assistant.
    primary_only: bool = False
    _names: dict[str, str] = field(default_factory=dict)
    _seen: list[str] = field(default_factory=list)
    _epoch: int = 0

    def observe(self, label: str, epoch: int | None) -> Heard:
        """Note a labelled turn."""
        epoch = epoch or 0
        key = _key(label, epoch)
        restarted = epoch > self._epoch
        self._epoch = max(self._epoch, epoch)
        new = key not in self._seen
        if new:
            self._seen.append(key)
        return Heard(key, new, restarted)

    def name(self, key: str, name: str) -> None:
        """Put *name* on a voice; an empty one gives it back its label.

        Two voices may share a name: Muse sometimes splits one person in
        two, and naming both is how that is mended.  A name is one line of
        at most ``NAME_MAX`` characters.
        """
        name = " ".join(name.split())[:NAME_MAX].strip()
        if name:
            self._names[key] = name
        else:
            self._names.pop(key, None)

    def display(self, key: str) -> str:
        """What the chat and the assistant call the voice: its name, else its label."""
        return self._names.get(key) or key

    def named(self, key: str) -> str | None:
        return self._names.get(key)

    def may_reach_assistant(self, key: str | None) -> bool:
        """Whether a turn of this voice reaches the assistant.

        With ``primary_only``, nothing does while no voice is known to be the
        user's: a label says who spoke, not who it is, and letting every
        voice through would hand the assistant (and its tools) to anyone in
        the room.
        """
        return not self.primary_only

    def heard(self) -> list[str]:
        """Every voice of the session, in the order they first spoke."""
        return list(self._seen)

    def prompt_note(self) -> str | None:
        """What the model should know of who is who; None while one voice speaks.

        A turn carries the name its voice had when it was said, so a voice
        named late shows in the history under its label first: the note ties
        the two together.
        """
        if len(self._seen) < 2:
            return None
        return "\n".join(
            [
                "Several people speak in this conversation; each of their turns opens "
                "with who said it.",
                *(f"- {self._who(key)}" for key in self._seen),
            ]
        )

    def _who(self, key: str) -> str:
        name = self._names.get(key)
        return f"{key} is {name}." if name else f"{key} has not been named yet."
