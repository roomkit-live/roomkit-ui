"""Streaming dictation uses real RoomKit capture with synthetic audio, never a device."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from roomkit.voice.audio_frame import AudioFrame
from roomkit.voice.base import TranscriptionResult
from roomkit.voice.capture.mock import MockCaptureSource
from roomkit.voice.stt.mock import MockSTTProvider

from roomkit_ui import stt_engine, stt_sessions
from roomkit_ui.dictation_stream import DictationStream
from roomkit_ui.engine_audio import local_audio_backend
from roomkit_ui.stt_engine import DictationState, STTEngine


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


class StreamingSTT(MockSTTProvider):
    def __init__(self, config=None):
        super().__init__(streaming=True)
        self.config = config
        self.streams = []
        self.finished_streams = 0
        self.warmups = self.closes = 0
        self.warmup_gate = asyncio.Event()
        self.warmup_gate.set()
        self.final_gate = asyncio.Event()
        self.final_gate.set()
        self.eof = asyncio.Event()
        self.failure = ""

    async def warmup(self):
        self.warmups += 1
        await self.warmup_gate.wait()

    async def transcribe(self, audio, **kwargs):
        raise AssertionError("A streaming model must decode while the microphone is open")

    async def transcribe_stream(self, audio_stream, **kwargs):
        chunks = []
        self.streams.append(chunks)
        try:
            async for chunk in audio_stream:
                chunks.append(chunk.data)
                if self.failure == "error":
                    raise RuntimeError("Connection lost")
                if self.failure == "early_end":
                    return
                if len(chunks) == 1:
                    yield TranscriptionResult(text="Bonjour", is_final=True)
                yield TranscriptionResult(text="partial, not final", is_final=False)
            self.eof.set()
            await self.final_gate.wait()
            yield TranscriptionResult(text="les derniers mots", is_final=True)
        finally:
            self.finished_streams += 1

    async def close(self):
        self.closes += 1


@pytest.fixture
async def capture(qapp, monkeypatch):
    engine = STTEngine()
    source = MockCaptureSource()
    backends = []
    subscriptions = []
    original_subscribe = source.subscribe

    def subscribe(*args, **kwargs):
        subscription = original_subscribe(*args, **kwargs)
        subscriptions.append(subscription)
        return subscription

    monkeypatch.setattr(source, "subscribe", subscribe)

    def backend(**kwargs):
        result = local_audio_backend(**kwargs, source=source)
        backends.append(result)
        return result

    monkeypatch.setattr(stt_sessions, "local_audio_backend", backend)
    monkeypatch.setattr(stt_sessions, "unavailable_reason", lambda _: None)
    monkeypatch.setattr(stt_sessions, "is_model_downloaded", lambda _: True)
    monkeypatch.setattr(stt_engine, "_get_frontmost_bundle", lambda: None)
    monkeypatch.delenv("STT_FAKE", raising=False)
    drafts, pasted, errors = [], [], []
    engine.draft_ready.connect(drafts.append)
    engine.text_ready.connect(pasted.append)
    engine.error_occurred.connect(errors.append)
    yield SimpleNamespace(
        engine=engine,
        source=source,
        backends=backends,
        subscriptions=subscriptions,
        drafts=drafts,
        pasted=pasted,
        errors=errors,
    )
    await engine.shutdown()
    assert not any(subscription.active for subscription in subscriptions)
    assert all(not backend.list_sessions("stt-room") for backend in backends)


@pytest.fixture
def local(capture, monkeypatch):
    providers = []
    settings = {"stt_provider": "local", "stt_model": "kroko-streaming-fr"}

    def build(config):
        provider = StreamingSTT(config)
        providers.append(provider)
        return provider

    monkeypatch.setattr("roomkit.voice.stt.sherpa_onnx.SherpaOnnxSTTProvider", build)
    monkeypatch.setattr(stt_sessions, "build_stt_config", lambda *a, **kw: SimpleNamespace())
    monkeypatch.setattr(stt_engine, "load_settings", lambda: settings)
    return settings, providers


@pytest.mark.parametrize("to_input", [True, False])
async def test_streaming_decodes_before_stop_and_drains_the_tail(capture, local, to_input):
    engine, source = capture.engine, capture.source
    if to_input:
        engine.start_input()
    else:
        engine.toggle_recording()
    await until(lambda: engine.state is DictationState.RECORDING)
    provider = local[1][0]
    frames = source.feed_blocks(4)
    await until(lambda: provider.streams and len(provider.streams[0]) == 4)
    assert not capture.drafts and not capture.pasted
    # These callbacks are still queued on the event loop when Stop is pressed.
    frames += source.feed_blocks(2, fill=20)
    engine.toggle_recording()
    await until(lambda: not engine.busy)
    assert provider.streams == [frames]
    assert provider.finished_streams == 1
    assert (capture.drafts if to_input else capture.pasted) == ["Bonjour les derniers mots"]
    assert not (capture.pasted if to_input else capture.drafts)
    assert not capture.errors


async def test_deepgram_also_uses_a_finite_stream(capture, monkeypatch):
    provider = StreamingSTT()
    monkeypatch.setattr("roomkit.voice.stt.deepgram.DeepgramSTTProvider", lambda _: provider)
    monkeypatch.setattr(
        stt_engine,
        "load_settings",
        lambda: {"stt_provider": "deepgram", "deepgram_api_key": "test"},
    )
    capture.engine.start_input()
    await until(lambda: capture.engine.state is DictationState.RECORDING)
    frames = capture.source.feed_blocks(2)
    await until(lambda: provider.streams == [frames])
    capture.engine.toggle_recording()
    await until(lambda: not capture.engine.busy)
    assert capture.drafts == ["Bonjour les derniers mots"]
    assert provider.closes == 1


@pytest.mark.parametrize("during_finish", [False, True])
async def test_cancel_closes_the_stream_and_does_not_reuse_a_running_decoder(
    capture, local, during_finish
):
    engine = capture.engine
    engine.start_input()
    await until(lambda: engine.state is DictationState.RECORDING)
    provider = local[1][0]
    provider.final_gate.clear()
    capture.source.feed_blocks(1)
    await until(lambda: provider.streams and provider.streams[0])
    if during_finish:
        engine.toggle_recording()
        await provider.eof.wait()
    engine.cancel()
    await until(lambda: not engine.busy)
    provider.final_gate.set()
    assert provider.finished_streams == provider.closes == 1
    assert not capture.drafts and not capture.errors
    engine.start_input()
    await until(lambda: engine.state is DictationState.RECORDING)
    assert len(local[1]) == 2


@pytest.mark.parametrize("failure", ["error", "early_end"])
async def test_provider_failure_releases_the_microphone_and_discards_partial_text(
    capture, local, failure
):
    capture.engine.start_input()
    await until(lambda: capture.engine.state is DictationState.RECORDING)
    provider = local[1][0]
    provider.failure = failure
    capture.source.feed_blocks(1)
    await until(lambda: not capture.engine.busy)
    assert len(capture.errors) == 1
    assert not capture.drafts
    assert not any(subscription.active for subscription in capture.subscriptions)
    assert provider.finished_streams == 1


async def test_two_dictations_share_only_the_warmed_model(capture, local):
    for _ in range(2):
        capture.engine.start_input()
        await until(lambda: capture.engine.state is DictationState.RECORDING)
        capture.source.feed_blocks(1)
        capture.engine.toggle_recording()
        await until(lambda: not capture.engine.busy)
    assert len(local[1]) == 1
    provider = local[1][0]
    assert provider.warmups == 1
    assert provider.finished_streams == len(provider.streams) == 2
    assert len(capture.drafts) == 2
    assert provider.closes == 0
    await capture.engine.shutdown()
    assert provider.closes == 1


@pytest.mark.parametrize(
    "change",
    [
        {"stt_model": "zipformer-streaming"},
        {"dictation_language": "fr"},
        {"stt_translate": True},
        {"inference_device": "coreml"},
    ],
)
async def test_model_settings_changes_invalidate_the_warmed_model(capture, local, change):
    capture.engine.start_input()
    await until(lambda: capture.engine.state is DictationState.RECORDING)
    capture.engine.toggle_recording()
    await until(lambda: not capture.engine.busy)
    local[0].update(change)
    capture.engine.start_input()
    await until(lambda: capture.engine.state is DictationState.RECORDING)
    assert len(local[1]) == 2
    assert local[1][0].closes == 1
    assert local[1][1].warmups == 1


async def test_cancel_during_native_model_loading_waits_without_opening_audio(capture, local):
    capture.engine.start_input()
    await until(lambda: local[1])
    provider = local[1][0]
    provider.warmup_gate.clear()
    await until(lambda: provider.warmups)
    capture.engine.cancel()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert capture.engine.busy
    assert not capture.engine.start_input()
    assert not capture.subscriptions
    provider.warmup_gate.set()
    await until(lambda: not capture.engine.busy)
    assert provider.closes == 1
    assert not capture.backends and not capture.drafts


async def test_full_buffer_still_accepts_eof_without_losing_audio(monkeypatch):
    monkeypatch.setattr(DictationStream, "MAX_FRAMES", 2)
    provider = StreamingSTT()
    errors = []
    stream = DictationStream(provider, errors.append)
    frame = AudioFrame(data=b"\x00\x00" * 320, sample_rate=16000)
    try:
        stream.feed(None, frame)
        stream.feed(None, frame)
        assert await stream.finish() == ["Bonjour", "les derniers mots"]
        assert provider.streams == [[frame.data, frame.data]]
        assert not errors
    finally:
        await stream.close()


async def test_overflow_reports_error_instead_of_silently_dropping_speech(monkeypatch):
    monkeypatch.setattr(DictationStream, "MAX_FRAMES", 2)
    errors = []
    stream = DictationStream(StreamingSTT(), errors.append)
    frame = AudioFrame(data=b"\x00\x00" * 320, sample_rate=16000)
    try:
        for _ in range(3):
            stream.feed(None, frame)
        await until(lambda: errors)
        with pytest.raises(RuntimeError, match="cannot keep up"):
            await stream.finish()
        assert len(errors) == 1
    finally:
        await stream.close()
