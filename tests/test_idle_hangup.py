"""Auto-hangup: what counts as activity, and what must never cut a session."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from roomkit_ui.engine_state import EngineState
from roomkit_ui.idle_hangup import IdleHangup


class FakeEngine(QObject):
    """Just the signals and attributes IdleHangup reads off the engine."""

    transcription = Signal(str, str, bool, str)
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    mic_audio_level = Signal(float)
    tool_started = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._state = EngineState.ACTIVE
        self._pending_tool_calls = 0
        self._background_tasks = 0


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def hangup(engine):
    h = IdleHangup(engine)
    h.configure(enabled=True, delay_seconds=15)
    h.start()
    return h


def _go_quiet_for(hangup: IdleHangup, seconds: float) -> None:
    """Pretend the conversation has been silent for *seconds*."""
    import time

    hangup._last_activity = time.monotonic() - seconds


def _fired(hangup: IdleHangup) -> list[str]:
    received: list[str] = []
    hangup.hangup.connect(received.append)
    hangup._check()
    return received


# -- firing ------------------------------------------------------------------


def test_hangs_up_after_the_configured_silence(hangup):
    _go_quiet_for(hangup, 20)
    assert _fired(hangup)


def test_stays_open_before_the_delay_elapses(hangup):
    _go_quiet_for(hangup, 10)
    assert not _fired(hangup)


def test_fires_only_once(hangup):
    _go_quiet_for(hangup, 20)
    assert _fired(hangup)
    _go_quiet_for(hangup, 40)
    assert not _fired(hangup)


# -- what must never cut the session -----------------------------------------


def test_never_hangs_up_while_a_tool_call_is_in_flight(engine, hangup):
    """An MCP server may think for a minute — cutting would discard its answer."""
    engine._pending_tool_calls = 1
    _go_quiet_for(hangup, 120)
    assert not _fired(hangup)


def test_tool_call_in_flight_also_resets_the_countdown(engine, hangup):
    engine._pending_tool_calls = 1
    _go_quiet_for(hangup, 120)
    hangup._check()
    engine._pending_tool_calls = 0
    assert hangup.idle_seconds < 1.0


def test_never_hangs_up_while_a_background_task_runs(engine, hangup):
    """The assistant said it would come back with the result; closing cancels it."""
    engine._background_tasks = 1
    _go_quiet_for(hangup, 120)
    assert not _fired(hangup)
    engine._background_tasks = 0
    assert hangup.idle_seconds < 1.0  # the countdown starts again from the end


def test_never_hangs_up_while_the_assistant_speaks(engine, hangup):
    engine.ai_speaking.emit(True)
    _go_quiet_for(hangup, 60)
    assert not _fired(hangup)


def test_does_nothing_when_the_session_is_not_active(engine, hangup):
    engine._state = EngineState.IDLE
    _go_quiet_for(hangup, 60)
    assert not _fired(hangup)


def test_disabled_never_fires(engine):
    h = IdleHangup(engine)
    h.configure(enabled=False, delay_seconds=15)
    h.start()
    _go_quiet_for(h, 600)
    assert not _fired(h)


# -- activity resets ---------------------------------------------------------


@pytest.mark.parametrize(
    "emit",
    [
        lambda e: e.transcription.emit("bonjour", "user", True, ""),
        lambda e: e.user_speaking.emit(True),
        lambda e: e.ai_speaking.emit(False),
        lambda e: e.tool_started.emit(object()),
    ],
)
def test_activity_resets_the_countdown(engine, hangup, emit):
    _go_quiet_for(hangup, 14)
    emit(engine)
    assert hangup.idle_seconds < 1.0


def test_speech_on_the_mic_resets_the_countdown(engine, hangup):
    _go_quiet_for(hangup, 14)
    engine.mic_audio_level.emit(0.7)
    assert hangup.idle_seconds < 1.0


def test_room_noise_does_not_keep_the_session_alive(engine, hangup):
    _go_quiet_for(hangup, 14)
    engine.mic_audio_level.emit(0.15)
    assert hangup.idle_seconds >= 13.0


def test_assistant_voice_bleeding_into_the_mic_is_ignored(engine, hangup):
    """Otherwise playback echo would hold the session open indefinitely."""
    engine.ai_speaking.emit(True)
    _go_quiet_for(hangup, 14)
    engine.mic_audio_level.emit(0.9)
    assert hangup.idle_seconds >= 13.0


# -- configuration -----------------------------------------------------------


def test_too_short_a_delay_is_raised_not_ignored(engine):
    """A 2 s trigger would cut the user off mid-thought."""
    h = IdleHangup(engine)
    h.configure(enabled=True, delay_seconds=2)
    assert h.delay_seconds >= 5.0


def test_disabling_stops_the_countdown(engine, hangup):
    hangup.configure(enabled=False, delay_seconds=15)
    assert not hangup.enabled
    _go_quiet_for(hangup, 60)
    assert not _fired(hangup)


def test_reports_how_long_it_has_been_quiet(hangup):
    _go_quiet_for(hangup, 7)
    assert 6.5 <= hangup.idle_seconds <= 8.0
