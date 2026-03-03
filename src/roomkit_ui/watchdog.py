"""Session health watchdog — detects and recovers from provider stalls.

Gemini's native-audio model intermittently ignores valid speech after
a turn_complete (server-side VAD stall).  Audio reaches Google cleanly
but the model never triggers a response — silence lasts 15-34 seconds.

This watchdog detects stalls and nudges the provider with a text
injection, which forces the model to re-evaluate.  Recovery takes
0.3-2 seconds.

Usage::

    watchdog = SessionWatchdog(engine)
    # watchdog auto-connects to engine signals and manages its own timer
"""

from __future__ import annotations

import asyncio
import logging
import time

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger(__name__)

# How often the timer fires (seconds)
_CHECK_INTERVAL_MS = 5_000
# Silence threshold before nudging (seconds)
_STALL_THRESHOLD = 8.0
# Longer threshold when MCP tool calls are in flight (seconds)
_TOOL_CALL_THRESHOLD = 90.0
# Message injected to nudge the provider
_NUDGE_TEXT = (
    "[The user has been speaking but you may not have heard them. "
    "Please let them know you are listening.]"
)


class SessionWatchdog(QObject):
    """Monitors a voice session and nudges the provider on stalls."""

    def __init__(self, engine: QObject, parent: QObject | None = None) -> None:
        super().__init__(parent or engine)
        self._engine = engine
        self._last_activity: float = 0.0
        self._stall_warned: bool = False
        self._ai_responding: bool = False
        self._pending_tool_calls: int = 0

        self._timer = QTimer(self)
        self._timer.setInterval(_CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._check)

        # Connect to engine signals
        engine.transcription.connect(lambda *_: self.touch())
        engine.user_speaking.connect(lambda _: self.touch())
        engine.ai_speaking.connect(self._on_ai_speaking)

    # -- public API ----------------------------------------------------------

    def start(self) -> None:
        """Start monitoring. Call when the session becomes active."""
        self._last_activity = time.monotonic()
        self._stall_warned = False
        self._ai_responding = False
        self._pending_tool_calls = 0
        self._timer.start()

    def stop(self) -> None:
        """Stop monitoring. Call on session cleanup."""
        self._timer.stop()
        self._pending_tool_calls = 0
        self._ai_responding = False

    def touch(self) -> None:
        """Record that a provider event was received."""
        self._last_activity = time.monotonic()
        self._stall_warned = False

    def tool_call_started(self) -> None:
        self._pending_tool_calls += 1

    def tool_call_ended(self) -> None:
        self._pending_tool_calls = max(0, self._pending_tool_calls - 1)

    def set_ai_responding(self, responding: bool) -> None:
        self._ai_responding = responding

    # -- internals -----------------------------------------------------------

    def _on_ai_speaking(self, speaking: bool) -> None:
        self._ai_responding = speaking
        self.touch()

    def _check(self) -> None:
        engine = self._engine
        if getattr(engine, "_state", None) != "active" or self._last_activity <= 0:
            return
        # Don't nudge while the AI is actively outputting audio
        if self._ai_responding:
            return

        elapsed = time.monotonic() - self._last_activity
        threshold = _TOOL_CALL_THRESHOLD if self._pending_tool_calls > 0 else _STALL_THRESHOLD

        if elapsed > threshold and not self._stall_warned:
            logger.warning(
                "Session stall: %.0fs silence (tools=%d, threshold=%.0fs)",
                elapsed,
                self._pending_tool_calls,
                threshold,
            )
            self._stall_warned = True
            self._nudge()

    def _nudge(self) -> None:
        engine = self._engine
        channel = getattr(engine, "_channel", None)
        session = getattr(engine, "_session", None)
        if channel is None or session is None:
            return
        if not hasattr(channel, "inject_text"):
            return
        try:
            asyncio.ensure_future(channel.inject_text(session, _NUDGE_TEXT))
            logger.info("Nudged stalled session")
        except Exception:
            logger.exception("Failed to nudge session")
