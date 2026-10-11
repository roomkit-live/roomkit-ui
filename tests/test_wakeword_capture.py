"""Capture lifecycle — chiefly: never close the device from inside the drain."""

from __future__ import annotations

import pytest

from roomkit_ui.wakeword.capture import SegmentCapture


class FakeStream:
    def __init__(self) -> None:
        self.stopped = False
        self.closed = False

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def capture():
    c = SegmentCapture("/nonexistent/vad.onnx")
    c._stream = FakeStream()
    c._vad = None  # feed() is a no-op without a VAD, which is what we want here
    return c


def test_stop_closes_the_device_when_idle(capture):
    stream = capture._stream
    capture.stop()
    assert stream.stopped and stream.closed
    assert capture._stream is None


def test_stop_during_drain_is_deferred_not_immediate(capture):
    """stream.stop() waits on the audio callback — closing mid-drain deadlocks."""
    stream = capture._stream
    capture._draining = True

    capture.stop()

    assert not stream.stopped
    assert capture._stop_pending
    assert capture._stream is stream


def test_deferred_stop_completes_once_the_drain_unwinds(capture):
    stream = capture._stream
    capture._draining = True
    capture.stop()

    capture._draining = False
    capture.stop()  # what the deferred singleShot ends up calling

    assert stream.stopped and stream.closed


def test_drain_clears_its_flag_even_when_a_handler_raises(capture):
    """A raising segment handler must not leave capture unable to stop."""

    def explode(_pcm: bytes) -> None:
        raise RuntimeError("handler blew up")

    capture.feed = explode  # type: ignore[method-assign]
    capture._queue.put(b"\x00\x00" * 160)

    with pytest.raises(RuntimeError):
        capture._drain()

    assert not capture._draining


def test_stop_is_idempotent(capture):
    capture.stop()
    capture.stop()
    assert capture._stream is None


def test_running_reflects_the_device_state(capture):
    assert capture.running
    capture.stop()
    assert not capture.running


# -- rate adaptation ---------------------------------------------------------


class FakeSource24k:
    sample_rate = 24000

    def subscribe(self, callback, *, since=None, name=None):
        return object()

    def mark(self):
        return "m"


def test_blocks_are_resampled_to_the_detection_rate():
    """A 24 kHz shared source must reach the 16 kHz VAD as 16 kHz."""
    c = SegmentCapture("/nonexistent/vad.onnx", source=FakeSource24k())
    block_24k = b"\x00\x00" * 480  # 20 ms at 24 kHz
    out = b"".join(c._to_detection_rate(block_24k) for _ in range(50))  # 1 s
    # 20 ms per block at 16 kHz, less the resampler's ~1 ms look-ahead.
    assert 16000 - 32 <= len(out) // 2 <= 16000


def test_native_rate_blocks_pass_through_untouched():
    c = SegmentCapture("/nonexistent/vad.onnx")
    block = b"\x01\x02" * 320
    assert c._to_detection_rate(block) is block


def test_empty_block_survives_resampling():
    c = SegmentCapture("/nonexistent/vad.onnx", source=FakeSource24k())
    assert c._to_detection_rate(b"") == b""
