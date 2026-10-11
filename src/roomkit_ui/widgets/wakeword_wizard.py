"""Guided setup for the wake word: choose a phrase, record it, test it.

The steps mirror what measurement showed to matter.  The phrase is
recorded under several conditions because a fingerprint enrolled only at
arm's length misses the same words spoken from across the room.  Decoys
are recorded because a threshold derived from the phrase alone sits too
loose and lets close names through.  And nothing is armed until the user
has seen it fire — arming a permanent microphone on trust is not a
reasonable thing to ask.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.wakeword.detector import EmbeddingWakeDetector
from roomkit_ui.wakeword.enroller import Enroller
from roomkit_ui.wakeword.fingerprint import Calibration, Fingerprint, save

logger = logging.getLogger(__name__)

_PHRASE_ADVICE = (
    "Two or three words work better than one — a single short word "
    "collides with everything that rhymes with it."
)


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size: 15px; font-weight: 600; background: transparent;")
    return label


def _body(text: str, colour: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"font-size: 12px; color: {colour}; background: transparent;")
    return label


class WakeWordWizard(QDialog):
    """Walks the user from a phrase to an armed, tested wake word."""

    PAGE_PHRASE, PAGE_RECORD, PAGE_DECOYS, PAGE_TEST = range(4)

    def __init__(
        self,
        encoder_path: str,
        vad_path: str,
        *,
        input_device: int | None = None,
        capture_rate: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set up wake word")
        self.setFixedSize(460, 420)
        self.setModal(True)

        self._colors = colors()
        self._encoder_path = encoder_path
        self._fingerprint: Fingerprint | None = None
        self._calibration: Calibration | None = None

        self._enroller = Enroller(
            encoder_path,
            vad_path,
            input_device=input_device,
            capture_rate=capture_rate,
            parent=self,
        )
        self._enroller.step_changed.connect(self._on_step)
        self._enroller.take_accepted.connect(self._on_take_accepted)
        self._enroller.take_rejected.connect(self._on_take_rejected)
        self._enroller.phase_finished.connect(self._on_phase_finished)
        self._enroller.level.connect(self._on_level)
        self._enroller.error.connect(self._on_error)

        self._detector: EmbeddingWakeDetector | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_phrase_page())
        self._pages.addWidget(self._build_record_page())
        self._pages.addWidget(self._build_decoy_page())
        self._pages.addWidget(self._build_test_page())
        root.addWidget(self._pages, 1)

        self._status = _body("", self._colors["TEXT_SECONDARY"])
        root.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self._cancel_button)
        self._next_button = QPushButton("Start recording")
        self._next_button.setDefault(True)
        self._next_button.clicked.connect(self._advance)
        buttons.addWidget(self._next_button)
        root.addLayout(buttons)

        self._phrase_input.textChanged.connect(self._update_next_enabled)
        self._update_next_enabled()

    # -- pages ---------------------------------------------------------------

    def _build_phrase_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(_title("What should wake the assistant?"))
        layout.addWidget(
            _body(
                "This text is only a label — detection compares sounds, not "
                "spelling, so any language works.",
                self._colors["TEXT_SECONDARY"],
            )
        )
        self._phrase_input = QLineEdit()
        self._phrase_input.setPlaceholderText("e.g. dis Xavier")
        layout.addWidget(self._phrase_input)
        layout.addWidget(_body(_PHRASE_ADVICE, self._colors["TEXT_SECONDARY"]))
        layout.addStretch(1)
        return page

    def _build_record_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        self._record_prompt = _title("")
        layout.addWidget(self._record_prompt)
        self._record_hint = _body("", self._colors["TEXT_SECONDARY"])
        layout.addWidget(self._record_hint)

        self._level_bar = QProgressBar()
        self._level_bar.setRange(0, 100)
        self._level_bar.setTextVisible(False)
        self._level_bar.setFixedHeight(6)
        layout.addWidget(self._level_bar)

        self._record_progress = _body("", self._colors["TEXT_PRIMARY"])
        layout.addWidget(self._record_progress)
        layout.addStretch(1)
        return page

    def _build_decoy_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(_title("Now teach it what to ignore"))
        layout.addWidget(
            _body(
                "Say a few words that sound close to your phrase. Without them "
                "the threshold is a guess, and near-misses get through.",
                self._colors["TEXT_SECONDARY"],
            )
        )
        self._decoy_prompt = _body("", self._colors["TEXT_PRIMARY"])
        layout.addWidget(self._decoy_prompt)
        layout.addStretch(1)
        return page

    def _build_test_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(_title("Try it"))
        self._test_summary = _body("", self._colors["TEXT_SECONDARY"])
        layout.addWidget(self._test_summary)
        self._test_result = _body("Say your phrase…", self._colors["TEXT_PRIMARY"])
        layout.addWidget(self._test_result)
        layout.addStretch(1)
        return page

    # -- flow ----------------------------------------------------------------

    def _update_next_enabled(self) -> None:
        if self._pages.currentIndex() == self.PAGE_PHRASE:
            self._next_button.setEnabled(bool(self._phrase_input.text().strip()))

    def _advance(self) -> None:
        page = self._pages.currentIndex()
        if page == self.PAGE_PHRASE:
            self._start_recording()
        elif page == self.PAGE_DECOYS:
            self._start_decoys()
        elif page == self.PAGE_TEST:
            self._finish()

    def _start_recording(self) -> None:
        if not self._enroller.begin(self._phrase_input.text().strip()):
            return
        self._pages.setCurrentIndex(self.PAGE_RECORD)
        self._next_button.setEnabled(False)
        self._next_button.setText("Next")

    def _start_decoys(self) -> None:
        if not self._enroller.begin_decoys():
            return
        self._pages.setCurrentIndex(self.PAGE_RECORD)
        self._next_button.setEnabled(False)

    def _on_step(self, prompt: str, hint: str, done: int, of: int) -> None:
        self._record_prompt.setText(prompt)
        self._record_hint.setText(hint)
        self._record_progress.setText(f"{done} of {of} recorded")

    def _on_take_accepted(self, done: int, total: int, duration: float) -> None:
        self._status.setText(f"Recorded ({duration:.1f}s) — {done} of {total}.")

    def _on_take_rejected(self, reason: str) -> None:
        # Say why on the spot: a take silently dropped looks like a dead mic.
        self._status.setText(reason)

    def _on_level(self, level: float) -> None:
        self._level_bar.setValue(int(level * 100))

    def _on_phase_finished(self) -> None:
        self._level_bar.setValue(0)
        if not self._enroller.state.collecting_decoys:
            self._pages.setCurrentIndex(self.PAGE_DECOYS)
            self._next_button.setEnabled(True)
            self._next_button.setText("Record decoys")
            self._status.setText("")
            return
        self._build_fingerprint()

    def _build_fingerprint(self) -> None:
        fingerprint, calibration = self._enroller.finish()
        self._fingerprint = fingerprint
        self._calibration = calibration
        self._detector = EmbeddingWakeDetector(self._encoder_path, fingerprint)
        # Reuse the encoder session enrolment already loaded — a second one
        # would cost another 12 MB and ~200 ms on the user's first attempt.
        self._detector.share_embedder(self._enroller.embedder)

        if calibration.overlapping:
            # Naming the collision beats a silent tighter threshold: the user
            # can pick a less crowded phrase instead of living with misses.
            self._test_summary.setText(
                "One of those words sits very close to your phrase, so the "
                "threshold had to be tightened — you may need to repeat "
                "yourself sometimes. A more distinctive phrase would help."
            )
        else:
            self._test_summary.setText("Ready. Say your phrase to check it fires.")

        self._pages.setCurrentIndex(self.PAGE_TEST)
        self._next_button.setEnabled(True)
        self._next_button.setText("Enable wake word")
        self._start_test()

    def _start_test(self) -> None:
        # The microphone is still open from enrolment — deliberately, see
        # Enroller._advance.  Only the destination of segments changes.
        self._enroller.capture.segment.connect(self._on_test_segment)

    def _on_test_segment(self, pcm: bytes, _duration: float) -> None:
        if self._detector is None:
            return
        detection = self._detector.detect(pcm)
        if detection is None:
            return
        if detection.triggered:
            self._test_result.setText("✓ Triggered")
        else:
            self._test_result.setText("Heard something else — not a match.")

    def _on_error(self, message: str) -> None:
        self._status.setText(message)

    def _finish(self) -> None:
        if self._fingerprint is None:
            return
        self._enroller.cancel()
        save(self._fingerprint)
        self.accept()

    # -- teardown ------------------------------------------------------------

    def reject(self) -> None:  # noqa: N802 — Qt override
        self._enroller.cancel()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        self._enroller.cancel()
        super().closeEvent(event)

    @property
    def fingerprint(self) -> Fingerprint | None:
        """The enrolled fingerprint, once the wizard was accepted."""
        return self._fingerprint
