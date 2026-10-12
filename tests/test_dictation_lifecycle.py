"""Dictation start/stop: a press that lands mid-transition must not race it.

Opening the OpenAI websocket takes about a second and the final commit up
to five; a hotkey press inside either window used to leave a session
streaming behind an idle tray, or tear down the session that replaced it.
Every roomkit object here is a fake — no device, no network.
"""

from __future__ import annotations

import asyncio

import pytest
import roomkit
import roomkit.providers.openai.realtime as openai_realtime
import roomkit.voice.backends.local as local_backend

from roomkit_ui import stt_engine, stt_sessions
from roomkit_ui.stt_engine import STTEngine


class World:
    """Records every fake roomkit object a dictation creates."""

    def __init__(self) -> None:
        self.kits: list[FakeKit] = []
        self.commits = 0
        self.microphone_stops = 0
        self.metadata = []
        self.callbacks = []
        # Held closed to keep a start "connecting" for as long as a test needs.
        self.start_gate = asyncio.Event()


class FakeKit:
    def __init__(self, world: World) -> None:
        self.closed = False
        world.kits.append(self)

    def register_channel(self, _channel) -> None:
        pass

    async def create_room(self, room_id: str) -> None:
        pass

    async def attach_channel(self, _room: str, _channel: str) -> None:
        pass

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def world(monkeypatch):
    w = World()

    class Channel:
        def __init__(self, *_a, **_kw) -> None:
            pass

        async def start_session(self, *_a, **_kw):
            w.metadata.append(_kw.get("metadata"))
            await w.start_gate.wait()
            return object()

        async def end_session(self, _session) -> None:
            pass

    class Provider:
        def __init__(self, **_kw) -> None:
            pass

        def on_transcription(self, _callback) -> None:
            w.callbacks.append(_callback)

        async def send_event(self, _session, event: dict) -> None:
            if event["type"] == "input_audio_buffer.commit":
                w.commits += 1

    monkeypatch.setattr(roomkit, "RoomKit", lambda: FakeKit(w))
    monkeypatch.setattr(roomkit, "RealtimeVoiceChannel", Channel)
    monkeypatch.setattr(openai_realtime, "OpenAIRealtimeProvider", Provider)

    class Backend:
        def __init__(self, **_kw):
            pass

        async def stop_listening(self, _session):
            w.microphone_stops += 1

    monkeypatch.setattr(local_backend, "LocalAudioBackend", Backend)
    monkeypatch.setattr(stt_sessions, "unavailable_reason", lambda _feature: None)
    monkeypatch.setattr(
        stt_engine, "load_settings", lambda: {"stt_provider": "openai", "openai_api_key": "k"}
    )
    monkeypatch.delenv("STT_FAKE", raising=False)
    return w


@pytest.fixture
def engine(qapp):
    return STTEngine()


async def _until(condition, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.01)


async def test_a_press_while_connecting_stops_once_the_session_is_up(world, engine):
    """Before: the mic stayed open and the session kept billing, tray idle."""
    changes: list[bool] = []
    engine.recording_changed.connect(changes.append)

    engine.toggle_recording()
    await _until(lambda: world.kits)  # start is waiting on the websocket
    engine.toggle_recording()  # the user changes their mind
    world.start_gate.set()

    await _until(lambda: not engine.recording)
    await _until(lambda: world.commits == 1)  # the pending stop ran
    engine._on_transcription(None, "hm", "user", True)
    await _until(lambda: world.kits[0].closed)
    assert engine._kit is None
    assert changes == [True, False]


async def test_a_second_press_while_connecting_cancels_the_first(world, engine):
    engine.toggle_recording()
    await _until(lambda: world.kits)
    engine.toggle_recording()
    engine.toggle_recording()  # ...and back again: keep dictating
    world.start_gate.set()

    await _until(lambda: engine._session is not None)
    await asyncio.sleep(0.05)
    assert engine.recording
    assert not world.kits[0].closed


async def test_a_press_while_flushing_waits_and_keeps_the_text(world, engine):
    """Before: the new session was torn down and the flushed text wiped."""
    world.start_gate.set()
    texts: list[str] = []
    engine.text_ready.connect(texts.append)

    engine.toggle_recording()
    await _until(lambda: engine._session is not None)
    engine.toggle_recording()  # stop: commit, then wait for the transcript
    await _until(lambda: world.commits == 1)
    engine.toggle_recording()  # a new dictation while the first still flushes
    await asyncio.sleep(0.05)
    engine._on_transcription(None, "first dictation", "user", True)

    await _until(lambda: texts)
    await _until(lambda: len(world.kits) == 2 and engine._session is not None)
    first, second = world.kits
    assert texts == ["first dictation"]
    assert first.closed
    assert not second.closed
    assert engine.recording


async def test_a_failed_start_drops_a_pending_press(world, engine, monkeypatch):
    """Nothing is left to stop, and the press must not restart dictation."""
    monkeypatch.setattr(stt_engine, "load_settings", lambda: {"stt_provider": "openai"})
    errors: list[str] = []
    engine.error_occurred.connect(errors.append)

    engine.toggle_recording()
    engine.toggle_recording()
    await asyncio.sleep(0.05)

    assert errors  # missing API key
    assert not engine.recording
    assert world.kits == []


async def test_openai_draft_commits_once_with_language_and_ignores_previous_callbacks(
    world, engine, monkeypatch
):
    from roomkit_ui.stt_engine import DictationState

    monkeypatch.setattr(
        stt_engine,
        "load_settings",
        lambda: {
            "stt_provider": "openai",
            "openai_api_key": "test-only",
            "dictation_language": "fr",
        },
    )
    drafts, pasted = [], []
    engine.draft_ready.connect(drafts.append)
    engine.text_ready.connect(pasted.append)
    world.start_gate.set()
    assert engine.start_input()
    await _until(lambda: engine.state is DictationState.RECORDING)
    assert world.metadata[0]["provider_config"] == {
        "turn_detection_type": None,
        "create_response": False,
        "language": "fr",
    }
    engine.toggle_recording()
    await _until(lambda: world.commits == 1)
    assert world.microphone_stops == 1
    world.callbacks[0](None, "Bonjour à tous", "user", True)
    await _until(lambda: not engine.busy)
    assert drafts == ["Bonjour à tous"] and pasted == []
    assert world.kits[0].closed

    assert engine.start_input()
    await _until(lambda: engine.state is DictationState.RECORDING)
    world.callbacks[0](None, "Stale transcript", "user", True)
    assert engine._accumulated_text == []
    await engine.shutdown()
    assert drafts == ["Bonjour à tous"]
    assert world.kits[1].closed
