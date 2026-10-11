"""Where wake-word work runs: VAD, encoder and DTW off the Qt thread.

Before, every utterance heard while armed ran the VAD, whisper's encoder
and a pure-Python DTW per prototype inside a Qt timer — the UI stalled
whenever anyone talked.  These tests pin the work to worker threads and
the results back to the Qt thread.
"""

from __future__ import annotations

import threading
import types

import numpy as np
import pytest
from roomkit.voice.pipeline.vad.base import VADEvent, VADEventType

from roomkit_ui.wakeword.capture import SegmentCapture
from roomkit_ui.wakeword.detector import Detection
from roomkit_ui.wakeword.enroller import Enroller
from roomkit_ui.wakeword.jobs import SerialWorker
from roomkit_ui.wakeword.listener import WakeWordListener

QT_THREAD = threading.get_ident()


# -- the worker --------------------------------------------------------------


def test_jobs_run_off_the_qt_thread_and_report_back_on_it_in_order(qtbot):
    worker = SerialWorker("test")
    ran_on: list[int] = []
    delivered_on: list[int] = []
    results: list[int] = []

    def job(i: int) -> int:
        ran_on.append(threading.get_ident())
        return i

    def done(i: int) -> None:
        delivered_on.append(threading.get_ident())
        results.append(i)

    for i in range(5):
        worker.submit(lambda i=i: job(i), done)
    qtbot.waitUntil(lambda: len(results) == 5, timeout=2000)

    assert results == [0, 1, 2, 3, 4]
    assert QT_THREAD not in ran_on
    assert set(delivered_on) == {QT_THREAD}
    worker.shutdown()


def test_a_failing_job_reports_its_error(qtbot):
    worker = SerialWorker("test")
    errors: list[Exception] = []

    def explode() -> None:
        raise ValueError("encoder exploded")

    worker.submit(explode, lambda _r: None, errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=2000)

    assert isinstance(errors[0], ValueError)
    worker.shutdown()


def test_results_from_before_shutdown_are_dropped(qtbot):
    """A verdict on speech heard before standing down must not open a session."""
    worker = SerialWorker("test")
    release = threading.Event()
    delivered: list[str] = []

    worker.submit(lambda: release.wait(2) and "late", delivered.append)
    worker.shutdown()
    release.set()
    qtbot.wait(100)

    assert delivered == []


# -- capture: VAD ------------------------------------------------------------


class FakeVAD:
    """Ends an utterance on the third block, noting the thread it ran on."""

    def __init__(self) -> None:
        self.threads: set[int] = set()
        self.blocks = 0

    def process(self, frame, _stream):
        self.threads.add(threading.get_ident())
        self.blocks += 1
        if self.blocks == 3:
            return VADEvent(type=VADEventType.SPEECH_END, audio_bytes=b"\x00\x00" * 16000)
        return None

    def close(self) -> None:
        pass


class PushSource:
    """A shared source the test pushes frames into, from its own thread."""

    sample_rate = 16000

    def __init__(self) -> None:
        self.callback = None

    def subscribe(self, callback, *, since=None, name=None):
        self.callback = callback
        return types.SimpleNamespace(unsubscribe=lambda: None)

    def mark(self):
        return "mark"


def test_the_vad_runs_off_the_qt_thread(qtbot, monkeypatch):
    vad, source = FakeVAD(), PushSource()
    capture = SegmentCapture("/nonexistent/vad.onnx", source=source)
    monkeypatch.setattr(capture, "_build_vad", lambda: vad)
    heard_on: list[int] = []
    capture.segment.connect(lambda _pcm, _d: heard_on.append(threading.get_ident()))
    assert capture.start()

    frame = types.SimpleNamespace(data=b"\x00\x00" * 320)
    for _ in range(3):
        source.callback(frame)
    qtbot.waitUntil(lambda: bool(heard_on), timeout=2000)
    capture.stop()

    assert QT_THREAD not in vad.threads
    assert heard_on == [QT_THREAD]


def test_stop_ends_the_vad_thread(qtbot, monkeypatch):
    capture = SegmentCapture("/nonexistent/vad.onnx", source=PushSource())
    monkeypatch.setattr(capture, "_build_vad", lambda: FakeVAD())
    capture.start()
    worker = capture._worker

    capture.stop()

    assert worker is not None and not worker.is_alive()


# -- listener: encoder + DTW -------------------------------------------------


