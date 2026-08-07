"""The watchdog nudges unanswered speech, never plain silence.

The 8 s threshold used to run against *any* quiet spell — a user thinking
for ten seconds got the model nudged into apologizing about connection
trouble. The detector now arms only on mic evidence of user speech and
disarms on any AI activity.
"""

import time

from PySide6.QtCore import QObject, Signal

from roomkit_ui.engine_state import EngineState
from roomkit_ui.watchdog import _SPEECH_LEVEL, SessionWatchdog


class _FakeEngine(QObject):
    transcription = Signal(str, str, bool, str)
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    mic_audio_level = Signal(float)

    def __init__(self):
        super().__init__()
        self._state = EngineState.ACTIVE
        self._channel = None
        self._session = None


def _watchdog(qapp):
    engine = _FakeEngine()
    wd = SessionWatchdog(engine)
    wd.start()
    wd._timer.stop()  # tests drive _check() directly
    nudges = []
    wd._nudge = lambda: nudges.append(time.monotonic())  # type: ignore[method-assign]
    return engine, wd, nudges


def _age(wd, seconds=30.0):
    wd._last_activity = time.monotonic() - seconds


def test_plain_silence_never_nudges(qapp):
    _, wd, nudges = _watchdog(qapp)
    _age(wd)
    wd._check()
    assert nudges == []


def test_unanswered_speech_nudges(qapp):
    engine, wd, nudges = _watchdog(qapp)
    engine.mic_audio_level.emit(_SPEECH_LEVEL + 0.2)
    _age(wd)
    wd._check()
    assert len(nudges) == 1
    # And only once per stall.
    wd._check()
    assert len(nudges) == 1


def test_ai_activity_disarms(qapp):
    engine, wd, nudges = _watchdog(qapp)
    engine.mic_audio_level.emit(0.8)
    engine.transcription.emit("answer", "assistant", True, "")
    _age(wd)
    wd._check()
    assert nudges == []


def test_echo_during_playback_does_not_arm(qapp):
    engine, wd, nudges = _watchdog(qapp)
    engine.ai_speaking.emit(True)
    engine.mic_audio_level.emit(0.9)  # speaker bleed while the AI talks
    engine.ai_speaking.emit(False)
    _age(wd)
    wd._check()
    assert nudges == []


def test_quiet_room_levels_do_not_arm(qapp):
    engine, wd, nudges = _watchdog(qapp)
    engine.mic_audio_level.emit(_SPEECH_LEVEL - 0.1)
    _age(wd)
    wd._check()
    assert nudges == []
