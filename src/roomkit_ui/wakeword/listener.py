"""Permanent local listening: hear the phrase, hand back a replay mark.

The listener owns the arming logic — when to listen, when to stand down,
and what to give the session so the words already spoken are not lost.

It stands down while a session is running, and while dictation holds the
microphone.  Not for contention (a shared source handles several
subscribers fine) but because the assistant's own voice comes back
through the microphone: a listener left armed hears the reply and wakes
on it.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal

from roomkit_ui.wakeword.capture import SegmentCapture
from roomkit_ui.wakeword.detector import WakeDetector

logger = logging.getLogger(__name__)


class WakeWordListener(QObject):
    """Listens for the wake phrase whenever nothing else needs the mic."""

    detected = Signal(object, float)  # capture mark (or None), distance
    error = Signal(str)

    def __init__(
        self,
        detector: WakeDetector,
        vad_model_path: str,
        *,
        input_device: int | None = None,
        source: Any = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._detector = detector
        self._capture = SegmentCapture(
            vad_model_path, input_device=input_device, source=source, parent=self
        )
        self._capture.segment.connect(self._on_segment)
        self._capture.speech_started.connect(self._on_speech_started)
        self._capture.error.connect(self.error)

        self._enabled = False
        self._suspended_by: set[str] = set()
        self._mark: Any = None

    # -- arming --------------------------------------------------------------

    @property
    def listening(self) -> bool:
        return self._capture.running

    def set_enabled(self, enabled: bool) -> None:
        """Turn the wake word on or off, as the user configured it."""
        self._enabled = enabled
        self._apply()

    def suspend(self, reason: str) -> None:
        """Stand down (a session started, dictation began…). Reference-counted."""
        self._suspended_by.add(reason)
        self._apply()

    def resume(self, reason: str) -> None:
        """Undo one :meth:`suspend`; listening resumes when none remain."""
        self._suspended_by.discard(reason)
        self._apply()

    def _apply(self) -> None:
        should_listen = self._enabled and not self._suspended_by
        if should_listen and not self._capture.running:
            if self._capture.start():
                logger.info("Wake word listening")
        elif not should_listen and self._capture.running:
            self._capture.stop()
            self._mark = None
            logger.info(
                "Wake word stood down (%s)",
                ", ".join(sorted(self._suspended_by)) or "disabled",
            )

    # -- detection -----------------------------------------------------------

    def _on_speech_started(self) -> None:
        # Mark the start of the utterance, not the moment of detection: the
        # phrase and the request that follows it are often one breath, and
        # the session must replay from before the wake word.
        self._mark = self._capture.mark()

    def _on_segment(self, pcm: bytes, _duration: float) -> None:
        try:
            detection = self._detector.detect(pcm)
        except Exception as exc:
            logger.exception("Wake word detection failed")
            self.error.emit(str(exc))
            return
        if detection is None or not detection.triggered:
            return

        mark, self._mark = self._mark, None
        logger.info(
            "Wake word detected (distance %.4f, threshold %.4f)",
            detection.distance,
            detection.threshold,
        )
        # Stand down before the session opens: from here the microphone is
        # the session's business, and the assistant is about to speak.
        self.suspend("session")
        self.detected.emit(mark, detection.distance)

    # -- teardown ------------------------------------------------------------

    def close(self) -> None:
        self._capture.stop()