class SlowDetector:
    """Notes its thread and waits to be released, like a long DTW would."""

    ready = True

    def __init__(self) -> None:
        self.threads: set[int] = set()
        self.release = threading.Event()

    def detect(self, pcm: bytes) -> Detection:
        self.threads.add(threading.get_ident())
        self.release.wait(2)
        return Detection(triggered=True, distance=0.04, threshold=0.08, duration=1.0)


@pytest.fixture
def listener(qtbot, monkeypatch):
    detector, source = SlowDetector(), PushSource()
    lis = WakeWordListener(detector, "/nonexistent/vad.onnx", source=source)
    monkeypatch.setattr(lis._capture, "_build_vad", lambda: FakeVAD())
    lis.set_enabled(True)
    yield lis, detector
    detector.release.set()
    lis.close()


def test_detection_runs_off_the_qt_thread(listener, qtbot):
    lis, detector = listener
    detected: list[object] = []
    lis.detected.connect(lambda mark, _d: detected.append(mark))

    lis._on_speech_started()
    lis._on_segment(b"\x00\x00" * 16000, 1.0)
    qtbot.wait(50)  # the UI keeps running while the detector works
    assert detected == []

    detector.release.set()
    qtbot.waitUntil(lambda: bool(detected), timeout=2000)
    assert QT_THREAD not in detector.threads


def test_the_mark_travels_with_its_own_utterance(listener, qtbot):
    """The user may start the request before the phrase's verdict is back."""
    lis, detector = listener
    marks = iter(["phrase-start", "request-start"])
    lis._capture.mark = lambda: next(marks)
    detected: list[object] = []
    lis.detected.connect(lambda mark, _d: detected.append(mark))

    lis._on_speech_started()
    lis._on_segment(b"\x00\x00" * 16000, 1.0)
    lis._on_speech_started()  # still talking while the phrase is judged
    detector.release.set()
    qtbot.waitUntil(lambda: bool(detected), timeout=2000)

    assert detected == ["phrase-start"]


def test_a_verdict_after_standing_down_opens_nothing(listener, qtbot):
    lis, detector = listener
    detected: list[object] = []
    lis.detected.connect(lambda mark, _d: detected.append(mark))

    lis._on_segment(b"\x00\x00" * 16000, 1.0)
    lis.suspend("dictation")  # dictation began while the phrase was judged
    lis.resume("dictation")
    detector.release.set()
    qtbot.wait(200)

    assert detected == []


# -- enrolment ---------------------------------------------------------------


def test_enrolment_embeds_and_calibrates_off_the_qt_thread(qtbot, tmp_path, monkeypatch):
    encoder = tmp_path / "encoder.onnx"
    encoder.write_bytes(b"")
    enroller = Enroller(str(encoder), "/nonexistent/vad.onnx")
    monkeypatch.setattr(enroller._capture, "start", lambda: True)
    monkeypatch.setattr(enroller._capture, "stop", lambda: None)
    threads: set[int] = set()
    monkeypatch.setattr(enroller._embedder, "load", lambda: threads.add(threading.get_ident()))

    def embed(pcm: bytes) -> np.ndarray:
        threads.add(threading.get_ident())
        return np.random.RandomState(len(pcm) % 97).randn(50, 8)

    monkeypatch.setattr(enroller._embedder, "embed", embed)
    accepted: list[int] = []
    enroller.take_accepted.connect(lambda done, _total, _d: accepted.append(done))
    built: list[object] = []
    enroller.fingerprint_ready.connect(lambda fp, _cal: built.append(fp))

    assert enroller.begin("dis xavier")
    for _ in range(enroller.state.total_takes):
        enroller._on_segment(b"\x00\x00" * 22400, 1.4)
    qtbot.waitUntil(lambda: len(accepted) == enroller.state.total_takes, timeout=2000)
    enroller.build_fingerprint()
    qtbot.waitUntil(lambda: bool(built), timeout=2000)
    enroller.cancel()

    assert threads and QT_THREAD not in threads
    assert built[0].label == "dis xavier"


def test_a_take_arriving_after_its_step_filled_is_ignored(qtbot, tmp_path, inline_jobs):
    encoder = tmp_path / "encoder.onnx"
    encoder.write_bytes(b"")
    enroller = Enroller(str(encoder), "/nonexistent/vad.onnx", jobs=inline_jobs)
    enroller.state.step_index = len(enroller.state.steps)  # every step done

    enroller._on_embedded(np.ones((50, 8)), 1.4)

    assert enroller.state.prototypes == []
