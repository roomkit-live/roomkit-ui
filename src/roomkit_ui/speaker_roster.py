"""The voices a diarizing STT tells apart, and the names put on them, for one session.

Meta Muse labels each turn with the voice it heard: "A", "B"… in the order
the voices first speak, within one stream.  roomkit names a label "Speaker A"
and numbers a stream that starts over ("Speaker A#1"), so the same letter
from two streams never reads as one person.  A label is nobody in particular
until someone names it: the user (a click on the speaker in the chat) or the
assistant (``name_speaker``, when someone says who they are).  The assistant
names from what it hears, so it never overrides a name the user gave.

Pure logic: the hooks and the chat call in (``speaker_naming``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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
    # The assistant can name voices (name_speaker is declared to it).
    assistant_names: bool = False
    _names: dict[str, str] = field(default_factory=dict)
    _named_by_user: set[str] = field(default_factory=set)
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

    def name(self, key: str, name: str, *, by: Literal["user", "assistant"] = "user") -> None:
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
        if by == "user":
            self._named_by_user.add(key)
        else:
            self._named_by_user.discard(key)

    def named_by_user(self, key: str) -> bool:
        """Whether the user named this voice: the assistant leaves it be."""
        return key in self._named_by_user

    def carried_by_another(self, key: str, name: str) -> bool:
        """Whether a voice other than *key* already carries *name*."""
        folded = " ".join(name.split()).casefold()
        return any(
            other != key and (named or "").casefold() == folded
            for other, named in self._names.items()
        )

    def resolve(self, ref: str) -> str | None:
        """The voice *ref* means: its label ("Speaker B", or "B" in the current
        stream) or the name it carries ("Julie", the latest voice so named)."""
        ref = " ".join(ref.split())
        if not ref:
            return None
        if ref in self._seen:
            return ref
        bare = ref[len("speaker ") :] if ref.casefold().startswith("speaker ") else ref
        # The current stream's voice first: "B" after a restart is "Speaker B#1".
        for key in (_key(bare.upper(), self._epoch), f"Speaker {bare.upper()}"):
            if key in self._seen:
                return key
        folded = ref.casefold()
        for key in reversed(self._seen):
            name = self._names.get(key)
            if name and name.casefold() == folded:
                return key
        return None

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
        lines = [
            "Several people speak in this conversation; each of their turns opens "
            "with who said it.",
            *(f"- {self._who(key)}" for key in self._seen),
        ]
        if self.assistant_names:
            lines.append(
                "When someone not yet named says who they are, call name_speaker "
                "with their label and name."
            )
        return "\n".join(lines)

    def _who(self, key: str) -> str:
        name = self._names.get(key)
        return f'{key} is "{name}".' if name else f"{key} has not been named yet."
