"""Listener arming: when it listens, when it stands down, what it hands over."""

from __future__ import annotations

import pytest

from roomkit_ui.wakeword.detector import Detection
from roomkit_ui.wakeword.listener import WakeWordListener


class FakeDetector:
    def __init__(self, triggered: bool = True) -> None:
        self.triggered = triggered
        self.calls = 0
        self.raises = False

    @property
    def ready(self) -> bool:
        return True

    def detect(self, pcm: bytes) -> Detection | None:
        self.calls += 1
        if self.raises:
            raise RuntimeError("encoder exploded")
        return Detection(triggered=self.triggered, distance=0.04, threshold=0.08, duration=1.4)


class FakeSource:
    """Stand-in for roomkit's shared capture source."""

    def __init__(self) -> None:
        self.marks = 0
        self.subscribed = 0
        self.unsubscribed = 0

    def mark(self) -> str:
        self.marks += 1
        return f"mark-{self.marks}"

    def subscribe(self, callback, *, since=None, name=None):
        self.subscribed += 1
        source = self

        class _Sub:
            def unsubscribe(self) -> None:
                source.unsubscribed += 1

        return _Sub()


@pytest.fixture
def detector():
    return FakeDetector()


@pytest.fixture
def source():
    return FakeSource()


@pytest.fixture
def listener(detector, source, monkeypatch, inline_jobs):
    lis = WakeWordListener(detector, "/nonexistent/vad.onnx", source=source, jobs=inline_jobs)
    monkeypatch.setattr(lis._capture, "_build_vad", lambda: object())
    return lis


# -- arming ------------------------------------------------------------------


def test_does_not_listen_until_enabled(listener):
    assert not listener.listening


def test_listens_once_enabled(listener, source):
    listener.set_enabled(True)
    assert listener.listening
    assert source.subscribed == 1


def test_stands_down_while_a_session_runs(listener, source):
    """Left armed, it would hear the assistant's reply and wake on it."""
    listener.set_enabled(True)
    listener.suspend("session")
    assert not listener.listening
    assert source.unsubscribed == 1


def test_resumes_after_the_session_ends(listener):
    listener.set_enabled(True)
    listener.suspend("session")
    listener.resume("session")
    assert listener.listening


def test_suspensions_are_reference_counted(listener):
    """Dictation ending must not re-arm while a session is still running."""
    listener.set_enabled(True)
    listener.suspend("session")
    listener.suspend("dictation")
    listener.resume("dictation")
    assert not listener.listening
    listener.resume("session")
    assert listener.listening


def test_disabling_stops_listening(listener):
    listener.set_enabled(True)
    listener.set_enabled(False)
    assert not listener.listening


def test_enabling_while_suspended_does_not_listen(listener):
    listener.suspend("session")
    listener.set_enabled(True)
    assert not listener.listening


# -- detection ---------------------------------------------------------------


def test_emits_the_mark_taken_at_speech_start(listener, source):
    """The session must replay from before the wake word, not after it."""
    listener.set_enabled(True)
    received = []
    listener.detected.connect(lambda mark, dist: received.append((mark, dist)))

    listener._on_speech_started()
    listener._on_segment(b"\x00\x00" * 16000, 1.0)

    assert received == [("mark-1", 0.04)]


def test_stands_down_on_detection(listener):
    listener.set_enabled(True)
    listener._on_speech_started()
    listener._on_segment(b"\x00\x00" * 16000, 1.0)
    assert not listener.listening


def test_non_matching_speech_keeps_listening(listener, detector):
    detector.triggered = False
    listener.set_enabled(True)
    listener._on_segment(b"\x00\x00" * 16000, 1.0)
    assert listener.listening


def test_mark_is_consumed_so_it_cannot_be_replayed_twice(listener):
    listener.set_enabled(True)
    received = []
    listener.detected.connect(lambda mark, dist: received.append(mark))

    listener._on_speech_started()
    listener._on_segment(b"\x00\x00" * 16000, 1.0)
    listener.resume("session")
    listener._on_segment(b"\x00\x00" * 16000, 1.0)

    assert received == ["mark-1", None]


def test_detector_failure_surfaces_and_keeps_listening(listener, detector):
    """A broken encoder must be reported, not silently stop the wake word."""
    detector.raises = True
    listener.set_enabled(True)
    errors = []
    listener.error.connect(errors.append)

    listener._on_segment(b"\x00\x00" * 16000, 1.0)

    assert errors
    assert listener.listening


# -- without a shared source -------------------------------------------------


def test_mark_is_none_without_a_shared_source(detector, monkeypatch, inline_jobs):
    """Older roomkit: the session still opens, only the backlog is lost."""
    lis = WakeWordListener(detector, "/nonexistent/vad.onnx", source=None, jobs=inline_jobs)
    monkeypatch.setattr(lis._capture, "_build_vad", lambda: object())
    monkeypatch.setattr(lis._capture, "_open_stream", lambda: object())
    lis.set_enabled(True)

    received = []
    lis.detected.connect(lambda mark, dist: received.append(mark))
    lis._on_speech_started()
    lis._on_segment(b"\x00\x00" * 16000, 1.0)

    assert received == [None]
