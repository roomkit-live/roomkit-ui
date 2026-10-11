"""Resampling to 16 kHz: duration kept, nothing folded back, edges invisible."""

from __future__ import annotations

import numpy as np
import pytest

from roomkit_ui.wakeword.capture import SegmentCapture
from roomkit_ui.wakeword.resample import StreamResampler

SRC, DST = 24000, 16000
BLOCK = 480  # 20 ms at 24 kHz


def _tone(freq: float, seconds: float, rate: int = SRC, amplitude: float = 10000.0) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16).tobytes()


def _from_bytes(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float64)


def _stream(resampler: StreamResampler, pcm: bytes, block: int = BLOCK) -> np.ndarray:
    out = b"".join(
        resampler.process(pcm[i : i + block * 2]) for i in range(0, len(pcm), block * 2)
    )
    return np.frombuffer(out, dtype=np.int16).astype(np.float64)


def _level_db(samples: np.ndarray, freq: float, rate: int = DST) -> float:
    """Level of *freq* in *samples*, relative to full scale."""
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    freqs = np.fft.rfftfreq(len(samples), 1 / rate)
    band = (freqs > freq - 50) & (freqs < freq + 50)
    return float(20 * np.log10(spectrum[band].max() / (len(samples) / 4) / 32768 + 1e-12))


def test_duration_is_preserved_across_blocks():
    """Two seconds in, two seconds out — less the kernel's ~1 ms look-ahead."""
    out = _stream(StreamResampler(SRC, DST), _tone(440, 2.0))
    assert DST * 2 - 32 <= len(out) <= DST * 2


def test_an_in_band_tone_keeps_its_pitch_and_level():
    out = _stream(StreamResampler(SRC, DST), _tone(1000, 1.0))[200:]
    spectrum = np.abs(np.fft.rfft(out * np.hanning(len(out))))
    peak = np.fft.rfftfreq(len(out), 1 / DST)[spectrum.argmax()]
    assert abs(peak - 1000) < 5
    rms = float(np.sqrt(np.mean(out[:-200] ** 2)))
    assert abs(rms - 10000 / np.sqrt(2)) / (10000 / np.sqrt(2)) < 0.01


def test_content_above_8_khz_does_not_fold_back():
    """Before: a 10 kHz tone reappeared at 6 kHz, inside the speech band."""
    out = _stream(StreamResampler(SRC, DST), _tone(10000, 1.0))[200:]
    assert _level_db(out, 6000) < -60


def test_naive_interpolation_did_fold_it_back():
    """The measurement above is able to see aliasing when there is some."""
    pcm = _tone(10000, 1.0)
    naive = []
    for i in range(0, len(pcm), BLOCK * 2):
        x = _from_bytes(pcm[i : i + BLOCK * 2])
        naive.append(np.interp(np.linspace(0, len(x) - 1, len(x) * 2 // 3), np.arange(len(x)), x))
    assert _level_db(np.concatenate(naive), 6000) > -20


def test_block_edges_are_invisible():
    """Streaming in 20 ms blocks gives the same samples as one long block."""
    pcm = _tone(440, 0.5)
    whole = _stream(StreamResampler(SRC, DST), pcm, block=len(pcm))
    blocks = _stream(StreamResampler(SRC, DST), pcm)
    n = min(len(whole), len(blocks))
    assert np.array_equal(whole[:n], blocks[:n])


@pytest.mark.parametrize("src", [48000, 22050, 16000 * 3 // 2])
def test_other_rates_keep_duration(src):
    resampler = StreamResampler(src, DST)
    out = _stream(resampler, _tone(440, 1.0, rate=src), block=src // 50)
    assert DST - 40 <= len(out) <= DST


def test_reset_starts_a_new_stream():
    resampler = StreamResampler(SRC, DST)
    first = _stream(resampler, _tone(440, 0.2))
    resampler.reset()
    second = _stream(resampler, _tone(440, 0.2))
    assert np.array_equal(first, second)


# -- capture -----------------------------------------------------------------


class FakeSource24k:
    sample_rate = SRC

    def subscribe(self, callback, *, since=None, name=None):
        return object()

    def mark(self):
        return "m"


def test_a_shared_source_is_resampled_with_state(monkeypatch):
    c = SegmentCapture("/nonexistent/vad.onnx", source=FakeSource24k())
    monkeypatch.setattr(c, "_build_vad", lambda: object())
    c.start()
    pcm = _tone(440, 1.0)
    out = b"".join(c._to_detection_rate(pcm[i : i + BLOCK * 2]) for i in range(0, len(pcm), 960))
    assert DST - 32 <= len(out) // 2 <= DST
    c.stop()


def test_own_device_capture_runs_at_the_rate_it_was_asked_for(monkeypatch):
    """Enrolment opens the device at the shared source's rate and converts it
    the same way detection does, so both produce comparable fingerprints."""
    c = SegmentCapture("/nonexistent/vad.onnx", capture_rate=SRC)
    opened = {}

    class FakeStream:
        def __init__(self, **kwargs) -> None:
            opened.update(kwargs)

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    import sounddevice

    monkeypatch.setattr(sounddevice, "RawInputStream", FakeStream)
    monkeypatch.setattr(c, "_build_vad", lambda: object())

    assert c.start()
    assert opened["samplerate"] == SRC
    assert opened["blocksize"] == BLOCK
    assert len(c._to_detection_rate(_tone(440, 0.5))) // 2 > 0
    c.stop()


def test_native_rate_blocks_pass_through_untouched():
    c = SegmentCapture("/nonexistent/vad.onnx")
    block = b"\x01\x02" * 320
    assert c._to_detection_rate(block) is block


# -- enrolment hears what detection hears ------------------------------------


@pytest.mark.parametrize(("provider", "rate"), [("gemini", 24000), ("elevenlabs", 16000)])
def test_capture_rate_follows_the_shared_source(provider, rate):
    pytest.importorskip("roomkit.voice.capture")
    from roomkit_ui.wakeword.controller import capture_rate

    assert capture_rate({"provider": provider}) == rate


def test_the_enroller_records_at_the_capture_rate(qapp):
    from roomkit_ui.wakeword.enroller import Enroller

    enroller = Enroller("/nonexistent/encoder.onnx", "/nonexistent/vad.onnx", capture_rate=SRC)
    assert enroller.capture._capture_rate == SRC


def test_the_wizard_is_opened_at_the_rate_detection_will_use(qapp, monkeypatch):
    """Before: enrolment took the device at 16 kHz while detection resampled 24 kHz."""
    pytest.importorskip("roomkit.voice.capture")
    from roomkit_ui.widgets import wakeword_wizard
    from roomkit_ui.widgets.settings import wakeword_page

    opened = {}

    class FakeWizard:
        def __init__(self, *_args, **kwargs) -> None:
            opened.update(kwargs)

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(wakeword_wizard, "WakeWordWizard", FakeWizard)
    page = wakeword_page._WakeWordPage({"provider": "openai", "input_device": 2})

    page._open_wizard()

    assert opened["capture_rate"] == 24000
    assert opened["input_device"] == 2
