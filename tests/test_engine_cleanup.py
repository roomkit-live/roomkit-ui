"""Tests for the ordered teardown in Engine._cleanup.

The ordering encodes hard-won fixes: STT/TTS must be detached BEFORE
kit.close() (ElevenLabs double-close hang) and the backend AFTER
(in-flight streaming tasks still reference it during close).
"""

import asyncio

import pytest

from roomkit_ui.engine import Engine


class _Recorder:
    def __init__(self):
        self.calls: list[tuple] = []

    def add(self, *entry):
        self.calls.append(entry)

    def names(self):
        return [c[0] for c in self.calls]


class _Channel:
    def __init__(self):
        self._stt = object()
        self._tts = object()
        self._backend = object()

    async def end_session(self, session):
        pass


class _Backend:
    def __init__(self, rec):
        self._rec = rec

    async def stop_listening(self, session):
        self._rec.add("backend.stop_listening")

    async def disconnect(self, session):
        self._rec.add("backend.disconnect")


class _Kit:
    def __init__(self, rec, channel):
        self._rec = rec
        self._channel = channel

    async def close(self):
        ch = self._channel
        self._rec.add("kit.close", ch._stt is None, ch._tts is None, ch._backend is not None)


class _TTS:
    def __init__(self, rec):
        self._rec = rec

    async def close(self):
        self._rec.add("tts.close")


class _MCP:
    def __init__(self, rec):
        self._rec = rec

    async def close_all(self):
        self._rec.add("mcp.close_all")


class _RealtimeChannel(_Channel):
    def __init__(self, rec):
        super().__init__()
        self._rec = rec

    async def end_session(self, session):
        self._rec.add("channel.end_session")


@pytest.fixture
def engine(qapp):
    eng = Engine()
    yield eng
    # post_cleanup_monitor is scheduled by _cleanup; don't leak it.
    if eng._cleanup_monitor_task is not None:
        eng._cleanup_monitor_task.cancel()


async def _run_cleanup(eng):
    # Protect the test runner's own tasks from the lingering-task sweep.
    eng._pre_session_tasks = frozenset(asyncio.all_tasks())
    await eng._cleanup()


async def test_voice_channel_teardown_order(engine):
    rec = _Recorder()
    ch = _Channel()
    engine._channel = ch
    engine._backend = _Backend(rec)
    engine._session = object()
    engine._kit = _Kit(rec, ch)
    engine._tts = _TTS(rec)
    engine._mcp = _MCP(rec)

    await _run_cleanup(engine)

    names = rec.names()
    # Backend stops listening before disconnecting.
    assert names.index("backend.stop_listening") < names.index("backend.disconnect")
    # TTS closed before kit (channel can no longer reach it).
    assert names.index("tts.close") < names.index("kit.close")
    # MCP closed after kit.
    assert names.index("kit.close") < names.index("mcp.close_all")
    # At kit.close() time: STT/TTS already detached, backend still attached.
    kit_entry = next(c for c in rec.calls if c[0] == "kit.close")
    assert kit_entry == ("kit.close", True, True, True)
    # Backend detached only after kit.close().
    assert ch._backend is None


async def test_realtime_teardown_ends_session(engine):
    rec = _Recorder()
    ch = _RealtimeChannel(rec)
    engine._channel = ch
    engine._session = object()
    engine._backend = None  # realtime mode has no separate backend
    engine._kit = _Kit(rec, ch)

    await _run_cleanup(engine)

    assert "channel.end_session" in rec.names()
    assert rec.names().index("channel.end_session") < rec.names().index("kit.close")


async def test_cached_tts_is_not_closed(engine):
    rec = _Recorder()
    ch = _Channel()
    tts = _TTS(rec)
    engine._channel = ch
    engine._kit = _Kit(rec, ch)
    engine._tts = tts
    engine._cached_models["tts"] = (("piper", "model"), tts)

    await _run_cleanup(engine)

    assert "tts.close" not in rec.names()


async def test_cleanup_nullifies_session_state(engine):
    ch = _Channel()
    rec = _Recorder()
    engine._channel = ch
    engine._session = object()
    engine._kit = _Kit(rec, ch)
    engine._transport = object()
    engine._partial_buffers["user"] = "leftover"
    engine._current_speaker_id = "spk1"
    engine._base_system_prompt = "prompt"

    await _run_cleanup(engine)

    assert engine._channel is None
    assert engine._session is None
    assert engine._kit is None
    assert engine._transport is None
    assert engine._partial_buffers == {}
    assert engine._current_speaker_id == ""
    assert engine._base_system_prompt == ""
