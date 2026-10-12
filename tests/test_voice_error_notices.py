"""roomkit's voice errors in the chat: a streaming STT that dropped is a notice,
since roomkit reconnects it; other errors stay errors."""

import logging
import sys

import pytest

from roomkit_ui.engine import STT_RECONNECT_NOTICE, Engine
from roomkit_ui.engine_state import EngineState

_DROPPED = "MetaSTT: Meta STT error: The backend is temporarily unavailable. Please retry."


@pytest.fixture
def engine(qapp):
    eng = Engine()
    eng.notices, eng.errors = [], []
    eng.session_notice.connect(eng.notices.append)
    eng.error_occurred.connect(eng.errors.append)
    eng._state = EngineState.ACTIVE
    return eng


def _logged(message: str, *args, error: Exception) -> logging.LogRecord:
    try:
        raise error
    except type(error):
        return logging.getLogger("roomkit.voice").makeRecord(
            "roomkit.voice", logging.ERROR, __file__, 1, message, args, sys.exc_info()
        )


def test_a_dropped_stt_stream_is_a_reconnect_notice(engine):
    record = _logged(
        "Continuous STT stream error for session %s", "s1", error=RuntimeError(_DROPPED)
    )

    engine._log_handler.emit(record)

    assert engine.notices == [STT_RECONNECT_NOTICE.format(cause=_DROPPED)]
    assert engine.errors == []


def test_another_voice_error_stays_an_error(engine):
    record = _logged("TTS stream failed", error=RuntimeError("insufficient credits"))

    engine._log_handler.emit(record)

    assert engine.errors == ["insufficient credits"]
    assert engine.notices == []
