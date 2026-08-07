"""Session health watchdog — detects and recovers from provider stalls.

Gemini's native-audio model intermittently ignores valid speech after
a turn_complete (server-side VAD stall).  Audio reaches Google cleanly
but the model never triggers a response — silence lasts 15-34 seconds.

This watchdog detects stalls and nudges the provider with a text
injection, which forces the model to re-evaluate.  Recovery takes
0.3-2 seconds.

A stall is *unanswered speech*, not silence: the user thinking quietly
for ten seconds is a conversation, not a defect, and nudging then makes
the model confabulate an apology about connection trouble.  The
detector therefore arms only on evidence the user spoke — sustained mic
level while the AI is not speaking, provider-independent — and disarms
on any AI activity.

Usage::

    watchdog = SessionWatchdog(engine)
    # watchdog auto-connects to engine signals and manages its own timer
"""

from __future__ import annotations

import asyncio
import logging
import time

from PySide6.QtCore import QObject, QTimer

from roomkit_ui.engine_state import EngineState

logger = logging.getLogger(__name__)

# How often the timer fires (seconds)
_CHECK_INTERVAL_MS = 5_000
# Silence threshold before nudging (seconds)
_STALL_THRESHOLD = 8.0
# Longer threshold when MCP tool calls are in flight (seconds)
_TOOL_CALL_THRESHOLD = 90.0
# Normalized mic level ((dB+60)/60) above which a frame counts as the user
# speaking.  Normal speech sits around 0.6–0.7; room noise below 0.3.
_SPEECH_LEVEL = 0.4
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
        # True once the mic heard the user since the AI last did anything —
        # the arming condition: silence alone never nudges.
        self._heard_user: bool = False
        # Tracks the fire-and-forget nudge tasks so that (a) exceptions
        # surface via a done-callback instead of going to sys.excepthook,
        # and (b) we can cancel them on stop() if they're still in flight.
        self._nudge_tasks: set[asyncio.Task[None]] = set()

        self._timer = QTimer(self)
        self._timer.setInterval(_CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._check)

        # Connect to engine signals
        engine.transcription.connect(self._on_transcription)
        engine.user_speaking.connect(lambda _: self.touch())
        engine.ai_speaking.connect(self._on_ai_speaking)
        engine.mic_audio_level.connect(self._on_mic_level)

    # -- public API ----------------------------------------------------------

    def start(self) -> None:
        """Start monitoring. Call when the session becomes active."""
        self._last_activity = time.monotonic()
        self._stall_warned = False
        self._ai_responding = False
        self._pending_tool_calls = 0
        self._heard_user = False
        self._timer.start()

    def stop(self) -> None:
        """Stop monitoring. Call on session cleanup."""
        self._timer.stop()
        self._pending_tool_calls = 0
        self._ai_responding = False
        # Cancel any in-flight nudges so they don't outlive the session.
        for task in list(self._nudge_tasks):
            if not task.done():
                task.cancel()
        self._nudge_tasks.clear()

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
        # Any AI activity answers whatever speech preceded it.
        self._heard_user = False
        self.touch()

    def _on_transcription(self, _text: str, role: str, _final: bool, _speaker: str) -> None:
        if role == "assistant":
            self._heard_user = False
        self.touch()

    def _on_mic_level(self, level: float) -> None:
        # Runs per 20 ms block — keep it to two compares.  Levels during AI
        # playback are ignored: residual echo must not arm the detector.
        if level >= _SPEECH_LEVEL and not self._ai_responding:
            self._heard_user = True
            self._last_activity = time.monotonic()
            self._stall_warned = False

    def _check(self) -> None:
        engine = self._engine
        if getattr(engine, "_state", None) != EngineState.ACTIVE or self._last_activity <= 0:
            return
        # Don't nudge while the AI is actively outputting audio
        if self._ai_responding:
            return
        # Silence alone is the user thinking, not a stall — nudge only when
        # the mic heard them and nothing answered.
        if not self._heard_user:
            return

        elapsed = time.monotonic() - self._last_activity
        threshold = _TOOL_CALL_THRESHOLD if self._pending_tool_calls > 0 else _STALL_THRESHOLD

        if elapsed > threshold and not self._stall_warned:
            logger.warning(
                "Session stall: %.0fs since unanswered speech (tools=%d, threshold=%.0fs)",
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
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("Nudge skipped: no running event loop")
            return
        create_owned_task = getattr(engine, "_create_owned_task", None)
        if callable(create_owned_task):
            task = create_owned_task(
                channel.inject_text(session, _NUDGE_TEXT),
                name="watchdog_nudge",
            )
        else:
            task = loop.create_task(
                channel.inject_text(session, _NUDGE_TEXT),
                name="watchdog_nudge",
            )
        self._nudge_tasks.add(task)
        task.add_done_callback(self._on_nudge_done)
        logger.info("Nudged stalled session")

    def _on_nudge_done(self, task: asyncio.Task[None]) -> None:
        """Log any exception from a nudge instead of dropping it silently."""
        self._nudge_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.exception("Failed to nudge session", exc_info=exc)
