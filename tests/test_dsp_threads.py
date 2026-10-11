"""The microphone's DSP runs off the Qt thread; what it fires lands back on it.

AEC, denoiser, VAD and diarization ran on the event-loop thread — the Qt
thread under qasync — once per 20 ms frame, so a slow stage delayed the UI.
roomkit's inbound DSP pool moves the stages to a worker; it stayed off while
the pool dropped the callbacks the stages fired. Since roomkit 0.95
(RMK-392) the callbacks go back to the pipeline's loop in order, which is
what these check: the stages run on the pool, every hook and every Qt emit
of a turn on the loop's thread — the stock asyncio loop, and qasync's.
"""

import asyncio
import threading

import pytest
import qasync
from roomkit import RoomKit
from roomkit.channels.realtime_voice import RealtimeVoiceChannel
from roomkit.voice.pipeline import AudioPipelineConfig, MockVADProvider
from roomkit.voice.realtime.mock import MockRealtimeProvider, MockRealtimeTransport
from roomkit.voice.tts.mock import MockTTSProvider
from vc_harness import open_session, until, utterance

from roomkit_ui.engine_audio import DSP_THREADS


class _ThreadNotingVAD(MockVADProvider):
    """A scripted VAD that records the threads it runs on."""

    def __init__(self) -> None:
        super().__init__(events=utterance())
        self.threads: set[int] = set()

    def process(self, frame, stream):
        self.threads.add(threading.get_ident())
        return super().process(frame, stream)


def test_the_pool_is_on():
    assert DSP_THREADS is not None and DSP_THREADS >= 1


async def _one_turn_off_the_loop() -> None:
    loop_thread = threading.get_ident()
    vad = _ThreadNotingVAD()
    vc = await open_session(
        tts=MockTTSProvider(),
        reply=["Hi there."],
        pipeline={"vad": vad, "inbound_dsp_threads": DSP_THREADS},
    )
    level_threads: set[int] = set()
    vc.engine.mic_audio_level.connect(lambda _level: level_threads.add(threading.get_ident()))
    try:
        await vc.speak()
        await until(lambda: vc.engine.finals("assistant"))

        assert vad.threads and loop_thread not in vad.threads  # the stages: on the pool
        assert vc.engine.finals("user") == [("Hello", "")]
        assert vc.engine.finals("assistant") == [("Hi there.", "")]
        assert vc.engine.emit_threads == {loop_thread}  # the chat: on the loop
        assert level_threads == {loop_thread}  # the VU meter too
    finally:
        await vc.kit.close()


async def test_a_turn_runs_its_stages_on_the_pool_and_its_hooks_on_the_loop():
    await _one_turn_off_the_loop()


@pytest.mark.filterwarnings("ignore:'asyncio.iscoroutinefunction':DeprecationWarning")
def test_the_same_holds_on_the_qt_loop(qapp):
    """The app runs on qasync: its call_soon_threadsafe is what brings them home."""
    loop = qasync.QEventLoop(qapp)
    try:
        loop.run_until_complete(asyncio.wait_for(_one_turn_off_the_loop(), 10))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


async def test_a_realtime_provider_still_hears_the_microphone():
    """The pool's first failure: realtime sessions sent the provider no audio."""
    provider = MockRealtimeProvider()
    transport = MockRealtimeTransport()
    channel = RealtimeVoiceChannel(
        "rt",
        provider=provider,
        transport=transport,
        pipeline=AudioPipelineConfig(inbound_dsp_threads=DSP_THREADS),
    )
    kit = RoomKit()
    kit.register_channel(channel)
    room = await kit.create_room()
    await kit.attach_channel(room.id, "rt")
    session = await channel.start_session(room.id, "user-1", "fake-ws")
    try:
        frame = b"\x01\x00" * 160
        for _ in range(5):
            await transport.simulate_client_audio(session, frame)

        await until(lambda: len(provider.sent_audio) == 5)
        assert b"".join(audio for _, audio in provider.sent_audio) == frame * 5
    finally:
        await channel.close()
