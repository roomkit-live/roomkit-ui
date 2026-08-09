"""Closes a voice session that nobody is using any more.

A session opened by voice has no natural end: the user walks away, and
the provider connection stays billed and the microphone stays live.
This watches for a conversation going quiet and hangs up, which returns
the app to idle — and, when the wake word is armed, back to listening.

Distinct from :mod:`roomkit_ui.watchdog`, which looks for *unanswered
speech* (the user talked, the model didn't react) and nudges the
provider.  Here the signal is the opposite: nothing at all is happening.

Two silences must not be confused with an abandoned session:

* the assistant is speaking — audio is flowing, that is the session working;
* a tool call is in flight — an MCP server can legitimately think for a
  minute, and hanging up mid-call would discard its answer.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal

from roomkit_ui.engine_state import EngineState

logger = logging.getLogger(__name__)

# How often the countdown is examined.  Fine-grained enough that the
# delay the user configured is honoured to about a second.
_CHECK_INTERVAL_MS = 1_000
# Normalised mic level ((dB+60)/60) counting as speech.  Same scale the
# watchdog uses: normal speech sits around 0.6-0.7, room noise below 0.3.
_SPEECH_LEVEL = 0.4
_MIN_DELAY_SECONDS = 5.0


class IdleHangup(QObject):
    """Ends the session after a configurable stretch of nothing happening."""

    hangup = Signal(str)  # human-readable reason, shown in the chat

    def __init__(self, engine: QObject, parent: QObject | None = None) -> None:
        super().__init__(parent or engine)
        self._engine = engine
        self._enabled = False
        self._delay = 15.0
        self._last_activity = 0.0
        self._ai_speaking = False
        self._fired = False

        self._timer = QTimer(self)
        self._timer.setInterval(_CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._check)

        engine.transcription.connect(self._on_transcription)
        engine.user_speaking.connect(self._on_user_speaking)
        engine.ai_speaking.connect(self._on_ai_speaking)
        engine.mic_audio_level.connect(self._on_mic_level)
        engine.tool_use.connect(self._on_tool_use)

    # -- configuration -------------------------------------------------------

    def configure(self, *, enabled: bool, delay_seconds: float) -> None:
        """Apply user settings; takes effect on the next session.

        A delay under :data:`_MIN_DELAY_SECONDS` is raised rather than
        rejected — a five-second hair trigger would cut the user off
        mid-thought, and silently doing nothing would be worse.
        """
        self._enabled = enabled
        self._delay = max(_MIN_DELAY_SECONDS, float(delay_seconds))
        if not enabled:
            self._timer.stop()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def delay_seconds(self) -> float:
        return self._delay

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Begin counting. Call when the session becomes active."""
        if not self._enabled:
            return
        self.touch()
        self._fired = False
        self._ai_speaking = False
        self._timer.start()

    def stop(self) -> None:
        """Stop counting. Call on session cleanup."""
        self._timer.stop()
        self._ai_speaking = False

    def touch(self) -> None:
        """Record that something happened."""
        self._last_activity = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        """How long the conversation has been quiet, 0 when not counting."""
        if self._last_activity <= 0:
            return 0.0
        return time.monotonic() - self._last_activity

    # -- activity signals ----------------------------------------------------

    def _on_transcription(self, _text: str, _role: str, _final: bool, _speaker: str) -> None:
        self.touch()

    def _on_user_speaking(self, _speaking: bool) -> None:
        self.touch()

    def _on_ai_speaking(self, speaking: bool) -> None:
        self._ai_speaking = speaking
        self.touch()

    def _on_tool_use(self, _name: str, _arguments: str) -> None:
        self.touch()

    def _on_mic_level(self, level: float) -> None:
        # Runs per 20 ms block — keep it to two compares.  Levels during
        # playback are ignored so the assistant's own voice, bleeding back
        # through the mic, can't keep the session alive by itself.
        if level >= _SPEECH_LEVEL and not self._ai_speaking:
            self._last_activity = time.monotonic()

    # -- decision ------------------------------------------------------------

    def _check(self) -> None:
        if not self._enabled or self._fired:
            return
        if getattr(self._engine, "_state", None) != EngineState.ACTIVE:
            return
        if self._ai_speaking:
            return
        if getattr(self._engine, "_pending_tool_calls", 0) > 0:
            # A slow MCP server is the session working, not the session
            # being abandoned; hanging up now would throw away its result.
            self.touch()
            return

        elapsed = self.idle_seconds
        if elapsed < self._delay:
            return

        self._fired = True
        self._timer.stop()
        logger.info("Idle hangup after %.0fs of silence", elapsed)
        self.hangup.emit(f"Session closed after {int(elapsed)}s without activity.")
