"""The voices a diarizing STT tells apart, for one session.

Meta Muse labels each turn with the voice it heard: "A", "B"… in the order
the voices first speak, within one stream.  roomkit names a label "Speaker A"
and numbers a stream that starts over ("Speaker A#1"), so the same letter
from two streams never reads as one person.

Pure logic: the hooks and the chat call in (``speaker_naming``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
    """The session's voices, keyed by their "Speaker A" name."""

    # "Listen only to primary speaker": only the user's turns reach the assistant.
    primary_only: bool = False
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

    def display(self, key: str) -> str:
        """What the chat and the assistant call the voice."""
        return key

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
