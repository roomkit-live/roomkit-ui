"""Guided enrolment: the recordings that become the wake-word fingerprint.

The guidance is not decoration.  A fingerprint enrolled only at arm's
length misses the same phrase spoken from across the room — measured, a
distant utterance scored *worse* than a different first name.  So the
takes are requested condition by condition rather than "say it six
times", and each one is checked before it joins the fingerprint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QObject, Signal

from roomkit_ui.wakeword.capture import SegmentCapture
from roomkit_ui.wakeword.features import WhisperEmbedder
from roomkit_ui.wakeword.fingerprint import Calibration, Fingerprint, calibrate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    """One condition to cover, and how to ask for it."""

    prompt: str
    hint: str
    takes: int


# Two takes per condition, so every condition has a near neighbour: the
# threshold is derived from nearest-neighbour distance, and a lone take in
# an unusual condition would otherwise look like an outlier.
PROTOTYPE_STEPS: tuple[Step, ...] = (
    Step("Say it normally", "As you would to wake the assistant.", 2),
    Step("Now more quietly", "Half-voice, as if someone were asleep nearby.", 2),
    Step("Now from further away", "A metre or two from the microphone.", 2),
)

DECOY_STEP = Step(
    "Now say some words it should ignore",
    "Names or words that sound close to your phrase.",
    3,
)

_MIN_TAKE_SECONDS = 0.4
_MAX_TAKE_SECONDS = 4.0
# A take far off the others' length caught a stray word or a phrase said
# twice; keeping it would poison the fingerprint and drag the threshold.
_LENGTH_TOLERANCE = 0.55


@dataclass
class Take:
    """One accepted recording."""

    embedding: np.ndarray
    duration: float


@dataclass
class EnrolmentState:
    """Progress through the guided steps."""

    label: str = ""
    prototypes: list[Take] = field(default_factory=list)
    decoys: list[Take] = field(default_factory=list)
    step_index: int = 0
    collecting_decoys: bool = False

    @property
    def steps(self) -> tuple[Step, ...]:
        return (DECOY_STEP,) if self.collecting_decoys else PROTOTYPE_STEPS

    @property
    def current_step(self) -> Step | None:
        steps = self.steps
        return steps[self.step_index] if self.step_index < len(steps) else None

    @property
    def taken_in_step(self) -> int:
        done = len(self.decoys) if self.collecting_decoys else len(self.prototypes)
        before = sum(s.takes for s in self.steps[: self.step_index])
        return done - before

    @property
    def total_takes(self) -> int:
        return sum(s.takes for s in self.steps)


class Enroller(QObject):
    """Drives guided enrolment and produces a calibrated fingerprint."""

    take_accepted = Signal(int, int, float)  # done, total, duration
    take_rejected = Signal(str)  # why, in the user's terms
    step_changed = Signal(str, str, int, int)  # prompt, hint, done_in_step, of
    phase_finished = Signal()  # prototypes done, or decoys done
    level = Signal(float)
    error = Signal(str)

    def __init__(
        self,
        encoder_path: str,
        vad_path: str,
        *,
        input_device: int | None = None,
        capture_rate: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._embedder = WhisperEmbedder(encoder_path)
        # Recorded at the rate detection captures at (see controller.capture_rate),
        # so takes and live audio reach the encoder through the same conversion.
        self._capture = SegmentCapture(
            vad_path, input_device=input_device, capture_rate=capture_rate, parent=self
        )
        self._capture.segment.connect(self._on_segment)
        self._capture.level.connect(self.level)
        self._capture.error.connect(self.error)
        self.state = EnrolmentState()

    # -- lifecycle -----------------------------------------------------------

    def begin(self, label: str) -> bool:
        """Start collecting the phrase itself."""
        self.state = EnrolmentState(label=label)
        try:
            self._embedder.load()
        except (FileNotFoundError, ImportError) as exc:
            self.error.emit(str(exc))
            return False
        if not self._capture.start():
            return False
        self._announce()
        return True

    def begin_decoys(self) -> bool:
        """Move on to the words that must *not* trigger."""
        self.state.collecting_decoys = True
        self.state.step_index = 0
        if not self._capture.running and not self._capture.start():
            return False
        self._announce()
        return True

    @property
    def embedder(self) -> WhisperEmbedder:
        """The loaded encoder, so detection can reuse it rather than reload."""
        return self._embedder

    @property
    def capture(self) -> SegmentCapture:
        """The shared microphone capture, still running between phases."""
        return self._capture

    def cancel(self) -> None:
        """Release the microphone. Safe only outside the capture call stack."""
        self._capture.stop()

    def finish(self) -> tuple[Fingerprint, Calibration]:
        """Build the calibrated fingerprint.

        Does *not* release the microphone: this runs inside the capture
        timer's call stack, and the wizard goes straight on to the test
        step.  Call :meth:`cancel` when the dialog closes.
        """
        prototypes = [t.embedding for t in self.state.prototypes]
        decoys = [t.embedding for t in self.state.decoys]
        cal = calibrate(prototypes, decoys)
        fingerprint = Fingerprint(
            label=self.state.label,
            prototypes=prototypes,
            decoys=decoys,
            threshold=cal.threshold,
        )
        return fingerprint, cal

    # -- collection ----------------------------------------------------------

    def _on_segment(self, pcm: bytes, duration: float) -> None:
        if self.state.current_step is None:
            return
        rejection = self._reject_reason(duration)
        if rejection:
            self.take_rejected.emit(rejection)
            return
        try:
            embedding = self._embedder.embed(pcm)
        except Exception as exc:
            logger.exception("Wake word enrolment: embedding failed")
            self.error.emit(str(exc))
            return
        if len(embedding) == 0:
            self.take_rejected.emit("That was too short to use — try again.")
            return

        take = Take(embedding=embedding, duration=duration)
        bucket = self.state.decoys if self.state.collecting_decoys else self.state.prototypes
        bucket.append(take)
        self.take_accepted.emit(len(bucket), self.state.total_takes, duration)
        self._advance()

    def _reject_reason(self, duration: float) -> str | None:
        """Why this take can't be used — phrased for the user, not the log."""
        if duration < _MIN_TAKE_SECONDS:
            return "That was too short — say the whole phrase."
        if duration > _MAX_TAKE_SECONDS:
            return "That was too long — just the phrase on its own."
        # Decoys are different words by design; only the phrase must stay
        # consistent with itself.
        if self.state.collecting_decoys or not self.state.prototypes:
            return None
        median = float(np.median([t.duration for t in self.state.prototypes]))
        if abs(duration - median) > median * _LENGTH_TOLERANCE:
            return "That one sounded different in length — say it as before."
        return None

    def _advance(self) -> None:
        if self.state.taken_in_step >= (self.state.current_step or DECOY_STEP).takes:
            self.state.step_index += 1
        if self.state.current_step is None:
            # The microphone stays open across phases on purpose.  Closing it
            # here would run stream.stop() inside the capture timer's own call
            # stack — and stop() waits for the audio callback to return, which
            # deadlocks the UI thread.  Segments arriving between phases are
            # ignored: _on_segment returns early when no step is active.
            self.phase_finished.emit()
        else:
            self._announce()

    def _announce(self) -> None:
        step = self.state.current_step
        if step is None:
            return
        self.step_changed.emit(step.prompt, step.hint, self.state.taken_in_step, step.takes)
