"""A realtime pipeline-stage AEC stays on from the first reply to the session's end.

roomkit 0.97's pipeline bypassed it at every reply's end; WebRTC AEC3 resumed
misaligned, the next reply's echo went through for seconds, and the provider
heard itself and cut its own reply off.
"""

import asyncio

from roomkit.voice.audio_frame import AudioFrame
from roomkit.voice.pipeline.aec.base import AECProvider
from roomkit.voice.pipeline.config import AudioPipelineConfig
from roomkit.voice.pipeline.engine import AudioPipeline

from roomkit_ui.engine_realtime import _kept_on


class _RecordingAEC(AECProvider):
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.processed = 0

    @property
    def name(self) -> str:
        return "recording"

    def process(self, frame: AudioFrame, stream: str) -> AudioFrame:
        self.processed += 1
        return frame

    def feed_reference(self, frame: AudioFrame, stream: str) -> None:
        pass

    def set_stream_active(self, stream: str, active: bool) -> None:
        self.calls.append((stream, active))

    def reset(self, stream: str) -> None:
        self.calls.append((stream, "reset"))


def test_none_stays_none():
    assert _kept_on(None) is None


async def test_roomkits_reply_end_no_longer_bypasses_it():
    inner = _RecordingAEC()
    pipeline = AudioPipeline(AudioPipelineConfig(aec=_kept_on(inner)))

    pipeline.set_aec_active("session", True)  # a reply starts playing
    pipeline.set_aec_active("session", False)  # it ends
    pipeline.set_aec_active("session", True)  # the next one

    assert inner.calls == [("session", True), ("session", True)]
    await asyncio.sleep(0)


def test_everything_else_reaches_the_canceller():
    inner = _RecordingAEC()
    aec = _kept_on(inner)
    frame = AudioFrame(data=b"\x00\x00" * 480, sample_rate=24000)

    aec.process(frame, "session")
    aec.reset("session")  # teardown still clears it

    assert inner.processed == 1
    assert inner.calls == [("session", "reset")]
    assert aec.name == "recording"
